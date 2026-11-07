"""Canonical worker-request coupling and complete protected job composition."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace
from hashlib import sha256
from typing import cast
from uuid import UUID

from modkit_events.persistence import bindings as common
from modkit_events.persistence import rows as common_rows
from modkit_events.persistence.catalog import get_statement as event_statement
from modkit_events.persistence.errors import _observation_boundary
from modkit_events.persistence.models import CleanupPolicy, Fence, MaterialState
from modkit_events.persistence.observations import ScanPage, WorkObservation
from modkit_events.persistence.scope import (
    Scope,
    canonical_scope,
    decode_scope_fields,
    encode_scope_fields,
)

from .bindings import PreparedJobFind
from .catalog import get_statement
from .models import _work_id
from .observations import (
    DispatchedJobObservation,
    JobAdmissionObservation,
    JobCandidate,
    JobClaimObservation,
    JobDetails,
    JobIdentityDecision,
    JobIdentityObservation,
    JobPayload,
    JobRecord,
)


def _request(request: object, key: str) -> dict:
    # Neutral factory/scalar helpers are not descriptor execution authority.
    if type(request) is not common.FrozenRequest or request.statement is not get_statement(key):
        raise ValueError
    common.freeze_request(request.statement, request.parameters, context=request.context)
    return dict(
        zip((parameter.name for parameter in request.statement.parameters), request.parameters)
    )


def _validated_parts(work, details, payload):
    if (
        type(work) is not WorkObservation
        or type(details) is not JobDetails
        or type(payload) is not JobPayload
    ):
        raise ValueError
    work, details, payload = replace(work), replace(details), replace(payload)
    if work.kind != "job" or work.subscription_id is not None or work.namespace != b"jobs":
        raise ValueError
    if _work_id(details.work_id) != work.work_id:
        raise ValueError
    logical = Scope(details.application, details.tenant, details.owner)
    if encode_scope_fields(logical) != (
        work.scope_application,
        work.scope_tenant,
        work.scope_owner,
    ):
        raise ValueError
    if canonical_scope(logical) != work.scope_evidence:
        raise ValueError
    if (
        details.protected_binding != work.protected_binding
        or payload.semantic_input != work.semantic_input
    ):
        raise ValueError
    original = common.decode_protected_binding(details.protected_binding)
    names = (
        "codec",
        "key_version",
        "expires_at",
        "recovery_metadata",
        "cleanup_policy",
        "projection_metadata",
    )
    if any(getattr(payload, name) != getattr(original, name) for name in names):
        raise ValueError
    if payload.material_state is MaterialState.ERASED:
        if (
            original.material_state is not MaterialState.PRESENT
            or payload.sidecar is not None
            or payload.reference is not None
        ):
            raise ValueError
        # Do not restore original embedded material into live payload fields.
    elif (payload.material_state, payload.sidecar, payload.reference) != (
        original.material_state,
        original.sidecar,
        original.reference,
    ):
        raise ValueError
    # Shared WorkObservation verifies canonical intent, replay/semantic equality,
    # original schedule, state/fence and full resolution provenance. No clone codec.
    return work, details, payload


@_observation_boundary
def compose_job(work: WorkObservation, details: JobDetails, payload: JobPayload, /) -> JobRecord:
    return JobRecord(work=work, details=details, payload=payload)


def _half(work: WorkObservation, values: Sequence[object]) -> JobRecord:
    work_width = len(event_statement("E15").result.columns)
    specs = get_statement("W02").result.columns[work_width:]
    normalized = common_rows._decode_columns(specs, values)
    data = dict(zip((column.name for column in specs), normalized))
    logical = decode_scope_fields(data["job_application"], data["job_tenant"], data["job_owner"])
    details = JobDetails(
        str(data["job_work_id"]),
        logical.application,
        logical.tenant,
        logical.owner,
        data["job_protected_binding"],
    )
    payload = JobPayload(
        semantic_input=data["job_semantic_input"],
        material_state=MaterialState(data["material_state"]),
        sidecar=data["protected_sidecar"],
        reference=data["protected_reference"],
        codec=None if data["protected_codec"] is None else data["protected_codec"].decode("utf-8"),
        key_version=None
        if data["protected_key_version"] is None
        else data["protected_key_version"].decode("utf-8"),
        expires_at=data["protected_expires_at"],
        recovery_metadata=data["protected_recovery_metadata"],
        cleanup_policy=CleanupPolicy(data["protected_cleanup_policy"]),
        projection_metadata=data["projection_metadata"],
    )
    return compose_job(work, details, payload)


def _full(values: Sequence[object]) -> JobRecord:
    specs = get_statement("W02").result.columns
    values = common_rows._decode_columns(specs, values)
    width = len(event_statement("E15").result.columns)
    work = common_rows.decode_work_observation(values[:width])
    return _half(work, values[width:])


def _candidate(values: Sequence[object]) -> JobCandidate:
    specs = get_statement("W04").result.columns
    values = common_rows._decode_columns(specs, values)
    width = len(event_statement("E15").result.columns)
    work = common_rows.decode_work_observation(values[:width])
    present, half = values[width], values[width + 1 :]
    if work.kind == "job":
        if present is not True:
            raise ValueError
        record = _half(work, half)
    else:
        if present is not False or any(value is not None for value in half):
            raise ValueError
        record = None
    return JobCandidate(work=work, job=record)


@_observation_boundary
def decode_submit(
    request: common.FrozenRequest, rows: Iterable[Sequence[object]], /
) -> JobAdmissionObservation:
    p = _request(request, "W01")
    fetched = common_rows._bounded_rows(rows, 1)
    if len(fetched) != 1:
        raise ValueError
    work_id, inserted = common_rows._decode_columns(request.statement.result.columns, fetched[0])
    if inserted and work_id != p["work_id"]:
        raise ValueError
    return JobAdmissionObservation(work_id=str(work_id), inserted=inserted)


@_observation_boundary
def decode_read(
    request: common.FrozenRequest, rows: Iterable[Sequence[object]], /
) -> JobRecord | None:
    p = _request(request, "W02")
    fetched = common_rows._bounded_rows(rows, 1)
    if not fetched:
        return None
    result = _full(fetched[0])
    if result.work.work_id != p["work_id"]:
        raise ValueError
    return result


def _key_bucket(work: WorkObservation, expected: dict) -> bool:
    if work.idempotency_key is None or expected["idempotency_key"] is None:
        return False
    return (
        work.kind == expected["kind"]
        and work.subscription_id == expected["subscription_id"]
        and work.namespace == expected["namespace"]
        and work.command_type == expected["command_type"]
        and sha256(work.scope_evidence).digest() == sha256(expected["scope_evidence"]).digest()
        and sha256(work.idempotency_key).digest() == sha256(expected["idempotency_key"]).digest()
    )


@_observation_boundary
def decode_find(
    prepared: PreparedJobFind, rows: Iterable[Sequence[object]], /
) -> JobIdentityObservation:
    if type(prepared) is not PreparedJobFind:
        raise ValueError
    p = _request(prepared.lookup, "W04")
    expected = _request(prepared.expected_submission, "W01")
    if any(p[name] != expected[name] for name in p):
        raise ValueError
    fetched = common_rows._bounded_rows(rows, 2)
    candidates = tuple(_candidate(row) for row in fetched)
    prior = None
    for candidate in candidates:
        work = candidate.work
        if prior is not None and work.work_id <= prior:
            raise ValueError
        prior = work.work_id
        if work.work_id != p["work_id"] and not _key_bucket(work, p):
            raise ValueError
    if not candidates:
        return JobIdentityObservation(
            decision=JobIdentityDecision.NEW, candidates=(), original_work_id=None
        )
    matches = False
    if len(candidates) == 1 and candidates[0].job is not None:
        work = candidates[0].work
        # All immutable fields are compared, not just a digest or semantic input.
        names = (
            "kind",
            "subscription_id",
            "namespace",
            "command_type",
            "scope_evidence",
            "idempotency_key",
            "canonical_version",
            "schema_version_decimal",
            "scope_application",
            "scope_tenant",
            "scope_owner",
            "intent_evidence",
            "semantic_input",
            "protected_binding",
            "replay_policy",
            "max_attempts",
            "deadline",
            "original_available_at",
        )
        matches = all(getattr(work, name) == expected[name] for name in names)
        # Retained binding supplies original storage identity even if live fields
        # are reserved ERASED. It never supplies execution readiness or material.
        # Replay spelling may differ; shared WorkObservation already proved its
        # complete semantic equivalence. First admitted raw replay stays intact.
    decision = JobIdentityDecision.MATCH if matches else JobIdentityDecision.CONFLICT
    return JobIdentityObservation(
        decision=decision,
        candidates=candidates,
        original_work_id=str(candidates[0].work.work_id) if matches else None,
    )


@_observation_boundary
def decode_list(
    request: common.FrozenRequest, rows: Iterable[Sequence[object]], /
) -> tuple[JobRecord, ...]:
    p = _request(request, "W03")
    fetched = common_rows._bounded_rows(rows, p["limit"])
    records = tuple(_full(row) for row in fetched)
    prior = None if p["after_created_at"] is None else (p["after_created_at"], p["after_work_id"])
    for record in records:
        current = (record.work.created_at, record.work.work_id)
        if record.work.namespace != p["namespace"] or prior is not None and current <= prior:
            raise ValueError
        prior = current
    return records


@_observation_boundary
def decode_acquire(
    request: common.FrozenRequest, rows: Iterable[Sequence[object]], /
) -> ScanPage[JobClaimObservation]:
    p = _request(request, "W05")
    frame = common_rows.split_scan_rows(request, rows)
    claims = []
    pairs = tuple(zip(p["command_types"], p["schema_versions"]))
    for raw in frame.item_columns:
        record = _full(raw)
        work = record.work
        if (work.command_type, work.runnable_version) not in pairs:
            raise ValueError
        fence = Fence(
            work_id=work.work_id,
            token=cast(UUID, work.token),
            ownership_revision=work.ownership_revision,
            cycle=work.cycle,
            expected_attempt=work.attempt_count,
        )
        claims.append(JobClaimObservation(record=record, fence=fence))
    # Every suffix and every bridge validates before any item becomes public.
    return ScanPage(
        items=tuple(claims),
        visited=frame.visited,
        next_cursor=frame.next_cursor,
        pass_exhausted=frame.pass_exhausted,
    )


@_observation_boundary
def observe_dispatch(
    claim: JobClaimObservation, dispatch_id: UUID, returned_attempt: int, /
) -> DispatchedJobObservation:
    if type(claim) is not JobClaimObservation:
        raise ValueError
    claim = replace(claim)
    common._integer(returned_attempt, 1, claim.record.work.max_attempts)
    fence = replace(claim.fence, expected_attempt=returned_attempt)
    return DispatchedJobObservation(
        claim=claim, fence=fence, dispatch_id=dispatch_id, attempt=returned_attempt
    )
