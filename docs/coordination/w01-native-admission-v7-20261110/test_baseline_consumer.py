"""Offline-only regression tests; inputs are the explicit accepted 48-file closure."""

import ast
import hashlib
import importlib.util
import json
import sys
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = "/home/faris/modkit-local-20261106/"
EVENTS = BASE + "resume-events-20261109/fence-reconciliation-v1/"
WORKERS = BASE + "resume-workers-20261109/"
REVIEW = WORKERS + "fence-reconciliation-v1-result-review.json"
RESULT = EVENTS + "attempt/reconciliation-result.json"
TERMINAL = EVENTS + "attempt/runtime-slot-terminal.json"
INPUTS_SHA = "e59ede22d9b626306d33fd67197bee1dc58539b71e8f2f0c2de44662053800f9"
GUARDED = False


def audit(event, args):
    if GUARDED and (
        event == "open"
        or event.startswith(("subprocess.", "socket.", "os.", "shutil."))
        or event in {"ctypes.dlopen", "fcntl.flock"}
    ):
        raise AssertionError(f"Forbidden verifier effect: {event}")


sys.addaudithook(audit)
raw = (HERE / "fixture-inputs.json").read_bytes()
assert hashlib.sha256(raw).hexdigest() == INPUTS_SHA
INPUTS = json.loads(raw)["files"]
BUNDLE = {}
for key, digest in INPUTS.items():
    data = Path(key).read_bytes()
    assert hashlib.sha256(data).hexdigest() == digest, key
    BUNDLE[key] = data
consumer = None
if (HERE / "baseline_consumer.py").exists():
    spec = importlib.util.spec_from_file_location(
        "baseline_consumer", HERE / "baseline_consumer.py"
    )
    consumer = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = consumer
    spec.loader.exec_module(consumer)


