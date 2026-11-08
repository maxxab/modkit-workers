"""Ordered reader source ABI checks; native behavior needs the native fixture."""

import re
from pathlib import Path

import pytest

from modkit_workers.persistence.catalog import get_statement

SQL = Path(__file__).parents[1] / "src/modkit_workers/persistence/sql/0001_initial.sql"


@pytest.mark.parametrize("key", ("W02", "W04"))
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


def test_reader_installation_keeps_private_boundary_and_not_ready_resources():
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
    assert not SQL.with_name("manifest.json").exists()
    assert not SQL.with_name("grants_runtime.sql").exists()
