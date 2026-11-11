"""Real source orchestration with test-only native I/O seams; no DB connections."""

import importlib
from contextlib import contextmanager
from dataclasses import replace

import pytest
from test_native_public_contracts import config_values

from modkit_workers.handlers import HandlerKind, HandlerRegistration, HandlerRegistry
from modkit_workers.native_contracts import (
    NativeJobConfig,
    NativeJobResources,
    NativeWorkerSettings,
)


def source_module():
    m = importlib.import_module("modkit_workers.native_job")
    assert hasattr(m, "JobWorkSource"), "concrete JobWorkSource missing"
    return m


class Control:
    settings = NativeWorkerSettings(renewal_interval_seconds=1)
    stop_requested = False

    def __init__(self):
        self.trace = []
        self.work = None
        self.pending = None

    def admit_startup(self, source):
        pass

    def reserve_acquisition(self, source):
        assert self.pending is None and self.work is None
        self.trace.append("reserve")
        self.pending = object()
        return self.pending

    def require_reserved_acquisition(self, source, token):
        assert token is self.pending

    def require_admission(self, source, *, kind):
        self.trace.append(kind.value)

    def publish_acquisition(self, token, work):
        assert token is self.pending
        self.trace.append("publish")
        self.pending = None
        self.work = work

    def refuse_acquisition(self, token, *, reason):
        assert token is self.pending
        self.trace.append("refuse")
        self.pending = None

    def activate(self, work, fence):
        assert work is self.work
        self.trace.append("activate")

    def close_renewal(self, work):
        assert work is self.work
        self.trace.append("close-renewal")
        return work

    def await_renewal_quiescent(self, token, *, deadline_monotonic):
        from modkit_workers.native_contracts import RenewalQuiescence

        self.trace.append("quiescent")
        return RenewalQuiescence(True, True, True)

    def retire_work(self, work):
        assert work is self.work
        self.trace.append("retire")
        self.work = None

    def fail(self, reason):
        self.trace.append(("fail", reason))


class App:
    def __init__(self):
        self.profiles = []
        self.contexts = []

    def validate_profile(self, request):
        self.profiles.append(request)

    def bind(self, root, context):
        self.contexts.append(context)

        class Binding:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def result(self):
                return b"done"

        return Binding()


def make_source(handler=lambda context: None):
    m = source_module()
    app = App()
    control = Control()
    registry = HandlerRegistry(
        [
            HandlerRegistration(
                command_type="send", schema_version=1, handler=handler, kind=HandlerKind.SYNC
            )
        ]
    )
    resources = NativeJobResources(
        configuration=object(),
        data_connection=object(),
        renewal_connection=object(),
        data_ledger=object(),
        renewal_ledger=object(),
    )
    source = m.JobWorkSource(
        registry=registry,
        application=app,
        config=NativeJobConfig(**config_values()),
        resources=resources,
        control=control,
    )
    return source, app, control


def test_constructor_is_inert_and_source_owned_renewal_preserves_protocol():
    from modkit_workers.work_source import RenewalOwner

    source, app, control = make_source()
    assert source.renewal_owner is RenewalOwner.SOURCE
    assert not source.snapshot().resources_adopted
    assert not source.snapshot().startup_verified
    assert app.profiles == [] and control.trace == []
    assert source.request_stop() is None
    assert source.snapshot().admission_closed


def test_source_rejects_acquisition_before_startup_without_slot_or_material():
    from modkit_events.persistence.models import Capability

    from modkit_workers.work_source import AcquireRequest

    source, app, control = make_source()
    req = AcquireRequest(
        capabilities=[Capability(command_type="send", schema_version=1)],
        limit=1,
        discovery_budget=1,
    )
    with pytest.raises(RuntimeError):
        source.acquire(req)
    assert control.pending is None and not source.snapshot().slot_occupied