class ConsumerTests(unittest.TestCase):
    def verify(self, bundle):
        global GUARDED
        self.assertIsNotNone(consumer, "The pure baseline consumer API is not implemented")
        GUARDED = True
        try:
            return consumer.verify_baseline(bundle)
        finally:
            GUARDED = False

    def refused(self, bundle):
        with self.assertRaises(ValueError):
            self.verify(bundle)

    def changed_json(self, key, change):
        bundle = dict(BUNDLE)
        value = json.loads(bundle[key])
        change(value)
        bundle[key] = json.dumps(value).encode()
        return bundle

    def test_positive_exact_chain_is_only_immutable_historical_baseline(self):
        before = dict(BUNDLE)
        receipt = self.verify(BUNDLE)
        self.assertEqual(receipt.attempt_id, "5cdf9e5d83534098860ffd0137bf26b7")
        self.assertEqual(receipt.scope, "REDIS8_CURRENT_ABSENCE_RECONCILIATION_V1")
        self.assertEqual(receipt.history, ("UNKNOWN_UNCHANGED", "UNKNOWN_UNCHANGED", "UNKNOWN"))
        self.assertFalse(receipt.native_authorized)
        self.assertFalse(receipt.live_absence_asserted)
        self.assertEqual(receipt.verified_file_count, 48)
        self.assertEqual(receipt.execution_window_utc[1], "2026-11-10T00:48:27.679071+00:00")
        self.assertEqual(BUNDLE, before)
        with self.assertRaises(FrozenInstanceError):
            receipt.native_authorized = True

    def test_every_missing_file_refuses_before_effects(self):
        for key in BUNDLE:
            with self.subTest(key=key):
                bundle = dict(BUNDLE)
                del bundle[key]
                self.refused(bundle)

    def test_every_changed_file_refuses_before_effects(self):
        for key in BUNDLE:
            with self.subTest(key=key):
                self.refused({**BUNDLE, key: BUNDLE[key] + b" "})

    def test_extra_files_and_old_success_contract_refuse(self):
        for key in [
            "unreviewed",
            WORKERS + "native-r4-final-assembly-v1/pending-admission-evidence-contract.json",
        ]:
            with self.subTest(key=key):
                self.refused({**BUNDLE, key: b"{}"})
        self.refused({})

    def test_self_rehashed_review_cannot_replace_external_anchor(self):
        bundle = self.changed_json(RESULT, lambda o: o.update(original_removal_outcome="SUCCESS"))
        review = json.loads(bundle[REVIEW])
        review["result_sha256"] = hashlib.sha256(bundle[RESULT]).hexdigest()
        review["files"][RESULT] = review["result_sha256"]
        bundle[REVIEW] = json.dumps(review).encode()
        self.refused(bundle)

    def test_scope_history_authority_and_terminal_mutations_refuse(self):
        cases = [
            (RESULT, "scope", "OLD_F552_SUCCESS"),
            (RESULT, "original_create_outcome", "SUCCESS"),
            (RESULT, "original_removal_outcome", "NO_EFFECTS"),
            (RESULT, "cause_of_current_absence", "ORIGINAL_RM"),
            (RESULT, "original_grant", "REUSABLE"),
            (RESULT, "native_authorized", True),
            (RESULT, "docker_mutations", True),
            (RESULT, "targets", list(reversed(json.loads(BUNDLE[RESULT])["targets"]))),
            (RESULT, "commands", []),
            (RESULT, "independent_review_sha256", "0" * 64),
            (TERMINAL, "attempt_id", "borrowed"),
            (TERMINAL, "disposition", "SUCCESS_CLEANED"),
            (TERMINAL, "evidence_sha256", "0" * 64),
            (TERMINAL, "predecessor_sha256", "0" * 64),
            (EVENTS + "authority.json", "native_authorized", True),
            (REVIEW, "decision", "UNREVIEWED"),
        ]
        for key, field, value in cases:
            with self.subTest(key=key, field=field):
                self.refused(self.changed_json(key, lambda o, f=field, v=value: o.update({f: v})))

    def test_capture_presence_partial_diagnostic_and_overflow_refuse(self):
        for name, data in [
            ("01.stdout", b'[{"Id":"present"}]\n'),
            ("02.stderr", b"daemon unavailable\n"),
            ("03.stdout", b"unexpected-container\n"),
            ("01.stderr", b""),
            ("01.stdout", b"x" * (2 * 1024 * 1024 + 1)),
        ]:
            with self.subTest(name=name, size=len(data)):
                self.refused({**BUNDLE, EVENTS + "attempt/" + name: data})

    def test_non_bytes_and_non_plain_mapping_refuse(self):
        for value in [bytearray(BUNDLE[RESULT]), BUNDLE[RESULT].decode(), None, 1]:
            with self.subTest(value_type=type(value).__name__):
                self.refused({**BUNDLE, RESULT: value})
        for bundle in [None, [], {"review": b"{}"}, {1: b"x"}]:
            with self.subTest(bundle_type=type(bundle).__name__):
                self.refused(bundle)

        class HostileDict(dict):
            def items(self):
                raise AssertionError("Caller-controlled mapping invoked")

        self.refused(HostileDict(BUNDLE))

    def test_duplicate_key_nan_non_utf8_and_reformatted_review_refuse(self):
        for data in [
            b'{"decision":0,"decision":1}',
            b'{"x":NaN}',
            b"\xff",
            json.dumps(json.loads(BUNDLE[REVIEW]), sort_keys=True).encode(),
        ]:
            with self.subTest(data=data[:30]):
                self.refused({**BUNDLE, REVIEW: data})

    def test_caller_mutation_cannot_change_the_anchored_observation_window(self):
        self.assertIsNotNone(consumer)
        source = (HERE / "baseline_consumer.py").read_text().splitlines()
        parse_line = next(
            i for i, line in enumerate(source, 1) if "review = _document(bundle[REVIEW])" in line
        )
        bundle = dict(BUNDLE)
        forged = json.loads(bundle[REVIEW])
        forged["execution_window_utc"] = [
            "2099-01-01T00:00:00+00:00",
            "2099-01-01T00:00:01+00:00",
        ]
        forged_bytes = json.dumps(forged).encode()
        schedule = []

        def trace(frame, event, arg):
            if frame.f_code is consumer.verify_baseline.__code__ and event == "line":
                if frame.f_lineno == parse_line and not schedule:
                    bundle[REVIEW] = forged_bytes
                    schedule.append("change")
                elif frame.f_lineno > parse_line and schedule == ["change"]:
                    bundle[REVIEW] = BUNDLE[REVIEW]
                    schedule.append("restore")
            return trace

        previous = sys.gettrace()
        sys.settrace(trace)
        try:
            receipt = self.verify(bundle)
        finally:
            sys.settrace(previous)
        self.assertEqual(schedule, ["change", "restore"])
        self.assertEqual(bundle, BUNDLE)
        self.assertEqual(
            receipt.execution_window_utc,
            tuple(json.loads(BUNDLE[REVIEW])["execution_window_utc"]),
        )

    def test_module_has_no_runtime_or_loader_surface(self):
        self.assertIsNotNone(consumer)
        tree = ast.parse((HERE / "baseline_consumer.py").read_text())
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(n.name for n in node.names)
            elif isinstance(node, ast.ImportFrom):
                imports.add(node.module)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"open", "eval", "exec", "__import__"})
        self.assertLessEqual(imports, {"dataclasses", "hashlib", "json"})
        self.assertFalse(hasattr(consumer, "main"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
