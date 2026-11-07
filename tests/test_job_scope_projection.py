"""Worker scope-consumer tests, not a rerun of standalone Scope qualification."""
import unittest
from datetime import UTC, datetime

from modkit_events.persistence.errors import PersistenceError
from modkit_events.persistence.models import CleanupPolicy, MaterialState, ProtectedBindingInput
from modkit_events.persistence.scope import Scope

from modkit_workers.persistence.bindings import submit
from modkit_workers.persistence.models import JobInput, JobSubmitRequest

ID = "11111111-1111-4111-8111-111111111111"
NOW = datetime(2030, 1, 1, tzinfo=UTC)


class WorkerScopeConsumerTests(unittest.TestCase):
    def test_exact_raw_nullable_scope_reaches_submit(self):
        # Break caught: worker reorders scope slots, uses TEXT, normalizes or loses None.
        for logical, raw in (
            (("\0", None, None), (b"\0", None, None)),
            (("app", "\0", None), (b"app", b"\0", None)),
            (("app", None, "\0"), (b"app", None, b"\0")),
            ((" A\0\n", "é", "e\u0301"), (b" A\0\n", b"\xc3\xa9", b"e\xcc\x81")),
        ):
            with self.subTest(logical=logical):
                material = ProtectedBindingInput(material_state=MaterialState.ABSENT,
                    codec=None, key_version=None, expires_at=None,
                    cleanup_policy=CleanupPolicy.RETAIN, sidecar=None, reference=None,
                    content_binding=b"", recovery_metadata=b"", projection_metadata={})
                request = JobInput(ID, "send", 1, Scope(*logical), {"value": 1},
                                  original_available_at=NOW, protected=material)
                prepared = submit(JobSubmitRequest(job=request))
                self.assertEqual(prepared.parameters[9:12], raw)
                self.assertEqual(prepared.parameters[5], request.scope_bytes)

    def test_logical_details_keep_nul_and_nullable_fields_through_read(self):
        from modkit_events.persistence.bindings import canonical_protected_binding

        from modkit_workers.persistence.observations import JobDetails
        material = ProtectedBindingInput(material_state=MaterialState.ABSENT,
            codec=None, key_version=None, expires_at=None,
            cleanup_policy=CleanupPolicy.RETAIN, sidecar=None, reference=None,
            content_binding=b"", recovery_metadata=b"", projection_metadata={})
        details = JobDetails(ID, "a\0", None, "e\u0301",
                             canonical_protected_binding(material).content)
        self.assertEqual((details.application, details.tenant, details.owner),
                         ("a\0", None, "e\u0301"))
        for value in ("", " \t", "x" * 257, b"a\0"):
            with self.subTest(value_type=type(value)), self.assertRaises(PersistenceError):
                JobDetails(ID, value, None, None, details.protected_binding)
