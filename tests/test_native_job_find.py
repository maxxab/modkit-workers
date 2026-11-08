"""W04 raw consumer checks; no database connections or native qualification."""
from uuid import UUID

import pytest
from modkit_events.persistence import bindings as common
from modkit_events.persistence.errors import _ValidationReject
from test_job_persistence_contracts import ID, OTHER_ID, full_job_row, job

from modkit_workers.persistence import bindings, models, observations, rows


def test_admission_extraction_preserves_original_submission():
    logical = job(schema_version=2**40, idempotency_key="key")
    expected = bindings._submit_raw(models.JobSubmitRequest(job=logical))
    helper = getattr(bindings, "_job_admission_raw", None)
    assert callable(helper), "missing shared raw admission extraction"
    admission, parameters = helper(logical)
    assert parameters == expected.parameters
    assert admission == expected.context.expected[0]
    assert len(parameters) == 29


def test_admission_extraction_preserves_material_decode_and_error_order(monkeypatch):
    logical = job()
    helper = getattr(bindings, "_job_admission_raw", None)
    assert callable(helper), "missing shared raw admission extraction"
    seen = []
    for name in ("_canonical_json_raw", "_parse_canonical_json_raw", "_emit_raw",
                 "_canonical_protected_binding_raw", "_decode_protected_binding_raw",
                 "_canonical_intent_raw"):
        original = getattr(common, name)
        def observe(*args, _name=name, _original=original, **kwargs):
            seen.append(_name)
            return _original(*args, **kwargs)
        monkeypatch.setattr(common, name, observe)
    helper(logical)
    assert seen.index("_canonical_json_raw") < seen.index("_canonical_protected_binding_raw")
    assert seen.index("_canonical_protected_binding_raw") < seen.index("_decode_protected_binding_raw")
    assert seen.index("_decode_protected_binding_raw") < seen.index("_canonical_intent_raw")


def test_admission_extraction_preserves_unexpected_primary(monkeypatch):
    logical = job()
    helper = getattr(bindings, "_job_admission_raw", None)
    assert callable(helper), "missing shared raw admission extraction"
    primary = RuntimeError("intent failure")
    def broken(*args, **kwargs):
        raise primary
    monkeypatch.setattr(common, "_canonical_intent_raw", broken)
    with pytest.raises(RuntimeError) as caught:
        helper(logical)
    assert caught.value is primary


def record():
    return rows._decode_read_raw(
        bindings._read_job_raw(models.JobReadRequest(work_id=ID)),
        (full_job_row(job()),),
    )


def test_raw_candidate_keeps_validated_work_alias_without_public_copy(monkeypatch):
    value = record()
    helper = getattr(observations, "_job_candidate_raw", None)
    assert callable(helper), "missing raw candidate constructor"
    def forbidden(*args, **kwargs):
        pytest.fail("raw candidate entered public copy")
    monkeypatch.setattr(observations, "replace", forbidden)
    candidate = helper(work=value.work, job=value)
    assert candidate.work is value.work
    assert candidate.job is value
    observations._validate_job_candidate_raw(candidate)


def test_raw_identity_rejects_forged_match_and_preserves_candidate_alias():
    value = record()
    helper = getattr(observations, "_job_identity_observation_raw", None)
    assert callable(helper), "missing raw identity constructor"
    candidate = observations._job_candidate_raw(work=value.work, job=value)
    result = helper(decision=observations.JobIdentityDecision.MATCH,
                    candidates=(candidate,), original_work_id=ID)
    assert result.candidates[0] is candidate
    with pytest.raises(_ValidationReject):
        helper(decision=observations.JobIdentityDecision.MATCH,
               candidates=(candidate,), original_work_id=OTHER_ID)
    with pytest.raises(_ValidationReject):
        helper(decision=observations.JobIdentityDecision.NEW,
               candidates=(candidate,), original_work_id=None)


