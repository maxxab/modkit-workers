"""Bounded W03 source contracts; SQL parser/native qualification remains separate."""

import ast
import hashlib
import re
from importlib.resources import files
from pathlib import Path

from modkit_events.persistence.catalog import WireType

from modkit_workers.persistence.catalog import get_statement

SQL = Path(__file__).parents[1] / "src/modkit_workers/persistence/sql/0001_initial.sql"
LEGACY = ("bytea", "timestamptz", "uuid", "int4")
BOUNDED = LEGACY + ("int8",)
LARGE_FIELDS = (
    "intent_evidence",
    "semantic_input",
    "replay_input",
    "protected_binding",
    "result",
    "resolution_record_result",
    "resolution_record_evidence",
    "resolution_record_binding",
    "job_protected_binding",
    "job_semantic_input",
    "protected_sidecar",
    "protected_reference",
    "protected_recovery_metadata",
    "projection_metadata",
)
SMALL_BOUNDS = {
    "kind": 3,
    "subscription_id": 256,
    "namespace": 256,
    "command_type": 256,
    "schema_version_decimal": 4096,
    "scope_evidence": 781,
    "scope_application": 256,
    "scope_tenant": 256,
    "scope_owner": 256,
    "idempotency_key": 256,
    "replay_policy": 16,
    "state": 14,
    "success_origin": 10,
    "completion_result_digest": 32,
    "resolution_record_operation_kind": 14,
    "resolution_record_outcome": 19,
    "resolution_record_result_digest": 32,
    "resolution_record_reason": 256,
    "job_application": 256,
    "job_tenant": 256,
    "job_owner": 256,
    "material_state": 7,
    "protected_codec": 256,
    "protected_key_version": 256,
    "protected_cleanup_policy": 20,
}


def functions(source):
    """Resolve source definitions by full identity, never first name match."""
    result = {}
    pattern = (
        r"CREATE(?: OR REPLACE)? FUNCTION (modkit_\w+\.\w+)\((.*?)\)"
        r"(.*?)AS \$(\w+)\$(.*?)\$\4\$;"
    )
    for match in re.finditer(pattern, source, re.S):
        name, parameters, declaration, _, body = match.groups()
        types = tuple(re.findall(r"pg_catalog\.(\w+(?:\[\])?)", parameters))
        key = (name, types)
        assert key not in result, f"Duplicate source function identity: {key}"
        result[key] = (parameters, declaration, body, match.group())
    return result


def bounded():
    found = functions(SQL.read_text())
    key = ("modkit_workers.w03", BOUNDED)
    assert key in found, "Exact five-argument W03 overload is missing"
    return found[key]


def test_bounded_overload_preserves_legacy_and_exact_71_column_abi():
    found = functions(SQL.read_text())
    legacy = found[("modkit_workers.w03", LEGACY)][3]
    assert hashlib.sha256(legacy.encode()).hexdigest() == (
        "3490891a618f02943c7fa9bd79b85c027a2f69c71e175b8bed7a476bbbc9fc7e"
    )
    parameters, declaration, body, _ = bounded()
    assert "DEFAULT" not in parameters.upper() and "=" not in parameters
    assert re.findall(r"(\w+) pg_catalog\.(\w+)", parameters) == [
        ("p_namespace", "bytea"),
        ("p_after_created_at", "timestamptz"),
        ("p_after_work_id", "uuid"),
        ("p_limit", "int4"),
        ("p_max_page_payload_bytes", "int8"),
    ]
    columns = re.search(r"RETURNS TABLE\((.*?)\n\)", declaration, re.S).group(1)
    expected = [(c.name, c.wire_type.value) for c in get_statement("W03").result.columns]
    assert re.findall(r"(\w+) pg_catalog\.(\w+)", columns) == expected
    projection = re.search(r"RETURN QUERY SELECT (.*?);", body, re.S).group(1)
    assert re.findall(r"item\.(\w+)", projection) == [name for name, _ in expected]
    assert "plpgsql STABLE SECURITY DEFINER CALLED ON NULL INPUT" in declaration
    assert "SET search_path = pg_catalog, pg_temp" in declaration