class Lane:
    def __init__(self, page=None, *, commit_unknown=False):
        self.page = page
        self.trace = []
        self.commit_unknown = commit_unknown
        self.connection = object()
        self.failed_root = None
        self.rollback_receipt = None

    def begin(self, check):
        check()
        self.trace.append("begin")

    def acquire(self, request, *, budget, project, check):
        check()
        self.trace.append("W05")
        try:
            return project(self.page)
        finally:
            self.trace.append("release-W05")

    def commit(self, check):
        check()
        self.trace.append("commit")
        if self.commit_unknown:
            raise RuntimeError("secret transport message")

    def rollback(self, check, *, strict=False):
        check()
        self.trace.append("strict-rollback" if strict else "rollback")
        if strict:
            self.failed_root = object()
            self.rollback_receipt = object()
        return self.rollback_receipt

    def finish_failed_root(self):
        self.trace.append("release-failed-root")
        self.failed_root = None

    def statement(
        self,
        key,
        parameters,
        *,
        expected,
        capacity,
        result_capacity,
        project,
        check,
        failure_binding=None,
    ):
        check()
        self.trace.append(key)
        if key == "E06":
            value = expected[0].expected_attempt + 1
        elif key == "E14":
            value = 42
        elif key == "E08":
            from uuid import UUID

            from modkit_events.persistence.observations import GuardRow

            f = expected[0]
            value = GuardRow(
                guard_id=UUID(int=7),
                work_id=f.work_id,
                root_xid=42,
                token=f.token,
                ownership_revision=f.ownership_revision,
                cycle=f.cycle,
                expected_attempt=f.expected_attempt,
                satisfied=False,
                final_fence_at=None,
                terminal_state=None,
                result_digest=None,
            )
        elif key == "E05":
            from datetime import UTC, datetime

            value = datetime(2030, 1, 1, tzinfo=UTC)
        else:
            value = True
        if key == "E11":
            assert failure_binding == (self.failed_root, self.rollback_receipt)
        answer = project(value)
        self.trace.append("release-" + key)
        return answer

    def finish_root(self):
        self.trace.append("release-root")


def acquired_page(*, empty=False, protected=False):
    from modkit_events.persistence.models import MaterialState
    from test_job_acquisition import frame, request
    from test_job_persistence_contracts import full_job_row, job

    from modkit_workers.persistence import rows

    page = rows.decode_acquire(
        request(limit=1),
        frame(
            *(() if empty else (full_job_row(job(), state="claimed", attempt=0),)),
            visited=1,
            exhausted=False,
        ),
    )
    if protected:
        object.__setattr__(page.items[0].record.payload, "material_state", MaterialState.ERASED)
    return page


def ready_source(page, **lane_options):
    from modkit_events.persistence.models import Capability

    from modkit_workers.work_source import AcquireRequest

    source, app, control = make_source()
    request = AcquireRequest(
        capabilities=[Capability(command_type="send", schema_version=1)],
        limit=1,
        discovery_budget=1,
    )
    source._request = request
    source._started = True
    source._data = Lane(page, **lane_options)
    return source, app, control, request


def test_confirmed_acquisition_detaches_releases_then_commits_before_publication():
    source, app, control, request = ready_source(acquired_page())
    batch = source.acquire(request)
    assert len(batch) == 1 and control.work is batch[0]
    assert source._data.trace == ["begin", "W05", "release-W05", "commit", "release-root"]
    assert control.trace == ["reserve", "publish"]
    assert source._material.reserved and source.snapshot().slot_occupied


def test_confirmed_empty_progress_is_not_exhaustion():
    page = acquired_page(empty=True)
    source, app, control, request = ready_source(page)
    assert source.acquire(request) == ()
    assert source._cursor == page.next_cursor
    assert source.snapshot().scan_progress and not source.snapshot().scan_exhausted
    assert not source._material.reserved and control.pending is None


def test_known_profile_refusal_rolls_back_not_publish_empty_or_failed_job():
    source, app, control, request = ready_source(acquired_page(protected=True))
    assert source.acquire(request) == ()
    assert "rollback" in source._data.trace and "commit" not in source._data.trace
    assert control.trace == ["reserve", "refuse"]
    assert not source._material.reserved
    state = source.snapshot()
    assert not state.unresolved and state.confirmed_failed == 0
    assert state.reason.value == "profile_unsupported"


