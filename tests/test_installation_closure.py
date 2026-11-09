"""Connection-free closure controls; PostgreSQL ACL/native qualification is separate."""
import hashlib
import json
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
SQLDIR = ROOT / "src/modkit_workers/persistence/sql"
ROLES = ("modkit_runtime", "modkit_reconciler", "modkit_operator")
SIGNATURES = {
    "modkit_workers.w01(uuid,text,bytea,bytea,bytea,bytea,bytea,int4,bytea,bytea,bytea,bytea,bytea,bytea,bytea,bytea,text,int4,timestamptz,timestamptz,text,bytea,bytea,bytea,bytea,timestamptz,bytea,text,bytea)": ROLES[:1],
    "modkit_workers.w02(uuid)": ROLES,
    "modkit_workers.w03(bytea,timestamptz,uuid,int4)": ROLES,
    "modkit_workers.w03(bytea,timestamptz,uuid,int4,int8)": ROLES,
    "modkit_workers.w04(uuid,text,bytea,bytea,bytea,bytea,bytea)": ROLES,
    "modkit_workers.w05(bytea,bytea[],int4[],int4,float8,uuid,int4)": ROLES[:1],
    "modkit_workers.w05(bytea,bytea[],int4[],int4,float8,uuid,int4,int8)": ROLES[:1],
}
OLD_SCHEMA_CHECK = """       OR EXISTS (SELECT 1 FROM pg_catalog.pg_namespace AS n,
           LATERAL pg_catalog.aclexplode(COALESCE(n.nspacl,pg_catalog.acldefault('n',n.nspowner))) AS acl
           WHERE n.nspname='modkit_events' AND acl.grantee<>owner_oid) THEN"""
BASELINE_NONHEADER_SHA = "f9178401661ca8f5ef838337e1efa3365a2df4465377b6373b56076aa75381ae"


def test_neutral_header_and_only_de6_change():
    text = (SQLDIR / "0001_initial.sql").read_text()
    assert text.splitlines()[0] == "-- Workers component initial schema."
    assert text.splitlines()[5] == "DO $preflight$"
    normalized = re.sub(
        r"       -- IC-D-E6 BEGIN.*?       -- IC-D-E6 END\n       THEN",
        OLD_SCHEMA_CHECK, text, flags=re.S,
    )
    assert hashlib.sha256("\n".join(normalized.splitlines()[5:]).encode()).hexdigest() == (
        BASELINE_NONHEADER_SHA
    )


def test_de6_requires_exact_presence_and_exclusion_and_effective_access():
    text = (SQLDIR / "0001_initial.sql").read_text()
    section = text.split("DO $workers_bounded_acquisition_preflight$")[1].split(
        "$workers_bounded_acquisition_preflight$;"
    )[0]
    assert "-- IC-D-E6 BEGIN" in section
    assert len(re.findall(r"\bEXCEPT\b", section)) == 2
    for role in ROLES:
        assert role in section
    for fragment in ("acldefault('n',owner_oid)", "acl.grantor", "acl.is_grantable",
                     "has_schema_privilege", "'USAGE'", "'CREATE'"):
        assert fragment in section
    # Still denies all nonowner access to the private bounded Events E04.
    assert "COALESCE(claim_abi.proacl,pg_catalog.acldefault('f',owner_oid))" in section
    assert "WHERE acl.grantee<>owner_oid)" in section
    assert "claim_abi.proargnames[14:69]" in section


def test_exact_grant_matrix_no_other_grants():
    path = SQLDIR / "grants_runtime.sql"
    assert path.is_file(), "Reviewed grants resource is missing"
    text = path.read_text()
    actual = {}
    for identity, roles in re.findall(
        r"^GRANT EXECUTE ON FUNCTION ([^;]+?) TO ([^;]+);$", text, re.M
    ):
        assert identity not in actual
        actual[identity] = tuple(roles.split(","))
    assert actual == SIGNATURES
    assert re.findall(r"^GRANT USAGE ON SCHEMA (.*);$", text, re.M) == [
        "modkit_workers TO " + ",".join(ROLES)
    ]
    assert len(re.findall(r"^GRANT ", text, re.M)) == 8
    assert not re.search(
        r"\b(?:COMMIT|ROLLBACK|SAVEPOINT|CREATE ROLE|ALTER ROLE|ALTER DEFAULT PRIVILEGES)\b",
        text,
    )
    assert "WITH GRANT OPTION" not in text


