"""Private coordinator tests with deterministic source fakes, never native I/O."""

from collections import deque
from dataclasses import replace
from importlib import import_module, util
from threading import Event, Lock
from time import monotonic

import pytest


def modules():
    name = "modkit_workers._native_supervisor"
    assert util.find_spec(name) is not None, "private supervisor is not implemented"
    return (
        import_module(name),
        import_module("modkit_workers._native_control"),
        import_module("modkit_workers._native_control_contracts"),
    )


class FakeSource:
    """Records only fake confirmed outcomes; contains no native implementation."""

    def __init__(self, control, c, jobs=()):
        self.control, self.c = control, c
        self._lock = Lock()
        self._snapshot = c.JobSourceSnapshot()
        self.jobs = deque(jobs)
        self.start_entered, self.start_release = Event(), Event()
        self.start_release.set()
        self.reserved, self.acquire_release = Event(), Event()
        self.acquire_release.set()
        self.handler_entered, self.handler_release = Event(), Event()
        self.handler_release.set()
        self.renewed, self.finished = Event(), Event()
        self.target = len(self.jobs)
        self.calls = []
        self.leases = []
        self.work_ids = []
        self.fail_start = False
        self.fail_execute = False

    def update(self, **values):
        with self._lock:
            self._snapshot = replace(self._snapshot, **values)

    def snapshot(self):
        with self._lock:
            return self._snapshot

    def startup(self, request):
        self.start_entered.set()
        assert self.start_release.wait(4)
        if self.fail_start:
            raise ValueError("fake startup failure")
        self.update(
            phase=self.c.JobSourcePhase.IDLE,
            startup_verified=True,
            domain_active=True,
            resources_adopted=True,
            admission_closed=False,
            last_progress_monotonic=monotonic(),
        )

    def acquire(self, request):
        token = self.control.reserve_acquisition(self)
        self.reserved.set()
        self.update(native_in_flight=True)
        assert self.acquire_release.wait(4)
        self.calls.append("physical_acquire")
        work = self.jobs.popleft() if self.jobs else None
        self.control.publish_acquisition(token, work)
        previous = self.snapshot()
        self.update(
            native_in_flight=False,
            slot_occupied=work is not None,
            phase=self.c.JobSourcePhase.CLAIMED if work else self.c.JobSourcePhase.IDLE,
            acquisition_pages=previous.acquisition_pages + 1,
            scan_progress=True,
            scan_exhausted=work is None,
            last_progress_monotonic=monotonic(),
        )
        return () if work is None else (work,)

    def execute(self, work):
        self.leases.append(
            self.control.require_admission(self, kind=self.c.NativeAdmissionKind.ADMITTED_EXECUTION)
        )
        self.work_ids.append(work)
        self.control.activate(work, object())  # Fake acknowledged E06.
        self.update(phase=self.c.JobSourcePhase.RUNNING)
        self.handler_entered.set()
        assert self.handler_release.wait(4)
        if self.fail_execute:
            self.update(unresolved=True)
            raise ValueError("fake uncertain execution")
        drain = self.control.close_renewal(work)
        q = self.control.await_renewal_quiescent(drain, deadline_monotonic=monotonic() + 3)
        assert q.quiescent and q.outcome_known and q.domain_active
        self.calls.append("confirmed_terminal")
        count = self.snapshot().confirmed_succeeded + 1
        self.update(
            confirmed_succeeded=count,
            slot_occupied=False,
            phase=self.c.JobSourcePhase.IDLE,
            last_progress_monotonic=monotonic(),
        )
        self.control.retire_work(work)
        if count >= self.target:
            self.finished.set()

    def renew(self, work, fence):
        self.control.require_admission(self, kind=self.c.NativeAdmissionKind.RENEWAL)
        self.update(
            renewal_commits=self.snapshot().renewal_commits + 1, last_progress_monotonic=monotonic()
        )
        self.renewed.set()

    def request_stop(self):
        self.update(admission_closed=True)

    def shutdown(self):
        self.calls.append("shutdown")
        unresolved = self.snapshot().unresolved or self.control.current_work is not None
        self.update(
            cleanup_complete=not unresolved,
            unresolved=unresolved,
            phase=self.c.JobSourcePhase.FAILED if unresolved else self.c.JobSourcePhase.STOPPED,
        )

    def unblock(self):
        self.start_release.set()
        self.acquire_release.set()
        self.handler_release.set()