def test_unknown_acquire_commit_retains_reservation_and_detached_charge():
    source, app, control, request = ready_source(acquired_page(), commit_unknown=True)
    with pytest.raises(source_module().NativeJobUnresolved) as caught:
        source.acquire(request)
    assert "secret" not in str(caught.value) and caught.value.__context__ is None
    assert control.pending is not None and control.work is None
    assert source._material.reserved and source.snapshot().unresolved
    assert "publish" not in control.trace and "refuse" not in control.trace


def test_real_native_adapter_drops_borrowed_result_before_release_then_commit(monkeypatch):
    from enum import Enum

    from modkit_events.persistence import bindings, catalog

    from modkit_workers import _native_job_lifecycle as life

    assert hasattr(life, "_NativeLane"), "actual native adapter is missing"
    trace = []
    payload = object()

    class Outcome(Enum):
        COMMITTED = 1

    class Root:
        def commit(self, **kw):
            trace.append("commit")
            return object()

    class Managed:
        CommitOutcome = Outcome

        def admit(self, *a, **kw):
            return object()

        def reserve_result(self, *a, **kw):
            return object()

        def read_result(self, *a, **kw):
            trace.append("read")
            return payload

        def release_result(self, *a, **kw):
            trace.append("release-B")

        def release_ticket(self, *a, **kw):
            trace.append("release-ticket")

        def release_preparation(self, *a, **kw):
            trace.append("release-A")

        def acknowledge_commit_result(self, *a, **kw):
            trace.append("ack")
            return Outcome.COMMITTED

    class Native:
        def prepare(self, *a, **kw):
            trace.append("prepare")
            return object()

        def execute(self, *a, **kw):
            trace.append("execute")

    monkeypatch.setattr(life, "_native_api", lambda: (Managed(), Native(), bindings, catalog))
    lane = life._NativeLane(object(), object())
    lane.execution = object()
    lane.root = Root()

    def project(value):
        assert value is payload
        trace.append("detach")
        return 7

    answer = lane.statement(
        "E14",
        (),
        expected=(),
        capacity=184,
        result_capacity=36,
        project=project,
        check=lambda: None,
    )
    assert answer == 7
    lane.commit(lambda: None)
    assert trace == [
        "prepare",
        "execute",
        "read",
        "detach",
        "release-B",
        "release-ticket",
        "release-A",
        "commit",
        "ack",
    ]


def test_native_projection_known_refusal_releases_statement_but_never_finalizes_root(monkeypatch):
    from modkit_events.persistence import bindings, catalog

    from modkit_workers import _native_job_lifecycle as life

    assert hasattr(life, "_NativeLane"), "actual native adapter is missing"
    trace = []

    class Managed:
        def admit(self, *a, **kw):
            return object()

        def reserve_result(self, *a, **kw):
            return object()

        def read_result(self, *a, **kw):
            return object()

        def release_result(self, *a, **kw):
            trace.append("release-B")

        def release_ticket(self, *a, **kw):
            trace.append("release-ticket")

        def release_preparation(self, *a, **kw):
            trace.append("release-A")

    class Native:
        def prepare(self, *a, **kw):
            return object()

        def execute(self, *a, **kw):
            pass

    monkeypatch.setattr(life, "_native_api", lambda: (Managed(), Native(), bindings, catalog))
    lane = life._NativeLane(object(), object())
    lane.execution = object()
    lane.root = object()

    def reject(value):
        raise life.UnsupportedJobProfile("unsupported")

    with pytest.raises(life.UnsupportedJobProfile):
        lane.statement(
            "E14",
            (),
            expected=(),
            capacity=184,
            result_capacity=36,
            project=reject,
            check=lambda: None,
        )
    assert trace == ["release-B", "release-ticket", "release-A"]
    assert lane.root is not None


