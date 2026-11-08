"""W05 source layout and ownership controls, not native SQL qualification."""

import re
from pathlib import Path

from modkit_events.persistence.catalog import get_statement as event_statement

from modkit_workers.persistence.catalog import get_statement

SQL = Path(__file__).parents[1] / "src/modkit_workers/persistence/sql/0001_initial.sql"


def function():
    match = re.search(
        r"CREATE FUNCTION modkit_workers\.w05\((.*?)\)\n"
        r"RETURNS TABLE\((.*?)\n\)\nLANGUAGE(.*?)\$body\$;",
        SQL.read_text(),
        re.S,
    )
    assert match is not None, "Acquisition W05 is missing"
    return match.groups()


def test_acquisition_matches_exact_catalog_abi():
    parameters, columns, body = function()
    statement = get_statement("W05")
    assert [
        (name[2:], wire)
        for name, wire in re.findall(r"(\w+) pg_catalog\.(\w+(?:\[\])?)", parameters)
    ] == [
        (
            p.name,
            {"bytea_array": "bytea[]", "int4_array": "int4[]"}.get(
                p.wire_type.value, p.wire_type.value
            ),
        )
        for p in statement.parameters
    ]
    assert re.findall(r"(\w+) pg_catalog\.(\w+)", columns) == [
        (c.name, c.wire_type.value) for c in statement.result.columns
    ]
    assert "plpgsql VOLATILE SECURITY DEFINER CALLED ON NULL INPUT" in body
    assert "SET search_path = pg_catalog, pg_temp" in body


def test_acquisition_retains_postimages_without_a_work_reread():
    _, _, body = function()
    assert body.count("modkit_events.e04(") == 1
    assert "modkit_events.e15(" not in body
    assert "modkit_workers.w02(" not in body
    assert not re.search(r"(?:FROM|JOIN|UPDATE|INSERT INTO) modkit_events\.work\b", body)
    retained = re.search(
        r"array_append\(retained_claims,ROW\((.*?)\)::modkit_events.work", body, re.S
    )
    assert retained is not None
    assert re.findall(r"acquired\.(\w+)", retained.group(1)) == [
        c.name for c in event_statement("E15").result.columns[:39]
    ]
    assert "FROM pg_catalog.unnest(retained_claims) AS saved" in body
    assert "LEFT JOIN modkit_events.job_payloads AS j" in body
    assert body.index("END LOOP;") < body.index("FROM pg_catalog.unnest(retained_claims)")


def test_acquisition_checks_all_omitted_provenance_before_projection():
    _, _, body = function()
    check = body.split("-- Validate the omitted provenance", 1)[1].split("-- Retain the exact", 1)[
        0
    ]
    assert "acquired.resolution_present IS DISTINCT FROM FALSE" in check
    for column in event_statement("E15").result.columns[40:]:
        assert f"acquired.{column.name} IS NOT NULL" in check


def test_acquisition_keeps_private_boundary_and_no_transaction_controller():
    source = SQL.read_text()
    _, _, body = function()
    assert "DO $workers_acquisition_preflight$" in source
    assert "DO $workers_acquisition_private_boundary$" in source
    assert (
        "REVOKE ALL ON FUNCTION modkit_workers.w05(pg_catalog.bytea,"
        "pg_catalog.bytea[],pg_catalog.int4[],pg_catalog.int4,pg_catalog.float8,"
        "pg_catalog.uuid,pg_catalog.int4) FROM PUBLIC;"
    ) in source
    assert not re.search(r"\b(?:COMMIT|ROLLBACK|SAVEPOINT|EXCEPTION WHEN)\b", body)
    assert not SQL.with_name("manifest.json").exists()
    assert not SQL.with_name("grants_runtime.sql").exists()


def test_emitted_header_and_item_projection_preserve_all_canonical_positions():
    _, _, body = function()
    statement = get_statement("W05")
    work = event_statement("E15").result.columns
    header = re.search(r"RETURN QUERY SELECT 'header'::pg_catalog.text,(.*?);", body, re.S)
    assert header is not None
    assert re.findall(r"NULL::pg_catalog\.(\w+)", header.group(1)) == [
        c.wire_type.value for c in statement.result.columns[4:]
    ]
    item = re.search(
        r"RETURN QUERY SELECT 'item'::pg_catalog.text,NULL::pg_catalog.int4,"
        r"NULL::pg_catalog.uuid,NULL::pg_catalog.bool,(.*?);",
        body,
        re.S,
    )
    assert item is not None
    assert [part.strip() for part in item.group(1).split(",")] == (
        ["item." + c.name for c in work[:39]]
        + ["FALSE::pg_catalog.bool"]
        + ["NULL::pg_catalog." + c.wire_type.value for c in work[40:]]
        + ["item." + c.name for c in statement.result.columns[60:]]
    )
