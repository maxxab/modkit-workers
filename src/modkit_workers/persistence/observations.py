"""Protected job observations, never public projections or execution grants."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from uuid import UUID

from modkit_events.persistence import bindings as common
from modkit_events.persistence import models as shared
from modkit_events.persistence.errors import _observation_boundary
from modkit_events.persistence.observations import WorkObservation
from modkit_events.persistence.scope import Scope

from .models import _work_id


@dataclass(frozen=True, slots=True, repr=False)
class JobDetails:
    work_id: str
    application: str
    tenant: str | None
    owner: str | None
    protected_binding: bytes

    @_observation_boundary
    def __post_init__(self) -> None:
        _work_id(self.work_id)
        Scope(self.application, self.tenant, self.owner)
        binding = common._bytes(self.protected_binding)
        common.decode_protected_binding(binding)
        object.__setattr__(self, 'protected_binding', binding)


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobPayload:
    semantic_input: bytes
    material_state: shared.MaterialState
    sidecar: bytes | None
    reference: bytes | None
    codec: str | None
    key_version: str | None
    expires_at: datetime | None
    recovery_metadata: bytes
    cleanup_policy: shared.CleanupPolicy
    projection_metadata: bytes

    @_observation_boundary
    def __post_init__(self) -> None:
        if type(self.material_state) is not shared.MaterialState or type(self.cleanup_policy) is not shared.CleanupPolicy:
            raise ValueError
        for name in ('semantic_input', 'recovery_metadata', 'projection_metadata'):
            object.__setattr__(self, name, common._bytes(getattr(self, name)))
        for name in ('sidecar', 'reference'):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, common._bytes(value))
        if not isinstance(common.parse_canonical_json(self.semantic_input), Mapping):
            raise ValueError
        if not isinstance(common.parse_canonical_json(self.projection_metadata), Mapping):
            raise ValueError
        if self.expires_at is not None:
            object.__setattr__(self, 'expires_at', common._instant(self.expires_at))
        if self.material_state is shared.MaterialState.ABSENT:
            if any(value is not None for value in (self.sidecar, self.reference, self.codec,
                                                   self.key_version, self.expires_at)):
                raise ValueError
            if self.recovery_metadata != b'' or self.cleanup_policy is not shared.CleanupPolicy.RETAIN:
                raise ValueError
        else:
            common._identifier(self.codec)
            common._identifier(self.key_version)
            if not isinstance(common.parse_canonical_json(self.recovery_metadata), Mapping):
                raise ValueError
            if self.material_state is shared.MaterialState.PRESENT:
                if (self.sidecar is None) == (self.reference is None) or self.sidecar == b'' or self.reference == b'':
                    raise ValueError
            elif self.sidecar is not None or self.reference is not None:
                raise ValueError


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobRecord:
    work: WorkObservation
    details: JobDetails
    payload: JobPayload

    @_observation_boundary
    def __post_init__(self) -> None:
        from .rows import _validated_parts
        work, details, payload = _validated_parts(self.work, self.details, self.payload)
        object.__setattr__(self, 'work', work)
        object.__setattr__(self, 'details', details)
        object.__setattr__(self, 'payload', payload)


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobCandidate:
    work: WorkObservation
    job: JobRecord | None

    @_observation_boundary
    def __post_init__(self) -> None:
        if type(self.work) is not WorkObservation:
            raise ValueError
        object.__setattr__(self, 'work', replace(self.work))
        if self.work.kind == 'job':
            if type(self.job) is not JobRecord:
                raise ValueError
            record = replace(self.job)
            if record.work != self.work:
                raise ValueError
            object.__setattr__(self, 'job', record)
        elif self.job is not None:
            raise ValueError


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobAdmissionObservation:
    work_id: str
    inserted: bool

    @_observation_boundary
    def __post_init__(self) -> None:
        _work_id(self.work_id)
        if type(self.inserted) is not bool:
            raise ValueError


class JobIdentityDecision(Enum):
    NEW = 'new'
    MATCH = 'match'
    CONFLICT = 'conflict'


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobIdentityObservation:
    decision: JobIdentityDecision
    candidates: tuple[JobCandidate, ...]
    original_work_id: str | None

    @_observation_boundary
    def __post_init__(self) -> None:
        if type(self.decision) is not JobIdentityDecision or type(self.candidates) is not tuple or len(self.candidates) > 2:
            raise ValueError
        if any(type(item) is not JobCandidate for item in self.candidates):
            raise ValueError
        items = tuple(replace(item) for item in self.candidates)
        if any(items[index - 1].work.work_id >= items[index].work.work_id for index in range(1, len(items))):
            raise ValueError
        object.__setattr__(self, 'candidates', items)
        if self.decision is JobIdentityDecision.NEW:
            if items or self.original_work_id is not None:
                raise ValueError
        elif self.decision is JobIdentityDecision.MATCH:
            if len(items) != 1 or items[0].job is None or _work_id(self.original_work_id) != items[0].work.work_id:
                raise ValueError
        elif not items or self.original_work_id is not None:
            raise ValueError


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobClaimObservation:
    record: JobRecord
    fence: shared.Fence

    @_observation_boundary
    def __post_init__(self) -> None:
        if type(self.record) is not JobRecord or type(self.fence) is not shared.Fence:
            raise ValueError
        record, fence = replace(self.record), replace(self.fence)
        work = record.work
        if work.state != 'claimed' or work.dispatch_id is not None or work.cancellation_requested:
            raise ValueError
        if work.runnable_version is None or work.lease_until is None or work.attempt_count >= work.max_attempts:
            raise ValueError
        if (fence.work_id, fence.token, fence.ownership_revision, fence.cycle, fence.expected_attempt) != (
            work.work_id, work.token, work.ownership_revision, work.cycle, work.attempt_count):
            raise ValueError
        object.__setattr__(self, 'record', record)
        object.__setattr__(self, 'fence', fence)
        # Structural ownership/input only. Even PRESENT material needs application
        # readiness and authorization; ERASED is always nonexecutable.


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class DispatchedJobObservation:
    claim: JobClaimObservation
    fence: shared.Fence
    dispatch_id: UUID
    attempt: int

    @_observation_boundary
    def __post_init__(self) -> None:
        if type(self.claim) is not JobClaimObservation or type(self.fence) is not shared.Fence or type(self.dispatch_id) is not UUID:
            raise ValueError
        claim, fence = replace(self.claim), replace(self.fence)
        if claim.record.payload.material_state is shared.MaterialState.ERASED:
            raise ValueError
        common._integer(self.attempt, 1, claim.record.work.max_attempts)
        prior = claim.fence
        if self.attempt != prior.expected_attempt + 1:
            raise ValueError
        if (fence.work_id, fence.token, fence.ownership_revision, fence.cycle, fence.expected_attempt) != (
            prior.work_id, prior.token, prior.ownership_revision, prior.cycle, self.attempt):
            raise ValueError
        object.__setattr__(self, 'claim', claim)
        object.__setattr__(self, 'fence', fence)
