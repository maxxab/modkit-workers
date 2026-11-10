"""Deterministic private-seam doubles; never native/runtime qualification."""

from contextlib import contextmanager
from threading import Event
from types import SimpleNamespace
from uuid import UUID

import pytest
from test_native_recovery_contracts import config, module


class Application:
    def __init__(self, events):
        self.events = events
        self.reject = False
        self.exit_fails = False

    def validate_profile(self, namespace):
        assert namespace == b"jobs"

    @contextmanager
    def authorize_root(self, connection, namespace):
        self.events.append("authority-enter")
        if self.reject:
            raise RuntimeError("denied")
        try:
            yield
        finally:
            self.events.append("authority-exit")
            if self.exit_fails:
                raise RuntimeError("exit failed")


class Lane:
    def __init__(self, pages, events):
        self.pages, self.events = list(pages), events
        self.owner = None
        self.commit_unknown = False
        self.cleanup_unknown = False
        self.root = False
        self.after_scan = None

    def attach(self):
        self.events.append("attach")

    def startup(self, expectation):
        self.events.append("readiness")

    def begin(self):
        self.root = True
        self.events.append("begin")

    def scan(self, config, cursor, project):
        self.events.append(("scan", cursor))
        answer = project(self.pages.pop(0))
        if self.after_scan:
            self.after_scan()
        if not self.pages:
            self.owner.request_stop()
        return answer

    def commit(self):
        self.events.append("commit-ack")
        if self.commit_unknown:
            raise RuntimeError("unknown")

    def finish_root(self):
        self.events.append("release-root")
        if self.cleanup_unknown:
            raise RuntimeError("uncertain cleanup")
        self.root = False

    def rollback(self):
        self.events.append("rollback-ack")

    def close(self):
        self.events.append("close")


def page(*, visited, cursor, exhausted, state=None):
    return SimpleNamespace(
        visited=visited,
        next_cursor=None if cursor is None else UUID(int=cursor),
        pass_exhausted=exhausted,
        items=() if state is None else (SimpleNamespace(state=state),),
    )


def owner(monkeypatch, pages):
    c = module()
    m = module("native_recovery")
    setup = module("native_recovery_setup")
    events = []
    lane = Lane(pages, events)
    app = Application(events)
    resources = c.NativeRecoveryResources(
        configuration=object(), connection=object(), ledger=object()
    )
    monkeypatch.setattr(setup, "_recheck_profile", lambda *args: None)
    monkeypatch.setattr(setup, "_validate_resources", lambda *args: None)
    monkeypatch.setattr(setup, "_adopt_resources", lambda *args: events.append("adopt"))
    monkeypatch.setattr(m, "_make_lane", lambda resources, config: lane)
    monkeypatch.setattr(m, "_domain_active", lambda: True)
    ticks = [0.0]
    monkeypatch.setattr(m, "_clock", lambda: ticks[0])
    monkeypatch.setattr(m, "_wait", lambda event, seconds: ticks.__setitem__(0, ticks[0] + seconds))
    result = m.create_job_recovery(
        config=config(discovery_budget=2), resources=resources, application=app
    )
    lane.owner = result
    return result, lane, app, events


@pytest.mark.requires_scalar_profile
def test_empty_progress_and_exhaustion_commit_cursor(monkeypatch):
    o, lane, app, events = owner(
        monkeypatch,
        [page(visited=2, cursor=9, exhausted=False), page(visited=0, cursor=9, exhausted=True)],
    )
    result = o.run(stop_event=Event())
    c = module()
    assert [e for e in events if isinstance(e, tuple)] == [("scan", None), ("scan", 9)]
    assert result.committed_pages == 2 and result.committed_sweeps == 1
    assert result.last_committed_raw_cursor == 9 and result.next_scan_after is None
    assert result.latest_page_outcome is c.RecoveryPageOutcome.COMMITTED
    assert result.clean_stop and not result.ready
    assert events.index("authority-enter") < events.index("begin")
    assert events.index("commit-ack") < events.index("authority-exit")
    o.dispose()
    with pytest.raises(RuntimeError):
        o.snapshot()