def build(jobs=(), drain_timeout=30, progress_timeout=10, renewal_interval=0.01):
    m, ctrl, c = modules()
    settings = c.NativeWorkerSettings(
        renewal_interval_seconds=renewal_interval,
        poll_interval_seconds=0.01,
        drain_timeout_seconds=drain_timeout,
        progress_timeout_seconds=progress_timeout,
    )
    control = ctrl._SourceControl(settings)
    source = FakeSource(control, c, jobs)
    worker = m._SupervisorCore(source, control, object(), settings)
    return worker, source, control, c


def cleanup(worker, source):
    source.unblock()
    worker.request_stop()
    worker.stop(timeout=4)
    assert worker.join(4), "supervisor test threads leaked"


def test_repeated_two_jobs_keep_lifetime_lease_and_report_durable_counts():
    worker, source, _, c = build((object(), object()))
    try:
        worker.start()
        assert source.finished.wait(3)
        snapshot = worker.stop(timeout=3)
        assert snapshot.state is c.WorkerState.STOPPED
        assert snapshot.clean_stop
        assert snapshot.source.confirmed_succeeded == 2
        assert len(source.leases) == 2 and source.leases[0] is source.leases[1]
        assert source.work_ids[0] is not source.work_ids[1]
        assert source.calls.count("shutdown") == 1
    finally:
        cleanup(worker, source)


def test_stop_wait_timeout_does_not_stop_active_renewal_or_claim_clean():
    worker, source, control, _ = build((object(),))
    source.handler_release.clear()
    try:
        worker.start()
        assert source.handler_entered.wait(3)
        assert source.renewed.wait(2)
        before = source.snapshot().renewal_commits
        source.renewed.clear()
        snapshot = worker.stop(timeout=0)
        assert not snapshot.clean_stop and snapshot.execution_in_flight
        assert source.renewed.wait(2)
        assert source.snapshot().renewal_commits > before
        assert control.current_work is source.work_ids[0]
        source.handler_release.set()
        assert worker.stop(timeout=3).clean_stop
    finally:
        cleanup(worker, source)


def test_s_r1_reserved_before_stop_may_physically_acquire_after_stop():
    worker, source, control, _ = build((object(),))
    source.acquire_release.clear()
    try:
        worker.start()
        assert source.reserved.wait(3)
        assert control.acquisition_in_flight
        worker.request_stop()
        assert "physical_acquire" not in source.calls
        source.acquire_release.set()
        assert source.finished.wait(3)
        assert worker.stop(timeout=3).clean_stop
        assert source.calls.count("physical_acquire") == 1
    finally:
        cleanup(worker, source)


def test_startup_stop_prevents_any_acquisition():
    worker, source, _, _ = build((object(),))
    source.start_release.clear()
    try:
        worker.start()
        assert source.start_entered.wait(2)
        worker.request_stop()
        source.start_release.set()
        assert worker.stop(timeout=3).clean_stop
        assert "physical_acquire" not in source.calls
    finally:
        cleanup(worker, source)


def test_startup_failure_never_claims_and_is_not_clean_success():
    worker, source, _, c = build((object(),))
    source.fail_start = True
    try:
        worker.start()
        assert worker.join(3)
        snapshot = worker.snapshot()
        assert snapshot.state is c.WorkerState.FAILED
        assert not snapshot.ready and not snapshot.clean_stop
        assert "physical_acquire" not in source.calls
    finally:
        cleanup(worker, source)


