"""Source-only bounded W05 checks. These do not execute PostgreSQL."""

import re
from hashlib import sha256
from pathlib import Path

SQL = Path(__file__).parents[1] / "src/modkit_workers/persistence/sql/0001_initial.sql"
PREFIX_BYTES = 126602
PREFIX_SHA = "5d2498760e4f419e08a41429e397c349b2a9c79b928441b578f7b85a4586f138"


ORIGINAL_HEADER = "-- Workers W01 SOURCE DRAFT / NOT_READY. NOT AUTHORIZED TO APPLY.\n-- Owner-only structural profile, not production E33/MKMF/grants readiness.\n-- Application owns the explicit installation transaction and every W01 root.\n-- No grants resource/manifest, transaction control, role or shared schema changes.\n-- Dependency source closure: w01-implementation/abi-pins.json + sql-owner.md.\n"


def legacy_header_bytes():
    # Preserve the original literal prefix oracle, not a regenerated candidate hash.
    # Only five approved comment lines are removed; DO $preflight$ is retained.
    lines = SQL.read_bytes().splitlines(keepends=True)
    assert lines[5] == b"DO $preflight$\n"
    return ORIGINAL_HEADER.encode() + b"".join(lines[5:])


def suffix():
    return legacy_header_bytes()[PREFIX_BYTES:].decode()


def test_entire_transferred_prefix_unchanged():
    assert sha256(legacy_header_bytes()[:PREFIX_BYTES]).hexdigest() == PREFIX_SHA


def test_new_overload_preserves_exact_75_output_columns():
    text = SQL.read_text()
    definitions = re.findall(r"CREATE FUNCTION modkit_workers.w05\((.*?)\n\$body\$;", text, re.S)
    assert len(definitions) == 2
    old, new = definitions
    assert (
        old.split("RETURNS TABLE(")[1].split("LANGUAGE")[0]
        == new.split("RETURNS TABLE(")[1].split("LANGUAGE")[0]
    )
    assert "p_max_page_payload_bytes pg_catalog.int8" in new
    assert "p_discovery_budget,p_max_page_payload_bytes)" in new
    assert "modkit_events.e15(" not in new
    assert "FROM modkit_events.work" not in new


def test_retained_guard_and_narrow_preflight_precede_wide_material_sort():
    text = suffix()
    assert text.index(
        "retained_payload_bytes := retained_payload_bytes+row_payload_bytes"
    ) < text.index("retained_claims := pg_catalog.array_append")
    narrow = text.split("-- Narrow fresh material preflight.")[1].split(
        "-- End narrow material preflight."
    )[0]
    for forbidden in (
        "saved.*",
        "j.*",
        "array_agg",
        "json_agg",
        "ORDER BY",
        "MATERIALIZED",
        "encode(",
    ):
        assert forbidden not in narrow
    assert "j.job_work_id IS NOT NULL" in narrow
    assert "pg_catalog.count(*)" in narrow and "pg_catalog.sum(" in narrow
    assert text.index("-- End narrow material preflight.") < text.index("SELECT saved.*,j.*")
    assert "preflight_payload_bytes>p_max_page_payload_bytes-retained_payload_bytes" in narrow
    assert "row_payload_bytes>p_max_page_payload_bytes-page_payload_bytes" in text


def test_q_header_and_error_contract():
    text = suffix()
    assert "p_max_page_payload_bytes NOT BETWEEN 1 AND 4294967296" in text
    assert "retained_payload_bytes pg_catalog.int8 := 6" in text
    assert "page_payload_bytes pg_catalog.int8 := 6" in text
    for state in ("PZ005", "PZ006", "PZ012", "PZ013"):
        assert "ERRCODE='" + state + "'" in text
    assert "EXCEPTION WHEN" not in text
    assert re.search(r"\b(?:COMMIT|ROLLBACK)\b", text) is None


def test_shifted_metadata_and_exact_private_signatures():
    text = suffix()
    assert "e04(bytea,text,bytea[],int4[],int4,float8,uuid,int4,int8)" in text
    assert "claim_abi.proargnames[10:13]" in text
    assert "claim_abi.proargnames[14:69]" in text
    assert "claim_abi.proallargtypes[1:9]" in text
    assert "pg_catalog.cardinality(claim_abi.proargnames) IS DISTINCT FROM 69" in text
    assert "pg_catalog.cardinality(claim_abi.proallargtypes) IS DISTINCT FROM 69" in text
    assert "w05(bytea,bytea[],int4[],int4,float8,uuid,int4,int8)" in text
    assert "new_abi.proargnames[9:83]" in text
    assert "new_abi.proallargtypes[9:83]" in text
    assert "acl.grantee<>owner_oid" in text