@pytest.mark.requires_scalar_profile
def test_unknown_commit_does_not_publish_or_cleanup(monkeypatch):
    o, lane, app, events = owner(
        monkeypatch, [page(visited=1, cursor=7, exhausted=False, state="held")]
    )
    lane.commit_unknown = True
    result = o.run(stop_event=Event())
    assert result.committed_pages == 0 and not result.has_committed_page
    assert result.unresolved and not result.clean_stop and "close" not in events
    with pytest.raises(RuntimeError):
        o.dispose()
    assert o.snapshot().unresolved


@pytest.mark.parametrize("where", ["authority", "release"])
@pytest.mark.requires_scalar_profile
def test_committed_cleanup_failure_preserves_counts(monkeypatch, where):
    o, lane, app, events = owner(
        monkeypatch, [page(visited=1, cursor=7, exhausted=False, state="held")]
    )
    if where == "authority":
        app.exit_fails = True
    else:
        lane.cleanup_unknown = True
    result = o.run(stop_event=Event())
    assert result.committed_pages == result.committed_held == 1
    assert result.next_scan_after == 7 and result.cleanup_unresolved
    assert result.unresolved and not result.clean_stop
    assert "rollback-ack" not in events and "close" not in events


@pytest.mark.requires_scalar_profile
def test_authority_denial_precedes_root(monkeypatch):
    o, lane, app, events = owner(monkeypatch, [page(visited=0, cursor=None, exhausted=True)])
    app.reject = True
    result = o.run(stop_event=Event())
    assert "begin" not in events and result.committed_pages == 0
    assert not result.ready


@pytest.mark.requires_scalar_profile
def test_observer_during_io_has_no_pending_graph_escape(monkeypatch):
    o, lane, app, events = owner(
        monkeypatch, [page(visited=1, cursor=7, exhausted=False, state="queued")]
    )
    snapshots = []
    lane.after_scan = lambda: snapshots.append(o.snapshot())
    result = o.run(stop_event=Event())
    assert snapshots[0].committed_pages == 0 and result.committed_pages == 1
    assert all(
        type(getattr(result, name)) in (bool, int, type(None))
        or type(getattr(result, name)).__module__.endswith("native_recovery_contracts")
        for name in result.__slots__
    )


@pytest.mark.parametrize(
    "bad",
    [
        page(visited=0, cursor=None, exhausted=False),
        page(visited=1, cursor=1, exhausted=False, state="cancelled"),
        page(visited=1, cursor=1, exhausted=True, state="held"),
    ],
)
@pytest.mark.requires_scalar_profile
def test_malformed_page_fails_closed(monkeypatch, bad):
    o, lane, app, events = owner(monkeypatch, [bad])
    result = o.run(stop_event=Event())
    assert result.committed_pages == 0 and not result.ready


@pytest.mark.requires_scalar_profile
def test_stop_before_run_no_adoption(monkeypatch):
    o, lane, app, events = owner(monkeypatch, [])
    o.request_stop()
    result = o.run(stop_event=Event())
    assert "adopt" not in events and result.clean_stop
    with pytest.raises(RuntimeError):
        o.run(stop_event=Event())


@pytest.mark.requires_scalar_profile
def test_unknown_root_retains_authority_lifetime(monkeypatch):
    o, lane, app, events = owner(
        monkeypatch, [page(visited=1, cursor=7, exhausted=False, state="held")]
    )
    lane.commit_unknown = True
    result = o.run(stop_event=Event())
    assert "authority-enter" in events and "authority-exit" not in events
    assert result.native_in_flight and result.unresolved


@pytest.mark.requires_scalar_profile
def test_live_domain_stop_removes_readiness(monkeypatch):
    o, lane, app, events = owner(
        monkeypatch, [page(visited=1, cursor=7, exhausted=False, state="held")]
    )
    m = module("native_recovery")
    observed = []

    def stop_domain():
        monkeypatch.setattr(m, "_domain_active", lambda: False)
        observed.append(o.snapshot())

    lane.after_scan = stop_domain
    result = o.run(stop_event=Event())
    assert not observed[0].domain_active and not observed[0].ready
    assert result.committed_pages == 0 and result.unresolved


