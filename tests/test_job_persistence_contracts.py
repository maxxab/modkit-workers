"""Worker-owned behavioral contracts; real pure dependency closure is required.

These tests do not create transactions, drivers or execution loops. The bounded
owner harness loads exact inspected modules without running package initializers.
Missing upstream modules are a blocker, not a mocked integration fixture.
"""
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from uuid import UUID
import unittest

from modkit_events.persistence.models import (
    Capability, CleanupPolicy, MaterialState, ProtectedBindingInput, ReplayPolicy,
)
from modkit_events.persistence.errors import ErrorCode, PersistenceError
from modkit_events.persistence.scope import Scope
from modkit_workers.persistence import bindings, models, rows

ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
NOW = datetime(2030, 1, 1, tzinfo=UTC)


def absent():
    return ProtectedBindingInput(
        material_state=MaterialState.ABSENT, codec=None, key_version=None,
        expires_at=None, cleanup_policy=CleanupPolicy.RETAIN,
        sidecar=None, reference=None, content_binding=b"",
        recovery_metadata=b"", projection_metadata={},
    )


def job(**changes):
    values = dict(
        work_id=ID, command_type="send", schema_version=1,
        scope=Scope("app", None, "owner"), payload={"value": 1},
        original_available_at=NOW, protected=absent(),
    )
    values.update(changes)
    return models.JobInput(**values)


class LogicalInputContracts(unittest.TestCase):
    def test_snapshot_does_not_retain_mutable_payload(self):
        # Break caught: constructor keeping application dict/list references.
        original = {"nested": [{"v": 1}]}
        request = job(payload=original)
        original["nested"][0]["v"] = 9
        original["nested"].append(3)
        self.assertEqual(request.payload["nested"][0]["v"], 1)
        self.assertEqual(len(request.payload["nested"]), 1)
        with self.assertRaises(TypeError):
            request.payload["nested"][0]["v"] = 4
        with self.assertRaises(FrozenInstanceError):
            request.schema_version = 2

    def test_logical_large_version_defers_managed_bound(self):
        # Break caught: constructor narrowing logical versions to storage/int4.
        version = 10 ** 4096
        request = job(schema_version=version)
        self.assertEqual(request.schema_version, version)
        with self.assertRaises(PersistenceError) as caught:
            bindings.submit(models.JobSubmitRequest(job=request))
        self.assertIs(caught.exception.code, ErrorCode.LOCAL_INVALID_ARGUMENT)
        self.assertFalse(caught.exception.unconfirmed)

    def test_bool_version_and_noncanonical_uuid_reject(self):
        for change in ({"schema_version": True}, {"schema_version": 0},
                       {"work_id": UUID(ID)}, {"work_id": " " + ID},
                       {"work_id": "bad"}, {"max_attempts": True}):
            with self.subTest(change=change), self.assertRaises(PersistenceError):
                job(**change)

    def test_schedule_is_explicit_and_original(self):
        with self.assertRaises(TypeError):
            models.JobInput(ID, "send", 1, Scope("app"), {}, NOW,
                            protected=absent())
        request = job()
        prepared = bindings.submit(models.JobSubmitRequest(job=request))
        # Hand-derived schema slot19 is immutable original availability.
        self.assertEqual(prepared.parameters[19], NOW)
        self.assertIsNone(prepared.parameters[18])

    def test_cycles_nonjson_and_nonfinite_reject(self):
        cycle = []
        cycle.append(cycle)
        for payload in ({"v": cycle}, {"v": object()}, {"v": float("nan")},
                        {1: "bad"}, {"v": float("inf")}):
            with self.subTest(payload_type=type(payload)), self.assertRaises(PersistenceError):
                job(payload=payload)

    def test_invalid_input_inside_ambient_except_has_detached_error(self):
        try:
            raise RuntimeError("secret ambient value")
        except RuntimeError:
            with self.assertRaises(PersistenceError) as caught:
                job(schema_version=False)
        error = caught.exception
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)
        self.assertTrue(error.__suppress_context__)
        self.assertNotIn("secret", str(error))


