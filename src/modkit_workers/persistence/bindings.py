"""Worker-only typed builders using the single neutral foundation freezer."""

from __future__ import annotations

from dataclasses import dataclass, replace

from modkit_events.persistence import bindings as common
from modkit_events.persistence.errors import _boundary

from .models import (
    JobAcquireRequest,
    JobFindRequest,
    JobListRequest,
    JobReadRequest,
    JobSubmitRequest,
    _admission,
    _work_id,
)
from .models import JobInput as JobInput


def _statement(key: str):
    from .catalog import get_statement

    return get_statement(key)


def _freeze(key: str, parameters: tuple, expected: tuple = ()):
    return common.freeze_request(
        _statement(key), parameters, context=common.ReturnContext(expected=expected, readiness=None)
    )


def _identity(admission) -> tuple:
    identity = admission.identity
    return (
        identity.work_id,
        identity.kind.value,
        None,
        b"jobs",
        common._identifier(identity.command_type),
        identity.scope.canonical,
        None if identity.idempotency_key is None else common._identifier(identity.idempotency_key),
    )


@_boundary
def submit(request: JobSubmitRequest, /) -> common.FrozenRequest:
    if type(request) is not JobSubmitRequest:
        raise ValueError
    job = replace(request.job)
    admission = _admission(job)
    identity = admission.identity
    material = common.decode_protected_binding(admission.protected_binding)
    if material.material_state.value not in ("absent", "present"):
        raise ValueError
    parameters = _identity(admission) + (
        1,
        common.version_to_decimal(admission.schema_version),
        identity.scope.application,
        identity.scope.tenant,
        identity.scope.owner,
        common.canonical_intent(admission).content,
        admission.semantic_input,
        admission.replay_input,
        admission.protected_binding,
        admission.replay_policy.value,
        admission.max_attempts,
        admission.deadline,
        admission.original_available_at,
        material.material_state.value,
        material.sidecar,
        material.reference,
        None if material.codec is None else common._identifier(material.codec),
        None if material.key_version is None else common._identifier(material.key_version),
        material.expires_at,
        material.recovery_metadata,
        material.cleanup_policy.value,
        material.projection_metadata,
    )
    return _freeze("W01", parameters, (admission,))


@_boundary
def read_job(request: JobReadRequest, /) -> common.FrozenRequest:
    if type(request) is not JobReadRequest:
        raise ValueError
    return _freeze("W02", (_work_id(request.work_id),))


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class PreparedJobFind:
    lookup: common.FrozenRequest
    expected_submission: common.FrozenRequest

    @_boundary
    def __post_init__(self) -> None:
        if (
            type(self.lookup) is not common.FrozenRequest
            or type(self.expected_submission) is not common.FrozenRequest
        ):
            raise ValueError
        if self.lookup.statement is not _statement(
            "W04"
        ) or self.expected_submission.statement is not _statement("W01"):
            raise ValueError
        if self.lookup.parameters != self.expected_submission.parameters[:7]:
            raise ValueError
        # Reuse the same neutral validation for tampered direct construction.
        common.freeze_request(
            self.lookup.statement, self.lookup.parameters, context=self.lookup.context
        )
        common.freeze_request(
            self.expected_submission.statement,
            self.expected_submission.parameters,
            context=self.expected_submission.context,
        )


@_boundary
def find_jobs(request: JobFindRequest, /) -> PreparedJobFind:
    if type(request) is not JobFindRequest:
        raise ValueError
    expected = submit(JobSubmitRequest(job=request.job))
    return PreparedJobFind(
        lookup=_freeze("W04", expected.parameters[:7]), expected_submission=expected
    )


@_boundary
def acquire(request: JobAcquireRequest, /) -> common.FrozenRequest:
    if type(request) is not JobAcquireRequest:
        raise ValueError
    snapshot = replace(request)
    return _freeze(
        "W05",
        (
            b"jobs",
            tuple(common._identifier(item.command_type) for item in snapshot.capabilities),
            tuple(item.schema_version for item in snapshot.capabilities),
            snapshot.limit,
            snapshot.lease_seconds,
            snapshot.scan_after,
            snapshot.discovery_budget,
        ),
    )