@pytest.mark.requires_scalar_profile
def test_stop_during_profile_prevents_adoption(monkeypatch):
    o, lane, app, events = owner(monkeypatch, [])
    app.validate_profile = lambda namespace: o.request_stop()
    result = o.run(stop_event=Event())
    assert "adopt" not in events and "attach" not in events
    assert result.clean_stop


@pytest.mark.requires_scalar_profile
def test_non_none_commit_is_not_success(monkeypatch):
    o, lane, app, events = owner(
        monkeypatch, [page(visited=1, cursor=7, exhausted=False, state="held")]
    )
    lane.commit = lambda: True
    result = o.run(stop_event=Event())
    assert result.committed_pages == 0 and result.unresolved


@pytest.mark.requires_scalar_profile
def test_factory_revalidates_forged_namespace_before_hooks():
    m = module("native_recovery")
    value = config()
    object.__setattr__(value, "namespace", b"tenant")
    with pytest.raises(ValueError, match="namespace"):
        m.create_job_recovery(config=value, resources=object(), application=object())


@pytest.mark.requires_scalar_profile
def test_exported_scalar_snapshot_is_independent(monkeypatch):
    o, lane, app, events = owner(monkeypatch, [page(visited=0, cursor=None, exhausted=True)])
    before = o.snapshot()
    object.__setattr__(before, "committed_pages", 123)
    result = o.run(stop_event=Event())
    assert result.committed_pages == 1 and result is not before


@pytest.mark.requires_scalar_profile
def test_public_snapshot_rejects_non_scalar_values(monkeypatch):
    from dataclasses import replace

    o, lane, app, events = owner(monkeypatch, [])
    with pytest.raises(ValueError):
        replace(o.snapshot(), committed_pages=True)
    with pytest.raises(ValueError):
        replace(o.snapshot(), phase="NEW")


@pytest.mark.requires_scalar_profile
def test_large_finite_timeout_preserves_configuration_contract():
    assert config(progress_timeout_seconds=100000.0).progress_timeout_seconds == 100000.0


@pytest.mark.parametrize("elapsed,code", [(29.0, 0), (30.0, 70), (31.0, 70)])
@pytest.mark.parametrize("stage", ["scan", "commit", "close"])
@pytest.mark.requires_scalar_profile
def test_authoritative_drain_deadline(monkeypatch, elapsed, code, stage):
    o, lane, app, events = owner(
        monkeypatch, [page(visited=1, cursor=7, exhausted=False, state="held")]
    )
    m = module("native_recovery")
    clock = [0.0]
    monkeypatch.setattr(m, "_clock", lambda: clock[0])

    def overrun():
        o.request_stop()
        clock[0] = elapsed

    if stage == "scan":
        lane.after_scan = overrun
    elif stage == "commit":
        lane.commit = overrun
    else:
        lane.close = overrun
    assert m.run_recovery_host(o, stop_event=Event()) == code
    result = o.snapshot()
    assert result.committed_pages == 1
    assert result.clean_stop is (code == 0)
    assert result.unresolved is (code != 0)
    if code == 0:
        clock[0] = 100.0
        assert o.snapshot().reason is module().RecoveryReason.NONE


@pytest.mark.parametrize("stage", ["scan", "commit", "wait"])
@pytest.mark.requires_scalar_profile
def test_owner_clock_regression_is_sticky(monkeypatch, stage):
    o, lane, app, events = owner(
        monkeypatch,
        [page(visited=2, cursor=7, exhausted=False), page(visited=0, cursor=7, exhausted=True)],
    )
    m = module("native_recovery")
    clock = [2.0]
    monkeypatch.setattr(m, "_clock", lambda: clock[0])
    if stage == "scan":
        lane.after_scan = lambda: (clock.__setitem__(0, 1.0), o.request_stop())
    elif stage == "commit":

        def regressed_commit():
            clock[0] = 1.0
            o.request_stop()

        lane.commit = regressed_commit
    else:
        monkeypatch.setattr(m, "_wait", lambda *args: (clock.__setitem__(0, 1.0), o.request_stop()))
    result = o.run(stop_event=Event())
    assert result.reason is module().RecoveryReason.INTERNAL_FAILURE
    assert not result.clean_stop and result.unresolved
    assert result.committed_pages == (0 if stage == "scan" else 1)