class BindingContracts(unittest.TestCase):
    def test_submit_full_projection_and_absent_material(self):
        prepared = bindings.submit(models.JobSubmitRequest(job=job()))
        self.assertEqual(prepared.statement.key, "W01")
        self.assertEqual(len(prepared.parameters), 29)
        self.assertEqual(prepared.parameters[0], UUID(ID))
        self.assertEqual(prepared.parameters[1:5], ("job", None, b"jobs", b"send"))
        self.assertEqual(prepared.parameters[8], b"1")
        self.assertEqual(prepared.parameters[9:12], (b"app", None, b"owner"))
        self.assertEqual(prepared.parameters[20:28],
                         ("absent", None, None, None, None, None, b"", "retain"))
        self.assertEqual(len(prepared.context.expected), 1)
        self.assertIsNone(prepared.context.readiness)

    def test_find_preserves_expected_submission_without_sending_it(self):
        prepared = bindings.find_jobs(models.JobFindRequest(job=job()))
        self.assertEqual(prepared.lookup.statement.key, "W04")
        self.assertEqual(prepared.expected_submission.statement.key, "W01")
        self.assertEqual(prepared.lookup.parameters[0], UUID(ID))
        self.assertEqual(prepared.lookup.context.expected, ())
        self.assertEqual(prepared.lookup.parameters[5],
                         prepared.expected_submission.parameters[5])
        # Pure construction cannot execute either statement; no callback exists.
        self.assertFalse(hasattr(prepared, "execute"))

    def test_different_proposed_uuid_same_key_preserves_intent(self):
        first = bindings.submit(models.JobSubmitRequest(job=job(idempotency_key="key")))
        other = bindings.submit(models.JobSubmitRequest(job=job(
            work_id=OTHER_ID, idempotency_key="key")))
        self.assertNotEqual(first.parameters[0], other.parameters[0])
        self.assertEqual(first.parameters[12], other.parameters[12])

    def test_acquire_freezes_pairs_limit_budget_cursor_before_use(self):
        pairs = [Capability(command_type="send", schema_version=1),
                 Capability(command_type="poll", schema_version=2)]
        request = models.JobAcquireRequest(capabilities=pairs, limit=1,
            lease_seconds=10, scan_after=UUID(ID), discovery_budget=64)
        prepared = bindings.acquire(request)
        pairs[:] = [Capability(command_type="send", schema_version=2)]
        self.assertEqual(prepared.parameters,
            (b"jobs", (b"poll", b"send"), (2, 1), 1, 10.0, UUID(ID), 64))
        self.assertEqual(prepared.statement.key, "W05")
        self.assertEqual(prepared.context.expected, ())

    def test_capability_duplicate_and_budget_bounds_reject(self):
        capability = Capability(command_type="send", schema_version=1)
        for pairs, limit, budget, lease in (
            ([], 1, 1, 1), ([capability, capability], 1, 2, 1),
            ([capability], 2, 1, 1), ([capability], True, 1, 1),
            ([capability], 1, 4097, 1), ([capability], 1, 1, True),
            ([capability], 1, 1, float("nan")),
        ):
            with self.subTest(limit=limit, budget=budget, lease=lease):
                with self.assertRaises(PersistenceError):
                    bindings.acquire(models.JobAcquireRequest(capabilities=pairs,
                        limit=limit, lease_seconds=lease, scan_after=None,
                        discovery_budget=budget))

    def test_list_and_read_use_no_hidden_cursor_sentinel(self):
        read = bindings.read_job(models.JobReadRequest(work_id=ID))
        page = bindings.list_jobs(models.JobListRequest(after=None, limit=2))
        self.assertEqual(read.parameters, (UUID(ID),))
        self.assertEqual(page.parameters, (b"jobs", None, None, 2))


class AdmissionAndEmptyReadContracts(unittest.TestCase):
    def test_admission_staged_cardinality_and_types(self):
        prepared = bindings.submit(models.JobSubmitRequest(job=job()))
        result = rows.decode_submit(prepared, [(UUID(ID), True)])
        self.assertEqual(result.work_id, ID)
        self.assertTrue(result.inserted)
        self.assertFalse(hasattr(result, "committed"))
        result = rows.decode_submit(prepared, [(UUID(OTHER_ID), False)])
        self.assertEqual(result.work_id, OTHER_ID)
        for raw in ([], [(UUID(ID), True)] * 2, [(UUID(ID), 1)],
                    [(UUID(OTHER_ID), True)], [(UUID(ID), None)],
                    [(UUID(ID), True, "secret")]):
            with self.subTest(raw=raw), self.assertRaises(PersistenceError) as caught:
                rows.decode_submit(prepared, raw)
            self.assertIs(caught.exception.code, ErrorCode.INVALID_OBSERVATION)
            self.assertTrue(caught.exception.unconfirmed)

    def test_optional_read_empty_is_not_replay_permission(self):
        prepared = bindings.read_job(models.JobReadRequest(work_id=ID))
        self.assertIsNone(rows.decode_read(prepared, []))
        with self.assertRaises(PersistenceError):
            rows.decode_read(prepared, [()])

    def test_empty_scan_header_preserves_progress(self):
        prepared = bindings.acquire(models.JobAcquireRequest(
            capabilities=[Capability(command_type="send", schema_version=1)],
            limit=2, lease_seconds=10, scan_after=UUID(ID), discovery_budget=64))
        header = ("header", 64, UUID(OTHER_ID), False) + (None,) * 71
        result = rows.decode_acquire(prepared, [header])
        self.assertEqual(result.items, ())
        self.assertEqual(result.visited, 64)
        self.assertEqual(result.next_cursor, UUID(OTHER_ID))
        self.assertFalse(result.pass_exhausted)
        for raw in ([], [header, header], [header[:-1]],
                    [("header", 0, UUID(OTHER_ID), True) + (None,) * 71]):
            with self.subTest(rows=len(raw)), self.assertRaises(PersistenceError):
                rows.decode_acquire(prepared, raw)