def test_native_adapter_strict_rollback_retains_original_root_for_same_checkout(monkeypatch):
    from modkit_events.persistence import bindings, catalog

    from modkit_workers import _native_job_lifecycle as life

    assert hasattr(life, "_NativeLane"), "actual native adapter is missing"
    trace = []
    original = object()
    receipt = object()

    class Root:
        def rollback(self, *, execution_ledger, confirm_failure=False):
            trace.append(("rollback", confirm_failure))
            return receipt

    root = Root()

    class Checkout:
        def start_root(self, **kw):
            trace.append("begin")
            return root

    checkout = Checkout()

    class Managed:
        def reserve_execution(self, ledger):
            trace.append("reserve-X")
            return object()

        def attach_native(self, actual, execution, **kw):
            assert actual is original
            trace.append("attach")
            return checkout

        def acknowledge_root_end(self, value, **kw):
            assert value is receipt
            trace.append("ack-rollback")

        def release_root(self, value, **kw):
            assert value is root
            trace.append("release-root")

    monkeypatch.setattr(life, "_native_api", lambda: (Managed(), None, bindings, catalog))
    lane = life._NativeLane(original, object())
    lane.attach(lambda: None)
    lane.begin(lambda: None)
    assert lane.rollback(lambda: None, strict=True) is receipt
    assert lane.failed_root is root and lane.root is None
    assert "release-root" not in trace
    lane.finish_failed_root()
    assert trace == [
        "reserve-X",
        "attach",
        "begin",
        ("rollback", True),
        "ack-rollback",
        "release-root",
    ]


def test_success_dispatch_ack_precedes_handler_and_terminal_quiescence():
    source, app, control, request = ready_source(acquired_page())
    (work,) = source.acquire(request)
    assert source.execute(work) is None
    trace = source._data.trace
    assert trace.index("E06") < trace.index("E08") < trace.index("E10")
    assert trace[trace.index("E06") + 2 : trace.index("E08")].count("commit") == 1
    assert (
        control.trace.index("activate")
        < control.trace.index("close-renewal")
        < control.trace.index("retire")
    )
    assert source.snapshot().confirmed_succeeded == 1 and not source.snapshot().unresolved
    assert not source._material.reserved and control.work is None


def test_safe_business_failure_is_ordinary_confirmed_failed_not_controller_fail():
    def bad(context):
        raise RuntimeError("application secret")

    source, app, control, request = ready_source(acquired_page())
    from modkit_workers.handlers import HandlerKind, HandlerRegistration, HandlerRegistry

    source._registry = HandlerRegistry(
        [
            HandlerRegistration(
                command_type="send", schema_version=1, handler=bad, kind=HandlerKind.SYNC
            )
        ]
    )
    (work,) = source.acquire(request)
    assert source.execute(work) is None
    trace = source._data.trace
    assert trace.index("strict-rollback") < trace.index("E11") < trace.index("release-failed-root")
    assert "E10" not in trace
    assert source.snapshot().confirmed_failed == 1 and not source.snapshot().unresolved
    assert not any(type(x) is tuple and x[0] == "fail" for x in control.trace)
    assert control.work is None


def test_unknown_dispatch_commit_never_enters_application_or_activates_renewal():
    source, app, control, request = ready_source(acquired_page())
    (work,) = source.acquire(request)
    source._data.commit_unknown = True
    with pytest.raises(source_module().NativeJobUnresolved):
        source.execute(work)
    assert app.contexts == [] and "activate" not in control.trace
    assert control.work is work and source._material.reserved


def test_blocked_renewal_quiescence_never_runs_terminal_sql():
    from modkit_workers.native_contracts import RenewalQuiescence

    source, app, control, request = ready_source(acquired_page())
    (work,) = source.acquire(request)
    control.await_renewal_quiescent = lambda token, **kw: RenewalQuiescence(False, False, True)
    with pytest.raises(source_module().NativeJobUnresolved):
        source.execute(work)
    assert "E10" not in source._data.trace and "E11" not in source._data.trace
    assert source._material.reserved and control.work is work


