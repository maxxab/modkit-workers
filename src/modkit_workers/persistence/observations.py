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
        binding = _details_fields(
            self.work_id, self.application, self.tenant, self.owner, self.protected_binding
        )
        object.__setattr__(self, "protected_binding", binding)


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
        normalized = _payload_fields(*_payload_values(self))
        for name, value in zip(_PAYLOAD_FIELDS, normalized):
            object.__setattr__(self, name, value)


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
        _admission_fields(self.work_id, self.inserted)


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


# Four concrete semantic cores. Public constructors keep their original boundary
# and normalization; native constructors/validators never enter those wrappers.
def _invalid(raw):
    if raw:
        from modkit_events.persistence.errors import _reject_validation
        _reject_validation()
    raise ValueError


def _details_fields(work_id, application, tenant, owner, binding, *, raw=False):
    from .models import _work_id_raw

    (_work_id_raw if raw else _work_id)(work_id)
    if raw:
        from modkit_events.persistence.scope import _scope_raw
        _scope_raw(application, tenant, owner)
        binding = common._bytes_raw(binding)
        common._decode_protected_binding_raw(binding)
    else:
        Scope(application, tenant, owner)
        binding = common._bytes(binding)
        common.decode_protected_binding(binding)
    return binding


_PAYLOAD_FIELDS = (
    "semantic_input", "material_state", "sidecar", "reference", "codec",
    "key_version", "expires_at", "recovery_metadata", "cleanup_policy", "projection_metadata",
)


def _payload_values(value):
    return (
        value.semantic_input, value.material_state, value.sidecar, value.reference,
        value.codec, value.key_version, value.expires_at, value.recovery_metadata,
        value.cleanup_policy, value.projection_metadata,
    )


def _payload_fields(semantic, state, sidecar, reference, codec, key, expiry,
                    recovery, cleanup, projection, *, raw=False):
    if type(state) is not shared.MaterialState or type(cleanup) is not shared.CleanupPolicy:
        _invalid(raw)
    byte_value = common._bytes_raw if raw else common._bytes
    parse = common._parse_canonical_json_raw if raw else common.parse_canonical_json
    identifier = common._identifier_raw if raw else common._identifier
    semantic, recovery, projection = (
        byte_value(semantic), byte_value(recovery), byte_value(projection)
    )
    sidecar = None if sidecar is None else byte_value(sidecar)
    reference = None if reference is None else byte_value(reference)
    if not isinstance(parse(semantic), Mapping) or not isinstance(parse(projection), Mapping):
        _invalid(raw)
    if expiry is not None:
        if raw:
            from datetime import timezone
            if type(expiry) is not datetime or expiry.tzinfo is not timezone.utc:
                _invalid(raw)
        else:
            expiry = common._instant(expiry)
    if state is shared.MaterialState.ABSENT:
        if any(value is not None for value in (sidecar, reference, codec, key, expiry)):
            _invalid(raw)
        if recovery != b"" or cleanup is not shared.CleanupPolicy.RETAIN:
            _invalid(raw)
    else:
        identifier(codec)
        identifier(key)
        if not isinstance(parse(recovery), Mapping):
            _invalid(raw)
        if state is shared.MaterialState.PRESENT:
            if (sidecar is None) == (reference is None) or sidecar == b"" or reference == b"":
                _invalid(raw)
        elif sidecar is not None or reference is not None:
            _invalid(raw)
    return semantic, state, sidecar, reference, codec, key, expiry, recovery, cleanup, projection


def _admission_fields(work_id, inserted, *, raw=False):
    from .models import _work_id_raw
    (_work_id_raw if raw else _work_id)(work_id)
    if type(inserted) is not bool:
        _invalid(raw)


def _job_details_raw(work_id, application, tenant, owner, protected_binding, /):
    binding = _details_fields(
        work_id, application, tenant, owner, protected_binding, raw=True
    )
    value = object.__new__(JobDetails)
    object.__setattr__(value, "work_id", work_id)
    object.__setattr__(value, "application", application)
    object.__setattr__(value, "tenant", tenant)
    object.__setattr__(value, "owner", owner)
    object.__setattr__(value, "protected_binding", binding)
    return value


