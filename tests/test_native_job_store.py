"""Actual Workers raw callbacks; no database or native readiness claims."""
from dataclasses import replace
from importlib import import_module
from importlib.util import find_spec
from uuid import UUID

import pytest
from modkit_events.persistence import bindings as common
from modkit_events.persistence.errors import ErrorCode, PersistenceError, _ValidationReject
from test_job_persistence_contracts import ID, OTHER_ID, full_job_row, job

from modkit_workers.persistence import bindings, models, observations, rows


def test_raw_uuid_has_deliberate_rejections(monkeypatch):
    valid = "abcdef01-2345-4678-9abc-def012345678"
    assert models._work_id_raw(valid) == UUID(valid)

    def forbidden(value):
        pytest.fail("malformed UUID spelling reached constructor")

    monkeypatch.setattr(models, "UUID", forbidden)
    malformed = (
        valid.upper(),
        valid[:7] + "g" + valid[8:],
        valid[:8] + "0" + valid[9:],
    )
    assert all(value != valid and len(value) == 36 for value in malformed)
    for value in (*malformed, "bad", valid.replace("-", ""), UUID(valid), " " + valid):
        with pytest.raises(_ValidationReject):
            models._work_id_raw(value)


@pytest.mark.parametrize("payload", [
    {"v": [1, 1.0, 0.0, -0.0, None, True, "é\0"]},
    {"z": (), "a": {"b": [1, 2]}},
    {"floats": [
        0.1, -1.25, 1e-300, -1e300,
        float.fromhex("0x0.0000000000001p-1022"),
        float.fromhex("0x1.fffffffffffffp+1023"),
    ]},
    {"integers": [10**4000 + 7, -(10**4000 + 7), 2**256]},
    {"\\0key\\\"\\\\": ["é", "e\u0301", "\n\t\r\b\f\0", 'quote" slash\\\\', "😺"]},
])
def test_raw_submit_matches_public_without_logical_recopy(monkeypatch, payload):
    logical = models.JobSubmitRequest(job=job(payload=payload, schema_version=2**40))
    expected = bindings.submit(logical)

    def forbidden(*args, **kwargs):
        pytest.fail("native builder reached a public copy/sanitizer")

    monkeypatch.setattr(models, "_logical_json", forbidden)
    monkeypatch.setattr(models, "replace", forbidden)
    monkeypatch.setattr(bindings, "replace", forbidden)
    monkeypatch.setattr(bindings, "submit", forbidden)
    for name in ("canonical_json", "parse_canonical_json", "encode_mapping_replay",
                 "canonical_intent", "canonical_protected_binding", "decode_protected_binding"):
        monkeypatch.setattr(common, name, forbidden)
    actual = bindings._submit_raw(logical)
    assert actual == expected
    assert actual.statement is expected.statement
    assert type(actual.context.expected) is tuple
    assert len(actual.context.expected) == 1
    assert common._canonical_json_raw(
        common._decode_mapping_replay_raw(actual.parameters[14])
    ) == actual.parameters[13]


def test_raw_submit_reordered_objects_and_list_tuple_have_equal_evidence():
    left = {"b": [1, 2], "a": {"value": -0.0}}
    right = {"a": {"value": -0.0}, "b": (1, 2)}
    requests = tuple(
        bindings._submit_raw(models.JobSubmitRequest(job=job(payload=payload)))
        for payload in (left, right)
    )
    assert requests[0].parameters[12:16] == requests[1].parameters[12:16]
    for request in requests:
        assert common._canonical_json_raw(
            common._decode_mapping_replay_raw(request.parameters[14])
        ) == request.parameters[13]


@pytest.mark.parametrize("payload", [
    {"v": [None] * 65537},
    {"v": "a" * 1048577},
    {"v": 10**4096},
])
def test_native_bound_rejects_before_logical_copy_or_replay(monkeypatch, payload):
    logical = models.JobSubmitRequest(job=job(payload=payload))
    def forbidden(*args, **kwargs):
        pytest.fail("unbounded copy or replay before managed rejection")
    monkeypatch.setattr(models, "_logical_json", forbidden)
    monkeypatch.setattr(bindings, "replace", forbidden)
    monkeypatch.setattr(models, "replace", forbidden)
    monkeypatch.setattr(common, "_emit_raw", forbidden)
    with pytest.raises(_ValidationReject):
        bindings._submit_raw(logical)


