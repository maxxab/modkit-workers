"""Inert scalar job-recovery contracts; no driver, connection or process creation.

Logical occurrence sizes are not native allocations, temporary-byte or RSS caps.
"""
from __future__ import annotations

import math
import struct
import sys
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from uuid import UUID

if TYPE_CHECKING:
    from modkit_events.persistence.bindings import ReadinessExpectation
    from modkit_events.persistence.ledger import ExecutionLedger
    from modkit_events.persistence.native_sync import ManagedConnection

    from .native_recovery_setup import NativeRecoveryConfigurationReceipt

UINT64_MAX = 2**64 - 1


class RecoveryPhase(Enum):
    NEW = 0
    STARTING = 1
    IDLE = 2
    SCANNING = 3
    DRAINING = 4
    STOPPED = 5
    FAILED = 6


class RecoveryReason(Enum):
    NONE = 0
    CONFIGURATION_REJECTED = 1
    PROFILE_REJECTED = 2
    RESOURCE_REJECTED = 3
    READINESS_REJECTED = 4
    AUTHORITY_REJECTED = 5
    DOMAIN_STOPPED = 6
    PREPARATION_REJECTED = 7
    RESULT_REJECTED = 8
    ROOT_UNKNOWN = 9
    COMMIT_UNKNOWN = 10
    ROLLBACK_UNKNOWN = 11
    AUTHORITY_EXIT_FAILED = 12
    CLEANUP_UNRESOLVED = 13
    PROGRESS_STALE = 14
    DRAIN_TIMEOUT = 15
    INTERNAL_FAILURE = 16


class RecoveryPageOutcome(Enum):
    NONE = 0
    PENDING = 1
    COMMITTED = 2
    ROLLED_BACK = 3
    UNKNOWN = 4


class RecoveryMaterialState(Enum):
    CONFIGURED = 0
    ADMITTED = 1
    HELD = 2
    RELEASED = 3


@dataclass(frozen=True, slots=True, repr=False)
class RecoverySnapshot:
    phase: RecoveryPhase
    reason: RecoveryReason
    latest_page_outcome: RecoveryPageOutcome
    ready: bool
    startup_verified: bool
    domain_active: bool
    stop_requested: bool
    admission_closed: bool
    native_in_flight: bool
    cleanup_unresolved: bool
    unresolved: bool
    clean_stop: bool
    has_committed_page: bool
    last_committed_raw_cursor: int | None
    next_scan_after: int | None
    last_committed_pass_exhausted: bool
    last_committed_visited: int
    last_committed_queued: int
    last_committed_expired: int
    last_committed_failed: int
    last_committed_held: int
    committed_pages: int
    committed_sweeps: int
    committed_visited: int
    committed_queued: int
    committed_expired: int
    committed_failed: int
    committed_held: int
    progress_sequence: int
    progress_age_ms: int | None
    counters_saturated: bool

    def __post_init__(self):
        if (type(self.phase) is not RecoveryPhase or type(self.reason) is not RecoveryReason
                or type(self.latest_page_outcome) is not RecoveryPageOutcome):
            raise ValueError("Invalid recovery snapshot enum")
        for name in self.__slots__[3:13] + ("last_committed_pass_exhausted", "counters_saturated"):
            if type(getattr(self, name)) is not bool:
                raise ValueError("Invalid recovery snapshot boolean")
        for value in (self.last_committed_raw_cursor, self.next_scan_after):
            if value is not None:
                _integer(value, 0, 2**128 - 1)
        _integer(self.last_committed_visited, 0, 4096)
        for name in self.__slots__[17:21]:
            _integer(getattr(self, name), 0, 1)
        if (self.last_committed_queued + self.last_committed_expired
                + self.last_committed_failed + self.last_committed_held
                > min(1, self.last_committed_visited)):
            raise ValueError("Invalid recovery snapshot cardinality")
        for name in self.__slots__[21:29]:
            _integer(getattr(self, name), 0, UINT64_MAX)
        if self.progress_age_ms is not None:
            _integer(self.progress_age_ms, 0, UINT64_MAX)