def test_explicit_cancel_before_dispatch_retains_claim_without_false_outcome():
    source, app, control, request = ready_source(acquired_page())
    (work,) = source.acquire(request)
    assert source.cancel(work) is None
    with pytest.raises(source_module().NativeJobUnresolved):
        source.execute(work)
    assert "E06" not in source._data.trace and source.snapshot().confirmed_cancelled == 0
    assert source._material.reserved and control.work is work


def setup_startup_seams(monkeypatch, source, *, attach_fail=False):
    from modkit_workers import _native_job_lifecycle as life
    from modkit_workers import native_setup

    trace = []
    association = []
    monkeypatch.setattr(
        native_setup, "_validate_resources", lambda *a, **kw: trace.append("validate")
    )

    def adopt(resources, owner):
        trace.append("adopt")
        association.append(owner)

    monkeypatch.setattr(native_setup, "_adopt_resources", adopt)
    monkeypatch.setattr(
        native_setup, "_resources_adopted", lambda resources, owner: owner in association
    )

    class StartupLane:
        def __init__(self, connection, ledger):
            self.connection = connection
            self.closed = False

        def attach(self, check):
            check()
            trace.append("attach")
            if attach_fail:
                raise RuntimeError("private attachment detail")

        def begin(self, check):
            check()
            trace.append("begin")

        def readiness(self, expectation, check):
            check()
            trace.append("E33")

        def commit(self, check):
            check()
            trace.append("commit")

        def finish_root(self):
            trace.append("release-root")

        def close(self, check):
            check()
            trace.append("close")
            self.closed = True

    monkeypatch.setattr(life, "_NativeLane", StartupLane)
    return trace, association


def test_startup_profile_once_before_adoption_and_both_readiness_checks(monkeypatch):
    from modkit_events.persistence.models import Capability

    from modkit_workers.work_source import AcquireRequest

    source, app, control = make_source()
    trace, association = setup_startup_seams(monkeypatch, source)
    request = AcquireRequest(
        capabilities=[Capability(command_type="send", schema_version=1)],
        limit=1,
        discovery_budget=1,
    )
    assert source.startup(request) is None
    assert app.profiles == [request] and association == [source]
    assert trace[:2] == ["validate", "adopt"] and trace.count("E33") == 2
    assert source.snapshot().startup_verified and source.snapshot().resources_adopted
    with pytest.raises(RuntimeError):
        source.startup(request)
    assert app.profiles == [request]
    assert source.shutdown() is None and trace.count("close") == 2
    assert source.snapshot().cleanup_complete


def test_profile_refusal_has_no_adoption_or_native_call(monkeypatch):
    from modkit_events.persistence.models import Capability

    from modkit_workers.work_source import AcquireRequest

    source, app, control = make_source()
    trace, association = setup_startup_seams(monkeypatch, source)
    app.validate_profile = lambda request: False
    request = AcquireRequest(
        capabilities=[Capability(command_type="send", schema_version=1)],
        limit=1,
        discovery_budget=1,
    )
    with pytest.raises(ValueError):
        source.startup(request)
    assert trace == [] and association == [] and not source.snapshot().resources_adopted


def test_post_adoption_attach_rejection_retains_truthful_ownership(monkeypatch):
    from modkit_events.persistence.models import Capability

    from modkit_workers.work_source import AcquireRequest

    source, app, control = make_source()
    trace, association = setup_startup_seams(monkeypatch, source, attach_fail=True)
    request = AcquireRequest(
        capabilities=[Capability(command_type="send", schema_version=1)],
        limit=1,
        discovery_budget=1,
    )
    with pytest.raises(source_module().NativeJobUnresolved):
        source.startup(request)
    assert source.snapshot().resources_adopted and source.snapshot().unresolved
    assert source.shutdown() is None and "close" not in trace
    assert not source.snapshot().cleanup_complete


