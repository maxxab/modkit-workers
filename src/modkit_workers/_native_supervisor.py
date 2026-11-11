"""Private three-lane coordinator against a source port, never a native source."""

from __future__ import annotations

from threading import Event, Lock, Thread, current_thread
from time import monotonic

from ._native_control import _SourceControl
from ._native_control_contracts import (
    JobSourceSnapshot,
    NativeWorkerSettings,
    WorkerReason,
    WorkerSnapshot,
    WorkerState,
    _AdmissionClosed,
    _NativeJobPort,
    _seconds,
)


class _SupervisorCore:
    """Runs a bound source without providing public/native configuration.

    Native ownership and durable results belong exclusively to the source. The
    private controller performs scheduling, not transactions or resource refunds.
    """

    def __init__(
        self,
        source: _NativeJobPort,
        control: _SourceControl,
        request: object,
        settings: NativeWorkerSettings,
    ):
        if type(settings) is not NativeWorkerSettings or type(control) is not _SourceControl:
            raise ValueError("Expected private control and validated settings")
        self._source, self._control = source, control
        self._request, self._settings = request, settings
        control.bind_source(source)
        control.bind_renewal(source.renew)
        self._lock = Lock()
        self._stop = Event()
        self._startup_done = Event()
        self._ready_gate = Event()
        self._data_done = Event()
        self._finished = Event()
        self._coordinator: Thread | None = None
        self._data: Thread | None = None
        self._state = WorkerState.NEW
        self._reason: WorkerReason | None = None
        self._source_snapshot = JobSourceSnapshot()
        self._executing = False
        self._startup_in_flight = False
        self._clean = False
        self._last_tick = monotonic()
        self._drain_admission_deadline: float | None = None

    def start(self) -> None:
        with self._lock:
            if self._state is not WorkerState.NEW:
                raise RuntimeError("Supervisor start is one-shot")
            self._state = WorkerState.STARTING
            self._startup_in_flight = True
        try:
            # Allocation can fail before a joinable coordinator exists too.
            with self._lock:
                self._coordinator = Thread(
                    target=self._coordinate, name="modkit-coordinator", daemon=False
                )
                thread = self._coordinator
            thread.start()
        except BaseException:
            self._record_failure(WorkerReason.CONTROL_FAILED)
            with self._lock:
                self._startup_in_flight = False
            self._finished.set()
            raise

    def request_stop(self) -> None:
        # The controller's lock defines stop versus W05 reservation ordering.
        self._control.request_stop()
        with self._lock:
            if self._drain_admission_deadline is None:
                self._drain_admission_deadline = monotonic() + self._settings.drain_timeout_seconds
        self._stop.set()
        try:
            self._source.request_stop()
        except BaseException:
            self._record_failure(WorkerReason.CONTROL_FAILED)
        with self._lock:
            if self._state in (WorkerState.STARTING, WorkerState.RUNNING):
                self._state = WorkerState.DRAINING

    def stop(self, *, timeout: float | None = None) -> WorkerSnapshot:
        wait = (
            self._settings.drain_timeout_seconds
            if timeout is None
            else _seconds(timeout, zero=True)
        )
        deadline = monotonic() + wait
        self.request_stop()
        if not self._finished.wait(max(0.0, deadline - monotonic())):
            return self.snapshot(wait_expired=True)
        self.join(max(0.0, deadline - monotonic()))
        return self.snapshot()

    def join(self, timeout: float | None = None) -> bool:
        wait = None if timeout is None else _seconds(timeout, zero=True)
        thread = self._coordinator
        if thread is None:
            return True
        if thread.ident is None:
            # Failed or pending start has no joinable thread. Keep the owner
            # and failure snapshot without claiming confirmed thread exit.
            return False
        if thread is current_thread():
            raise RuntimeError("Cannot join own coordinator")
        thread.join(wait)
        return not thread.is_alive()

    def _record_failure(self, reason: WorkerReason) -> None:
        self._control.fail(reason)
        self._stop.set()
        with self._lock:
            if self._reason is None:
                self._reason = reason
            self._state = WorkerState.FAILED

    def _observe_source(self) -> JobSourceSnapshot:
        snapshot = self._source.snapshot()
        if type(snapshot) is not JobSourceSnapshot:
            raise TypeError("Source.snapshot must return JobSourceSnapshot")
        with self._lock:
            self._source_snapshot = snapshot
        return snapshot

    def _coordinate(self) -> None:
        try:
            self._control.register_lane("coordinator")
            self._control.start_renewal()
            self._data = Thread(target=self._run_data, name="modkit-data", daemon=False)
            self._data.start()
            while not self._startup_done.wait(0.01):
                self._observe_source()
                with self._lock:
                    self._last_tick = monotonic()
            with self._lock:
                self._startup_in_flight = False
            source = self._observe_source()
            if not self._stop.is_set() and not self._control.stop_requested:
                if not source.startup_verified or not source.domain_active:
                    self._record_failure(WorkerReason.STARTUP_REJECTED)
                else:
                    try:
                        self._control.publish_ready(self._source)
                    except _AdmissionClosed:
                        if not self._control.stop_requested or self._control.failure is not None:
                            raise
                    with self._lock:
                        self._state = (
                            WorkerState.DRAINING
                            if self._stop.is_set() or self._control.stop_requested
                            else WorkerState.RUNNING
                        )
            self._ready_gate.set()
            while not self._data_done.wait(0.01):
                source = self._observe_source()
                if source.startup_verified and not source.domain_active:
                    self._record_failure(WorkerReason.DOMAIN_STOPPED)
                if self._control.failure is not None:
                    self._record_failure(self._control.failure)
                with self._lock:
                    self._last_tick = monotonic()
        except BaseException:
            self._record_failure(WorkerReason.CONTROL_FAILED)
        finally:
            self._ready_gate.set()
            data = self._data
            if data is not None and data.ident is not None:
                data.join()
            self._control.request_renewal_exit()
            self._control.join_renewal()
            try:
                source = self._observe_source()
            except BaseException:
                self._record_failure(WorkerReason.CONTROL_FAILED)
                with self._lock:
                    source = self._source_snapshot
            if self._control.failure is not None:
                self._record_failure(self._control.failure)
            with self._lock:
                self._startup_in_flight = False
                self._clean = (
                    (self._reason is None or self._control.known_refusal)
                    and source.cleanup_complete
                    and not source.unresolved
                    and not source.native_in_flight
                    and not source.slot_occupied
                    and not self._control.acquisition_in_flight
                    and self._control.current_work is None
                )
                self._state = (
                    WorkerState.STOPPED
                    if self._clean and self._reason is None
                    else WorkerState.FAILED
                )
            self._finished.set()

    def _run_data(self) -> None:
        started = False
        try:
            self._control.register_lane("data")
            # Defensive runtime validation must detect violations of the typed port.
            if self._source.startup(self._request) is not None:  # type: ignore[func-returns-value]
                raise TypeError("Source.startup must return None")
            started = True
            self._startup_done.set()
            self._ready_gate.wait()
            while not self._stop.is_set() and self._control.failure is None:
                try:
                    batch = self._source.acquire(self._request)
                except _AdmissionClosed:
                    if (
                        not self._control.stop_requested
                        or self._control.acquisition_in_flight
                        or self._control.current_work is not None
                    ):
                        raise
                    break
                if type(batch) is not tuple or len(batch) > 1:
                    raise TypeError("Private source must acquire an exact one-slot tuple")
                if batch:
                    work = batch[0]
                    if work is not self._control.current_work:
                        raise RuntimeError("Source returned unadmitted work")
                    with self._lock:
                        deadline = self._drain_admission_deadline
                    if deadline is not None and monotonic() >= deadline:
                        self._record_failure(WorkerReason.DRAIN_TIMEOUT)
                        break
                    with self._lock:
                        self._executing = True
                    try:
                        if self._source.execute(work) is not None:  # type: ignore[func-returns-value]
                            raise TypeError("Source.execute must return None")
                    finally:
                        with self._lock:
                            self._executing = False
                    if self._control.current_work is not None:
                        raise RuntimeError("Source returned without confirmed terminal retirement")
                else:
                    if (
                        self._control.acquisition_in_flight
                        or self._control.current_work is not None
                    ):
                        raise RuntimeError("Source returned while acquisition is unresolved")
                    self._stop.wait(self._settings.poll_interval_seconds)
        except _AdmissionClosed:
            # Only pre-start stop nonadmission is orderly. Source exceptions
            # after admission or unrelated failures remain real failures.
            if (
                started
                or not self._control.stop_requested
                or self._control.failure is not None
                or self._control._startup_admitted
            ):
                self._record_failure(
                    WorkerReason.EXECUTION_FAILED if started else WorkerReason.STARTUP_REJECTED
                )
        except BaseException:
            self._record_failure(
                WorkerReason.EXECUTION_FAILED if started else WorkerReason.STARTUP_REJECTED
            )
        finally:
            self._startup_done.set()
            self._control.request_renewal_exit()
            self._control.join_renewal()
            try:
                if self._source.shutdown() is not None:  # type: ignore[func-returns-value]
                    raise TypeError("Source.shutdown must return None")
            except BaseException:
                self._record_failure(WorkerReason.CONTROL_FAILED)
            self._data_done.set()

    def snapshot(self, *, wait_expired: bool = False) -> WorkerSnapshot:
        with self._lock:
            state, reason, source = self._state, self._reason, self._source_snapshot
            startup, executing, clean = self._startup_in_flight, self._executing, self._clean
            tick = self._last_tick
        now = monotonic()
        source_tick = source.last_progress_monotonic
        clean = clean and (self._coordinator is None or not self._coordinator.is_alive())
        stale = (
            now - tick > self._settings.progress_timeout_seconds
            or source_tick is None
            or now - source_tick > self._settings.progress_timeout_seconds
        )
        ready = (
            state is WorkerState.RUNNING
            and self._control.live
            and source.startup_verified
            and source.domain_active
            and not source.unresolved
            and not stale
        )
        if wait_expired:
            reason = reason or WorkerReason.DRAIN_TIMEOUT
        elif stale and state is WorkerState.RUNNING:
            reason = reason or WorkerReason.PROGRESS_STALE
        return WorkerSnapshot(
            state=state,
            ready=ready,
            clean_stop=clean,
            stop_requested=self._stop.is_set(),
            execution_in_flight=executing,
            renewal_in_flight=self._control.renewal_in_flight,
            startup_in_flight=startup,
            source=source,
            reason=reason,
        )