def test_find_classifier_rechecks_full_context_and_entire_family():
    classify = getattr(rows, "_classify_find_raw", None)
    assert callable(classify), "missing raw context-dependent classifier"
    expected = common._admission_values_raw(
        bindings._job_admission_raw(job())[0]
    )
    candidate = observations._job_candidate_raw(work=record().work, job=record())
    decision, original = classify(expected, (candidate,))
    assert decision is observations.JobIdentityDecision.MATCH
    assert original == ID
    changed = dict(expected, max_attempts=expected["max_attempts"] + 1)
    assert classify(changed, (candidate,)) == (
        observations.JobIdentityDecision.CONFLICT, None
    )
    assert classify(expected, ()) == (observations.JobIdentityDecision.NEW, None)
    with pytest.raises(_ValidationReject):
        classify(expected, (candidate, candidate))
    unrelated = dict(expected, work_id=UUID(OTHER_ID), idempotency_key=None)
    with pytest.raises(_ValidationReject):
        classify(unrelated, (candidate,))


def test_find_classifier_validates_later_corruption_before_conflict():
    classify = getattr(rows, "_classify_find_raw", None)
    assert callable(classify), "missing raw context-dependent classifier"
    first = record()
    candidate = observations._job_candidate_raw(work=first.work, job=first)
    invalid = object.__new__(observations.JobCandidate)
    object.__setattr__(invalid, "work", first.work)
    object.__setattr__(invalid, "job", None)
    expected = common._admission_values_raw(bindings._job_admission_raw(job())[0])
    with pytest.raises(_ValidationReject):
        classify(dict(expected, max_attempts=999), (candidate, invalid))


def test_raw_find_builder_and_decoder_match_pure_job_lookup():
    logical = models.JobFindRequest(job=job())
    prepared = bindings.find_jobs(logical)
    request = bindings._find_jobs_raw(logical)
    assert request.parameters == prepared.lookup.parameters
    assert request.context.expected == prepared.expected_submission.context.expected
    values = full_job_row(job())
    family = (values[:56] + (True,) + values[56:],)
    actual = rows._decode_find_raw(request, family)
    assert actual == rows.decode_find(prepared, family)
    rows._validate_find_result_raw(request, actual)
    forged = observations._job_identity_observation_raw(
        decision=observations.JobIdentityDecision.CONFLICT,
        candidates=actual.candidates, original_work_id=None,
    )
    with pytest.raises(_ValidationReject):
        rows._validate_find_result_raw(request, forged)


@pytest.mark.parametrize("field", (
    "kind", "subscription_id", "namespace", "command_type", "scope_evidence",
    "idempotency_key", "canonical_version", "schema_version_decimal",
    "scope_application", "scope_tenant", "scope_owner", "intent_evidence",
    "semantic_input", "protected_binding", "replay_policy", "max_attempts",
    "deadline", "original_available_at",
))
def test_find_classifier_compares_each_immutable_field(field):
    value = record()
    candidate = observations._job_candidate_raw(work=value.work, job=value)
    expected = common._admission_values_raw(bindings._job_admission_raw(job())[0])
    # Direct-ID membership remains valid; each immutable mismatch must conflict.
    expected[field] = object()
    assert rows._classify_find_raw(expected, (candidate,)) == (
        observations.JobIdentityDecision.CONFLICT, None,
    )


def inbox_family():
    from modkit_events.models import Event
    from modkit_events.persistence.models import AdmissionInput, ReplayPolicy, WorkIdentity, WorkKind
    from test_job_persistence_contracts import NOW

    desired = job(max_attempts=3)
    prepared = bindings.find_jobs(models.JobFindRequest(job=desired))
    original = prepared.expected_submission.context.expected[0]
    event = Event("event", "send", {"value": 1})
    incoming = AdmissionInput(
        identity=WorkIdentity(work_id=UUID(ID), kind=WorkKind.INBOX,
                              subscription_id="sub", namespace="jobs",
                              command_type="send", scope=original.identity.scope,
                              idempotency_key=None),
        schema_version=1, semantic_input=common.canonical_event(event).content,
        replay_input=b'{"event_id":"event","name":"send","schema_version":1,"payload":{"value":1},"metadata":{}}',
        protected_binding=original.protected_binding, replay_policy=ReplayPolicy.DISABLED,
        max_attempts=3, deadline=None, original_available_at=NOW,
    )
    values = list(full_job_row(desired)[:56])
    values[1], values[2] = "inbox", b"sub"
    values[13] = common.canonical_intent(incoming).content
    values[14], values[15] = incoming.semantic_input, incoming.replay_input
    return desired, tuple(values) + (False,) + (None,) * 15