@pytest.mark.requires_scalar_profile
def test_final_export_fault_prevents_host_success(monkeypatch):
    o, lane, app, events = owner(monkeypatch, [page(visited=0, cursor=None, exhausted=True)])
    m = module("native_recovery")
    monkeypatch.setattr(m, "_clock", lambda: 2.0)
    original = m.JobRecoveryOwner.snapshot

    def export(self):
        monkeypatch.setattr(m, "_clock", lambda: 1.0)
        return original(self)

    monkeypatch.setattr(m.JobRecoveryOwner, "snapshot", export)
    assert m.run_recovery_host(o, stop_event=Event()) == 70
    for _ in range(2):
        result = original(o)
        assert result.reason is module().RecoveryReason.INTERNAL_FAILURE
        assert result.unresolved and not result.clean_stop
        assert result.committed_pages == 1


@pytest.mark.requires_scalar_profile
def test_status_postcandidate_sample_fault_is_authoritative(monkeypatch):
    o, lane, app, events = owner(monkeypatch, [])
    m = module("native_recovery")
    values = iter((2.0, 1.0))
    monkeypatch.setattr(m, "_clock", lambda: next(values, 1.0))
    o._status(phase=module().RecoveryPhase.STOPPED, clean=True)
    result = o.snapshot()
    assert result.reason is module().RecoveryReason.INTERNAL_FAILURE
    assert result.unresolved and not result.clean_stop


@pytest.mark.requires_scalar_profile
def test_clock_sample_compare_publication_share_owner_lock(monkeypatch):
    o, lane, app, events = owner(monkeypatch, [])
    m = module("native_recovery")
    sampled = []

    def clock():
        sampled.append(getattr(o._lock, "_is_owned", lambda: False)())
        return 2.0

    monkeypatch.setattr(m, "_clock", clock)
    o._observe_time()
    o.snapshot()
    o.request_stop()
    assert sampled and all(sampled)
    assert o._last_clock == 2.0 and not o._clock_failed


class NativeAPI:
    """Structural interface double; no driver or registry code is imported."""

    def __init__(self):
        self.events = []
        self.fail = None
        self.payload = None
        self.CommitOutcome = SimpleNamespace(COMMITTED=object())
        self.outcome = self.CommitOutcome.COMMITTED
        self.checkout = SimpleNamespace(start_root=self.start_root)
        self.root = SimpleNamespace(commit=self.commit)
        self.permit = SimpleNamespace(close=lambda **kw: self.call("physical-close"))

    def call(self, name, *args, **kwargs):
        self.events.append((name, args, kwargs))
        if self.fail == name:
            raise RuntimeError("injected unknown")
        return object()

    def __getattr__(self, name):
        return lambda *args, **kw: self.call(name, *args, **kw)

    def attach_native(self, *args, **kwargs):
        self.call("attach_native", *args, **kwargs)
        return self.checkout

    def start_root(self, **kwargs):
        self.call("start_root", **kwargs)
        return self.root

    def commit(self, **kwargs):
        return self.call("commit", **kwargs)

    def acknowledge_commit_result(self, *args, **kwargs):
        self.call("acknowledge_commit_result", *args, **kwargs)
        return self.outcome

    def read_result(self, *args, **kwargs):
        self.call("read_result", *args, **kwargs)
        return self.payload

    def pin_cleanup(self, *args, **kwargs):
        self.call("pin_cleanup", *args, **kwargs)
        return self.permit


def real_lane(monkeypatch):
    lifecycle = module("_native_recovery_lifecycle")
    assert hasattr(lifecycle, "_NativeRecoveryLane"), "S2 native lane is absent"
    api = NativeAPI()
    monkeypatch.setattr(lifecycle, "_recovery_api", lambda: (api, api))
    requirements = SimpleNamespace(
        e13_preparation_min=101, e13_result_min=202, e33_preparation_min=303, e33_result_min=404
    )
    resources = SimpleNamespace(connection=object(), ledger=object())
    lane = lifecycle._NativeRecoveryLane(resources, requirements)
    return lane, api


