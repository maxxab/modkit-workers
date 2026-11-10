"""Offline controls for the fresh synthetic PostgreSQL CI lane."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/check_postgres.py"


def load_script():
    assert SCRIPT.is_file(), "PostgreSQL CI checker has not been implemented"
    spec = importlib.util.spec_from_file_location("workers_postgres_ci_tests", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ci_env():
    return {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_REPOSITORY": "maxxab/modkit-workers",
        "MODKIT_POSTGRES_TEST": "workers-composition-v1",
    }


def test_exact_synthetic_ci_context_is_required():
    module = load_script()
    module.require_ci_environment(ci_env())
    for key in ci_env():
        env = ci_env()
        del env[key]
        with pytest.raises(ValueError, match="synthetic GitHub CI"):
            module.require_ci_environment(env)
        env[key] = "different"
        with pytest.raises(ValueError, match="synthetic GitHub CI"):
            module.require_ci_environment(env)


@pytest.mark.parametrize("key", ["PGHOST", "PGSERVICE", "PGPASSFILE", "PGOPTIONS", "PGPASSWORD"])
def test_existing_postgres_environment_is_rejected(key):
    module = load_script()
    with pytest.raises(ValueError, match="PostgreSQL environment"):
        module.require_ci_environment({**ci_env(), key: "must-not-be-used"})


def test_connection_target_cannot_be_selected_by_caller():
    module = load_script()
    for name in module.LOGIN_ROLES:
        settings = module.connection_options(name)
        assert settings["host"] == settings["hostaddr"] == "127.0.0.1"
        assert settings["port"] == 5432
        assert settings["dbname"] == "modkit_workers_ci"
        assert settings["connect_timeout"] == 5
        assert settings["user"] == name
        assert settings["passfile"] == "/dev/null"
        assert "service" not in settings  # Empty service names still trigger libpq lookup.
    with pytest.raises(ValueError, match="unknown fixture login"):
        module.connection_options("postgres")


def test_server_preflight_rejects_wrong_or_used_targets():
    module = load_script()
    row = (171100, "modkit_workers_ci", "modkit_ci_bootstrap", "modkit_ci_bootstrap")
    module.validate_target(row, ["modkit_ci_bootstrap"], [], [])
    for index, changed in enumerate((160000, "existing_app", "owner", "owner")):
        bad = list(row)
        bad[index] = changed
        with pytest.raises(ValueError, match="fresh synthetic PostgreSQL 17"):
            module.validate_target(tuple(bad), ["modkit_ci_bootstrap"], [], [])
    for roles, schemas in (
        (["modkit_ci_bootstrap", "existing_user"], []),
        (["modkit_ci_bootstrap"], ["existing_app"]),
    ):
        with pytest.raises(ValueError, match="fresh synthetic PostgreSQL 17"):
            module.validate_target(row, roles, schemas, [])


def test_worker_signature_permissions_are_exact():
    module = load_script()
    assert len(module.WORKER_SIGNATURES) == 7
    assert sorted(module.WORKER_SIGNATURES.values()) == [1, 1, 1, 3, 3, 3, 3]
    assert (
        len({name for name in module.WORKER_SIGNATURES if name.startswith("modkit_workers.w05(")})
        == 2
    )
    assert (
        len({name for name in module.WORKER_SIGNATURES if name.startswith("modkit_workers.w03(")})
        == 2
    )


def test_pair_dependency_must_match_exact_current_events():
    from types import SimpleNamespace

    module = load_script()
    event = SimpleNamespace(component="events", version=1, migration_digest="a" * 64)
    dependency = SimpleNamespace(component="events", version=1, migration_digest="a" * 64)
    worker = SimpleNamespace(component="workers", version=1, depends_on=(dependency,))
    module.validate_pair(event, worker, "a" * 64)
    for wrong in ("b" * 64, "", None):
        with pytest.raises(ValueError, match="dependency"):
            module.validate_pair(event, worker, wrong)
    dependency.migration_digest = "b" * 64
    with pytest.raises(ValueError, match="dependency"):
        module.validate_pair(event, worker, "a" * 64)


def test_main_refuses_before_package_or_driver_import(monkeypatch):
    import builtins

    module = load_script()
    monkeypatch.setattr(module.os, "environ", {})
    original = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        assert not name.startswith(("psycopg", "modkit_events", "modkit_workers")), (
            "guard ran too late"
        )
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    with pytest.raises(ValueError, match="synthetic GitHub CI"):
        module.main()


def test_existing_public_objects_are_rejected_before_bootstrap():
    import inspect

    module = load_script()
    assert "objects" in inspect.signature(module.validate_target).parameters, (
        "target guard must inspect objects even in the default public schema"
    )
    row = (171100, "modkit_workers_ci", "modkit_ci_bootstrap", "modkit_ci_bootstrap")
    module.validate_target(row, ["modkit_ci_bootstrap"], [], [])
    for objects in (
        [("relation", "public.existing_table")],
        [("function", "public.existing_function")],
        [("type", "public.existing_enum")],
    ):
        with pytest.raises(ValueError, match="fresh synthetic PostgreSQL 17"):
            module.validate_target(row, ["modkit_ci_bootstrap"], [], objects)


def test_exact_worker_inventory_includes_reviewed_security_attributes():
    from types import SimpleNamespace

    module = load_script()
    names = list(module.WORKER_SIGNATURES)
    rows = [
        (n, True, True, "f", "modkit_owner", ["search_path=pg_catalog, pg_temp"])
        for n in range(1, 8)
    ]

    def execute(statement, parameters=None):
        if parameters:
            return SimpleNamespace(fetchone=lambda: (names.index(parameters[0]) + 1,))
        return SimpleNamespace(fetchall=lambda: rows)

    connection = SimpleNamespace(execute=execute)
    assert module.worker_inventory(connection) == {
        n: module.WORKER_SIGNATURES[name] for n, name in enumerate(names, 1)
    }
    rows.append((99, True, True, "f", "modkit_owner", ["search_path=pg_catalog, pg_temp"]))
    with pytest.raises(AssertionError):
        module.worker_inventory(connection)


@pytest.mark.parametrize(
    "failure", ["expected", "wrong-state", "wrong-reason", "success", "rollback"]
)
def test_missing_dependency_requires_verified_owner_exact_error_and_rollback(monkeypatch, failure):
    from types import SimpleNamespace
    from unittest.mock import MagicMock

    module = load_script()

    class DatabaseError(Exception):
        sqlstate = "42501" if failure == "wrong-state" else "PZ011"
        diag = SimpleNamespace(
            message_primary="other"
            if failure == "wrong-reason"
            else "invalid structural owner or namespace"
        )

    connection = MagicMock()
    selected = []
    monkeypatch.setattr(module, "selected_role", lambda *args: selected.append(args[-1]))
    observed = MagicMock(return_value=((False, False), []))
    monkeypatch.setattr(module, "observer_state", observed)

    def execute(statement, **kwargs):
        assert selected == ["modkit_ci_owner_login"]
        if statement.startswith("SELECT rolcanlogin"):
            return SimpleNamespace(fetchone=lambda: (False,) * 6)
        if statement.startswith("SELECT has_database_privilege"):
            return SimpleNamespace(fetchone=lambda: (True,))
        assert statement == "COMPLETE WORKERS SQL" and kwargs == {"prepare": False}
        if failure != "success":
            raise DatabaseError()

    connection.execute.side_effect = execute
    driver = SimpleNamespace(Error=DatabaseError)
    if failure == "rollback":
        connection.transaction.return_value.__exit__.side_effect = RuntimeError(
            "rollback uncertain"
        )
    if failure == "expected":
        module.refuse_without_events(connection, driver, "COMPLETE WORKERS SQL")
        assert observed.call_count == 2
    else:
        with pytest.raises(RuntimeError if failure == "rollback" else AssertionError):
            module.refuse_without_events(connection, driver, "COMPLETE WORKERS SQL")
        assert observed.call_count == 1


def test_workflow_has_only_the_reviewed_disposable_composition_scope():
    workflow = (SCRIPT.parents[1] / ".github/workflows/ci.yml").read_text()
    job = workflow.split("  postgres-composition:\n", 1)[1]
    assert "runs-on: ubuntu-24.04" in job and "timeout-minutes: 10" in job
    assert "ports: ['127.0.0.1:5432:5432']" in job
    assert (
        "postgres:17.11-bookworm@sha256:665dc7b37ac52a17e298511414c21d23ffa4e6a6ef6225b3e5d59c7afb35e994"
        in job
    )
    assert "POSTGRES_DB: modkit_workers_ci" in job
    assert "MODKIT_POSTGRES_TEST: workers-composition-v1" in job
    assert "persist-credentials: false" in job
    assert "--check-dependency-only" in job and "audit_wheel" in job
    assert "--no-deps --no-index dist/*.whl dependency-dist/*.whl" in job
    assert 'python" -I -B check_postgres.py' in job
    for forbidden in ("secrets.", "volumes:", "upload-artifact", "retry", "ssh", "kubectl"):
        assert forbidden not in job