def test_renewal_uses_distinct_lane_and_only_counts_commit_acknowledgement():
    source, app, control, request = ready_source(acquired_page())
    (work,) = source.acquire(request)
    source._renewal = Lane()
    source._dispatch_committed = True
    source._fence = replace(source._fence, expected_attempt=source._fence.expected_attempt + 1)
    assert source.renew(work, source._fence) is None
    assert "E05" in source._renewal.trace and "E05" not in source._data.trace
    assert source.snapshot().renewal_commits == 1
    source._renewal.commit_unknown = True
    with pytest.raises(source_module().NativeJobUnresolved):
        source.renew(work, source._fence)
    assert source.snapshot().renewal_commits == 1 and source._material.reserved


def test_predispatch_renewal_is_not_an_eligible_native_operation():
    source, app, control, request = ready_source(acquired_page())
    (work,) = source.acquire(request)
    source._renewal = Lane()
    with pytest.raises(ValueError):
        source.renew(work, source._fence)
    assert source._renewal.trace == []


def test_native_acquire_and_readiness_use_real_paid_preparation_entrypoints(monkeypatch):
    from modkit_events.persistence import bindings, catalog

    from modkit_workers import _native_job_lifecycle as life
    from modkit_workers.persistence import native_store

    assert hasattr(life._NativeLane, "acquire") and hasattr(life._NativeLane, "readiness")
    trace = []
    expectation = object()
    request = object()

    class Native:
        READINESS_RESULT_CAPACITY = 16384

        def prepare_readiness(self, execution, profile, pins, **kw):
            assert profile == "workers" and pins is expectation
            trace.append("prepare-E33")
            return object()

    def acquire(execution, value, **kw):
        assert value is request and kw["max_page_payload_bytes"] == 2**32
        trace.append("prepare-W05")
        return object()

    monkeypatch.setattr(native_store, "prepare_acquire", acquire)
    monkeypatch.setattr(life, "_native_api", lambda: (None, Native(), bindings, catalog))
    lane = life._NativeLane(object(), object())
    lane.execution = object()

    def consume(**kw):
        trace.append(("consume", kw["result_capacity"]))
        return 7

    monkeypatch.setattr(lane, "_consume", consume)
    assert lane.acquire(request, budget=2**32, project=lambda x: x, check=lambda: None) == 7
    assert lane.readiness(expectation, lambda: None) is None
    assert trace == ["prepare-W05", ("consume", None), "prepare-E33", ("consume", 16384)]


def test_native_close_uses_managed_receipts_not_raw_close_and_is_idempotent(monkeypatch):
    from modkit_events.persistence import bindings, catalog

    from modkit_workers import _native_job_lifecycle as life

    assert hasattr(life._NativeLane, "close")
    trace = []

    class Permit:
        def close(self, **kw):
            trace.append("close")
            return object()

    class Managed:
        def retire(self, *a, **kw):
            trace.append("retire")

        def prepare_cleanup(self, *a, **kw):
            trace.append("cleanup-intent")
            return object()

        def reserve_cleanup(self, intent, capacity, **kw):
            assert capacity == 4096
            trace.append("reserve-cleanup")
            return object()

        def pin_cleanup(self, *a, **kw):
            trace.append("pin")
            return Permit()

        def acknowledge_physical_close(self, *a, **kw):
            trace.append("ack-close")

        def release_cleanup(self, *a, **kw):
            trace.append("release-cleanup")

        def detach_terminal(self, *a, **kw):
            trace.append("detach")

        def dispose_execution(self, *a, **kw):
            trace.append("dispose-X")

    monkeypatch.setattr(life, "_native_api", lambda: (Managed(), None, bindings, catalog))
    lane = life._NativeLane(object(), object())
    lane.execution = object()
    lane.checkout = object()
    lane.close(lambda: None)
    lane.close(lambda: None)
    assert trace == [
        "retire",
        "cleanup-intent",
        "reserve-cleanup",
        "pin",
        "close",
        "ack-close",
        "release-cleanup",
        "detach",
        "dispose-X",
    ]
    assert lane.closed


