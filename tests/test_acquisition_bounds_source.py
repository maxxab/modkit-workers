"""Caller-owned bounds helper ABI controls; not native execution evidence."""

import ast
import importlib.util
import inspect
from pathlib import Path

SOURCE = Path(__file__).with_name("acquisition_bounds_protocol_source.py")


def test_bounds_helper_preserves_caller_owned_connection_and_exact_limits():
    assert SOURCE.is_file(), "Missing caller-owned W05 upper-limit helper"
    spec = importlib.util.spec_from_file_location("acquisition_bounds", SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert str(inspect.signature(module.run_acquisition_bounds)) == "(conn, *, protocol)"
    assert (module.PAGE_LIMIT, module.DISCOVERY_BUDGET, module.TOTAL_JOBS) == (256, 4096, 4353)
    tree = ast.parse(SOURCE.read_text())
    forbidden = {"connect", "commit", "rollback", "close", "Pool", "scenario", "run_source_fixture"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else (node.func.id if isinstance(node.func, ast.Name) else "")
            )
            assert name not in forbidden, name
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert not any(
                token in node.value.upper()
                for token in (
                    "BEGIN ISOLATION",
                    "SET ROLE",
                    "CREATE TABLE",
                    "INSERT INTO",
                    "E10(",
                )
            )


def test_native_uuid_builds_canonical_read_request():
    from uuid import UUID

    import acquisition_bounds_protocol_source as bounds
    from test_job_persistence_contracts import ID

    assert callable(getattr(bounds, "_read_request", None)), "Missing native UUID read adapter"
    request = bounds._read_request(UUID(ID))
    assert request.statement.key == "W02"
    assert request.parameters == (UUID(ID),)