def native_page(state=None):
    from datetime import datetime, timedelta, timezone

    from modkit_events.persistence import bindings as b
    from modkit_events.persistence import models as models
    from modkit_events.persistence.observations import ScanPage, WorkObservation
    from modkit_events.persistence.scope import Scope, canonical_scope

    if state is None:
        return ScanPage(items=(), visited=0, next_cursor=None, pass_exhausted=True)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    material = models.ProtectedBindingInput(
        material_state=models.MaterialState.ABSENT,
        codec=None,
        key_version=None,
        expires_at=None,
        cleanup_policy=models.CleanupPolicy.RETAIN,
        sidecar=None,
        reference=None,
        content_binding=b"",
        recovery_metadata=b"",
        projection_metadata={},
    )
    admission = models.AdmissionInput(
        identity=models.WorkIdentity(
            work_id=UUID(int=7),
            kind=models.WorkKind.JOB,
            subscription_id=None,
            namespace="jobs",
            command_type="task",
            scope=models.ScopeEvidence(
                canonical_version=1,
                canonical=canonical_scope(Scope("recovery-test")),
                application=b"recovery-test",
                tenant=None,
                owner=None,
            ),
            idempotency_key=None,
        ),
        schema_version=1,
        semantic_input=b.canonical_json({"source": "recovery-lifetime"}),
        replay_input=b'{"source":"recovery-lifetime"}',
        protected_binding=b.canonical_protected_binding(material).content,
        replay_policy=models.ReplayPolicy.DISABLED,
        max_attempts=3,
        deadline=now + timedelta(seconds=1) if state == "expired" else None,
        original_available_at=now,
    )
    fields = b._admission_values(admission)
    fields.update(
        schema_version_decimal=b"1",
        runnable_version=1,
        state=state,
        cancellation_requested=False,
        token=None,
        ownership_revision=2,
        lease_until=None,
        available_at=now,
        cycle=1,
        attempt_count={"queued": 0, "expired": 0, "failed": 3, "held": 1}[state],
        dispatch_id=UUID(int=8) if state == "held" else None,
        result=None,
        created_at=now,
        updated_at=now + timedelta(seconds=2),
        success_origin=None,
        completion_guard_id=None,
        final_fence_at=None,
        completion_result_digest=None,
        resolution_operation_id=None,
        terminal_resolution_operation_id=None,
        resolution=None,
    )
    work = WorkObservation(**fields)
    return ScanPage(items=(work,), visited=1, next_cursor=work.work_id, pass_exhausted=False)


@pytest.mark.requires_scalar_profile
def test_s2_lane_exact_serial_issuance_and_cleanup(monkeypatch):
    lane, api = real_lane(monkeypatch)
    lane.attach()
    lane.startup(config().readiness)
    lane.begin()
    api.payload = native_page()
    observed = []
    lane.scan(config(), 7, lambda p: observed.append(p.visited))
    lane.commit()
    lane.finish_root()
    lane.close()
    names = [e[0] for e in api.events]
    assert observed == [0]
    assert names.count("start_root") == names.count("release_root") == 2
    assert names.index("prepare_readiness") < names.index("prepare_recovery")
    recovery = next(e[2] for e in api.events if e[0] == "prepare_recovery")
    assert recovery == dict(
        execution_ledger=lane.ledger,
        capacity=101,
        namespace=b"jobs",
        kind="job",
        limit=1,
        scan_after=UUID(int=7),
        discovery_budget=128,
    )
    assert [e[1][1] for e in api.events if e[0] == "reserve_result"] == [404, 202]
    tail = names[names.index("retire") :]
    assert tail == [
        "retire",
        "prepare_cleanup",
        "reserve_cleanup",
        "pin_cleanup",
        "physical-close",
        "acknowledge_physical_close",
        "release_cleanup",
        "detach_terminal",
        "dispose_execution",
    ]
    assert next(e[1][1] for e in api.events if e[0] == "reserve_cleanup") == 4096
    assert lane.closed and lane.execution is lane.checkout is lane.root is None


