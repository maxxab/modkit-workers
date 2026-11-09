"""Private bounded control lane. No database operations or native imports."""
from __future__ import annotations

from collections.abc import Callable
from threading import Condition, Thread, current_thread
from time import monotonic

from ._native_control_contracts import (
    NativeAdmissionKind,
    NativeWorkerSettings,
    RenewalQuiescence,
    WorkerReason,
    _AdmissionClosed,
    _seconds,
)


class _Identity:
    __slots__ = ()

    def __new__(cls):
        raise TypeError("Control identities are issued internally")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("Control identities cannot be subclassed")

    def __copy__(self):
        raise TypeError("Control identities cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("Control identities cannot be copied")

    def __reduce__(self):
        raise TypeError("Control identities cannot be serialized")


def _identity():
    return object.__new__(_Identity)


class _SourceControl:
    """One lifetime lease, one admitted acquisition/work and one renewal.

    Methods accepting source lifecycle observations do not themselves establish
    database outcomes. Only the bound data/renewal lanes may publish them.
    """

    def __init__(self, settings: NativeWorkerSettings):
        if type(settings) is not NativeWorkerSettings:
            raise ValueError("Expected NativeWorkerSettings")
        self.settings = settings
        self._cv = Condition()
        self._source = None
        self._renew: Callable | None = None
        self._lanes: dict[str, Thread] = {}
        self._renewal_thread: Thread | None = None
        self._lease = None
        self._started = False
        self._ready = False
        self._startup_admitted = False
        self._stop = False
        self._exit = False
        self._failure: WorkerReason | None = None
        self._known_refusal = False
        self._acquisition = None
        self._work = None
        self._fence = None
        self._active = False
        self._drain = None
        self._in_renewal = False
        self._renewal_known = True
        self._next_renewal = 0.0
        self._last_progress = monotonic()

    def bind_source(self, source: object, /) -> None:
        with self._cv:
            if source is None or self._source is not None or self._started:
                raise RuntimeError("Source binding is one-shot")
            self._source = source

    def bind_renewal(self, callback: Callable, /) -> None:
        with self._cv:
            if (not callable(callback) or getattr(callback, "__self__", None) is not self._source
                    or self._source is None or self._renew is not None or self._started):
                raise RuntimeError("Renewal binding is one-shot")
            self._renew = callback

    def register_lane(self, name: str, /) -> None:
        with self._cv:
            if name not in ("data", "coordinator", "renewal") or name in self._lanes:
                raise RuntimeError("Lane registration is one-shot")
            thread = current_thread()
            if thread in self._lanes.values():
                raise RuntimeError("Execution lanes must be independent")
            self._lanes[name] = thread
            self._cv.notify_all()

    def _on_lane(self, name: str) -> None:
        if self._lanes.get(name) is not current_thread():
            raise RuntimeError("Wrong control execution lane")

    def _live(self) -> bool:
        return all(name in self._lanes and self._lanes[name].is_alive()
                   for name in ("data", "coordinator", "renewal"))

    def start_renewal(self) -> None:
        with self._cv:
            if self._started or self._source is None or self._renew is None:
                raise RuntimeError("Renewal needs one complete binding")
            self._started = True
            thread = Thread(target=self._renewal_loop, name="modkit-renewal", daemon=False)
            self._renewal_thread = thread
            try:
                thread.start()
            except BaseException:
                self._fail_locked(WorkerReason.CONTROL_FAILED)
                raise
            while "renewal" not in self._lanes and thread.is_alive():
                self._cv.wait(0.01)
            if "renewal" not in self._lanes:
                raise RuntimeError("Renewal lane failed to start")

    def admit_startup(self, source: object, /) -> None:
        """Admit one bound data-lane initialization without granting work authority."""
        with self._cv:
            self._on_lane("data")
            if (source is not self._source or self._source is None
                    or not self._started or not self._live()
                    or self._failure is not None or self._ready or self._lease is not None
                    or self._startup_admitted):
                raise RuntimeError("Startup requires unused bound pre-ready control")
            if self._stop:
                raise _AdmissionClosed("Stop won startup admission")
            self._startup_admitted = True
            self._last_progress = monotonic()

    def publish_ready(self, source: object, /) -> None:
        with self._cv:
            self._on_lane("coordinator")
            if source is not self._source or self._lease is not None or not self._live():
                raise RuntimeError("Ready requires all bound live lanes")
            if self._failure is not None:
                raise RuntimeError("Failed control cannot become ready")
            if self._stop:
                raise _AdmissionClosed("Stop won readiness publication")
            self._lease = _identity()
            self._ready = True
            self._last_progress = monotonic()
            self._cv.notify_all()

    def _require(self, source: object, kind: NativeAdmissionKind):
        if type(kind) is not NativeAdmissionKind or source is not self._source:
            raise RuntimeError("Invalid admission identity")
        lane = "renewal" if kind is NativeAdmissionKind.RENEWAL else "data"
        self._on_lane(lane)
        if not self._ready or self._lease is None or self._failure or not self._live():
            raise RuntimeError("Control is not live")
        if kind is NativeAdmissionKind.ACQUIRE and self._stop:
            raise _AdmissionClosed("Acquisition stopped before reservation")
        if kind is not NativeAdmissionKind.ACQUIRE and self._work is None:
            raise RuntimeError("No admitted work")
        return self._lease

    def require_admission(self, source: object, /, *, kind: NativeAdmissionKind):
        with self._cv:
            return self._require(source, kind)

    def reserve_acquisition(self, source: object, /):
        with self._cv:
            self._require(source, NativeAdmissionKind.ACQUIRE)
            if self._acquisition is not None or self._work is not None:
                raise RuntimeError("One slot is already occupied")
            # Same lock as request_stop; this record precedes return/native call.
            self._acquisition = _identity()
            self._last_progress = monotonic()
            return self._acquisition

    def require_reserved_acquisition(self, source: object, reservation, /):
        """Validate an already-reserved continuation; ordinary stop is allowed."""
        with self._cv:
            self._on_lane("data")
            if (source is not self._source or not self._ready or self._lease is None
                    or self._failure is not None or not self._live()
                    or reservation is None or reservation is not self._acquisition
                    or self._work is not None):
                raise RuntimeError("Not a live reserved acquisition")
            return self._lease

    def publish_acquisition(self, reservation, work: object | None, /) -> None:
        with self._cv:
            self._on_lane("data")
            if reservation is not self._acquisition or reservation is None:
                raise RuntimeError("Not the current acquisition reservation")
            # A post-stop confirmed acquisition is retained admitted drain work.
            self._work = work
            self._acquisition = None
            self._last_progress = monotonic()
            self._cv.notify_all()

    def refuse_acquisition(self, reservation, /, *, reason: WorkerReason) -> None:
        """Source-observed confirmed no-claim only; never a native refund.

        Committed-empty uses publish_acquisition(token, None). Unknown outcomes
        use fail(), which retains this reservation. No rollback is inferred here.
        """
        if type(reason) is not WorkerReason:
            raise ValueError("Expected WorkerReason")
        with self._cv:
            self._on_lane("data")
            if (reservation is None or reservation is not self._acquisition
                    or self._failure is not None):
                raise RuntimeError("Refusal requires the exact known acquisition")
            self._acquisition = None
            self._fail_locked(reason)
            self._known_refusal = True
            self._last_progress = monotonic()

    def activate(self, work: object, fence: object, /) -> None:
        with self._cv:
            self._require(self._source, NativeAdmissionKind.ADMITTED_EXECUTION)
            if work is not self._work or fence is None or self._active or self._drain:
                raise RuntimeError("Invalid dispatched generation")
            self._fence = fence
            self._active = True
            self._renewal_known = True
            self._next_renewal = monotonic() + self.settings.renewal_interval_seconds
            self._cv.notify_all()

    def close_renewal(self, work: object, /):
        with self._cv:
            self._on_lane("data")
            if work is not self._work or work is None:
                raise RuntimeError("Not the current work")
            self._active = False
            if self._drain is None:
                self._drain = _identity()
            self._cv.notify_all()
            return self._drain

    def await_renewal_quiescent(self, token, /, *, deadline_monotonic: float):
        deadline = _seconds(deadline_monotonic, zero=True)
        with self._cv:
            self._on_lane("data")
            if token is not self._drain or token is None:
                raise RuntimeError("Not the current drain token")
            while self._in_renewal:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                self._cv.wait(remaining)
            return RenewalQuiescence(
                not self._in_renewal,
                not self._in_renewal and self._renewal_known,
                self._failure is None,
            )

    def retire_work(self, work: object, /) -> None:
        with self._cv:
            self._on_lane("data")
            if (work is not self._work or work is None or self._drain is None
                    or self._active or self._in_renewal or not self._renewal_known
                    or self._failure is not None):
                raise RuntimeError("Work is not known settled and quiescent")
            self._work = self._fence = self._drain = None
            self._last_progress = monotonic()
            self._cv.notify_all()

    def request_stop(self) -> None:
        with self._cv:
            self._stop = True
            self._cv.notify_all()

    def _fail_locked(self, reason: WorkerReason) -> None:
        if self._known_refusal and reason is not self._failure:
            self._known_refusal = False
        if self._failure is None:
            self._failure = reason
        self._stop = True
        self._ready = False
        self._active = False
        self._cv.notify_all()

    def fail(self, reason: WorkerReason, /) -> None:
        if type(reason) is not WorkerReason:
            raise ValueError("Expected WorkerReason")
        with self._cv:
            self._fail_locked(reason)

    def revoke_admission(self) -> None:
        self.fail(WorkerReason.CONTROL_FAILED)

    def wait_failed(self, timeout: float) -> bool:
        with self._cv:
            return self._cv.wait_for(lambda: self._failure is not None, _seconds(timeout, zero=True))

    def request_renewal_exit(self) -> None:
        with self._cv:
            self._exit = True
            self._active = False
            self._cv.notify_all()

    def join_renewal(self, timeout: float | None = None) -> bool:
        thread = self._renewal_thread
        if thread is None:
            return True
        if thread is current_thread():
            raise RuntimeError("Cannot join own renewal lane")
        thread.join(None if timeout is None else _seconds(timeout, zero=True))
        return not thread.is_alive()

    def _renewal_loop(self) -> None:
        self.register_lane("renewal")
        while True:
            with self._cv:
                while not self._exit:
                    delay = self._next_renewal - monotonic()
                    if self._active and self._failure is None and delay <= 0:
                        break
                    self._cv.wait(max(0.001, delay) if self._active else None)
                if self._exit:
                    return
                work, fence, callback = self._work, self._fence, self._renew
                self._in_renewal = True
                self._renewal_known = False
            succeeded = False
            try:
                # No control lock across application/native renewal.
                if callback(work, fence) is not None:
                    raise TypeError("Source.renew must return None")
                succeeded = True
            except BaseException:
                # Preserve bounded reason; source retains native uncertainty.
                with self._cv:
                    self._fail_locked(WorkerReason.RENEWAL_FAILED)
            finally:
                work = fence = callback = None
                with self._cv:
                    self._in_renewal = False
                    self._renewal_known = succeeded
                    self._last_progress = monotonic()
                    self._next_renewal = monotonic() + self.settings.renewal_interval_seconds
                    self._cv.notify_all()

    @property
    def known_refusal(self) -> bool:
        with self._cv:
            return self._known_refusal

    @property
    def acquisition_in_flight(self) -> bool:
        with self._cv:
            return self._acquisition is not None

    @property
    def renewal_in_flight(self) -> bool:
        with self._cv:
            return self._in_renewal

    @property
    def current_work(self):
        with self._cv:
            return self._work

    @property
    def stop_requested(self) -> bool:
        with self._cv:
            return self._stop

    @property
    def failure(self) -> WorkerReason | None:
        with self._cv:
            return self._failure

    @property
    def last_progress(self) -> float:
        with self._cv:
            return self._last_progress

    @property
    def live(self) -> bool:
        with self._cv:
            return self._ready and not self._stop and self._failure is None and self._live()