def test_repeated_cross_scope_current_authorization_reuses_fixed_ledgers():
    # Break caught: cached authorization/context, handler before authorization,
    # failure poisoning the slot, or replacing scope-bound ledgers between jobs.
    from uuid import UUID

    from modkit_events.persistence.scope import Scope
    from test_job_acquisition import frame
    from test_job_acquisition import request as wire_request
    from test_job_persistence_contracts import full_job_row, job

    from modkit_workers.persistence import rows

    scopes = (Scope("app-a", "tenant-a", "owner-a"), Scope("app-b", None, "owner-b"))

    def page(scope, sequence):
        return rows.decode_acquire(
            wire_request(limit=1),
            frame(
                full_job_row(
                    job(work_id=str(UUID(int=sequence)), scope=scope),
                    state="claimed",
                    attempt=0,
                ),
                visited=1,
                exhausted=False,
            ),
        )

    source, _, control, request = ready_source(page(scopes[0], 101))
    source._renewal = Lane()
    data, renewal = source._data, source._renewal
    data.ledger = source._resources.data_ledger
    renewal.ledger = source._resources.renewal_ledger
    fixed = (data.connection, renewal.connection, data.ledger, renewal.ledger)
    assert data.ledger is not renewal.ledger
    trace = []
    permitted = {scopes[0]}
    active = []

    class CurrentAuthorization:
        def bind(self, root, context):
            assert root.connection is fixed[0]
            assert root.root_xid == 42
            trace.append(("bind", context.scope))

            class Binding:
                def __enter__(self):
                    trace.append(("authorize", context.scope))
                    if context.scope not in permitted:
                        trace.append(("deny", context.scope))
                        raise PermissionError("current application authorization denied")
                    active.append(context)
                    return self

                def result(self):
                    assert active == [context]
                    return b"authorized"

                def __exit__(self, *args):
                    assert active.pop() is context
                    trace.append(("unbind", context.scope))
                    return False

            return Binding()

    def business(context):
        assert active == [context]
        trace.append(("business-write", context.scope))

    source._application = CurrentAuthorization()
    source._registry = HandlerRegistry(
        [
            HandlerRegistration(
                command_type="send", schema_version=1, handler=business, kind=HandlerKind.SYNC
            )
        ]
    )
    for index, scope in enumerate((scopes[0], scopes[1], scopes[1])):
        if index == 2:
            permitted.add(scopes[1])  # Changed current grant, not cached denial.
        data.page = page(scope, 101 + index)
        before = len(data.trace)
        (work,) = source.acquire(request)
        assert source.execute(work) is None
        operation = data.trace[before:]
        if index == 1:
            assert "E10" not in operation
            assert operation.index("strict-rollback") < operation.index("E11")
            assert operation.index("E11") < operation.index("release-failed-root")
        else:
            assert "E10" in operation and "E11" not in operation
        assert source._data is data and source._renewal is renewal
        assert all(
            a is b
            for a, b in zip(
                fixed,
                (data.connection, renewal.connection, data.ledger, renewal.ledger),
                strict=True,
            )
        )
        assert control.work is None and control.pending is None
        assert not source._material.reserved and not source.snapshot().unresolved
        assert not active

    assert trace == [
        ("bind", scopes[0]),
        ("authorize", scopes[0]),
        ("business-write", scopes[0]),
        ("unbind", scopes[0]),
        ("bind", scopes[1]),
        ("authorize", scopes[1]),
        ("deny", scopes[1]),
        ("bind", scopes[1]),
        ("authorize", scopes[1]),
        ("business-write", scopes[1]),
        ("unbind", scopes[1]),
    ]
    assert source.snapshot().confirmed_succeeded == 2
    assert source.snapshot().confirmed_failed == 1
    assert control.trace.count("retire") == 3
    assert not any(type(item) is tuple and item[0] == "fail" for item in control.trace)