def _validate_job_details_raw(value, /):
    if type(value) is not JobDetails:
        _invalid(True)
    _details_fields(
        value.work_id, value.application, value.tenant, value.owner,
        value.protected_binding, raw=True,
    )


def _job_payload_raw(*, semantic_input, material_state, sidecar, reference, codec,
                     key_version, expires_at, recovery_metadata, cleanup_policy,
                     projection_metadata):
    fields = _payload_fields(
        semantic_input, material_state, sidecar, reference, codec, key_version,
        expires_at, recovery_metadata, cleanup_policy, projection_metadata, raw=True,
    )
    value = object.__new__(JobPayload)
    for name, item in zip(_PAYLOAD_FIELDS, fields):
        object.__setattr__(value, name, item)
    return value


def _validate_job_payload_raw(value, /):
    if type(value) is not JobPayload:
        _invalid(True)
    _payload_fields(*_payload_values(value), raw=True)


def _job_record_raw(*, work, details, payload):
    from .rows import _validated_parts
    _validated_parts(work, details, payload, _raw=True)
    value = object.__new__(JobRecord)
    object.__setattr__(value, "work", work)
    object.__setattr__(value, "details", details)
    object.__setattr__(value, "payload", payload)
    return value


def _validate_job_record_raw(value, /):
    from .rows import _validated_parts
    if type(value) is not JobRecord:
        _invalid(True)
    _validated_parts(value.work, value.details, value.payload, _raw=True)


def _job_admission_raw(*, work_id, inserted):
    _admission_fields(work_id, inserted, raw=True)
    value = object.__new__(JobAdmissionObservation)
    object.__setattr__(value, "work_id", work_id)
    object.__setattr__(value, "inserted", inserted)
    return value


def _validate_job_admission_raw(value, /):
    if type(value) is not JobAdmissionObservation:
        _invalid(True)
    _admission_fields(value.work_id, value.inserted, raw=True)


def _validate_job_candidate_raw(value, /):
    from modkit_events.persistence.observations import _validate_work_observation_raw

    if type(value) is not JobCandidate:
        _invalid(True)
    _validate_work_observation_raw(value.work)
    if value.work.kind == "job":
        _validate_job_record_raw(value.job)
        if value.job.work != value.work:
            _invalid(True)
    elif value.work.kind != "inbox" or value.job is not None:
        _invalid(True)


def _job_candidate_raw(*, work, job):
    value = object.__new__(JobCandidate)
    object.__setattr__(value, "work", work)
    object.__setattr__(value, "job", job)
    _validate_job_candidate_raw(value)
    return value


def _validate_job_identity_observation_raw(value, /):
    from .models import _work_id_raw

    if type(value) is not JobIdentityObservation:
        _invalid(True)
    if (
        type(value.decision) is not JobIdentityDecision
        or type(value.candidates) is not tuple
        or len(value.candidates) > 2
    ):
        _invalid(True)
    # Validate the entire family before decision and order checks.
    for candidate in value.candidates:
        _validate_job_candidate_raw(candidate)
    if any(
        value.candidates[index - 1].work.work_id >= value.candidates[index].work.work_id
        for index in range(1, len(value.candidates))
    ):
        _invalid(True)
    if value.decision is JobIdentityDecision.NEW:
        if value.candidates or value.original_work_id is not None:
            _invalid(True)
    elif value.decision is JobIdentityDecision.MATCH:
        if (
            len(value.candidates) != 1
            or value.candidates[0].job is None
            or _work_id_raw(value.original_work_id) != value.candidates[0].work.work_id
        ):
            _invalid(True)
    elif not value.candidates or value.original_work_id is not None:
        _invalid(True)


def _job_identity_observation_raw(*, decision, candidates, original_work_id):
    value = object.__new__(JobIdentityObservation)
    object.__setattr__(value, "decision", decision)
    object.__setattr__(value, "candidates", candidates)
    object.__setattr__(value, "original_work_id", original_work_id)
    _validate_job_identity_observation_raw(value)
    return value