def test_grant_oracle_covers_effective_defaults_columns_and_private_helpers():
    text = (SQLDIR / "grants_runtime.sql").read_text()
    for fragment in (
        "pg_catalog.pg_default_acl", "d.defaclnamespace IN (0,workers_oid)",
        "d.defaclrole=owner_oid", "pg_catalog.pg_auth_members",
        "pg_catalog.has_schema_privilege", "pg_catalog.has_function_privilege",
        "pg_catalog.has_table_privilege", "pg_catalog.has_column_privilege",
        "pg_catalog.has_sequence_privilege", "a.attacl",
        "p.prosrc", "p.proargnames", "p.proallargtypes", "p.proargmodes",
        "p.proconfig", "p.proowner", "p.prosecdef", "pg_catalog.sha256",
        "schema_versions", "pg_catalog.pg_type", "_parse_result",
        "EXCEPT", "is_grantable", "'PZ011'",
    ):
        assert fragment in text, fragment
    assert "DO $workers_grants_preflight$" in text
    assert "DO $workers_grants_postflight$" in text
    assert "GRANT ALL" not in text
    assert not re.search(r"(?:GRANT|REVOKE).*ON TYPE", text)


def aggregate(component, entries):
    chunks = [b"MKMF\x01", len(entries).to_bytes(4, "big")]
    for entry in sorted(entries, key=lambda value: value["path"].encode()):
        path = entry["path"].encode()
        assert path.startswith(component.encode() + b"/")
        chunks += [len(path).to_bytes(4, "big"), path, bytes.fromhex(entry["sha256"])]
    return hashlib.sha256(b"".join(chunks)).hexdigest()


def verify_pair(workers, events):
    for component, directory in (("workers", workers), ("events", events)):
        descriptor = json.loads((directory / "manifest.json").read_text())
        migration = descriptor["migrations"][0]
        assert migration["component"] == component
        for resource in migration["resources"]:
            raw = (directory / resource["path"].split("/")[1]).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == resource["sha256"]
        assert aggregate(component, migration["resources"]) == migration["migration_digest"]
    worker = json.loads((workers / "manifest.json").read_text())["migrations"][0]
    event = json.loads((events / "manifest.json").read_text())["migrations"][0]
    assert worker["depends_on"] == [{
        "component": "events", "version": 1, "migration_digest": event["migration_digest"]
    }]
    return worker, event


@pytest.mark.skipif(not os.environ.get("MODKIT_FROZEN_EVENTS_SQL"),
                    reason="Explicit frozen Events dependency handoff required")
def test_actual_frozen_pair_and_inert_public_api():
    events = Path(os.environ["MODKIT_FROZEN_EVENTS_SQL"])
    verify_pair(SQLDIR, events)
    from modkit_workers.persistence import migrations
    migration, = migrations.manifest()
    for resource in migration.resources:
        assert migrations.read_sql(migration, resource).encode() == (
            SQLDIR / resource.path.split("/")[1]
        ).read_bytes()


@pytest.mark.skipif(not os.environ.get("MODKIT_FROZEN_EVENTS_SQL"),
                    reason="Explicit frozen Events dependency handoff required")
def test_wrong_well_formed_dependency_is_rejected(tmp_path):
    import shutil
    events = Path(os.environ["MODKIT_FROZEN_EVENTS_SQL"])
    own = tmp_path / "workers"
    shutil.copytree(SQLDIR, own, ignore=shutil.ignore_patterns("__pycache__"))
    descriptor = json.loads((own / "manifest.json").read_text())
    descriptor["migrations"][0]["depends_on"][0]["migration_digest"] = "a" * 64
    (own / "manifest.json").write_text(json.dumps(descriptor))
    with pytest.raises(AssertionError):
        verify_pair(own, events)


def test_type_oracle_preserves_only_canonical_implicit_topology():
    text = (SQLDIR / "grants_runtime.sql").read_text()
    for token in ("t.typrelid", "c.reltype=t.oid", "element.typarray=t.oid",
                  "t.typacl IS NOT NULL", "t.typowner<>owner_oid"):
        assert token in text
    assert "has_type_privilege" not in text


