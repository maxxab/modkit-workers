"""Real canonical case construction only; never database qualification."""

import importlib.util
import sys
import unittest
from pathlib import Path
from uuid import UUID

HERE = Path(__file__).resolve().parent


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class CompleteFamilyCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.h = load("w01_case_protocol", HERE / "w01_protocol_source.py")
        cls.cases = load("reader_case_data", HERE / "reader_protocol_source.py")

    def test_two_real_admissions_have_ordered_distinct_identity(self):
        self.assertTrue(
            hasattr(self.cases, "corrupt_last_family"),
            "Missing complete-family canonical fixture construction",
        )
        good, bad, lookup = self.cases.corrupt_last_family(self.h)
        self.assertEqual(good.work_id, "00000000-0000-4000-8000-000000000101")
        self.assertEqual(bad.work_id, "00000000-0000-4000-8000-000000000102")
        self.assertLess(UUID(good.work_id), UUID(bad.work_id))
        self.assertEqual(good.idempotency_key, "reader-corrupt-last-good")
        self.assertEqual(bad.idempotency_key, "reader-corrupt-last-bad")
        self.assertEqual(good.payload, {"value": 1})
        self.assertEqual(bad.payload, {"value": 99})
        self.assertEqual(self.h.prepared(good).parameters[0], UUID(good.work_id))
        self.assertEqual(self.h.prepared(bad).parameters[0], UUID(bad.work_id))

    def test_lookup_hits_bad_direct_and_good_key_with_good_comparison_intent(self):
        self.assertTrue(
            hasattr(self.cases, "corrupt_last_family"),
            "Missing complete-family canonical fixture construction",
        )
        good, bad, lookup = self.cases.corrupt_last_family(self.h)
        self.assertEqual(lookup.lookup.statement.key, "W04")
        self.assertEqual(lookup.lookup.parameters[0], UUID(bad.work_id))
        self.assertEqual(lookup.lookup.parameters[1:5], ("job", None, b"jobs", b"fixture-w01"))
        self.assertEqual(lookup.lookup.parameters[6], b"reader-corrupt-last-good")
        good_admission = self.h.prepared(good)
        self.assertEqual(lookup.expected_submission.parameters[0], UUID(bad.work_id))
        self.assertEqual(lookup.expected_submission.parameters[1:], good_admission.parameters[1:])
        self.assertNotEqual(
            lookup.expected_submission.parameters[13], self.h.prepared(bad).parameters[13]
        )


if __name__ == "__main__":
    unittest.main()
