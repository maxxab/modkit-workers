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
def submit(request: JobSubmitRequest, /):
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
def read_job(request: JobReadRequest, /):
    if type(request) is not JobReadRequest:
        raise ValueError
    return _freeze("W02", (_work_id(request.work_id),))


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class PreparedJobFind:
    lookup: object
    expected_submission: object

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
def acquire(request: JobAcquireRequest, /):
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
def list_jobs(request: JobListRequest, /):
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