def test_native_depth_rejects_without_logical_copy(monkeypatch):
    payload = {}
    for _ in range(33):
        payload = {"v": payload}
    logical = models.JobSubmitRequest(job=job(payload=payload))
    monkeypatch.setattr(models, "_logical_json", lambda *a: pytest.fail("whole copy"))
    with pytest.raises(_ValidationReject):
        bindings._submit_raw(logical)


def test_replay_uses_bounded_snapshot_not_original_payload(monkeypatch):
    logical = models.JobSubmitRequest(job=job(payload={"value": [1, -0.0]}))
    expected = bindings.submit(logical)
    original = common._canonical_json_raw
    target = logical.job.payload
    seen = []
    def encode(value):
        if value is target:
            seen.append(value)
            encoded = original(value)
            object.__setattr__(logical.job, "payload", {"bad": object()})
            return encoded
        return original(value)
    monkeypatch.setattr(common, "_canonical_json_raw", encode)
    actual = bindings._submit_raw(logical)
    assert len(seen) == 1
    assert actual == expected


@pytest.mark.parametrize("error", [RuntimeError("sentinel"), ValueError("sentinel"),
                                  KeyboardInterrupt("sentinel"),
                                  PersistenceError(ErrorCode.DATABASE_FAILURE, unconfirmed=True)])
def test_raw_submit_preserves_unexpected_nested_primary(monkeypatch, error):
    logical = models.JobSubmitRequest(job=job())
    def fail(value):
        raise error
    monkeypatch.setattr(common, "_canonical_json_raw", fail)
    with pytest.raises(type(error)) as caught:
        bindings._submit_raw(logical)
    assert caught.value is error


def test_raw_submit_result_staged_coupling_and_exact_types():
    request = bindings._submit_raw(models.JobSubmitRequest(job=job()))
    result = rows._decode_submit_raw(request, ((UUID(ID), True),))
    assert result == observations.JobAdmissionObservation(work_id=ID, inserted=True)
    rows._validate_submit_result_raw(request, result)
    old = rows._decode_submit_raw(request, ((UUID(OTHER_ID), False),))
    assert old.work_id == OTHER_ID
    for data in ((), ((UUID(OTHER_ID), True),), ((UUID(ID), 1),),
                 ((UUID(ID), True), (UUID(ID), True))):
        with pytest.raises(_ValidationReject):
            rows._decode_submit_raw(request, data)


def test_raw_read_full_graph_matches_public_and_validates_without_replacement(monkeypatch):
    logical = models.JobReadRequest(work_id=ID)
    values = full_job_row(job())
    public_request = bindings.read_job(logical)
    expected = rows.decode_read(public_request, (values,))
    request = bindings._read_job_raw(logical)

    def forbidden(*args, **kwargs):
        pytest.fail("native read reached public sanitizer or replacement")
    monkeypatch.setattr(rows, "replace", forbidden)
    monkeypatch.setattr(observations, "replace", forbidden)
    for cls in (observations.JobDetails, observations.JobPayload,
                observations.JobRecord, observations.JobAdmissionObservation):
        monkeypatch.setattr(cls, "__post_init__", forbidden)
    value = rows._decode_read_raw(request, (values,))
    assert value == expected
    refs = (value.work, value.details, value.payload, value.work.resolution,
            request.parameters, request.context, request.context.expected)
    rows._validate_read_result_raw(request, value)
    assert all(a is b for a, b in zip(refs, (
        value.work, value.details, value.payload, value.work.resolution,
        request.parameters, request.context, request.context.expected)))
    assert rows._decode_read_raw(request, ()) is None
    rows._validate_read_result_raw(request, None)


@pytest.mark.parametrize("index,bad", [(57, b"wrong"), (58, b"wrong"),
                                      (61, b"bad-binding"), (70, b"bad-json")])
def test_raw_read_rejects_complete_bad_suffix(index, bad):
    request = bindings._read_job_raw(models.JobReadRequest(work_id=ID))
    values = list(full_job_row(job()))
    values[index] = bad
    with pytest.raises(_ValidationReject):
        rows._decode_read_raw(request, (tuple(values),))


def test_raw_read_rejects_wrong_request_id_and_copied_descriptor():
    request = bindings._read_job_raw(models.JobReadRequest(work_id=OTHER_ID))
    with pytest.raises(_ValidationReject):
        rows._decode_read_raw(request, (full_job_row(job()),))
    request = bindings._read_job_raw(models.JobReadRequest(work_id=ID))
    object.__setattr__(request, "statement", replace(request.statement))
    with pytest.raises(_ValidationReject):
        rows._decode_read_raw(request, ())