def test_raw_find_inbox_uses_real_shared_validation_and_null_half():
    desired, candidate = inbox_family()
    logical = models.JobFindRequest(job=desired)
    request = bindings._find_jobs_raw(logical)
    result = rows._decode_find_raw(request, (candidate,))
    assert result == rows.decode_find(bindings.find_jobs(logical), (candidate,))
    assert result.decision is observations.JobIdentityDecision.CONFLICT
    assert result.candidates[0].job is None
    rows._validate_find_result_raw(request, result)
    for index, changed in ((56, True), (57, UUID(ID)), (15, b"{}")):
        invalid = list(candidate)
        invalid[index] = changed
        with pytest.raises(_ValidationReject):
            rows._decode_find_raw(request, (tuple(invalid),))


def test_raw_find_preserves_unexpected_shared_decoder_primary(monkeypatch):
    from modkit_events.persistence import rows as shared_rows
    request = bindings._find_jobs_raw(models.JobFindRequest(job=job()))
    values = full_job_row(job())
    primary = ValueError("unexpected shared decoder failure")
    def fail(value):
        raise primary
    monkeypatch.setattr(shared_rows, "_decode_work_observation_raw", fail)
    with pytest.raises(ValueError) as caught:
        rows._decode_find_raw(request, (values[:56] + (True,) + values[56:],))
    assert caught.value is primary


def test_real_mixed_find_family_and_late_corruption_are_atomic():
    _, inbox = inbox_family()
    logical = models.JobFindRequest(job=job(idempotency_key="key", max_attempts=3))
    request = bindings._find_jobs_raw(logical)
    full = full_job_row(job(work_id=OTHER_ID, idempotency_key="key", max_attempts=3))
    family = (inbox, full[:56] + (True,) + full[56:])
    result = rows._decode_find_raw(request, family)
    rows._validate_find_result_raw(request, result)
    assert result.decision is observations.JobIdentityDecision.CONFLICT
    assert result.candidates[0].job is None
    assert result.candidates[1].job is not None
    assert result == rows.decode_find(bindings.find_jobs(logical), family)
    from modkit_events.persistence import native_profile
    from modkit_workers.persistence.native_store import _FIND_JOBS, FIND_JOBS_RESULT_CAPACITY
    assert native_profile._result_size(request, result, _FIND_JOBS) <= FIND_JOBS_RESULT_CAPACITY
    bad = list(family[1])
    bad[58] = b"different-application"
    with pytest.raises(_ValidationReject):
        rows._decode_find_raw(request, (inbox, tuple(bad)))
    # A retained family must be revalidated, not accepted because it once decoded.
    object.__setattr__(result.candidates[1].job.details, "application", "different")
    with pytest.raises(_ValidationReject):
        rows._validate_find_result_raw(request, result)
    with pytest.raises(_ValidationReject):
        native_profile._result_size(request, result, _FIND_JOBS)


def test_raw_find_inbox_never_calls_public_sanitizing_helpers(monkeypatch):
    desired, inbox = inbox_family()
    logical = models.JobFindRequest(job=desired)
    expected = rows.decode_find(bindings.find_jobs(logical), (inbox,))

    def forbidden(*args, **kwargs):
        pytest.fail("raw find entered a public sanitizer or copy")

    for name in ("canonical_event", "validate_event_replay", "canonical_json",
                 "parse_canonical_json", "canonical_intent",
                 "canonical_protected_binding", "decode_protected_binding"):
        monkeypatch.setattr(common, name, forbidden)
    monkeypatch.setattr(bindings, "find_jobs", forbidden)
    monkeypatch.setattr(bindings, "submit", forbidden)
    monkeypatch.setattr(bindings, "replace", forbidden)
    monkeypatch.setattr(observations, "replace", forbidden)
    monkeypatch.setattr(rows, "decode_find", forbidden)
    request = bindings._find_jobs_raw(logical)
    result = rows._decode_find_raw(request, (inbox,))
    rows._validate_find_result_raw(request, result)
    assert result == expected


