"""Offline transport harness controls. No driver, socket, or installed native import."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


def load():
    path = Path(__file__).resolve().parents[1] / "scripts/check_native_transport.py"
    assert path.is_file(), "non-autostart transport helper is missing"
    spec = importlib.util.spec_from_file_location("transport_helper", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ordinary_entry_is_inert():
    helper = load()
    with pytest.raises(ValueError, match="NOT_RUN"):
        helper.main()


def test_environment_refuses_before_any_adapter_call():
    helper = load()
    with pytest.raises(ValueError, match="environment"):
        helper.Harness(object(), {}).run()


def test_host_oracle_refuses_unpaid_or_unbounded_values():
    helper = load()
    oracle = helper.HostOracle()
    with pytest.raises(ValueError, match="reservation"):
        oracle.xid(1)
    oracle.reserve()
    for value in (True, -1, 2**64, "1", object()):
        with pytest.raises(ValueError):
            oracle.xid(value)
    for value in (None, "unknown", object()):
        with pytest.raises(ValueError):
            oracle.status(value)
    for value in (101, 101, 102, 102):
        oracle.xid(value)
    with pytest.raises(ValueError, match="occurrences"):
        oracle.xid(103)
    assert oracle.peak <= 8192
    oracle.release()
    assert oracle.used == 0 and not oracle.reserved


def test_exact_target_identity_and_profile_refusals():
    helper = load()
    target = (171100, "modkit_workers_ci", "modkit_ci_bootstrap", "modkit_ci_bootstrap")
    helper.validate_target(target, ["modkit_ci_bootstrap"], [], [])
    for index, value in enumerate((170000, "production", "postgres", "modkit_owner")):
        changed = list(target)
        changed[index] = value
        with pytest.raises(ValueError):
            helper.validate_target(tuple(changed), ["modkit_ci_bootstrap"], [], [])
    for roles, schemas, objects in (
        (["other"], [], []),
        (["modkit_ci_bootstrap"], ["app"], []),
        (["modkit_ci_bootstrap"], [], [("table", "app")]),
    ):
        with pytest.raises(ValueError):
            helper.validate_target(target, roles, schemas, objects)
    helper.validate_profile(helper.PROFILE)
    for key in helper.PROFILE:
        with pytest.raises(ValueError):
            helper.validate_profile({**helper.PROFILE, key: None})


def test_receipts_compare_all_fields_and_order_without_returning_borrowed_values():
    from types import SimpleNamespace

    helper = load()
    values = helper.EXPECTED_RECEIPTS
    rows = tuple(SimpleNamespace(**dict(zip(helper.FIELDS, row))) for row in values)
    assert helper.check_native_receipts(rows) is None
    with pytest.raises(ValueError):
        helper.check_native_receipts(tuple(reversed(rows)))
    for index in range(2):
        for field in helper.FIELDS:
            bad = tuple(SimpleNamespace(**dict(zip(helper.FIELDS, row))) for row in values)
            setattr(bad[index], field, None)
            with pytest.raises(ValueError):
                helper.check_native_receipts(bad)


def test_fixed_options_have_no_caller_target_and_startup_role_only():
    helper = load()
    for kind, login, role, autocommit in (
        ("bootstrap", "modkit_ci_bootstrap", None, True),
        ("owner", "modkit_ci_owner_login", None, True),
        ("observer", "modkit_ci_operator_login", "modkit_operator", True),
        ("native", "modkit_ci_runtime_login", "modkit_runtime", False),
    ):
        options = helper.connection_options(kind)
        assert options["host"] == options["hostaddr"] == "127.0.0.1"
        assert options["port"] == 5432 and options["dbname"] == "modkit_workers_ci"
        assert options["user"] == login and options["autocommit"] is autocommit
        assert options["connect_timeout"] == 5 and options["passfile"] == "/dev/null"
        assert "default_transaction_isolation" in options["options"]
        if role:
            assert f"-c role={role}" in options["options"]
    with pytest.raises(ValueError):
        helper.connection_options("arbitrary")


class FakeAdapter:
    """Finite fake host. It does not import the Events or driver packages."""

    def __init__(self, helper, fail=None):
        self.h = helper
        self.calls = []
        self.fail = fail
        self.xids = iter((101, 101, 102, 102))
        self.statuses = iter(("in progress", "aborted", "in progress", "committed"))
        self.receipts = helper.EXPECTED_RECEIPTS
        self.facts = dict(helper.PROFILE)
        self.identity = ("modkit_ci_operator_login", "modkit_operator") + (False,) * 5 + (True,) * 2
        self.ledger = SimpleNamespace(uncertainty=SimpleNamespace(present=False))
        self.counts = dict.fromkeys("P V C R X A AB B BB K KB D".split(), 0)
        self.outcome = object()
        self.payload = None
        self.native_rows = None
        self.unknown_after = None
        self.escape = False
        self.leaked_alias = None
        self.modules = SimpleNamespace(
            ledger=self.ledger,
            managed=self,
            native=self,
            execution=self,
            catalog=SimpleNamespace(get_statement=lambda key: key),
            expectation=object(),
        )
        self.CommitOutcome = SimpleNamespace(COMMITTED=self.outcome)
        self.LifecycleLimits = lambda **kwargs: SimpleNamespace(**kwargs)

    def __getattr__(self, name):
        def call(*args, **kwargs):
            self.calls.append(name)
            if self.fail == (name, self.calls.count(name)):
                raise RuntimeError("fake uncertainty")
            if self.unknown_after == (name, self.calls.count(name)):
                self.ledger.uncertainty.present = True
            if name == "profile":
                return self.facts
            if name == "freshness":
                return (
                    (171100, "modkit_workers_ci", "modkit_ci_bootstrap", "modkit_ci_bootstrap"),
                    ["modkit_ci_bootstrap"],
                    [],
                    [],
                )[args[1]]
            if name == "observer_preflight":
                return self.identity
            if name == "observer_receipts":
                return self.receipts
            if name == "observer_status":
                return next(self.statuses)
            if name == "load_native":
                return self.modules
            if name == "reserve_execution":
                self.counts["X"] = 1
            if name == "attach_native":
                self.counts.update(P=1, V=1, C=1)
            if name == "capacity_snapshot":
                return dict(self.counts)
            if name == "prepare":
                assert args[1:] == ("E14", ()) and kwargs["capacity"] == 4096
                self.payload = next(self.xids)
            if name == "prepare_readiness":
                assert args[1] == "workers" and args[2] is self.modules.expectation
                assert kwargs["capacity"] == 4096
                self.payload = self.native_rows or tuple(
                    SimpleNamespace(**dict(zip(self.h.FIELDS, row))) for row in self.receipts
                )
            if name == "read_result":
                if self.escape and type(self.payload) is tuple:
                    self.leaked_alias = self.payload[0]
                return self.payload
            if name == "release_result":
                # A borrowed tuple retained by Harness or its frame would add a reference.
                import sys

                refs = sys.getrefcount(self.payload)
                assert refs == 2 or type(self.payload) is int
                if type(self.payload) is tuple:
                    for index in range(2):
                        refs = sys.getrefcount(self.payload[index])
                        assert refs == 2, "borrowed row alias escaped"
                self.payload = None
            if name == "acknowledge_commit_result":
                return self.outcome
            if name == "acknowledge_physical_close":
                self.counts["V"] = 0
            if name == "detach_terminal":
                self.counts.update(P=0, C=0)
            if name == "dispose_execution":
                self.counts["X"] = 0
            return object()

        return call


def fake_run(helper, **kwargs):
    adapter = FakeAdapter(helper, **kwargs)
    env = {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_REPOSITORY": "maxxab/modkit-workers",
        "MODKIT_POSTGRES_TEST": "workers-native-transport-v1",
    }
    return helper.Harness(adapter, env), adapter


def test_exact_successful_schedule_and_zero_cleanup():
    helper = load()
    run, adapter = fake_run(helper)
    run.run()
    assert run.status == "PASS_OFFLINE_OR_ADAPTER_ONLY"
    assert run.counts["observer"] == 7
    assert run.counts["catalog"] == 6
    assert run.counts["connections"] == 4
    assert adapter.calls.count("freshness") == 4
    assert adapter.calls.count("bootstrap_statement") == 18
    assert adapter.calls.count("install_component") == 2
    assert adapter.calls.count("start_root") == 2
    assert adapter.calls.count("prepare") == 4
    assert adapter.calls.count("prepare_readiness") == 2
    assert adapter.calls.count("rollback") == adapter.calls.count("commit") == 1
    assert adapter.calls.count("acknowledge_root_end") == 1
    assert adapter.calls.count("acknowledge_commit_result") == 1
    assert adapter.calls.count("close") == 1
    assert not any(adapter.counts.values())
    assert run.oracle.used == 0
    with pytest.raises(ValueError):
        run.run()


def test_no_native_entry_before_prerequisites():
    helper = load()
    run, adapter = fake_run(helper)
    with pytest.raises(ValueError, match="prerequisites"):
        run.native_phase()
    assert adapter.calls == []


@pytest.mark.parametrize(
    "bad",
    [(101, 103, 102, 102), (101, 101, 101, 101), (True, True, 102, 102), (2**64, 2**64, 102, 102)],
)
def test_root_identity_must_match_within_and_differ_between_roots(bad):
    helper = load()
    run, adapter = fake_run(helper)
    adapter.xids = iter(bad)
    with pytest.raises(ValueError):
        run.run()
    assert "close" not in adapter.calls
    assert run.oracle.reserved


@pytest.mark.parametrize("bad", [None, "committed", "aborted", "unknown"])
def test_in_progress_status_is_exact_without_polling(bad):
    helper = load()
    run, adapter = fake_run(helper)
    adapter.statuses = iter((bad,))
    with pytest.raises(ValueError):
        run.run()
    assert adapter.calls.count("observer_status") == 1
    assert "rollback" not in adapter.calls and "close" not in adapter.calls


def test_aborted_commit_is_not_success_or_cleaned():
    helper = load()
    run, adapter = fake_run(helper)
    adapter.outcome = object()  # Deliberately not CommitOutcome.COMMITTED.
    with pytest.raises(ValueError, match="COMMITTED"):
        run.run()
    assert "close" not in adapter.calls


def test_every_external_failure_stops_without_retry_or_finally_cleanup():
    helper = load()
    baseline, adapter = fake_run(helper)
    baseline.run()
    calls = adapter.calls
    for index, name in enumerate(calls):
        run, broken = fake_run(helper, fail=(name, calls[: index + 1].count(name)))
        with pytest.raises(RuntimeError, match="fake uncertainty"):
            run.run()
        assert broken.calls == calls[: index + 1], (index, name)
        assert run.status == "UNKNOWN"
        assert run.diagnostic()["synthetic_teardown"] == "NOT_MANAGED_CLEANUP"


def test_excess_calls_refused_before_adapter():
    helper = load()
    run, adapter = fake_run(helper)
    run.counts["observer"] = 7
    with pytest.raises(ValueError, match="budget"):
        run.observe("observer_receipts", object())
    assert adapter.calls == []


def test_returned_uncertainty_never_reaches_next_operation():
    helper = load()
    for name in (
        "configure_managed_registry",
        "reserve_execution",
        "connect_native",
        "attach_native",
        "start_root",
        "prepare",
        "admit",
        "reserve_result",
        "execute",
        "read_result",
        "release_result",
        "release_ticket",
        "release_preparation",
        "rollback",
        "acknowledge_root_end",
        "release_root",
        "commit",
        "acknowledge_commit_result",
        "capacity_snapshot",
        "retire",
        "prepare_cleanup",
        "reserve_cleanup",
        "pin_cleanup",
        "close",
        "acknowledge_physical_close",
        "release_cleanup",
        "detach_terminal",
        "dispose_execution",
        "close_observer",
    ):
        run, adapter = fake_run(helper)
        adapter.unknown_after = (name, 1)
        with pytest.raises(ValueError, match="UNKNOWN"):
            run.run()
        assert adapter.calls[-1] == name, name
        assert run.oracle.reserved


def test_unexpected_capacity_prevents_close():
    helper = load()
    run, adapter = fake_run(helper)
    adapter.counts["BB"] = 64
    with pytest.raises(ValueError, match="capacity"):
        run.run()
    assert "retire" not in adapter.calls and "close" not in adapter.calls


def test_alias_escape_negative_control_is_detected_before_refund():
    helper = load()
    run, adapter = fake_run(helper)
    adapter.escape = True
    with pytest.raises(AssertionError, match="alias escaped"):
        run.run()
    assert run.status == "UNKNOWN" and adapter.payload is not None
    assert "rollback" not in adapter.calls


@pytest.mark.parametrize("field", range(9))
def test_observer_identity_and_privileges_gate_native_import(field):
    helper = load()
    run, adapter = fake_run(helper)
    values = list(adapter.identity)
    values[field] = None
    adapter.identity = tuple(values)
    with pytest.raises(ValueError, match="identity"):
        run.run()
    assert "load_native" not in adapter.calls


@pytest.mark.parametrize("position", [1, 3])
@pytest.mark.parametrize("bad", [None, "in progress", "wrong"])
def test_final_status_is_exact_without_polling_or_cleanup(position, bad):
    helper = load()
    run, adapter = fake_run(helper)
    values = ["in progress", "aborted", "in progress", "committed"]
    values[position] = bad
    adapter.statuses = iter(values)
    with pytest.raises(ValueError):
        run.run()
    assert adapter.calls.count("observer_status") == position + 1
    assert "close" not in adapter.calls


@pytest.mark.parametrize("key", ["PGHOST", "PGSERVICE", "PGOPTIONS", "PGPASSFILE", "PG"])
def test_postgres_environment_is_rejected_before_adapter(key):
    helper = load()
    run, adapter = fake_run(helper)
    run.env[key] = "ignored"
    with pytest.raises(ValueError, match="environment"):
        run.run()
    assert adapter.calls == []


def test_asserted_wrong_artifact_prevents_first_connection():
    helper = load()
    for key in helper.PROFILE:
        run, adapter = fake_run(helper)
        adapter.facts[key] = None
        with pytest.raises(ValueError, match="profile"):
            run.run()
        assert adapter.calls == ["profile"]


def test_import_and_cli_refuse_without_driver_or_native_import(monkeypatch):
    import builtins

    original = builtins.__import__

    def guarded(name, *args, **kwargs):
        assert not name.startswith(("psycopg", "modkit_events", "modkit_workers", "socket"))
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    helper = load()
    with pytest.raises(ValueError, match="NOT_RUN"):
        helper.main()


def test_receipt_mismatch_keeps_result_paid_and_blocks_root_finalization():
    helper = load()
    run, adapter = fake_run(helper)
    adapter.native_rows = tuple(
        SimpleNamespace(**dict(zip(helper.FIELDS, row)))
        for row in reversed(helper.EXPECTED_RECEIPTS)
    )
    with pytest.raises(ValueError, match="receipt"):
        run.run()
    assert adapter.calls.count("release_result") == 2  # Only the two successful E14s.
    assert "result" in run.handles and "rollback" not in adapter.calls


def test_oracle_duplicate_and_status_limits_and_draft_overlap():
    helper = load()
    oracle = helper.HostOracle()
    oracle.reserve()
    with pytest.raises(ValueError, match="duplicate"):
        oracle.reserve()
    for value in (2**64 - 1,) * 4:
        oracle.xid(value)
    for value in ("in progress", "aborted", "in progress", "committed"):
        oracle.status(value)
    with pytest.raises(ValueError, match="occurrences"):
        oracle.status("committed")
    assert oracle.used == oracle.peak == 8192
    assert oracle.xids == (2**64 - 1,) * 4
    oracle.release()
    with pytest.raises(ValueError, match="reservation"):
        oracle.release()


def test_returned_unknown_native_receipt_is_retained():
    helper = load()
    run, adapter = fake_run(helper)
    adapter.unknown_after = ("close", 1)
    with pytest.raises(ValueError, match="UNKNOWN"):
        run.run()
    assert "pending_native" in run.handles
    assert "acknowledge_physical_close" not in adapter.calls
