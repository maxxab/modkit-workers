"""Workers owns integration with its required Events persistence foundation.

Moved from Events without dropping any W01/W05 assertions. The helpers are local
so this suite requires installed package APIs, not the Events test checkout.
"""

from modkit_events.persistence import bindings as B
from modkit_events.persistence import errors as E
from modkit_events.persistence import models as M
from modkit_events.persistence import rows as R


def rejects(call):
    try:
        call()
    except E.PersistenceError:
        return
    assert False, "expected sanitized rejection"


def _work_observation_fields():
    from datetime import datetime, timezone
    from uuid import UUID

    from modkit_events.persistence.scope import Scope, canonical_scope, encode_scope_fields

    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    scope = Scope("app")
    app, tenant, owner = encode_scope_fields(scope)
    se = M.ScopeEvidence(
        canonical_version=1,
        canonical=canonical_scope(scope),
        application=app,
        tenant=tenant,
        owner=owner,
    )
    ident = M.WorkIdentity(
        work_id=UUID(int=1),
        kind=M.WorkKind.JOB,
        subscription_id=None,
        namespace="jobs",
        command_type="run",
        scope=se,
        idempotency_key=None,
    )
    material = M.ProtectedBindingInput(
        material_state=M.MaterialState.ABSENT,
        codec=None,
        key_version=None,
        expires_at=None,
        cleanup_policy=M.CleanupPolicy.RETAIN,
        sidecar=None,
        reference=None,
        content_binding=b"",
        recovery_metadata=b"",
        projection_metadata={},
    )
    admission = M.AdmissionInput(
        identity=ident,
        schema_version=1,
        semantic_input=B.canonical_json({}),
        replay_input=b"{}",
        protected_binding=B.canonical_protected_binding(material).content,
        replay_policy=M.ReplayPolicy.DISABLED,
        max_attempts=3,
        deadline=None,
        original_available_at=now,
    )
    fields = dict(
        work_id=ident.work_id,
        kind="job",
        subscription_id=None,
        namespace=b"jobs",
        command_type=b"run",
        schema_version_decimal=b"1",
        runnable_version=1,
        canonical_version=1,
        scope_evidence=se.canonical,
        scope_application=app,
        scope_tenant=None,
        scope_owner=None,
        idempotency_key=None,
        intent_evidence=B.canonical_intent(admission).content,
        semantic_input=admission.semantic_input,
        replay_input=admission.replay_input,
        protected_binding=admission.protected_binding,
        replay_policy="disabled",
        max_attempts=3,
        deadline=None,
        original_available_at=now,
        state="queued",
        cancellation_requested=False,
        token=None,
        ownership_revision=0,
        lease_until=None,
        available_at=now,
        cycle=1,
        attempt_count=0,
        dispatch_id=None,
        result=None,
        created_at=now,
        updated_at=now,
        success_origin=None,
        completion_guard_id=None,
        final_fence_at=None,
        completion_result_digest=None,
        resolution_operation_id=None,
        terminal_resolution_operation_id=None,
        resolution=None,
    )
    return fields


def _work_wire(fields=None):
    from modkit_events.persistence.catalog import get_statement

    data = _work_observation_fields() if fields is None else fields
    return tuple(
        False
        if c.name == "resolution_present"
        else None
        if c.name.startswith("resolution_record_")
        else data[c.name]
        for c in get_statement("E15").result.columns
    )


def _admission_from_work_fields(data):
    identity = M.WorkIdentity(
        work_id=data["work_id"],
        kind=M.WorkKind(data["kind"]),
        subscription_id=None
        if data["subscription_id"] is None
        else data["subscription_id"].decode(),
        namespace=data["namespace"].decode(),
        command_type=data["command_type"].decode(),
        scope=M.ScopeEvidence(
            canonical_version=data["canonical_version"],
            canonical=data["scope_evidence"],
            application=data["scope_application"],
            tenant=data["scope_tenant"],
            owner=data["scope_owner"],
        ),
        idempotency_key=None
        if data["idempotency_key"] is None
        else data["idempotency_key"].decode(),
    )
    return M.AdmissionInput(
        identity=identity,
        schema_version=B.version_from_decimal(data["schema_version_decimal"]),
        semantic_input=data["semantic_input"],
        replay_input=data["replay_input"],
        protected_binding=data["protected_binding"],
        replay_policy=M.ReplayPolicy(data["replay_policy"]),
        max_attempts=data["max_attempts"],
        deadline=data["deadline"],
        original_available_at=data["original_available_at"],
    )


def test_worker_catalog_factory_and_scan_shared_seam():
    from uuid import UUID

    from modkit_workers.persistence.catalog import get_statement

    data = _work_observation_fields()
    admission = _admission_from_work_fields(data)
    data.update(
        material_state="absent",
        protected_sidecar=None,
        protected_reference=None,
        protected_codec=None,
        protected_key_version=None,
        protected_expires_at=None,
        protected_recovery_metadata=b"",
        protected_cleanup_policy="retain",
        projection_metadata=B.canonical_json({}),
    )
    params = [data[p.name] for p in get_statement("W01").parameters]
    req = B.freeze_request(
        get_statement("W01"), params, context=B.ReturnContext(expected=(admission,), readiness=None)
    )
    assert len(req.parameters) == 29 and req.statement is get_statement("W01")
    wrong = list(params)
    wrong[-1] = B.canonical_json({"changed": True})
    rejects(lambda: B.freeze_request(get_statement("W01"), wrong, context=req.context))
    empty = B.ReturnContext(expected=(), readiness=None)
    scan = B.freeze_request(
        get_statement("W05"), [b"jobs", [b"run"], [1], 2, 30, None, 4], context=empty
    )
    work = {
        **_work_observation_fields(),
        "state": "claimed",
        "token": UUID(int=2),
        "ownership_revision": 1,
        "lease_until": data["created_at"],
    }
    suffix = (
        work["work_id"],
        work["scope_application"],
        None,
        None,
        work["protected_binding"],
        work["semantic_input"],
        "absent",
        None,
        None,
        None,
        None,
        None,
        b"",
        "retain",
        B.canonical_json({}),
    )
    row = ("item", None, None, None) + _work_wire(work) + suffix
    header = ("header", 1, work["work_id"], True) + (None,) * 71
    frame = R.split_scan_rows(scan, [header, row])
    assert frame.visited == 1 and len(frame.item_columns) == 1 and len(frame.item_columns[0]) == 71
    for bad in ([header, row, row], [header, ("item", 1, None, None) + row[4:]]):
        try:
            R.split_scan_rows(scan, bad)
        except E.PersistenceError as exc:
            assert exc.code is E.ErrorCode.INVALID_OBSERVATION
        else:
            assert False