def test_bounded_key_page_precedes_one_row_reader_and_early_budget_check():
    _, _, body, _ = bounded()
    loop = re.search(r"FOR selected IN(.*?)\n    LOOP", body, re.S).group(1)
    assert "WITH page AS MATERIALIZED" in loop
    assert loop.count("LIMIT p_limit") == 2
    assert loop.count("listed.kind COLLATE") == 2
    assert "(listed.created_at,listed.work_id)>(p_after_created_at,p_after_work_id)" in loop
    assert "ORDER BY page.selected_created_at,page.selected_work_id" in loop
    assert not re.search(r"\b(?:JOIN|e15|w02|job_payloads)\b", loop, re.I)
    assert set(re.findall(r"listed\.(\w+)", loop)) == {
        "work_id",
        "created_at",
        "namespace",
        "kind",
    }
    assert body.count("modkit_workers.w02(selected.selected_work_id)") == 1
    assert "IF NOT FOUND" in body
    assert "item.work_id IS DISTINCT FROM selected.selected_work_id" in body
    assert "item.created_at IS DISTINCT FROM selected.selected_created_at" in body
    assert "item.namespace IS DISTINCT FROM p_namespace" in body
    assert "(item.created_at,item.work_id)<=(previous_created_at,previous_id)" in body
    assert body.index("ERRCODE='PZ005'") < body.index("ERRCODE='PZ006'")
    assert "p_max_page_payload_bytes NOT BETWEEN 1 AND 3758096384" in body
    guard = body.index("IF row_payload_bytes > p_max_page_payload_bytes - page_payload_bytes")
    assert body.index("modkit_workers.w02(") < guard < body.index("RETURN QUERY")
    assert "ERRCODE='PZ013',MESSAGE='W03 page payload budget exceeded'" in body
    assert "EXCEPTION WHEN" not in body.upper()
    assert "modkit_workers.w03(" not in body


def test_all_native_variable_caps_and_fourteen_bigint_occurrences_precede_append():
    _, _, body, _ = bounded()
    cap = body.split("-- Fixed native variable-field bounds.", 1)[1].split(
        "row_payload_bytes:=", 1
    )[0]
    expected = {**SMALL_BOUNDS, **dict.fromkeys(LARGE_FIELDS, 1048576)}
    actual = {
        name: int(bound)
        for name, bound in re.findall(
            r"item\.(\w+)(?:, 'UTF8'\))?\) OPERATOR\(pg_catalog\.<=\) (\d+)", cap
        )
    }
    assert actual == expected
    variable = {
        c.name
        for c in get_statement("W03").result.columns
        if c.wire_type in (WireType.BYTEA, WireType.TEXT)
    }
    assert set(actual) == variable
    for column in get_statement("W03").result.columns:
        if column.name in variable:
            nullability = "IS NULL OR" if column.nullable else "IS NOT NULL AND"
            assert f"item.{column.name} {nullability}" in cap
    assert "invalid native job listing field bounds" in cap
    total = body.split("row_payload_bytes:=", 1)[1].split(";", 1)[0]
    assert re.findall(
        r"COALESCE\(pg_catalog.octet_length\(item\.(\w+)\)::pg_catalog.int8,0::pg_catalog.int8\)",
        total,
    ) == list(LARGE_FIELDS)
    assert "row_payload_bytes pg_catalog.int8" in body
    assert "page_payload_bytes pg_catalog.int8:=0" in body


def test_exact_dependency_and_overload_acl_guards_do_not_trust_installer_defaults():
    source = SQL.read_text()
    w02 = functions(source)[("modkit_workers.w02", ("uuid",))]
    assert hashlib.sha256(w02[3].encode()).hexdigest() == (
        "9784ff7149b671b7cd7cc4a46fa6923ce78bbffa613b1c738cd9ae1598761adf"
    )
    assert "job reader cardinality exceeded" in w02[2]
    guard = source.split("DO $workers_bounded_listing_preflight$", 1)[1].split(
        "$workers_bounded_listing_preflight$;", 1
    )[0]
    assert "modkit_workers.w02(uuid)" in guard
    assert hashlib.sha256(w02[2].encode()).hexdigest() in guard
    for check in (
        "proowner",
        "provolatile",
        "prosecdef",
        "pronargdefaults",
        "proargtypes",
        "proallargtypes",
        "proargnames",
        "proargmodes",
        "prosrc",
        "proconfig",
    ):
        assert check in guard
    definition = bounded()[3]
    suffix = source.split(definition, 1)[1]
    revoke = (
        "REVOKE ALL ON FUNCTION modkit_workers.w03(pg_catalog.bytea,"
        "pg_catalog.timestamptz,pg_catalog.uuid,pg_catalog.int4,pg_catalog.int8) FROM PUBLIC;"
    )
    assert suffix.lstrip().startswith(revoke)
    boundary = suffix.split("DO $workers_bounded_listing_private_boundary$", 1)[1].split(
        "$workers_bounded_listing_private_boundary$;", 1
    )[0]
    assert (
        "'modkit_workers.w03(bytea,timestamptz,uuid,int4,int8)'::pg_catalog.regprocedure"
        in boundary
    )
    assert "COALESCE(p.proacl,pg_catalog.acldefault('f',p.proowner))" in boundary
    assert "acl.grantee<>p.proowner" in boundary and "acl.grantee<>n.nspowner" in boundary
    assert "ERRCODE='PZ011'" in boundary
    assert SQL.with_name("manifest.json").is_file()
    assert SQL.with_name("grants_runtime.sql").is_file()


