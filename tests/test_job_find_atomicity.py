"""Complete W04 family validation; pure decoder checks, never SQL qualification."""

import unittest

from modkit_events.persistence.errors import ErrorCode, PersistenceError
from test_job_persistence_contracts import ID, OTHER_ID, full_job_row, job

from modkit_workers.persistence import bindings, models, rows


def candidate(full):
    return full[:56] + (True,) + full[56:]


class FindFamilyAtomicity(unittest.TestCase):
    def setUp(self):
        desired = job(work_id=OTHER_ID, idempotency_key="key", max_attempts=3)
        self.request = bindings.find_jobs(models.JobFindRequest(job=desired))
        self.first = full_job_row(job(idempotency_key="key", max_attempts=3))
        self.last = full_job_row(
            job(work_id=OTHER_ID, idempotency_key="different", payload={"value": 2}, max_attempts=3)
        )

    def test_corrupt_final_half_invalidates_otherwise_valid_entire_family(self):
        # The valid control proves both requested paths are legal; an unrelated
        # membership/order failure must not make the corrupt test appear valid.
        control = rows.decode_find(self.request, [candidate(self.first), candidate(self.last)])
        self.assertEqual(control.decision.value, "conflict")
        self.assertEqual(
            tuple(str(item.work.work_id) for item in control.candidates), (ID, OTHER_ID)
        )
        self.assertIsNone(control.original_work_id)
        bad = list(self.last)
        bad[57] = b"inconsistent-application"  # Raw half disagrees with checked Work.
        with self.assertRaises(PersistenceError) as caught:
            rows.decode_find(self.request, [candidate(self.first), candidate(tuple(bad))])
        self.assertIs(caught.exception.code, ErrorCode.INVALID_OBSERVATION)
        self.assertTrue(caught.exception.unconfirmed)

    def test_cancellation_after_first_row_keeps_identity_without_a_partial_result(self):
        class CursorCancellation(BaseException):
            pass

        cancellation = CursorCancellation()
        pulled = []

        def interrupted():
            pulled.append("first")
            yield candidate(self.first)
            pulled.append("cancel")
            raise cancellation

        with self.assertRaises(CursorCancellation) as caught:
            rows.decode_find(self.request, interrupted())
        self.assertIs(caught.exception, cancellation)
        self.assertEqual(pulled, ["first", "cancel"])

    def test_overlong_driver_stream_stops_after_one_overflow_probe(self):
        pulls = []

        def oversized():
            for value in (candidate(self.first), candidate(self.last), candidate(self.last)):
                pulls.append(len(pulls) + 1)
                yield value
            pulls.append(4)  # Detect a fourth next(), even if its error is translated.
            self.fail("Decoder exhausted beyond its two-row bound and one overflow probe")

        with self.assertRaises(PersistenceError) as caught:
            rows.decode_find(self.request, oversized())
        self.assertIs(caught.exception.code, ErrorCode.INVALID_OBSERVATION)
        self.assertTrue(caught.exception.unconfirmed)
        self.assertEqual(pulls, [1, 2, 3])


if __name__ == "__main__":
    unittest.main()