@pytest.mark.parametrize("lane", ["coordinator", "renewal", "data"])
def test_thread_start_failure_preserves_observable_failed_stop(monkeypatch, lane):
    supervisor, control_module, c = modules()
    worker, source, control, _ = build()
    failure = RuntimeError("synthetic thread resource exhaustion")
    thread_type = supervisor.Thread

    class RefusedStart(thread_type):
        def start(self):
            if self.name == "modkit-" + lane:
                raise failure
            super().start()

    # Refuse the OS-thread boundary only; keep real lifecycle and join behavior.
    monkeypatch.setattr(supervisor, "Thread", RefusedStart)
    monkeypatch.setattr(control_module, "Thread", RefusedStart)
    if lane == "coordinator":
        with pytest.raises(RuntimeError) as raised:
            worker.start()
        assert raised.value is failure
    else:
        worker.start()
    assert worker._finished.wait(3), "failed startup never published its final snapshot"
    for _ in range(2):
        snapshot = worker.stop(timeout=1)
        assert snapshot.state is c.WorkerState.FAILED
        assert snapshot.reason is c.WorkerReason.CONTROL_FAILED
        assert not snapshot.ready and not snapshot.clean_stop
        assert not snapshot.startup_in_flight and not snapshot.execution_in_flight
        assert not snapshot.source.resources_adopted
    assert not source.start_entered.is_set() and not source.calls
    assert control.current_work is None and not control.acquisition_in_flight
    for thread in (worker._coordinator, worker._data, control._renewal_thread):
        if thread is not None and thread.ident is not None:
            thread.join(3)
            assert not thread.is_alive(), "startup failure leaked a thread"
    with pytest.raises(RuntimeError, match="one-shot"):
        worker.start()


def test_uncertain_execution_retains_slot_and_zero_success_without_restart():
    worker, source, control, c = build((object(),))
    source.fail_execute = True
    try:
        worker.start()
        assert worker.join(3)
        snapshot = worker.snapshot()
        assert snapshot.state is c.WorkerState.FAILED
        assert not snapshot.clean_stop and snapshot.source.confirmed_succeeded == 0
        assert control.current_work is not None
        assert source.calls.count("physical_acquire") == 1
        with pytest.raises(RuntimeError):
            worker.start()
    finally:
        cleanup(worker, source)


def test_direct_source_calls_reject_without_live_bound_supervisor():
    worker, source, _, _ = build((object(),))
    with pytest.raises(RuntimeError):
        source.acquire(object())
    assert not source.calls
    # No threads were started; no native objects exist in this fake.


def test_source_foreign_thread_call_rejects_while_worker_active():
    worker, source, _, _ = build((object(),))
    source.handler_release.clear()
    try:
        worker.start()
        assert source.handler_entered.wait(3)
        with pytest.raises(RuntimeError):
            source.acquire(object())
    finally:
        cleanup(worker, source)


def test_stop_between_loop_check_and_reservation_is_clean_no_acquire():
    worker, source, _, _ = build((object(),))
    before, release = Event(), Event()
    original = source.acquire

    def paused(request):
        before.set()
        assert release.wait(3)
        return original(request)

    source.acquire = paused
    try:
        worker.start()
        assert before.wait(2)
        worker.request_stop()
        release.set()
        assert worker.stop(timeout=3).clean_stop
        assert "physical_acquire" not in source.calls
    finally:
        release.set()
        cleanup(worker, source)


def test_configured_drain_deadline_before_e06_retains_unstarted_claim():
    worker, source, control, c = build((object(),), drain_timeout=0.01)
    source.acquire_release.clear()
    try:
        worker.start()
        assert source.reserved.wait(2)
        worker.request_stop()
        Event().wait(0.03)
        source.acquire_release.set()
        assert worker.join(3)
        snapshot = worker.snapshot()
        assert not snapshot.clean_stop
        assert snapshot.reason is c.WorkerReason.DRAIN_TIMEOUT
        assert not source.handler_entered.is_set()
        assert control.current_work is not None
        assert source.snapshot().confirmed_succeeded == 0
    finally:
        cleanup(worker, source)


