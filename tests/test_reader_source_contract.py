"""Ordered reader source ABI checks; native behavior needs the native fixture."""

import re
from pathlib import Path

import pytest

from modkit_workers.persistence.catalog import get_statement

SQL = Path(__file__).parents[1] / "src/modkit_workers/persistence/sql/0001_initial.sql"


@pytest.mark.parametrize("key", ("W02", "W03", "W04"))
def test_reader_source_matches_ordered_canonical_abi(key):
    assert SQL.is_file(), "Reviewed Workers SQL resource is missing"
    source = SQL.read_text()
    match = re.search(
        r"CREATE FUNCTION modkit_workers\."
        + key.lower()
        + r"\((.*?)\)\nRETURNS TABLE\((.*?)\n\)\nLANGUAGE(.*?)\$body\$;",
        source,
        re.S,
    )
    assert match is not None, f"Reader {key} is missing"
    parameters, columns, body = match.groups()
    statement = get_statement(key)
    actual_parameters = [
        (name[2:], wire) for name, wire in re.findall(r"(\w+) pg_catalog\.(\w+)", parameters)
    ]
    expected_parameters = [(p.name, p.wire_type.value) for p in statement.parameters]
    expected_columns = [(c.name, c.wire_type.value) for c in statement.result.columns]
    assert actual_parameters == expected_parameters
    assert re.findall(r"(\w+) pg_catalog\.(\w+)", columns) == expected_columns
    projection = re.search(r"RETURN QUERY SELECT (.*?);", body, re.S)
    assert projection is not None
    assert re.findall(r"item\.(\w+)", projection.group(1)) == [n for n, _ in expected_columns]


def test_reader_installation_keeps_private_boundary_before_explicit_grants():
    assert SQL.is_file(), "Reviewed Workers SQL resource is missing"
    source = SQL.read_text()
    assert "DO $workers_readers_private_boundary$" in source
    boundary = source.split("DO $workers_readers_private_boundary$", 1)[1]
    assert "'modkit_workers.w02(uuid)'::pg_catalog.regprocedure" in boundary
    assert (
        "'modkit_workers.w04(uuid,text,bytea,bytea,bytea,bytea,bytea)'::pg_catalog.regprocedure"
        in boundary
    )
    assert "acl.grantee<>p.proowner" in boundary
    # Initial SQL stays private; only the separate reviewed grants resource
    # exposes the closed read matrix. Presence does not attest an installed DB.
    from modkit_workers.persistence.migrations import manifest, read_sql

    (migration,) = manifest()
    assert migration.component == "workers"
    resources = {resource.path: resource for resource in migration.resources}
    assert read_sql(migration, resources["workers/0001_initial.sql"]) == source
    grants = read_sql(migration, resources["workers/grants_runtime.sql"])
    assert (
        "GRANT EXECUTE ON FUNCTION modkit_workers.w02(uuid) "
        "TO modkit_runtime,modkit_reconciler,modkit_operator;"
    ) in grants
    assert (
        "GRANT EXECUTE ON FUNCTION "
        "modkit_workers.w04(uuid,text,bytea,bytea,bytea,bytea,bytea) "
        "TO modkit_runtime,modkit_reconciler,modkit_operator;"
    ) in grants