def closure():
    found = functions(
        files("modkit_events.persistence.sql").joinpath("0001_initial.sql").read_text()
    )
    found.update(functions(SQL.read_text()))
    root = ("modkit_workers.w03", BOUNDED)
    assert root in found, "Bounded overload absent from source closure"
    pending, seen, edges = [root], set(), {}
    while pending:
        key = pending.pop()
        if key in seen:
            continue
        seen.add(key)
        body = re.sub(r"--[^\n]*", "", found[key][2])
        names = set(re.findall(r"(modkit_(?:events|workers)\.\w+)\(", body))
        children = []
        for name in sorted(names):
            matches = [identity for identity in found if identity[0] == name]
            assert len(matches) == 1, f"Unresolved/ambiguous call {name} in {key}"
            children.append(matches[0])
        edges[key] = children
        pending.extend(children)
    return found, seen, edges


def test_bounded_signature_aware_closure_has_no_e10_or_mutation():
    found, seen, _ = closure()
    assert ("modkit_workers.w02", ("uuid",)) in seen
    assert ("modkit_events.e15", ("uuid",)) in seen
    assert ("modkit_workers.w03", LEGACY) not in seen
    for key in seen:
        assert key[0] != "modkit_events.e10"
        declaration, body = found[key][1:3]
        assert "VOLATILE" not in declaration.upper()
        body = re.sub(r"--[^\n]*", "", body)
        assert not re.search(
            r"\b(?:INSERT\s+INTO|UPDATE\s+modkit_|DELETE\s+FROM|nextval|setval|"
            r"FOR\s+UPDATE|LOCK\s+TABLE)\b",
            body,
            re.I,
        ), key


def test_installation_helpers_address_both_exact_overloads():
    import listing_installation_source as fixture

    assert fixture.IDENTITIES == (
        "modkit_workers.w03(bytea,timestamptz,uuid,int4)",
        "modkit_workers.w03(bytea,timestamptz,uuid,int4,int8)",
    )
    assert callable(fixture.check_bounded_installation)


def test_bounded_protocol_params_keep_the_original_business_request():
    import listing_protocol_source as fixture

    from modkit_workers.persistence import bindings, models

    request = bindings.list_jobs(models.JobListRequest(after=None, limit=256))
    actual = fixture.bounded_params(request, 2**31)
    assert actual == {
        "namespace": b"jobs",
        "after_created_at": None,
        "after_work_id": None,
        "limit": 256,
        "max_page_payload_bytes": 2**31,
    }
    assert request.parameters == (b"jobs", None, None, 256)
    assert "%(max_page_payload_bytes)s::int8" in fixture.BOUNDED_LIST


def test_installation_negative_snapshots_both_but_drops_only_selected_overload():
    import listing_installation_source as fixture

    class ExpectedFailure(Exception):
        sqlstate = "PZ011"

    class Connection:
        def __init__(self):
            self.commands = []
            self.rollbacks = 0

        def execute(self, statement, parameters=None, **kwargs):
            self.commands.append((statement, parameters))
            if statement == "bounded source":
                raise ExpectedFailure()
            return self

        def fetchall(self):
            return []

        def rollback(self):
            self.rollbacks += 1

    connection = Connection()
    fixture.rejected(
        connection,
        "bounded source",
        [],
        identities=(fixture.BOUNDED_IDENTITY,),
    )
    assert connection.rollbacks == 1
    drops = [sql for sql, _ in connection.commands if sql.startswith("DROP FUNCTION")]
    assert drops == ["DROP FUNCTION IF EXISTS " + fixture.BOUNDED_IDENTITY]
    snapshots = [params for sql, params in connection.commands if "pg_get_functiondef" in sql]
    assert snapshots == [fixture.IDENTITIES, fixture.IDENTITIES]


def test_named_budget_is_explicit_and_does_not_change_the_business_descriptor():
    source = SQL.parents[1].joinpath("native_store.py").read_text()
    tree = ast.parse(source)
    wrapper = next(
        n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "prepare_list_jobs"
    )
    options = dict(
        zip((argument.arg for argument in wrapper.args.kwonlyargs), wrapper.args.kw_defaults)
    )
    assert "max_page_payload_bytes" in options
    assert isinstance(options["max_page_payload_bytes"], ast.Name)
    assert options["max_page_payload_bytes"].id == "DEFAULT_LIST_PAGE_PAYLOAD_BYTES"
    call = next(
        n for n in ast.walk(wrapper) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    )
    forwarded = next(k.value for k in call.keywords if k.arg == "max_page_payload_bytes")
    assert isinstance(forwarded, ast.Name) and forwarded.id == "max_page_payload_bytes"
    common = next(
        n
        for n in tree.body
        if isinstance(n, ast.ImportFrom) and n.module == "modkit_events.persistence.native_profile"
    )
    assert {"DEFAULT_LIST_PAGE_PAYLOAD_BYTES", "MAX_LIST_PAGE_PAYLOAD_BYTES"} <= {
        alias.name for alias in common.names
    }
    assert len(get_statement("W03").parameters) == 4