@pytest.mark.parametrize(
    "failure",
    [
        "admit",
        "reserve_result",
        "execute",
        "read_result",
        "release_result",
        "release_ticket",
        "release_preparation",
        "commit",
        "acknowledge_commit_result",
        "release_root",
    ],
)
@pytest.mark.requires_scalar_profile
def test_s2_lane_failure_retains_no_retry_or_cleanup(monkeypatch, failure):
    lane, api = real_lane(monkeypatch)
    lane.attach()
    lane.begin()
    api.payload = native_page()
    api.fail = failure
    with pytest.raises(RuntimeError):
        lane.scan(config(), None, lambda value: None)
        lane.commit()
        lane.finish_root()
    count = len(api.events)
    with pytest.raises(RuntimeError):
        lane.close()
    assert len(api.events) == count


def test_s2_unknown_commit_never_releases_root(monkeypatch):
    lane, api = real_lane(monkeypatch)
    lane.attach()
    lane.begin()
    api.outcome = object()
    with pytest.raises(RuntimeError):
        lane.commit()
    assert lane.root is not None


@pytest.mark.requires_scalar_profile
@pytest.mark.parametrize("state", [None, "queued", "expired", "failed", "held"])
def test_s2_projection_failure_keeps_result_charged(monkeypatch, state):
    lane, api = real_lane(monkeypatch)
    lane.attach()
    lane.begin()
    api.payload = native_page(state)

    def reject(value):
        raise ValueError("projection failed")

    with pytest.raises(ValueError):
        lane.scan(config(), None, reject)
    assert lane.result is not None
    assert "release_result" not in [e[0] for e in api.events]


@pytest.mark.parametrize(
    "failure",
    [
        "retire",
        "prepare_cleanup",
        "reserve_cleanup",
        "pin_cleanup",
        "physical-close",
        "acknowledge_physical_close",
        "release_cleanup",
        "detach_terminal",
        "dispose_execution",
    ],
)
def test_s2_cleanup_unknown_stops_without_replacement(monkeypatch, failure):
    lane, api = real_lane(monkeypatch)
    lane.attach()
    api.fail = failure
    with pytest.raises(RuntimeError):
        lane.close()
    count = len(api.events)
    with pytest.raises(RuntimeError):
        lane.close()
    assert len(api.events) == count and not lane.closed


@pytest.mark.requires_scalar_profile
def test_s2_noncanonical_page_never_releases_result(monkeypatch):
    lane, api = real_lane(monkeypatch)
    lane.attach()
    lane.begin()
    api.payload = page(visited=0, cursor=None, exhausted=True)
    with pytest.raises(ValueError, match="exact native"):
        lane.scan(config(), None, lambda value: pytest.fail("unvalidated graph escaped"))
    assert lane.result is not None and lane.failed