@_boundary
def list_jobs(request: JobListRequest, /) -> common.FrozenRequest:
    if type(request) is not JobListRequest:
        raise ValueError
    snapshot = replace(request)
    return _freeze(
        "W03",
        (
            b"jobs",
            None if snapshot.after is None else snapshot.after.created_at,
            None if snapshot.after is None else snapshot.after.work_id,
            snapshot.limit,
        ),
    )


def _submit_raw(request: JobSubmitRequest, /) -> common.FrozenRequest:
    """Trusted native builder; caller reserves D/A before entering this function."""
    from collections.abc import Mapping
    from datetime import datetime, timezone

    from modkit_events.persistence import models as shared
    from modkit_events.persistence import native_profile
    from modkit_events.persistence.errors import _reject_validation
    from modkit_events.persistence.scope import (
        Scope,
        _canonical_scope_raw,
        _encode_scope_fields_raw,
    )

    from .models import _work_id_raw

    if type(request) is not JobSubmitRequest or type(request.job) is not JobInput:
        _reject_validation()
    job = request.job
    # Fixed references only. Never replace/copy JobInput or traverse payload here.
    work_id, command, version, scope, payload, protected, original, deadline, key, policy, attempts = (
        job.work_id, job.command_type, job.schema_version, job.scope, job.payload,
        job.protected, job.original_available_at, job.deadline, job.idempotency_key,
        job.replay_policy, job.max_attempts,
    )
    uuid = _work_id_raw(work_id)
    command_bytes = common._identifier_raw(command)
    version_bytes = common._version_to_decimal_raw(version)
    key_bytes = None if key is None else common._identifier_raw(key)
    if type(scope) is not Scope or type(protected) is not shared.ProtectedBindingInput:
        _reject_validation()
    if type(policy) is not shared.ReplayPolicy:
        _reject_validation()
    common._integer_raw(attempts, 1, 1000)
    if type(original) is not datetime or original.tzinfo is not timezone.utc:
        _reject_validation()
    if deadline is not None and (
        type(deadline) is not datetime or deadline.tzinfo is not timezone.utc
    ):
        _reject_validation()
    if not isinstance(payload, Mapping):
        _reject_validation()
    application, tenant, owner = _encode_scope_fields_raw(scope)
    canonical_scope = _canonical_scope_raw(scope)
    # The shared managed budget is the FIRST payload traversal. Replay uses only
    # its accepted immutable snapshot, never a second read of caller payload.
    semantic = common._canonical_json_raw(payload)
    bounded = common._parse_canonical_json_raw(semantic)
    replay = common._emit_raw(bounded)
    binding = common._canonical_protected_binding_raw(protected).content
    material = common._decode_protected_binding_raw(binding)
    scope_evidence = shared._scope_evidence_raw(
        canonical_version=1, canonical=canonical_scope,
        application=application, tenant=tenant, owner=owner,
    )
    identity = shared._work_identity_raw(
        work_id=uuid, kind=shared.WorkKind.JOB, subscription_id=None,
        namespace="jobs", command_type=command, scope=scope_evidence, idempotency_key=key,
    )
    admission = shared._admission_input_raw(
        identity=identity, schema_version=version, semantic_input=semantic,
        replay_input=replay, protected_binding=binding, replay_policy=policy,
        max_attempts=attempts, deadline=deadline, original_available_at=original,
    )
    parameters = (
        uuid, "job", None, b"jobs", command_bytes, canonical_scope, key_bytes,
        1, version_bytes, application, tenant, owner,
        common._canonical_intent_raw(admission).content, semantic, replay, binding,
        policy.value, attempts, deadline, original,
        material.material_state.value, material.sidecar, material.reference,
        None if material.codec is None else common._identifier_raw(material.codec),
        None if material.key_version is None else common._identifier_raw(material.key_version),
        material.expires_at, material.recovery_metadata, material.cleanup_policy.value,
        material.projection_metadata,
    )
    return native_profile.freeze_request(
        _statement("W01"), parameters,
        context=common._return_context_raw(expected=(admission,), readiness=None),
    )


def _read_job_raw(request: JobReadRequest, /) -> common.FrozenRequest:
    from modkit_events.persistence import native_profile
    from modkit_events.persistence.errors import _reject_validation

    from .models import _work_id_raw

    if type(request) is not JobReadRequest:
        _reject_validation()
    return native_profile.freeze_request(
        _statement("W02"), (_work_id_raw(request.work_id),),
        context=common._return_context_raw(),
    )