def test_raw_read_preserves_shared_decoder_primary(monkeypatch):
    from modkit_events.persistence import rows as shared_rows
    request = bindings._read_job_raw(models.JobReadRequest(work_id=ID))
    values = full_job_row(job())
    primary = ValueError("shared sentinel")
    def fail(value):
        raise primary
    monkeypatch.setattr(shared_rows, "_decode_work_observation_raw", fail)
    with pytest.raises(ValueError) as caught:
        rows._decode_read_raw(request, (values,))
    assert caught.value is primary


def test_native_store_prepares_fixed_operations_without_building_early(monkeypatch):
    store = import_module("modkit_workers.persistence.native_store")
    if find_spec("psycopg") is None:
        pytest.skip("optional psycopg native extra required for wrapper-import control")
    # A present but broken driver must fail normally, not become an optional skip.
    from modkit_events.persistence import native_execution, native_profile
    logical = models.JobSubmitRequest(job=job())
    marker = object()
    calls = []
    def prepare(execution, operation, request, /, *, execution_ledger):
        calls.append((execution, operation, request, execution_ledger))
        return marker
    monkeypatch.setattr(native_execution, "prepare_component", prepare)
    assert store.prepare_submit("execution", logical, execution_ledger="ledger") is marker
    operation = calls[0][1]
    assert operation.statement is bindings._statement("W01")
    assert operation.build_request is bindings._submit_raw
    assert store.SUBMIT_RESULT_CAPACITY == native_profile.result_capacity(operation)
    read = models.JobReadRequest(work_id=ID)
    assert store.prepare_read_job("execution", read, execution_ledger="ledger") is marker
    assert calls[-1][1].statement is bindings._statement("W02")
    assert store.READ_JOB_RESULT_CAPACITY == native_profile.result_capacity(calls[-1][1])


def test_public_observation_error_remains_sanitized():
    with pytest.raises(PersistenceError) as caught:
        observations.JobAdmissionObservation(work_id=ID, inserted=1)
    assert caught.value.code.value == "INVALID_OBSERVATION"
    assert caught.value.unconfirmed


@pytest.mark.parametrize("storage", ["sidecar", "reference"])
def test_native_present_protected_and_erased_observation(storage):
    from modkit_events.persistence.models import CleanupPolicy, MaterialState, ProtectedBindingInput
    protected = ProtectedBindingInput(
        material_state=MaterialState.PRESENT, codec="sealed\0", key_version="v1",
        expires_at=None, cleanup_policy=CleanupPolicy.ERASE_AFTER_TERMINAL,
        sidecar=b"ciphertext" if storage == "sidecar" else None,
        reference=b"durable-ref" if storage == "reference" else None,
        content_binding=b"input", recovery_metadata={"recover": 1},
        projection_metadata={"visible": True},
    )
    logical = models.JobSubmitRequest(job=job(protected=protected))
    assert bindings._submit_raw(logical) == bindings.submit(logical)
    request = bindings._read_job_raw(models.JobReadRequest(work_id=ID))
    values = full_job_row(logical.job)
    actual = rows._decode_read_raw(request, (values,))
    assert actual.payload.material_state is MaterialState.PRESENT
    erased = list(values)
    erased[62], erased[63], erased[64] = "erased", None, None
    value = rows._decode_read_raw(request, (tuple(erased),))
    assert value.payload.material_state is MaterialState.ERASED
    assert value.payload.sidecar is None and value.payload.reference is None
    assert value.details.protected_binding == actual.details.protected_binding
    rows._validate_read_result_raw(request, value)


def test_native_read_reconciled_resolution_and_provenance():
    from hashlib import sha256

    from test_job_persistence_contracts import NOW
    values = list(full_job_row(job()))
    operation = UUID("33333333-3333-4333-8333-333333333333")
    dispatch = UUID(OTHER_ID)
    values[21] = "succeeded"
    values[28:31] = [1, dispatch, b"result"]
    values[33] = "reconciled"
    values[37:40] = [operation, operation, True]
    values[40:56] = [
        operation, "reconcile_work", UUID(ID), 0, 1, 1, dispatch,
        "confirmed_success", None, b"result", sha256(b"result").digest(),
        None, b"evidence", b"binding", 7, NOW,
    ]
    request = bindings._read_job_raw(models.JobReadRequest(work_id=ID))
    actual = rows._decode_read_raw(request, (tuple(values),))
    assert actual.work.resolution.operation_id == operation
    nested = actual.work.resolution
    rows._validate_read_result_raw(request, actual)
    assert actual.work.resolution is nested
    values[46] = UUID(ID)
    with pytest.raises(_ValidationReject):
        rows._decode_read_raw(request, (tuple(values),))