def test_find_request_stays_job_only_and_result_membership_is_rechecked():
    from modkit_events.persistence import native_profile

    request = bindings._find_jobs_raw(models.JobFindRequest(job=job()))
    forged = object.__new__(common.FrozenRequest)
    object.__setattr__(forged, "statement", request.statement)
    object.__setattr__(forged, "parameters", (
        request.parameters[0], "inbox", b"sub", *request.parameters[3:],
    ))
    object.__setattr__(forged, "context", request.context)
    with pytest.raises(_ValidationReject):
        native_profile.validate_request(forged, request.statement)
    logical = object.__new__(models.JobFindRequest)
    object.__setattr__(logical, "job", object())
    with pytest.raises(_ValidationReject):
        bindings._find_jobs_raw(logical)

    other = full_job_row(job(work_id=OTHER_ID))
    other_request = bindings._find_jobs_raw(
        models.JobFindRequest(job=job(work_id=OTHER_ID))
    )
    result = rows._decode_find_raw(other_request, (other[:56] + (True,) + other[56:],))
    with pytest.raises(_ValidationReject):
        rows._validate_find_result_raw(request, result)


def test_named_find_preparation_pays_before_mapping_visit_without_connection():
    import os
    import subprocess
    import sys

    # Isolated real registry/execution only. No connection, fake physical root,
    # callback replacement, or database outcome is involved in preparation.
    script = r"""
from collections.abc import Mapping
from modkit_events.persistence import managed_lifecycle as m
from modkit_events.persistence.errors import PersistenceError, ErrorCode
from modkit_events.persistence.ledger import ExecutionLedger
from modkit_workers.persistence import models
from modkit_workers.persistence.native_store import prepare_find_jobs, _FIND_JOBS
from test_job_persistence_contracts import job

ledger = ExecutionLedger()
m.configure_managed_registry(
    limits=m.LifecycleLimits(
        retained_cells=1, admitted_live=1, checkouts=1, roots=1, roots_per_checkout=1,
        executions=1, preparations=1, preparations_per_execution=1,
        prepare_bytes=4000000, prepare_bytes_per_execution=4000000,
        results=1, results_per_ticket=1, result_bytes=130000000,
        result_bytes_per_ticket=130000000, cleanup_bundles=1,
        cleanup_bytes=1024, construction_slots=1,
    ),
    execution_ledger=ledger,
)
execution = m.reserve_execution(ledger)
class Watched(Mapping):
    visits = 0
    def __iter__(self):
        counts = m.capacity_snapshot(execution_ledger=ledger)
        assert counts["D"] == 1 and counts["A"] == 1 and counts["AB"] > 0
        self.visits += 1
        return iter(("value",))
    def __len__(self):
        return 1
    def __getitem__(self, key):
        if key != "value":
            raise KeyError(key)
        return 1
logical = models.JobFindRequest(job=job())
watched = Watched()
object.__setattr__(logical.job, "payload", watched)
preparation = prepare_find_jobs(execution, logical, execution_ledger=ledger)
assert watched.visits == 1
retained = m._preparations[preparation._stamp]
assert retained["profile"] is _FIND_JOBS
assert retained["data"].statement.key == "W04"
assert len(retained["data"].parameters) == 7
assert len(retained["data"].context.expected) == 1
assert retained["data"].context.readiness is None
blocked = Watched()
object.__setattr__(logical.job, "payload", blocked)
try:
    prepare_find_jobs(execution, logical, execution_ledger=ledger)
except PersistenceError as error:
    assert error.code is ErrorCode.CAPACITY_EXCEEDED
else:
    raise AssertionError("second preparation exceeded paid capacity")
assert blocked.visits == 0
m.release_preparation(preparation, execution_ledger=ledger)
m.dispose_execution(execution, execution_ledger=ledger)
assert m.capacity_snapshot(execution_ledger=ledger)["AB"] == 0
print("PAID_FIND_PREPARATION_COMPLETE")
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        capture_output=True, text=True, timeout=20, env=os.environ.copy(),
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout == "PAID_FIND_PREPARATION_COMPLETE\n"
    assert result.stderr == ""