def full_job_row(request=None, *, state="queued", attempt=0):
    """Complete hand-ordered wire fixture; no decoder produces its own oracle."""
    from datetime import timedelta
    request = job(max_attempts=3) if request is None else request
    p = bindings.submit(models.JobSubmitRequest(job=request)).parameters
    token = UUID(OTHER_ID) if state == "claimed" else None
    lease = NOW + timedelta(seconds=10) if token is not None else None
    work = (
        p[0], "job", None, b"jobs", p[4], p[8], 1, 1, p[5], p[9], p[10], p[11],
        p[6], p[12], p[13], p[14], p[15], p[16], p[17], p[18], p[19],
        state, False, token, 1, lease, NOW, 1, attempt, None, None, NOW, NOW,
        None, None, None, None, None, None,
    )
    resolution = (False,) + (None,) * 16
    half = (p[0], p[9], p[10], p[11], p[15], p[13]) + p[20:29]
    return work + resolution + half


class JoinedObservationContracts(unittest.TestCase):
    def test_complete_read_retains_input_scope_and_original_schedule(self):
        prepared = bindings.read_job(models.JobReadRequest(work_id=ID))
        result = rows.decode_read(prepared, [full_job_row()])
        self.assertEqual(result.details.work_id, ID)
        self.assertEqual((result.details.application, result.details.tenant, result.details.owner),
                         ("app", None, "owner"))
        self.assertEqual(result.work.original_available_at, NOW)
        self.assertEqual(result.work.attempt_count, 0)
        self.assertEqual(result.payload.material_state, MaterialState.ABSENT)
        self.assertFalse(hasattr(result, "public_status"))

    def test_missing_mismatched_halves_and_extra_columns_fail(self):
        prepared = bindings.read_job(models.JobReadRequest(work_id=ID))
        full = full_job_row()
        variants = [full[:56], full + (None,), full[:56] + (None,) * 15]
        for slot, bad in ((56, UUID(OTHER_ID)), (57, b"other"), (60, b"wrong"),
                          (61, b"wrong"), (62, "present"), (70, b"")):
            values = list(full)
            values[slot] = bad
            variants.append(tuple(values))
        for raw in variants:
            with self.subTest(width=len(raw)), self.assertRaises(PersistenceError) as caught:
                rows.decode_read(prepared, [raw])
            self.assertIs(caught.exception.code, ErrorCode.INVALID_OBSERVATION)
            self.assertTrue(caught.exception.unconfirmed)

    def test_candidate_half_discriminator_and_split_winners(self):
        request = job(idempotency_key="key", max_attempts=3)
        prepared = bindings.find_jobs(models.JobFindRequest(job=request))
        raw = full_job_row(request)
        candidate = raw[:56] + (True,) + raw[56:]
        matched = rows.decode_find(prepared, [candidate])
        self.assertEqual(matched.decision.value, "match")
        self.assertEqual(matched.original_work_id, ID)
        wrong_half = raw[:56] + (False,) + (None,) * 15
        with self.assertRaises(PersistenceError):
            rows.decode_find(prepared, [wrong_half])
        other = full_job_row(job(work_id=OTHER_ID, idempotency_key="key", max_attempts=3))
        split = rows.decode_find(prepared, [candidate, other[:56] + (True,) + other[56:]])
        self.assertEqual(split.decision.value, "conflict")
        self.assertIsNone(split.original_work_id)

    def test_find_same_key_can_match_original_different_unused_proposal(self):
        desired = job(work_id=OTHER_ID, idempotency_key="key", max_attempts=3)
        existing = full_job_row(job(idempotency_key="key", max_attempts=3))
        result = rows.decode_find(bindings.find_jobs(models.JobFindRequest(job=desired)),
                                  [existing[:56] + (True,) + existing[56:]])
        self.assertEqual(result.original_work_id, ID)
        self.assertEqual(result.decision.value, "match")

    def test_mutable_driver_buffers_are_copied(self):
        prepared = bindings.read_job(models.JobReadRequest(work_id=ID))
        raw = list(full_job_row())
        raw[57] = bytearray(b"app")
        raw[60] = bytearray(raw[60])
        result = rows.decode_read(prepared, [tuple(raw)])
        raw[57][:] = b"bad"
        raw[60][:] = b"bad"
        self.assertEqual(result.details.application, "app")
        self.assertNotEqual(result.details.protected_binding, b"bad")

    def test_claim_prior_count_and_exact_dispatch_increment(self):
        from modkit_workers.persistence.observations import JobClaimObservation
        from modkit_events.persistence.models import Fence
        record = rows.decode_read(bindings.read_job(models.JobReadRequest(work_id=ID)),
                                  [full_job_row(state="claimed", attempt=2)])
        fence = Fence(work_id=UUID(ID), token=UUID(OTHER_ID), ownership_revision=1,
                      cycle=1, expected_attempt=2)
        claim = JobClaimObservation(record=record, fence=fence)
        dispatch = rows.observe_dispatch(claim, UUID(ID), 3)
        self.assertEqual(dispatch.fence.expected_attempt, 3)
        self.assertEqual(claim.fence.expected_attempt, 2)
        self.assertIsNone(claim.record.work.dispatch_id)
        for wrong in (2, 4, True):
            with self.subTest(returned=wrong), self.assertRaises(PersistenceError) as caught:
                rows.observe_dispatch(claim, UUID(ID), wrong)
            self.assertIs(caught.exception.code, ErrorCode.INVALID_OBSERVATION)

    def test_scan_validates_late_bad_half_before_any_result(self):
        prepared = bindings.acquire(models.JobAcquireRequest(
            capabilities=[Capability(command_type="send", schema_version=1)],
            limit=2, lease_seconds=10, scan_after=None, discovery_budget=64))
        one = full_job_row(state="claimed")
        two = list(full_job_row(job(work_id=OTHER_ID, max_attempts=3), state="claimed"))
        two[57] = b"mismatch"
        header = ("header", 2, UUID(OTHER_ID), False) + (None,) * 71
        with self.assertRaises(PersistenceError):
            rows.decode_acquire(prepared, [header, ("item", None, None, None) + one,
                                           ("item", None, None, None) + tuple(two)])

    def test_copied_descriptor_cannot_enter_worker_decoder(self):
        from modkit_events.persistence.bindings import freeze_request
        prepared = bindings.read_job(models.JobReadRequest(work_id=ID))
        copied = replace(prepared.statement)
        fake = freeze_request(copied, prepared.parameters, context=prepared.context)
        with self.assertRaises(PersistenceError):
            rows.decode_read(fake, [])

    def test_wrong_kind_direct_candidate_is_conflict_not_corruption(self):
        from modkit_events.models import Event
        from modkit_events.persistence import bindings as common
        from modkit_events.persistence.models import AdmissionInput, WorkIdentity, WorkKind
        desired = job(max_attempts=3)
        prepared = bindings.find_jobs(models.JobFindRequest(job=desired))
        original = prepared.expected_submission.context.expected[0]
        event = Event("event", "send", {"value": 1})
        identity = WorkIdentity(work_id=UUID(ID), kind=WorkKind.INBOX,
            subscription_id="sub", namespace="jobs", command_type="send",
            scope=original.identity.scope, idempotency_key=None)
        incoming = AdmissionInput(identity=identity, schema_version=1,
            semantic_input=common.canonical_event(event).content,
            replay_input=b'{"event_id":"event","name":"send","schema_version":1,"payload":{"value":1},"metadata":{}}',
            protected_binding=original.protected_binding,
            replay_policy=ReplayPolicy.DISABLED, max_attempts=3,
            deadline=None, original_available_at=NOW)
        raw = list(full_job_row(desired)[:56])
        raw[1], raw[2] = "inbox", b"sub"
        raw[13] = common.canonical_intent(incoming).content
        raw[14], raw[15] = incoming.semantic_input, incoming.replay_input
        result = rows.decode_find(prepared, [tuple(raw) + (False,) + (None,) * 15])
        self.assertEqual(result.decision.value, "conflict")
        self.assertIsNone(result.candidates[0].job)
        self.assertEqual(result.candidates[0].work.kind, "inbox")
        with self.assertRaises(PersistenceError):
            rows.decode_find(prepared, [tuple(raw) + (True,) + full_job_row(desired)[56:]])

    def test_reserved_erased_read_never_restores_embedded_live_material(self):
        from modkit_events.persistence.models import Fence
        from modkit_workers.persistence.observations import JobClaimObservation
        protected = ProtectedBindingInput(material_state=MaterialState.PRESENT,
            codec="sealed-v1", key_version="key1", expires_at=None,
            cleanup_policy=CleanupPolicy.ERASE_AFTER_TERMINAL,
            sidecar=b"sealed material", reference=None, content_binding=b"opaque-content",
            recovery_metadata={}, projection_metadata={})
        request = job(protected=protected, max_attempts=3)
        raw = list(full_job_row(request, state="claimed"))
        raw[62], raw[63], raw[64] = "erased", None, None
        record = rows.decode_read(bindings.read_job(models.JobReadRequest(work_id=ID)), [raw])
        self.assertIs(record.payload.material_state, MaterialState.ERASED)
        self.assertIsNone(record.payload.sidecar)
        self.assertIsNone(record.payload.reference)
        self.assertIn(b"sealed material", record.details.protected_binding)
        claim = JobClaimObservation(record=record, fence=Fence(work_id=UUID(ID),
            token=UUID(OTHER_ID), ownership_revision=1, cycle=1, expected_attempt=0))
        with self.assertRaises(PersistenceError):
            rows.observe_dispatch(claim, UUID(ID), 1)
        altered = list(raw)
        altered[66] = b"different-key"
        with self.assertRaises(PersistenceError):
            rows.decode_read(bindings.read_job(models.JobReadRequest(work_id=ID)), [altered])

    def test_direct_composition_cannot_bypass_repeated_scope_and_binding(self):
        prepared = bindings.read_job(models.JobReadRequest(work_id=ID))
        record = rows.decode_read(prepared, [full_job_row()])
        different_scope = replace(record.details, application="other")
        with self.assertRaises(PersistenceError):
            rows.compose_job(record.work, different_scope, record.payload)
        with self.assertRaises(PersistenceError):
            rows.compose_job(record.work, {}, record.payload)

    def test_claim_pointer_must_be_null_even_with_resolved_prior_attempts(self):
        raw = list(full_job_row(state="claimed", attempt=2))
        raw[29] = UUID(ID)
        with self.assertRaises(PersistenceError):
            rows.decode_read(bindings.read_job(models.JobReadRequest(work_id=ID)), [raw])

    def test_valid_full_scan_then_late_bad_half_is_atomic(self):
        prepared = bindings.acquire(models.JobAcquireRequest(
            capabilities=[Capability(command_type="send", schema_version=1)],
            limit=2, lease_seconds=10, scan_after=None, discovery_budget=64))
        one = full_job_row(state="claimed")
        two = full_job_row(job(work_id=OTHER_ID, max_attempts=3), state="claimed")
        header = ("header", 2, UUID(OTHER_ID), False) + (None,) * 71
        batch = [header, ("item", None, None, None) + one,
                 ("item", None, None, None) + two]
        result = rows.decode_acquire(prepared, batch)
        self.assertEqual(tuple(item.record.details.work_id for item in result.items),
                         (ID, OTHER_ID))
        self.assertEqual(result.visited, 2)
        changed = list(two)
        changed[57] = b"mismatch"
        batch[-1] = ("item", None, None, None) + tuple(changed)
        with self.assertRaises(PersistenceError):
            rows.decode_acquire(prepared, batch)

    def test_list_complete_rows_cursor_order_and_overflow(self):
        from modkit_events.persistence.models import WorkCursor
        first, second = full_job_row(), full_job_row(job(work_id=OTHER_ID,max_attempts=3))
        prepared = bindings.list_jobs(models.JobListRequest(after=None,limit=2))
        self.assertEqual(tuple(item.details.work_id for item in rows.decode_list(prepared,[first,second])),(ID,OTHER_ID))
        after = bindings.list_jobs(models.JobListRequest(after=WorkCursor(created_at=NOW,work_id=UUID(ID)),limit=1))
        self.assertEqual(rows.decode_list(after,[second])[0].details.work_id,OTHER_ID)
        for request,values in ((prepared,[second,first]),(prepared,[first,first]),
                               (after,[first]),(after,[second,second])):
            with self.assertRaises(PersistenceError):rows.decode_list(request,values)