def test_native_decode_codec_length_checked_before_utf8(monkeypatch):
    # Direct raw decoding must retain scalar guards even before native SQL caps.
    original = common._decode_utf8
    sentinel = b"x" * 257
    def decode(value, **kwargs):
        if value is sentinel:
            pytest.fail("oversized protected identifier decoded before byte bound")
        return original(value, **kwargs)
    request = bindings._read_job_raw(models.JobReadRequest(work_id=ID))
    values = list(full_job_row(job()))
    values[65] = sentinel
    monkeypatch.setattr(common, "_decode_utf8", decode)
    with pytest.raises(_ValidationReject):
        rows._decode_read_raw(request, (tuple(values),))


def test_raw_uuid_unexpected_constructor_primary(monkeypatch):
    error = ValueError("unexpected constructor sentinel")
    def fail(value):
        raise error
    monkeypatch.setattr(models, "UUID", fail)
    with pytest.raises(ValueError) as caught:
        models._work_id_raw(ID)
    assert caught.value is error


def test_raw_identifier_text_guard_rejects_before_decoding(monkeypatch):
    sentinel = b"x" * 257
    original = common._decode_utf8
    def decode(value, **kwargs):
        if value is sentinel:
            pytest.fail("byte limit must precede UTF8 allocation")
        return original(value, **kwargs)
    monkeypatch.setattr(common, "_decode_utf8", decode)
    assert rows._identifier_text_raw(b"codec\0") == "codec\0"
    for value in (sentinel, b"\xff", b"", b" \t"):
        with pytest.raises(_ValidationReject):
            rows._identifier_text_raw(value)


def test_native_paths_never_enter_shared_public_model_boundaries(monkeypatch):
    from modkit_events.persistence import models as shared
    from modkit_events.persistence import observations as shared_observations
    from modkit_events.persistence.scope import Scope
    logical = models.JobSubmitRequest(job=job())
    read = models.JobReadRequest(work_id=ID)
    values = full_job_row(logical.job)
    def forbidden(*args, **kwargs):
        pytest.fail("nested public model sanitizer on native path")
    for cls in (shared.ScopeEvidence, shared.WorkIdentity, shared.AdmissionInput,
                shared.ProtectedBindingInput, Scope, shared_observations.WorkObservation,
                shared_observations.ResolutionObservation):
        monkeypatch.setattr(cls, "__post_init__", forbidden)
    bindings._submit_raw(logical)
    request = bindings._read_job_raw(read)
    value = rows._decode_read_raw(request, (values,))
    rows._validate_read_result_raw(request, value)


def test_native_raw_tampered_result_is_rejected_without_normalizing():
    request = bindings._read_job_raw(models.JobReadRequest(work_id=ID))
    value = rows._decode_read_raw(request, (full_job_row(job()),))
    buffer = bytearray(value.payload.semantic_input)
    object.__setattr__(value.payload, "semantic_input", buffer)
    with pytest.raises(_ValidationReject):
        rows._validate_read_result_raw(request, value)
    assert value.payload.semantic_input is buffer


def test_raw_list_builder_retains_exact_cursor_without_public_boundaries(monkeypatch):
    from modkit_events.persistence.models import WorkCursor
    from test_job_persistence_contracts import NOW

    logical = models.JobListRequest(
        after=WorkCursor(created_at=NOW, work_id=UUID(ID)), limit=2
    )
    cursor = logical.after
    expected = bindings.list_jobs(logical)

    def forbidden(*args, **kwargs):
        pytest.fail("native list entered public copy or constructor")

    monkeypatch.setattr(bindings, "replace", forbidden)
    monkeypatch.setattr(models, "replace", forbidden)
    monkeypatch.setattr(bindings, "list_jobs", forbidden)
    monkeypatch.setattr(models.JobListRequest, "__post_init__", forbidden)
    monkeypatch.setattr(WorkCursor, "__post_init__", forbidden)
    actual = bindings._list_jobs_raw(logical)
    assert actual == expected
    assert actual.statement is expected.statement
    assert actual.parameters == (b"jobs", NOW, UUID(ID), 2)
    assert actual.parameters[1] is cursor.created_at
    assert actual.parameters[2] is cursor.work_id
    assert actual.context.expected == ()
    assert actual.context.readiness is None


@pytest.mark.parametrize("limit", [1, 256])
def test_raw_list_builder_accepts_limit_boundaries(limit):
    request = bindings._list_jobs_raw(models.JobListRequest(after=None, limit=limit))
    assert request.parameters == (b"jobs", None, None, limit)