@contextmanager
def startup_control_harness(source, request):
    """Real control and registered live threads, with native I/O only seam-mocked."""
    from queue import Queue
    from threading import Event, Thread

    from modkit_workers._native_control import _SourceControl
    from modkit_workers._native_supervisor import _SupervisorCore

    control = _SourceControl(NativeWorkerSettings(renewal_interval_seconds=1))
    source._control = control
    _SupervisorCore(source, control, request, control.settings)
    control.register_lane("coordinator")
    calls = Queue()
    boot = Event()

    def data_lane():
        control.register_lane("data")
        boot.set()
        while (item := calls.get()) is not None:
            call, done, result = item
            try:
                result.append((True, call()))
            except BaseException as error:
                result.append((False, error))
            finally:
                done.set()

    thread = Thread(target=data_lane, daemon=False)
    thread.start()
    assert boot.wait(2)

    def on_data(call):
        done, result = Event(), []
        calls.put((call, done, result))
        assert done.wait(3)
        ok, value = result[0]
        if not ok:
            raise value
        return value

    try:
        yield control, on_data
    finally:
        control.request_stop()
        control.request_renewal_exit()
        assert control.join_renewal(3)
        calls.put(None)
        thread.join(3)
        assert not thread.is_alive()


def startup_request():
    from modkit_events.persistence.models import Capability

    from modkit_workers.work_source import AcquireRequest

    return AcquireRequest(
        capabilities=[Capability(command_type="send", schema_version=1)],
        limit=1,
        discovery_budget=1,
    )


def test_startup_unstarted_and_foreign_calls_cannot_poison_legitimate_start(monkeypatch):
    from modkit_workers._native_control import _SourceControl

    source, app, _ = make_source()
    trace, association = setup_startup_seams(monkeypatch, source)
    request = startup_request()
    before = source.snapshot()
    source._control = _SourceControl(NativeWorkerSettings(renewal_interval_seconds=1))
    with pytest.raises(RuntimeError):
        source.startup(request)  # Inert, unbound real control.
    assert source.snapshot() == before
    assert not source._startup_called and not trace and not app.profiles
    with startup_control_harness(source, request) as (control, data):
        with pytest.raises(RuntimeError):
            data(lambda: source.startup(request))  # Bound, but renewal has not started.
        assert source.snapshot() == before
        assert not source._startup_called and not trace and not app.profiles
        control.start_renewal()
        with pytest.raises(RuntimeError):
            source.startup(request)  # Coordinator is not the registered data lane.
        assert source.snapshot() == before
        assert not source._startup_called and not trace and not association
        assert data(lambda: source.startup(request)) is None
        assert app.profiles == [request] and association == [source]
        assert trace.count("E33") == 2
        with pytest.raises(RuntimeError):
            data(lambda: source.startup(request))
        assert app.profiles == [request] and trace.count("E33") == 2
        data(source.shutdown)
        assert source.snapshot().cleanup_complete


def test_stop_wins_startup_without_local_mutation_or_adoption(monkeypatch):
    from modkit_workers._native_control_contracts import _AdmissionClosed

    source, app, _ = make_source()
    trace, association = setup_startup_seams(monkeypatch, source)
    request = startup_request()
    before = source.snapshot()
    with startup_control_harness(source, request) as (control, data):
        control.start_renewal()
        control.request_stop()
        with pytest.raises(_AdmissionClosed):
            data(lambda: source.startup(request))
        assert source.snapshot() == before
        assert not source._startup_called and not trace and not association and not app.profiles


def test_admitted_startup_stop_drains_without_claim_permission(monkeypatch):
    source, app, _ = make_source()
    trace, association = setup_startup_seams(monkeypatch, source)
    request = startup_request()
    with startup_control_harness(source, request) as (control, data):
        control.start_renewal()

        def stop_after_admission(actual):
            app.profiles.append(actual)
            control.request_stop()
            source.request_stop()

        app.validate_profile = stop_after_admission
        assert data(lambda: source.startup(request)) is None
        assert association == [source] and trace.count("E33") == 2
        assert source.snapshot().startup_verified and source.snapshot().admission_closed
        with pytest.raises(RuntimeError):
            data(lambda: source.acquire(request))
        assert not control.acquisition_in_flight and not source._material.reserved
        assert "W05" not in trace
        data(source.shutdown)
        assert trace.count("close") == 2 and source.snapshot().cleanup_complete