def test_grant_function_attestation_matches_every_exact_initial_body():
    initial = (SQLDIR / "0001_initial.sql").read_text()
    grants = (SQLDIR / "grants_runtime.sql").read_text()
    definitions = re.findall(
        r"CREATE FUNCTION (modkit_workers\.\w+)\((.*?)\)\s*RETURNS TABLE\s*"
        r"\((.*?)\)\s*LANGUAGE(.*?)AS \$body\$(.*?)\$body\$;",
        initial, re.S,
    )
    assert len(definitions) == 7
    for name, inputs, outputs, attributes, body in definitions:
        parameters = re.findall(r"(\w+)\s+pg_catalog\.(\w+(?:\[\])?)", inputs)
        columns = re.findall(r"(\w+)\s+pg_catalog\.(\w+(?:\[\])?)", outputs)
        identity = name + "(" + ",".join(kind for _, kind in parameters) + ")"
        assert identity in SIGNATURES
        digest = hashlib.sha256(body.encode()).hexdigest()
        assert grants.count("'" + digest + "'") == 2
        for expected in (
            [key for key, _ in parameters + columns],
            [kind for _, kind in parameters + columns],
            ["i"] * len(parameters) + ["t"] * len(columns),
        ):
            literal = "ARRAY[" + ",".join("'" + value + "'" for value in expected) + "]"
            assert literal in grants
        assert ("'s'" if "STABLE" in attributes else "'v'") + ",'" + digest + "'" in grants


@pytest.mark.skipif(not os.environ.get("MODKIT_FROZEN_EVENTS_SQL"),
                    reason="Explicit frozen Events dependency handoff required")
def test_missing_and_tampered_real_closure_fail_closed(tmp_path, monkeypatch):
    import shutil

    from modkit_workers.persistence import migrations
    from modkit_workers.persistence._resource_io import PosixLease

    own = tmp_path / "sql"
    shutil.copytree(SQLDIR, own, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(migrations._io, "open_lease", lambda anchor: PosixLease(own))
    (own / "grants_runtime.sql").unlink()
    with pytest.raises(FileNotFoundError):
        migrations.manifest()
    (own / "grants_runtime.sql").write_bytes(b"-- changed bytes")
    with pytest.raises(ValueError, match="migration resource digest mismatch"):
        migrations.manifest()


@pytest.mark.skipif(not os.environ.get("MODKIT_FROZEN_EVENTS_SQL"),
                    reason="Explicit frozen Events dependency handoff required")
def test_shared_receipt_uses_events_descriptor_and_six_native_parameters():
    from modkit_events.persistence import migrations as events

    from modkit_workers.persistence import migrations as workers

    event, = events.manifest()
    worker, = workers.manifest()
    assert worker.depends_on[0].migration_digest == event.migration_digest
    text = events.read_owner_receipt(event)
    assert set(re.findall(r"\$(\d+)", text)) == set("123456")
    assert "clock_timestamp()" in text
    assert "applied_at" in text
    with pytest.raises(ValueError):
        events.read_owner_receipt(worker)


def test_sequence_relkind_uses_sequence_default_acl_semantics():
    # PostgreSQL acldefault uses s for sequence, S for foreign server.
    # pg_class.relkind deliberately uses uppercase S for sequence.
    text = (SQLDIR / "grants_runtime.sql").read_text()
    fallbacks = re.findall(
        r"CASE WHEN object_row\.relkind='([^']+)' THEN '([^']+)'::pg_catalog\.\"char\""
        r"\s+ELSE '([^']+)'::pg_catalog\.\"char\" END,owner_oid",
        text,
    )
    assert len(fallbacks) == 2  # Independent preflight and postflight.
    expected_default_kind = {"S": "s", "r": "r", "p": "r", "v": "r", "m": "r", "f": "r"}
    for sequence_relkind, sequence_default_kind, relation_default_kind in fallbacks:
        actual = {
            kind: sequence_default_kind if kind == sequence_relkind else relation_default_kind
            for kind in expected_default_kind
        }
        assert actual == expected_default_kind
    assert text.count("object_row.relkind='S'") == 4