def test_source_progress_stale_removes_ready_even_with_live_coordinator():
    worker, source, _, c = build((object(),), progress_timeout=0.02, renewal_interval=1.0)
    source.handler_release.clear()
    try:
        worker.start()
        assert source.handler_entered.wait(2)
        Event().wait(0.04)
        snapshot = worker.snapshot()
        assert not snapshot.ready
        assert snapshot.reason is c.WorkerReason.PROGRESS_STALE
    finally:
        cleanup(worker, source)


def test_confirmed_refusal_reports_not_ready_but_can_cleanly_release_resources():
    worker, source, control, c = build((object(),))

    def refuse(request):
        token = control.reserve_acquisition(source)
        # Fake source has observed a confirmed rollback/no claim.
        control.refuse_acquisition(token, reason=c.WorkerReason.CAPACITY_UNAVAILABLE)
        return ()

    source.acquire = refuse
    try:
        worker.start()
        assert worker.join(3)
        snapshot = worker.snapshot()
        assert snapshot.state is c.WorkerState.FAILED
        assert not snapshot.ready and snapshot.clean_stop
        assert snapshot.reason is c.WorkerReason.CAPACITY_UNAVAILABLE
        assert snapshot.source.confirmed_succeeded == 0
        assert snapshot.source.confirmed_failed == 0
        assert not control.acquisition_in_flight
    finally:
        cleanup(worker, source)


def test_clean_stop_waits_for_actual_coordinator_thread_exit():
    worker, source, _, _ = build((object(),))
    published, release = Event(), Event()

    class PausedFinish(Event):
        def set(self):
            super().set()
            published.set()
            assert release.wait(3)

    worker._finished = PausedFinish()
    try:
        worker.start()
        assert source.finished.wait(2)
        worker.request_stop()
        assert published.wait(2)
        assert not worker.join(0)
        assert not worker.snapshot().clean_stop
        release.set()
        assert worker.stop(timeout=2).clean_stop
    finally:
        release.set()
        cleanup(worker, source)


def test_s_s1_control_stop_before_core_event_is_known_nonadmission():
    worker, source, control, c = build((object(),))
    before_acquire, continue_acquire = Event(), Event()
    control_stopped, continue_stop = Event(), Event()
    original_acquire, original_stop = source.acquire, control.request_stop

    def acquire(request):
        before_acquire.set()
        assert continue_acquire.wait(3)
        return original_acquire(request)

    def pause_stop():
        original_stop()
        control_stopped.set()
        assert continue_stop.wait(3)

    source.acquire, control.request_stop = acquire, pause_stop
    from threading import Thread

    stopper = Thread(target=worker.request_stop)
    try:
        worker.start()
        assert before_acquire.wait(2)
        stopper.start()
        assert control_stopped.wait(2)
        assert not worker._stop.is_set()
        continue_acquire.set()
        assert worker.join(2)
        assert worker.snapshot().reason is not c.WorkerReason.EXECUTION_FAILED
        assert worker.snapshot().clean_stop
        assert "physical_acquire" not in source.calls
    finally:
        continue_acquire.set()
        continue_stop.set()
        if stopper.ident is not None:
            stopper.join(3)
            assert not stopper.is_alive()
        control.request_stop = original_stop
        cleanup(worker, source)


