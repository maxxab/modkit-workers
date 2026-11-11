"""Private import-neutral scheduling contracts, not a native product API."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from math import isfinite
from typing import Protocol, TypeVar, cast

WorkT = TypeVar("WorkT")
FenceT = TypeVar("FenceT", contravariant=True)


def _seconds(value: object, *, zero: bool = False) -> float:
    if type(value) not in (int, float):
        raise ValueError("Expected finite seconds")
    try:
        # Exact type membership is stricter than the numeric protocols.
        result = float(cast("int | float", value))
    except OverflowError:
        raise ValueError("Expected finite seconds") from None
    if not isfinite(result) or result < 0 or (not zero and result == 0):
        raise ValueError("Expected finite seconds")
    return result


@dataclass(frozen=True, slots=True, kw_only=True)
class NativeWorkerSettings:
    renewal_interval_seconds: float
    poll_interval_seconds: float = 1.0
    drain_timeout_seconds: float = 30.0
    progress_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        for name in self.__dataclass_fields__:
            object.__setattr__(self, name, _seconds(getattr(self, name)))


class JobSourcePhase(Enum):
    NEW = "new"
    STARTING = "starting"
    IDLE = "idle"
    ACQUIRING = "acquiring"
    CLAIMED = "claimed"
    DISPATCHING = "dispatching"
    RUNNING = "running"
    SETTLING = "settling"
    DRAINING = "draining"
    STOPPED = "stopped"
    FAILED = "failed"


class WorkerState(Enum):
    NEW = "new"
    STARTING = "starting"
    RUNNING = "running"
    DRAINING = "draining"
    STOPPED = "stopped"
    FAILED = "failed"


class WorkerReason(Enum):
    PROFILE_UNSUPPORTED = "profile_unsupported"
    STARTUP_REJECTED = "startup_rejected"
    STARTUP_UNKNOWN = "startup_unknown"
    EXECUTION_FAILED = "execution_failed"
    RENEWAL_FAILED = "renewal_failed"
    OUTCOME_UNKNOWN = "outcome_unknown"
    DOMAIN_STOPPED = "domain_stopped"
    CAPACITY_UNAVAILABLE = "capacity_unavailable"
    CONTROL_FAILED = "control_failed"
    DRAIN_TIMEOUT = "drain_timeout"
    PROGRESS_STALE = "progress_stale"


class _AdmissionClosed(RuntimeError):
    """Known local nonadmission because stop won the reservation lock."""


class NativeAdmissionKind(Enum):
    ACQUIRE = "acquire"
    ADMITTED_EXECUTION = "admitted_execution"
    RENEWAL = "renewal"
    SETTLEMENT = "settlement"


@dataclass(frozen=True, slots=True)
class RenewalQuiescence:
    quiescent: bool
    outcome_known: bool
    domain_active: bool

    def __post_init__(self) -> None:
        if any(
            type(value) is not bool
            for value in (self.quiescent, self.outcome_known, self.domain_active)
        ):
            raise ValueError("Quiescence requires exact booleans")


@dataclass(frozen=True, slots=True, kw_only=True)
class JobSourceSnapshot:
    phase: JobSourcePhase = JobSourcePhase.NEW
    resources_adopted: bool = False
    startup_verified: bool = False
    admission_closed: bool = True
    domain_active: bool = False
    slot_occupied: bool = False
    native_in_flight: bool = False
    renewal_in_flight: bool = False
    cleanup_complete: bool = False
    unresolved: bool = False
    scan_exhausted: bool = False
    scan_progress: bool = False
    confirmed_succeeded: int = 0
    confirmed_failed: int = 0
    confirmed_cancelled: int = 0
    confirmed_held: int = 0
    unknown_outcomes: int = 0
    acquisition_pages: int = 0
    renewal_commits: int = 0
    progress_sequence: int = 0
    counters_saturated: bool = False
    last_progress_monotonic: float | None = None
    reason: WorkerReason | None = None

    def __post_init__(self) -> None:
        if type(self.phase) is not JobSourcePhase:
            raise ValueError("Expected JobSourcePhase")
        if self.reason is not None and type(self.reason) is not WorkerReason:
            raise ValueError("Expected WorkerReason")
        for name in (
            "resources_adopted",
            "startup_verified",
            "admission_closed",
            "domain_active",
            "slot_occupied",
            "native_in_flight",
            "renewal_in_flight",
            "cleanup_complete",
            "unresolved",
            "scan_exhausted",
            "scan_progress",
            "counters_saturated",
        ):
            if type(getattr(self, name)) is not bool:
                raise ValueError("Expected exact boolean observation")
        for name in (
            "confirmed_succeeded",
            "confirmed_failed",
            "confirmed_cancelled",
            "confirmed_held",
            "unknown_outcomes",
            "acquisition_pages",
            "renewal_commits",
            "progress_sequence",
        ):
            value = getattr(self, name)
            if type(value) is not int or not 0 <= value <= 2**64 - 1:
                raise ValueError("Expected bounded unsigned counter")
        if self.last_progress_monotonic is not None:
            _seconds(self.last_progress_monotonic, zero=True)


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkerSnapshot:
    state: WorkerState
    ready: bool
    clean_stop: bool
    stop_requested: bool
    execution_in_flight: bool
    renewal_in_flight: bool
    startup_in_flight: bool
    source: JobSourceSnapshot
    reason: WorkerReason | None = None


class _NativeJobPort(Protocol[WorkT, FenceT]):
    def startup(self, request: object, /) -> None: ...
    def acquire(self, request: object, /) -> tuple[WorkT, ...]: ...
    def execute(self, work: WorkT, /) -> None: ...
    def request_stop(self) -> None: ...
    def renew(self, work: WorkT, fence: FenceT, /) -> None: ...
    def shutdown(self) -> None: ...
    def snapshot(self) -> JobSourceSnapshot: ...
