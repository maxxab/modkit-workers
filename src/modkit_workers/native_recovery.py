"""One-shot, independently hosted recovery scheduler; no process creation.

Events-owned requirements and native issuers supply the one-lane adapter.
Unavailable capability fails closed. Pure tests do not qualify native runtime.
"""

from __future__ import annotations

import math
from threading import Event, RLock
from time import monotonic

from . import native_recovery_setup as _setup
from ._native_recovery_lifecycle import _build_snapshot, _project_page, _RecoveryMaterialLease
from .native_recovery_contracts import (
    UINT64_MAX,
    NativeRecoveryResources,
    RecoveryPageOutcome,
    RecoveryPhase,
    RecoveryReason,
    _add,
    _age_ms,
    _validate_config,
)

_clock = monotonic


def _wait(event, seconds):
    event.wait(seconds)


def _domain_active():
    from modkit_events.persistence.resource_registry import resource_domain

    return not resource_domain().stopped


def _make_lane(resources, config):
    from ._native_recovery_lifecycle import _NativeRecoveryLane

    return _NativeRecoveryLane(resources, _setup._recheck_profile(config, resources))


def _require_none(value):
    import inspect

    if value is not None:
        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise ValueError("Recovery application hook must return None")


def _time():
    value = _clock()
    if type(value) is not float or not math.isfinite(value) or value < 0:
        raise ValueError("Invalid recovery clock")
    return value