@dataclass(frozen=True, slots=True, repr=False)
class PendingRecoverySummary:
    visited: int
    raw_cursor: int | None
    pass_exhausted: bool
    queued: int
    expired: int
    failed: int
    held: int

    def __post_init__(self):
        _integer(self.visited, 0, 4096)
        if self.raw_cursor is not None:
            _integer(self.raw_cursor, 0, 2**128 - 1)
        if type(self.pass_exhausted) is not bool:
            raise ValueError("Invalid recovery summary boolean")
        for value in (self.queued, self.expired, self.failed, self.held):
            _integer(value, 0, 1)
        if self.queued + self.expired + self.failed + self.held > min(1, self.visited):
            raise ValueError("Invalid recovery summary cardinality")


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError("Invalid recovery integer bound")
    return value


def _seconds(value):
    if type(value) not in (int, float) or not 0 < value <= sys.float_info.max:
        raise ValueError("Invalid recovery seconds")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("Invalid recovery seconds")
    return result


def _namespace(namespace):
    if type(namespace) is not bytes or namespace != b"jobs":
        raise ValueError("Recovery namespace must be exact jobs bytes")


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class NativeRecoveryConfig:
    namespace: bytes
    readiness: ReadinessExpectation
    source_material_bytes: int
    discovery_budget: int = 128
    turn_interval_seconds: float = 0.05
    fallback_interval_seconds: float = 5.0
    progress_timeout_seconds: float = 30.0
    drain_timeout_seconds: float = 30.0

    def __post_init__(self):
        _namespace(self.namespace)  # Before dependency validators or any hook.
        _integer(self.discovery_budget, 1, 4096)
        _integer(self.source_material_bytes, required_recovery_source_material_bytes(), UINT64_MAX)
        turn = _seconds(self.turn_interval_seconds)
        fallback = _seconds(self.fallback_interval_seconds)
        progress = _seconds(self.progress_timeout_seconds)
        drain = _seconds(self.drain_timeout_seconds)
        if not 0.001 <= turn <= 5 or fallback > 5 or progress < fallback:
            raise ValueError("Invalid recovery scheduling bounds")
        from modkit_events.persistence.bindings import ReadinessExpectation

        if type(self.readiness) is not ReadinessExpectation:
            raise ValueError("Expected exact recovery readiness")
        self.readiness.__post_init__()
        if tuple(item.component for item in self.readiness.components) != ("events", "workers"):
            raise ValueError("Expected workers readiness pins")
        object.__setattr__(self, "turn_interval_seconds", turn)
        object.__setattr__(self, "fallback_interval_seconds", fallback)
        object.__setattr__(self, "progress_timeout_seconds", progress)
        object.__setattr__(self, "drain_timeout_seconds", drain)


def _validate_config(config):
    if type(config) is not NativeRecoveryConfig:
        raise ValueError("Expected exact recovery configuration")
    _namespace(config.namespace)
    config.__post_init__()


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class NativeRecoveryResources:
    configuration: NativeRecoveryConfigurationReceipt
    connection: ManagedConnection
    ledger: ExecutionLedger


def _scalar_interpreter_profile():
    if sys.implementation.name != "cpython":
        raise ValueError("Unsupported recovery scalar profile")
    if sys.version_info[:2] == (3, 12):
        # Preserve the existing family/platform scope; layout guards still apply.
        return "cpython-3.12-scalar-64"
    if tuple(sys.version_info) != (3, 13, 5, "final", 0):
        raise ValueError("Unsupported recovery scalar profile")
    import platform
    import sysconfig

    gil_disabled = sysconfig.get_config_var("Py_GIL_DISABLED")
    debug = sysconfig.get_config_var("Py_DEBUG")
    gil_enabled = getattr(sys, "_is_gil_enabled", None)
    if (sys.platform != "linux" or platform.machine() != "x86_64"
            or type(gil_disabled) is not int or gil_disabled != 0
            or type(debug) is not int or debug != 0
            or not callable(gil_enabled) or gil_enabled() is not True):
        raise ValueError("Unsupported recovery scalar profile")
    return "cpython-3.13.5-linux-x86_64-gil-scalar-64"