@pytest.mark.parametrize("variant", [
    "request_type", "limit_zero", "limit_over", "limit_bool", "cursor_type",
    "non_utc", "naive", "uuid_type", "uuid_integer", "uuid_safety",
])
def test_raw_list_builder_rejects_tampered_logical_fields(variant):
    from datetime import timedelta, timezone

    from modkit_events.persistence.models import WorkCursor
    from test_job_persistence_contracts import NOW

    request = models.JobListRequest(
        after=WorkCursor(created_at=NOW, work_id=UUID(ID)), limit=2
    )
    if variant == "request_type":
        request = object()
    elif variant.startswith("limit_"):
        object.__setattr__(request, "limit", {
            "limit_zero": 0, "limit_over": 257, "limit_bool": True,
        }[variant])
    elif variant == "cursor_type":
        object.__setattr__(request, "after", object())
    elif variant in ("non_utc", "naive"):
        value = (
            NOW.replace(tzinfo=timezone(timedelta(hours=1)))
            if variant == "non_utc" else NOW.replace(tzinfo=None)
        )
        object.__setattr__(request.after, "created_at", value)
    elif variant == "uuid_type":
        object.__setattr__(request.after, "work_id", ID)
    elif variant == "uuid_integer":
        object.__setattr__(request.after.work_id, "int", True)
    else:
        object.__setattr__(request.after.work_id, "is_safe", object())
    with pytest.raises(_ValidationReject):
        bindings._list_jobs_raw(request)


@pytest.mark.parametrize("error", [ValueError("list sentinel"), RuntimeError("list sentinel"),
                                  KeyboardInterrupt("list sentinel")])
def test_raw_list_builder_preserves_unexpected_primary(monkeypatch, error):
    from modkit_events.persistence.models import WorkCursor
    from test_job_persistence_contracts import NOW

    logical = models.JobListRequest(
        after=WorkCursor(created_at=NOW, work_id=UUID(ID)), limit=2
    )

    def fail(value):
        raise error

    monkeypatch.setattr(common, "_instant_raw", fail)
    with pytest.raises(type(error)) as caught:
        bindings._list_jobs_raw(logical)
    assert caught.value is error


def test_raw_read_id_check_precedes_job_half(monkeypatch):
    request = bindings._read_job_raw(models.JobReadRequest(work_id=OTHER_ID))

    def forbidden(*args):
        pytest.fail("wrong read ID entered job-half composition")

    monkeypatch.setattr(rows, "_decode_job_half_raw", forbidden, raising=False)
    with pytest.raises(_ValidationReject):
        rows._decode_read_raw(request, (full_job_row(job()),))


@pytest.mark.parametrize("explicit,budget", [
    (False, None), (True, 1), (True, 16777216), (True, 2**31),
    (True, 3758096384), (True, None),
])
def test_native_list_preparation_forwards_without_building_early(monkeypatch, explicit, budget):
    store = import_module("modkit_workers.persistence.native_store")
    if find_spec("psycopg") is None:
        pytest.skip("optional psycopg native extra required for wrapper-import control")
    # An installed but broken driver must fail, not become an optional skip.
    from modkit_events.persistence import native_execution

    logical = models.JobListRequest(after=None, limit=2)
    marker = object()
    calls = []

    def prepare(execution, operation, request, /, *, execution_ledger, max_page_payload_bytes):
        calls.append((execution, operation, request, execution_ledger, max_page_payload_bytes))
        return marker

    monkeypatch.setattr(native_execution, "prepare_component", prepare)
    kwargs = {"max_page_payload_bytes": budget} if explicit else {}
    assert store.prepare_list_jobs("execution", logical, execution_ledger="ledger", **kwargs) is marker
    execution, operation, request, ledger, retained_budget = calls[0]
    assert retained_budget is (budget if explicit else store.DEFAULT_LIST_PAGE_PAYLOAD_BYTES)
    assert store.DEFAULT_LIST_PAGE_PAYLOAD_BYTES == 16777216
    assert store.MAX_LIST_PAGE_PAYLOAD_BYTES == 3758096384
    assert (execution, ledger) == ("execution", "ledger")
    assert request is logical
    assert operation.statement is bindings._statement("W03")
    assert operation.build_request is bindings._list_jobs_raw
    assert operation.decode_rows is rows._decode_list_raw
    assert operation.validate_result is rows._validate_list_result_raw
    assert "prepare_list_jobs" in store.__all__