@pytest.mark.requires_scalar_profile
@pytest.mark.parametrize("state", [None, "queued", "expired", "failed", "held"])
@pytest.mark.parametrize("committed", [True, False])
def test_s2_owner_drives_real_lane_authority_through_ack(monkeypatch, state, committed):
    lifecycle = module("_native_recovery_lifecycle")
    setup = module("native_recovery_setup")
    m = module("native_recovery")
    c = module()
    api = NativeAPI()
    api.payload = native_page(state)
    req = SimpleNamespace(
        e13_preparation_min=101, e13_result_min=202, e33_preparation_min=303, e33_result_min=404
    )
    monkeypatch.setattr(lifecycle, "_recovery_api", lambda: (api, api))
    monkeypatch.setattr(setup, "_recheck_profile", lambda *args: req)
    monkeypatch.setattr(setup, "_validate_resources", lambda *args: None)
    monkeypatch.setattr(setup, "_adopt_resources", lambda *args: None)
    monkeypatch.setattr(m, "_domain_active", lambda: True)
    monkeypatch.setattr(m, "_clock", lambda: 0.0)
    resources = c.NativeRecoveryResources(
        configuration=object(), connection=object(), ledger=object()
    )

    original_acknowledge = api.acknowledge_commit_result
    acknowledged = []

    def acknowledge(receipt, **kwargs):
        recovering = any(event[0] == "prepare_recovery" for event in api.events)
        if recovering:
            before = o.snapshot()
            assert_unpublished_summary(before)
            assert before.latest_page_outcome is c.RecoveryPageOutcome.PENDING
            api.outcome = api.CommitOutcome.COMMITTED if committed else object()
        outcome = original_acknowledge(receipt, **kwargs)
        if recovering:
            acknowledged.append(committed)
        return outcome

    api.acknowledge_commit_result = acknowledge

    def release(result, *, execution_ledger):
        if any(event[0] == "prepare_recovery" for event in api.events):
            assert o._pending is not None
            assert_no_adapter_graph_aliases(api, state)
        api.call("release_result", result, execution_ledger=execution_ledger)

    api.release_result = release

    class App:
        def validate_profile(self, namespace):
            assert namespace == b"jobs"

        @contextmanager
        def authorize_root(self, connection, namespace):
            assert connection is resources.connection and namespace == b"jobs"
            api.call("authority-enter")
            yield
            api.call("authority-exit")
            o.request_stop()

    o = m.create_job_recovery(config=config(), resources=resources, application=App())
    assert m.run_recovery_host(o, stop_event=Event()) == (0 if committed else 70)
    # The owner catches callback failures, so UNKNOWN alone is not this oracle.
    assert acknowledged == [committed]
    names = [e[0] for e in api.events]
    assert names.index("authority-enter") < names.index("prepare_recovery")
    result = o.snapshot()
    if not committed:
        assert "authority-exit" not in names and "retire" not in names
        assert o._authority is not None and o._lane.root is not None
        assert_unpublished_summary(result)
        assert result.latest_page_outcome is c.RecoveryPageOutcome.UNKNOWN
        assert result.unresolved and not result.clean_stop
        with pytest.raises(RuntimeError, match="quiescent"):
            o.dispose()
        return
    assert names.index("authority-exit") > max(
        i for i, n in enumerate(names) if n == "acknowledge_commit_result"
    )
    assert result.committed_pages == 1 and result.clean_stop
    assert result.committed_visited == (0 if state is None else 1)
    assert result.last_committed_raw_cursor == (None if state is None else 7)
    assert result.next_scan_after == (None if state is None else 7)
    assert result.committed_sweeps == int(state is None)
    assert (
        result.committed_queued,
        result.committed_expired,
        result.committed_failed,
        result.committed_held,
    ) == {
        None: (0, 0, 0, 0),
        "queued": (1, 0, 0, 0),
        "expired": (0, 1, 0, 0),
        "failed": (0, 0, 1, 0),
        "held": (0, 0, 0, 1),
    }[state]
    o.dispose()


def assert_unpublished_summary(snapshot):
    assert not snapshot.has_committed_page
    assert snapshot.last_committed_raw_cursor is snapshot.next_scan_after is None
    assert not snapshot.last_committed_pass_exhausted
    assert (
        snapshot.committed_pages,
        snapshot.committed_sweeps,
        snapshot.committed_visited,
        snapshot.committed_queued,
        snapshot.committed_expired,
        snapshot.committed_failed,
        snapshot.committed_held,
        snapshot.last_committed_visited,
        snapshot.last_committed_queued,
        snapshot.last_committed_expired,
        snapshot.last_committed_failed,
        snapshot.last_committed_held,
    ) == (0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)


def assert_no_adapter_graph_aliases(api, state):
    import sys

    # Only the test-native registry's field plus getrefcount's argument.
    # Any adapter page/frame alias would add another occurrence.
    refs = sys.getrefcount(api.payload)  # Outside pytest assertion rewrite temporaries.
    assert refs == 2
    if state is not None:
        # No validation-loop item, tuple, or payload alias may outlive B.
        item_refs = sys.getrefcount(api.payload.items[0])
        tuple_refs = sys.getrefcount(api.payload.items)
        payload_refs = sys.getrefcount(api.payload.items[0].semantic_input)
        assert item_refs == tuple_refs == payload_refs == 2


@pytest.mark.requires_scalar_profile
@pytest.mark.parametrize("state", [None, "queued", "expired", "failed", "held"])
def test_s2_result_alias_dropped_before_release(monkeypatch, state):
    lane, api = real_lane(monkeypatch)
    lane.attach()
    lane.begin()
    api.payload = native_page(state)

    def release(result, *, execution_ledger):
        assert_no_adapter_graph_aliases(api, state)
        api.call("release_result", result, execution_ledger=execution_ledger)

    api.release_result = release
    lane.scan(config(), None, lambda value: None)
    assert lane.result is None
