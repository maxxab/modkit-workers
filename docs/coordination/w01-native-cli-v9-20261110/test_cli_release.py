"""Exercise the existing CLI boundary; never enter a real runtime slot."""

import contextlib
import fcntl
import hashlib
import io
import json
import runpy
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ACTIVE = False
assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode


def guard(event, args):
    if ACTIVE and (
        event.startswith("socket.")
        or event
        in {
            "subprocess.Popen",
            "os.system",
            "os.fork",
            "os.forkpty",
            "os.posix_spawn",
            "os.exec",
            "os.kill",
            "os.killpg",
            "ctypes.dlopen",
            "fcntl.flock",
        }
    ):
        raise AssertionError("CLI tests forbid actual effects: " + event)


sys.addaudithook(guard)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ReachedSlot(Exception):
    pass


class CliReleaseTests(unittest.TestCase):
    def setUp(self):
        global ACTIVE
        ACTIVE = True
        self.addCleanup(lambda: globals().__setitem__("ACTIVE", False))
        temporary = tempfile.TemporaryDirectory(prefix="workers-cli-synthetic-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "candidate"
        shutil.copytree(ROOT, self.root)
        self.controller = self.root / "execute_packet.py"
        self.scope = {"__name__": "inert_cli_test", "__file__": str(self.controller)}
        exec(
            compile(self.controller.read_bytes(), str(self.controller), "exec"),
            self.scope,
        )
        self.lookups = []

        def sentinel():
            self.lookups.append(True)
            raise ReachedSlot()

        self.scope["_runtime_slot_class"] = sentinel
        self.scope["_execute_owned"] = lambda *args: self.fail(
            "Actual native body entered"
        )
        pins = json.loads((self.root / "execution-pins.json").read_text())
        pins["controller_sha256"] = sha(self.controller)
        for name in self.scope["PREP_CHECKS"]:
            target = self.root / name
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    "Synthetic test-only check evidence; no execution authority.\n"
                )
        pins["preparation_checks"] = {
            n: sha(self.root / n) for n in self.scope["PREP_CHECKS"]
        }
        (self.root / "execution-pins.json").write_text(json.dumps(pins))
        review = self.root / "independent-execution-review.md"
        review.write_text("SYNTHETIC UNIT TEST REVIEW ONLY. NOT USER AUTHORIZATION.\n")
        self.release = self.root / "synthetic-release.json"
        self.release_data = {
            "decision": "APPROVE_EXACT_ONCE",
            "attempt": 1,
            "fixture": "modkit-install-20261109-r4",
            "pins_sha256": sha(self.root / "execution-pins.json"),
            "review_sha256": sha(review),
            "authority_reference": "SYNTHETIC UNIT TEST ONLY; NOT USER AUTHORITY",
        }
        self.release.write_text(json.dumps(self.release_data))
        self.addCleanup(self.assert_no_effects)

    def assert_no_effects(self):
        for name in ("attempt.claim", "runtime-r4", "runtime-slot-terminal.json"):
            self.assertFalse((self.root / name).exists(), name)

    def main(self, args):
        self.assertTrue(
            callable(self.scope.get("main")), "A testable standard CLI main is missing"
        )
        return self.scope["main"](args)

    def run_cli(self, args):
        old = sys.argv
        try:
            sys.argv = [str(self.controller), *args]
            return runpy.run_path(str(self.controller), run_name="__main__")
        finally:
            sys.argv = old

    def test_default_actual_cli_is_preparation_only(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.run_cli([])
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "PREPARATION_ONLY_NO_NATIVE_IO")
        self.assertEqual(report["files"], 97)
        self.assertEqual(report["bytes"], 2920942)
        self.assertEqual(self.lookups, [])

    def test_actual_cli_missing_release_refuses_at_authority_boundary(self):
        caught = None
        try:
            self.run_cli(["--release", str(self.root / "absent-release.json")])
        except BaseException as error:
            caught = error
        self.assertIsInstance(caught, FileNotFoundError)
        self.assertEqual(self.lookups, [])

    def test_actual_cli_invalid_release_refuses_at_authority_boundary(self):
        invalid = self.root / "invalid-release.json"
        invalid.write_text("{}")
        caught = None
        try:
            self.run_cli(["--release", str(invalid)])
        except BaseException as error:
            caught = error
        self.assertIsInstance(caught, ValueError)
        self.assertEqual(str(caught), "NO_EXACT_AUTHORITY")
        self.assertEqual(self.lookups, [])

    def test_valid_synthetic_release_reaches_only_slot_sentinel(self):
        with self.assertRaises(ReachedSlot):
            self.main(["--release", str(self.release)])
        self.assertEqual(self.lookups, [True])

    def test_changed_release_fields_refuse_before_slot(self):
        for field, value in (
            ("attempt", 2),
            ("attempt", True),
            ("fixture", "other"),
            ("pins_sha256", "0" * 64),
            ("authority_reference", ""),
            ("decision", "OTHER"),
            ("review_sha256", "0" * 64),
        ):
            with self.subTest(field=field, value=value):
                changed = dict(self.release_data)
                changed[field] = value
                self.release.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    self.main(["--release", str(self.release)])
                self.assertEqual(self.lookups, [])

    def test_missing_final_review_refuses_before_slot(self):
        (self.root / "independent-execution-review.md").unlink()
        with self.assertRaises(FileNotFoundError):
            self.main(["--release", str(self.release)])
        self.assertEqual(self.lookups, [])

    def test_static_plan_or_baseline_drift_refuses_before_slot(self):
        for name in ("execution-plan.json", "baseline-evidence/001.bin"):
            target = self.root / name
            raw = target.read_bytes()
            with self.subTest(name=name):
                target.write_bytes(raw + b" ")
                with self.assertRaises(ValueError):
                    self.main(["--release", str(self.release)])
                self.assertEqual(self.lookups, [])
                target.write_bytes(raw)

    def test_unknown_argument_refuses_without_authority_or_effect(self):
        with (
            contextlib.redirect_stderr(io.StringIO()),
            self.assertRaises(SystemExit) as raised,
        ):
            self.run_cli(["--native-without-release"])
        self.assertEqual(raised.exception.code, 2)

    def test_default_main_never_looks_up_slot(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(self.main([]))
        self.assertEqual(self.lookups, [])

    def test_guard_is_active_for_this_case(self):
        with (self.root / "guard-test").open("wb") as stream:
            with self.assertRaisesRegex(
                AssertionError, "forbid actual effects: fcntl.flock"
            ):
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


if __name__ == "__main__":
    unittest.main()
