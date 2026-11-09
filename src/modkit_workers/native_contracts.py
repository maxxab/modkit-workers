"""Import-neutral shared native job contracts.

Constructing a carrier does not validate native resources, adopt them, start
threads, configure Events, or grant application authorization.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from ._native_control_contracts import (
    JobSourcePhase,
    JobSourceSnapshot,
    NativeAdmissionKind,
    NativeWorkerSettings,
    RenewalQuiescence,
    WorkerReason,
    WorkerSnapshot,
    WorkerState,
    _seconds,
)

if TYPE_CHECKING:
    from modkit_events.persistence.bindings import ReadinessExpectation
    from modkit_events.persistence.ledger import ExecutionLedger
    from modkit_events.persistence.models import Fence
    from modkit_events.persistence.native_sync import ManagedConnection

    from .native_job import JobWork
    from .native_setup import NativeJobConfigurationReceipt

__all__ = [
    "JobSourcePhase", "JobSourceSnapshot", "NativeAdmissionKind", "NativeJobConfig",
    "NativeJobResources", "NativeWorkerSettings", "RenewalQuiescence", "SourceControl",
    "WorkerReason", "WorkerSnapshot", "WorkerState",
]


def _integer(value: object, low: int, high: int | None = None) -> int:
    if type(value) is not int or value < low or (high is not None and value > high):
        raise ValueError("Invalid native job bound")
    return value


def _required_source_material_bytes(payload_bytes: int, result_bytes: int) -> int:
    """Accepted logical source envelope; not an allocation or RSS promise."""
    graph = 1024 * (1 + payload_bytes // 9) + 8 * payload_bytes
    return 4 * graph + 16 * 33 * payload_bytes + 262144 + 4 * result_bytes + 4096


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class NativeJobConfig:
    readiness: ReadinessExpectation
    lease_seconds: float
    max_acquire_page_payload_bytes: int
    max_payload_bytes: int
    max_payload_depth: int
    max_result_bytes: int
    source_material_bytes: int

    def __post_init__(self) -> None:
        from modkit_events.persistence.bindings import ReadinessExpectation

        if type(self.readiness) is not ReadinessExpectation:
            raise ValueError("Expected exact ReadinessExpectation")
        self.readiness.__post_init__()
        if tuple(item.component for item in self.readiness.components) != ("events", "workers"):
            raise ValueError("Native jobs require events and workers readiness pins")
        lease = _seconds(self.lease_seconds)
        if lease > 3600:
            raise ValueError("Invalid native job lease")
        object.__setattr__(self, "lease_seconds", lease)
        _integer(self.max_acquire_page_payload_bytes, 1, 2**32)
        _integer(self.max_payload_bytes, 1, 1048576)
        _integer(self.max_result_bytes, 1, 1048576)
        _integer(self.max_payload_depth, 1, 32)
        _integer(self.source_material_bytes, _required_source_material_bytes(
            self.max_payload_bytes, self.max_result_bytes
        ))


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class NativeJobResources:
    configuration: NativeJobConfigurationReceipt
    data_connection: ManagedConnection
    renewal_connection: ManagedConnection
    data_ledger: ExecutionLedger
    renewal_ledger: ExecutionLedger


class SourceControl(Protocol):
    """Source supplies durable observations; scheduler never infers DB truth."""

    settings: NativeWorkerSettings

    def admit_startup(self, source: object, /) -> None: ...
    def require_admission(self, source: object, /, *, kind: NativeAdmissionKind) -> object: ...
    def reserve_acquisition(self, source: object, /) -> object: ...
    def require_reserved_acquisition(self, source: object, reservation: object, /) -> object: ...
    def publish_acquisition(self, reservation: object, work: JobWork | None, /) -> None: ...
    def refuse_acquisition(self, reservation: object, /, *, reason: WorkerReason) -> None: ...
    def activate(self, work: JobWork, fence: Fence, /) -> None: ...
    def close_renewal(self, work: JobWork, /) -> object: ...
    def await_renewal_quiescent(
        self, token: object, /, *, deadline_monotonic: float,
    ) -> RenewalQuiescence: ...
    def retire_work(self, work: JobWork, /) -> None: ...
    def fail(self, reason: WorkerReason, /) -> None: ...

    @property
    def stop_requested(self) -> bool: ...