class JobRecoveryOwner:
    """Factory-issued one-shot owner. Native resources never escape via snapshots."""

    def __new__(cls, *args, **kwargs):
        raise TypeError("Use create_job_recovery")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("Recovery owner is sealed")

    def __copy__(self):
        raise TypeError("Recovery owner cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("Recovery owner cannot be copied")

    def __reduce_ex__(self, protocol):
        raise TypeError("Recovery owner cannot be serialized")

    def _observe_time(self):
        # Sample and continuity publication are one ordered owner operation.
        # RLock supports callers already owning scalar state; no I/O/callbacks here.
        with self._lock:
            value = _time()
            if self._last_clock is not None and value < self._last_clock:
                self._clock_failed = True
                self._stop.set()
                return self._last_clock
            self._last_clock = value
            return value

    def _project_clock_fault_locked(self):
        if not self._clock_failed:
            return
        self._material.enter()
        try:
            s = self._current
            draft = (
                RecoveryPhase.FAILED,
                RecoveryReason.INTERNAL_FAILURE,
                s.latest_page_outcome,
                False,
                s.startup_verified,
                s.domain_active,
                True,
                True,
                s.native_in_flight,
                s.cleanup_unresolved,
                True,
                False,
                s.has_committed_page,
                s.last_committed_raw_cursor,
                s.next_scan_after,
                s.last_committed_pass_exhausted,
                s.last_committed_visited,
                s.last_committed_queued,
                s.last_committed_expired,
                s.last_committed_failed,
                s.last_committed_held,
                s.committed_pages,
                s.committed_sweeps,
                s.committed_visited,
                s.committed_queued,
                s.committed_expired,
                s.committed_failed,
                s.committed_held,
                s.progress_sequence,
                s.progress_age_ms,
                s.counters_saturated,
            )
            self._current = _build_snapshot(draft)
            draft = s = None
            self._material.hold()
        finally:
            self._material.leave()

    def _status(
        self,
        *,
        phase=None,
        reason=None,
        outcome=None,
        ready=None,
        startup=None,
        domain=None,
        native=None,
        cleanup=None,
        unresolved=None,
        clean=None,
    ):
        with self._lock:
            self._material.enter()
            try:
                now = self._observe_time()
                if self._clock_failed:
                    phase, reason = RecoveryPhase.FAILED, RecoveryReason.INTERNAL_FAILURE
                    ready, unresolved, clean = False, True, False
                    self._material.hold()
                s = self._current
                draft = (
                    s.phase if phase is None else phase,
                    s.reason if reason is None else reason,
                    s.latest_page_outcome if outcome is None else outcome,
                    s.ready if ready is None else ready,
                    s.startup_verified if startup is None else startup,
                    s.domain_active if domain is None else domain,
                    self._stop.is_set(),
                    self._stop.is_set() or s.admission_closed,
                    s.native_in_flight if native is None else native,
                    s.cleanup_unresolved if cleanup is None else cleanup,
                    s.unresolved if unresolved is None else unresolved,
                    s.clean_stop if clean is None else clean,
                    s.has_committed_page,
                    s.last_committed_raw_cursor,
                    s.next_scan_after,
                    s.last_committed_pass_exhausted,
                    s.last_committed_visited,
                    s.last_committed_queued,
                    s.last_committed_expired,
                    s.last_committed_failed,
                    s.last_committed_held,
                    s.committed_pages,
                    s.committed_sweeps,
                    s.committed_visited,
                    s.committed_queued,
                    s.committed_expired,
                    s.committed_failed,
                    s.committed_held,
                    _add(s.progress_sequence, 1),
                    0,
                    s.counters_saturated or s.progress_sequence == UINT64_MAX,
                )
                self._current = _build_snapshot(draft)
                self._last_progress = now
                draft = s = None
            finally:
                self._material.leave()

    def request_stop(self):
        with self._lock:
            self._material.require()
            self._stop.set()
            if self._drain_deadline is None:
                deadline = self._observe_time() + self._config.drain_timeout_seconds
                if not math.isfinite(deadline):
                    raise ValueError("Invalid recovery drain deadline")
                self._drain_deadline = deadline

    def _check(self):
        self._observe_time()
        if self._clock_failed:
            raise RuntimeError("Recovery clock regressed")
        if not _domain_active():
            raise RuntimeError("Recovery domain is stopped")

    def _project(self, page):
        with self._lock:
            self._material.enter(projection=True)
            try:
                if self._pending is not None or not self._page_reserved:
                    raise RuntimeError("Recovery projection has no sole page reservation")
                self._pending = _project_page(
                    page,
                    incoming=self._current.next_scan_after,
                    discovery_budget=self._config.discovery_budget,
                )
            finally:
                self._material.leave()
        # Do not return a page or summary alias to the lane/caller.
        return None

    def _publish_commit(self):
        with self._lock:
            self._material.enter()
            try:
                now = self._observe_time()
                s, p = self._current, self._pending
                if p is None:
                    raise RuntimeError("Committed recovery page has no scalar summary")
                saturated = (
                    s.counters_saturated
                    or s.committed_pages == UINT64_MAX
                    or s.progress_sequence == UINT64_MAX
                    or s.committed_sweeps > UINT64_MAX - int(p.pass_exhausted)
                    or s.committed_visited > UINT64_MAX - p.visited
                    or s.committed_queued > UINT64_MAX - p.queued
                    or s.committed_expired > UINT64_MAX - p.expired
                    or s.committed_failed > UINT64_MAX - p.failed
                    or s.committed_held > UINT64_MAX - p.held
                )
                draft = (
                    s.phase,
                    s.reason,
                    RecoveryPageOutcome.COMMITTED,
                    False,
                    s.startup_verified,
                    s.domain_active,
                    self._stop.is_set(),
                    self._stop.is_set(),
                    s.native_in_flight,
                    False,
                    False,
                    False,
                    True,
                    p.raw_cursor,
                    None if p.pass_exhausted else p.raw_cursor,
                    p.pass_exhausted,
                    p.visited,
                    p.queued,
                    p.expired,
                    p.failed,
                    p.held,
                    _add(s.committed_pages, 1),
                    _add(s.committed_sweeps, int(p.pass_exhausted)),
                    _add(s.committed_visited, p.visited),
                    _add(s.committed_queued, p.queued),
                    _add(s.committed_expired, p.expired),
                    _add(s.committed_failed, p.failed),
                    _add(s.committed_held, p.held),
                    _add(s.progress_sequence, 1),
                    0,
                    saturated,
                )
                self._current = _build_snapshot(draft)
                self._last_progress = now
                self._pending = None
                draft = s = p = None
            finally:
                self._material.leave()

    def _failed(self, reason, *, unknown, cleanup=False):
        self._stop.set()
        self._status(
            phase=RecoveryPhase.FAILED,
            reason=reason,
            ready=False,
            native=unknown,
            unresolved=unknown,
            cleanup=cleanup,
        )
        if unknown:
            with self._lock:
                self._material.hold()

    def _turn(self):
        # Stop and reservation linearize on one short lock. No lock across I/O.
        with self._lock:
            self._material.require(projection=True)
            if self._stop.is_set():
                return
            if self._page_reserved or self._pending is not None:
                raise RuntimeError("Recovery already has an admitted page")
            self._page_reserved = True
        self._status(
            phase=RecoveryPhase.SCANNING,
            ready=False,
            outcome=RecoveryPageOutcome.PENDING,
            native=True,
        )
        entered = began = committed = False
        authority = None
        failed = False
        reason = RecoveryReason.AUTHORITY_REJECTED
        try:
            self._check()
            authority = self._application.authorize_root(
                self._resources.connection, self._config.namespace
            )
            entry = authority.__enter__()
            entered = True
            _require_none(entry)
            entry = None
            self._authority = authority
            self._check()
            reason = RecoveryReason.ROOT_UNKNOWN
            began = True  # Unknown begin return still retains this liability.
            _require_none(self._lane.begin())
            reason = RecoveryReason.RESULT_REJECTED
            self._check()
            _require_none(
                self._lane.scan(self._config, self._current.next_scan_after, self._project)
            )
            if self._pending is None:
                raise RuntimeError("Native lane did not project a page")
            reason = RecoveryReason.COMMIT_UNKNOWN
            self._check()
            _require_none(self._lane.commit())  # Only after COMMITTED acknowledgement.
            committed = True
            self._publish_commit()
            reason = RecoveryReason.CLEANUP_UNRESOLVED
            _require_none(self._lane.finish_root())
        except BaseException:
            failed = True
        finally:
            if entered and (not began or committed):
                try:
                    # No suppression semantics: failure remains sticky, no traceback retention.
                    disposition = authority.__exit__(None, None, None)
                    if disposition is not None and disposition is not False:
                        raise ValueError("Recovery authority cannot suppress failures")
                except BaseException:
                    failed = True
                    if committed:
                        reason = RecoveryReason.AUTHORITY_EXIT_FAILED
                else:
                    self._authority = None
            # Unknown root keeps its host authority lifetime and owner alive.
            authority = None
        if failed:
            if began and not committed:
                self._status(outcome=RecoveryPageOutcome.UNKNOWN)
            self._failed(reason, unknown=began, cleanup=committed)
            if not began:
                self._page_reserved = False
            return
        with self._lock:
            self._page_reserved = False
        self._status(phase=RecoveryPhase.IDLE, native=False, ready=not self._stop.is_set())
        interval = (
            self._config.fallback_interval_seconds
            if self._current.last_committed_pass_exhausted
            else self._config.turn_interval_seconds
        )
        due = self._observe_time() + interval
        if not math.isfinite(due):
            self._failed(RecoveryReason.INTERNAL_FAILURE, unknown=False)
        else:
            self._next_due = due

    def run(self, *, stop_event):
        if type(stop_event) is not Event:
            raise ValueError("Expected exact stop Event")
        with self._lock:
            self._material.require()
            if self._run_called:
                raise RuntimeError("Recovery run is once-only")
            self._run_called = True
        if stop_event.is_set():
            self.request_stop()
        if self._stop.is_set():
            self._status(phase=RecoveryPhase.STOPPED, ready=False, clean=True)
            return self.snapshot()
        adopted = False
        try:
            self._status(phase=RecoveryPhase.STARTING)
            _setup._recheck_profile(self._config, self._resources)
            _require_none(self._application.validate_profile(self._config.namespace))
            _setup._validate_resources(self._resources, self)
            # Stop and adoption admission share the same short lock.
            with self._lock:
                stopped = self._stop.is_set() or stop_event.is_set()
                if not stopped:
                    self._adoption_attempted = True
                    adopted = True
            if stopped:
                self.request_stop()
                self._status(phase=RecoveryPhase.STOPPED, ready=False, clean=True)
                return self.snapshot()
            _setup._adopt_resources(self._resources, self)
            self._lane = _make_lane(self._resources, self._config)
            self._check()
            self._status(native=True)
            _require_none(self._lane.attach())
            _require_none(self._lane.startup(self._config.readiness))
            self._status(
                phase=RecoveryPhase.IDLE, startup=True, domain=True, native=False, ready=True
            )
            self._next_due = self._observe_time()
            while not self._stop.is_set():
                if stop_event.is_set():
                    self.request_stop()
                    break
                delay = self._next_due - self._observe_time()
                if delay > 0:
                    _wait(stop_event, min(delay, 0.05))
                    continue
                self._turn()
        except _setup.RecoveryUnavailable:
            self._failed(RecoveryReason.PROFILE_REJECTED, unknown=adopted)
        except BaseException:
            self._failed(RecoveryReason.INTERNAL_FAILURE, unknown=adopted)
        if self._clock_failed:
            self._failed(RecoveryReason.INTERNAL_FAILURE, unknown=True)
        # A failed/uncertain owner never manufactures cleanup authority.
        if not self._current.unresolved:
            try:
                if self._lane is not None:
                    self._check()
                    _require_none(self._lane.close())
                now = self._observe_time()
                if self._clock_failed:
                    self._failed(RecoveryReason.INTERNAL_FAILURE, unknown=True)
                elif self._drain_deadline is not None and now >= self._drain_deadline:
                    self._failed(RecoveryReason.DRAIN_TIMEOUT, unknown=True)
                    self._status(native=False)  # Close returned; lifecycle still timed out.
                elif self._current.phase is not RecoveryPhase.FAILED:
                    self._status(phase=RecoveryPhase.STOPPED, ready=False, native=False, clean=True)
                else:
                    self._status(ready=False, native=False, clean=True)
            except BaseException:
                self._failed(RecoveryReason.CLEANUP_UNRESOLVED, unknown=True, cleanup=True)
        return self.snapshot()

    def snapshot(self):
        with self._lock:
            self._material.require()
            now = self._observe_time()
            self._project_clock_fault_locked()
            self._material.enter()
            try:
                s = self._current
                age = None if self._last_progress is None else _age_ms(self._last_progress, now)
                domain = s.startup_verified and _domain_active()
                stale = age is None or age > self._config.progress_timeout_seconds * 1000
                reason = s.reason
                if reason is RecoveryReason.NONE:
                    if (
                        not s.clean_stop
                        and self._drain_deadline is not None
                        and now >= self._drain_deadline
                    ):
                        reason = RecoveryReason.DRAIN_TIMEOUT
                    elif stale and s.phase is RecoveryPhase.IDLE:
                        reason = RecoveryReason.PROGRESS_STALE
                draft = (
                    s.phase,
                    reason,
                    s.latest_page_outcome,
                    s.ready
                    and domain
                    and not stale
                    and not self._stop.is_set()
                    and not s.unresolved,
                    s.startup_verified,
                    domain,
                    self._stop.is_set(),
                    s.admission_closed or self._stop.is_set(),
                    s.native_in_flight,
                    s.cleanup_unresolved,
                    s.unresolved,
                    s.clean_stop,
                    s.has_committed_page,
                    s.last_committed_raw_cursor,
                    s.next_scan_after,
                    s.last_committed_pass_exhausted,
                    s.last_committed_visited,
                    s.last_committed_queued,
                    s.last_committed_expired,
                    s.last_committed_failed,
                    s.last_committed_held,
                    s.committed_pages,
                    s.committed_sweeps,
                    s.committed_visited,
                    s.committed_queued,
                    s.committed_expired,
                    s.committed_failed,
                    s.committed_held,
                    s.progress_sequence,
                    age,
                    s.counters_saturated or age == UINT64_MAX,
                )
                exported = _build_snapshot(draft)
                draft = s = None
                return exported  # Ownership transfers while export allowance remains admitted.
            finally:
                self._material.leave()

    def dispose(self):
        with self._lock:
            self._material.require()
            if (
                self._current.unresolved
                or not self._current.clean_stop
                or self._page_reserved
                or self._pending is not None
                or self._material.busy
            ):
                raise RuntimeError("Recovery owner is not known quiescent")
            self._current = None
            self._material.release(known=True, quiescent=True)


def create_job_recovery(*, config, resources, application):
    _validate_config(config)
    if type(resources) is not NativeRecoveryResources:
        raise ValueError("Expected exact recovery resources")
    if not callable(getattr(application, "validate_profile", None)) or not callable(
        getattr(application, "authorize_root", None)
    ):
        raise ValueError("Expected explicit recovery authorization lifetime")
    _setup._recheck_profile(config, resources)
    owner = object.__new__(JobRecoveryOwner)
    owner._config, owner._resources, owner._application = config, resources, application
    owner._lock, owner._stop = RLock(), Event()
    owner._material = _RecoveryMaterialLease(config.source_material_bytes)
    owner._material.admit()  # Before initial snapshot, not just before SQL projection.
    owner._material.enter()
    try:
        draft = (
            RecoveryPhase.NEW,
            RecoveryReason.NONE,
            RecoveryPageOutcome.NONE,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
            None,
            None,
            False,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            None,
            False,
        )
        owner._current = _build_snapshot(draft)
        draft = None
    finally:
        owner._material.leave()
    owner._pending = owner._lane = owner._authority = None
    owner._last_progress = owner._next_due = owner._drain_deadline = None
    owner._run_called = owner._adoption_attempted = owner._page_reserved = False
    owner._last_clock = None
    owner._clock_failed = False
    return owner


def run_recovery_host(owner, /, *, stop_event):
    if type(owner) is not JobRecoveryOwner:
        raise ValueError("Expected exact recovery owner")
    owner.run(stop_event=stop_event)
    with owner._lock:
        result = owner.snapshot()  # Authoritative fault projection before host success.
        if result.clean_stop and result.phase is RecoveryPhase.STOPPED:
            return 0
        if not result.unresolved and not result.startup_verified:
            return 78
        return 70