def _summary_profile():
    """Evaluate the reviewed scalar formula, never instantiate a paid leaf.

    Fail closed outside the exact CPython layout. This qualifies scalar layout
    only: it neither attests an Events native profile nor driver/build readiness.
    The dictionary is a pure setup report, not retained per-page material.
    """
    profile_id = _scalar_interpreter_profile()
    if (struct.calcsize("P") != 8 or hasattr(sys, "gettotalrefcount")
            or sys.int_info.bits_per_digit != 30 or sys.int_info.sizeof_digit != 4
            or object.__basicsize__ != 16 or tuple.__basicsize__ != 24
            or sys.getsizeof(()) != 40 or sys.getsizeof(0) != 28
            or RecoverySnapshot.__basicsize__ != 264
            or PendingRecoverySummary.__basicsize__ != 72):
        raise ValueError("Unsupported recovery scalar profile")
    # Shallow carrier + GC header, with all referents counted per occurrence.
    u = max(sys.getsizeof(None), sys.getsizeof(True), sys.getsizeof(False))
    e = max(sys.getsizeof(member) for kind in (
        RecoveryPhase, RecoveryReason, RecoveryPageOutcome, RecoveryMaterialState
    ) for member in kind)
    f = sys.getsizeof(0.0)
    if u != 28 or e != 48 or f != 24:
        raise ValueError("Unsupported recovery scalar coefficients")
    j13, j64, j128 = 28, 36, 44
    v31 = 3 * e + 12 * u + 2 * max(j128, u) + 5 * j13 + 9 * max(j64, u)
    v7 = 5 * j13 + max(j128, u) + u
    s, p = 280 + v31, 88 + v7
    c31, c7 = 288 + v31, 96 + v7
    lease = 64 + 2 * j64 + e + u
    scratch = 7 * max(f, u) + 3 * j64 + 5 * u
    if sys.getsizeof(UUID(int=0)) != 64:
        raise ValueError("Unsupported recovery cursor profile")
    # Caller-owned UUID + its int + borrowed scalar occurrence, before native D.
    # No pending summary exists in this preparation phase.
    cursor_transient = 64 + 2 * j128
    required = lease + scratch + max(s + c31, s + p + c7, 2 * s + p + c31,
                                     3 * s + p + c31, 3 * s + c31 + cursor_transient)
    _integer(required, 1, UINT64_MAX)
    return {"interpreter_profile_id": profile_id,
            "interpreter_version": tuple(sys.version_info[:3]), "S": s, "P": p, "C31": c31, "C7": c7, "L": lease, "Q": scratch,
            "cursor_transient": cursor_transient, "required": required}


def required_recovery_source_material_bytes() -> int:
    return _summary_profile()["required"]


def _add(value, delta):
    _integer(value, 0, UINT64_MAX)
    _integer(delta, 0, 4096)
    return UINT64_MAX if value > UINT64_MAX - delta else value + delta


def _age_ms(start, now):
    if type(start) is not float or type(now) is not float:
        raise ValueError("Expected exact monotonic observations")
    if not math.isfinite(start) or not math.isfinite(now) or now < start:
        raise ValueError("Invalid recovery clock")
    elapsed = now - start
    if not math.isfinite(elapsed) or elapsed >= UINT64_MAX / 1000:
        return UINT64_MAX
    scaled = elapsed * 1000
    if not math.isfinite(scaled) or scaled >= UINT64_MAX:
        return UINT64_MAX
    return int(scaled)