@pytest.mark.parametrize("after_publication", [False, True])
def test_s_s2_stop_during_ready_publication_never_overwrites_draining(after_publication):
    worker, source, control, c = build((object(),))
    at_publication, continue_publication = Event(), Event()
    at_shutdown, continue_shutdown = Event(), Event()
    original_publish, original_shutdown = control.publish_ready, source.shutdown

    def publish(bound_source):
        if after_publication:
            original_publish(bound_source)
        at_publication.set()
        assert continue_publication.wait(3)
        if not after_publication:
            return original_publish(bound_source)

    def shutdown():
        at_shutdown.set()
        assert continue_shutdown.wait(3)
        return original_shutdown()

    control.publish_ready, source.shutdown = publish, shutdown
    try:
        worker.start()
        assert at_publication.wait(2)
        worker.request_stop()
        continue_publication.set()
        assert at_shutdown.wait(2)
        snapshot = worker.snapshot()
        assert snapshot.state is c.WorkerState.DRAINING
        assert snapshot.reason is not c.WorkerReason.CONTROL_FAILED
        assert not snapshot.ready
        assert "physical_acquire" not in source.calls
        continue_shutdown.set()
        assert worker.stop(timeout=2).clean_stop
    finally:
        continue_publication.set()
        continue_shutdown.set()
        cleanup(worker, source)


def test_stop_wins_startup_gate_before_core_event_is_published(monkeypatch):
    from threading import Thread

    supervisor, control_module, c = modules()
    settings = c.NativeWorkerSettings(renewal_interval_seconds=0.01)
    control = control_module._SourceControl(settings)
    source = FakeSource(control, c)
    core = supervisor._SupervisorCore(source, control, object(), settings)
    at_gate, continue_gate, stop_published, continue_stop = Event(), Event(), Event(), Event()
    original_start = source.startup
    original_stop = control.request_stop

    def startup(request):
        at_gate.set()
        assert continue_gate.wait(3)
        # Emulate the accepted source gate without requiring sibling edits.
        if control.stop_requested:
            raise c._AdmissionClosed("Stop won startup")
        original_start(request)

    def stopping():
        original_stop()
        stop_published.set()
        assert continue_stop.wait(3)

    monkeypatch.setattr(source, "startup", startup)
    monkeypatch.setattr(control, "request_stop", stopping)
    thread = Thread(target=core.request_stop)
    try:
        core.start()
        assert at_gate.wait(3)
        thread.start()
        assert stop_published.wait(3)
        continue_gate.set()
        assert core.join(3)
        state = core.snapshot()
        assert state.reason is None and state.clean_stop
        assert not source.start_entered.is_set() and source.calls == ["shutdown"]
    finally:
        continue_gate.set()
        continue_stop.set()
        if thread.ident is not None:
            thread.join(3)
            assert not thread.is_alive()
        original_stop()
        assert core.join(3)


def test_admitted_startup_drains_after_stop_without_ready_or_claim(monkeypatch):
    core, source, control, c = build()
    original = source.startup
    source.start_release.clear()

    def startup(request):
        control.admit_startup(source)
        original(request)

    monkeypatch.setattr(source, "startup", startup)
    try:
        core.start()
        assert source.start_entered.wait(3)
        assert control._startup_admitted and control._lease is None
        state = core.stop(timeout=0)
        assert not state.clean_stop
        source.start_release.set()
        assert core.join(3)
        state = core.snapshot()
        assert state.clean_stop and state.reason is None and not state.ready
        assert source.calls == ["shutdown"] and control._lease is None
    finally:
        source.unblock()
        core.request_stop()
        assert core.join(3)


@pytest.mark.parametrize("hook", ["startup", "execute", "shutdown"])
def test_typed_void_hooks_still_reject_non_none_runtime_returns(hook):
    worker, source, _, c = build((object(),))
    original = getattr(source, hook)

    def broken_return(*args):
        original(*args)
        return object()

    setattr(source, hook, broken_return)
    try:
        worker.start()
        if hook == "shutdown":
            assert source.finished.wait(3)
            worker.request_stop()
        assert worker.join(3)
        snapshot = worker.snapshot()
        assert snapshot.state is c.WorkerState.FAILED
        assert not snapshot.clean_stop
        if hook == "startup":
            assert "physical_acquire" not in source.calls
        assert source.calls.count("shutdown") == 1
    finally:
        cleanup(worker, source)
