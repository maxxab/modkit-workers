"""Actual execute-path admission checks with a sentinel before slot lookup."""

import fcntl
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
STATIC = (
    "source-inputs.json",
    "execution-plan.json",
    "profile-probe-qa-inventory.json",
    "validation/source_smoke.py",
    "validation/expected-grant-contract.json",
    "fixture_runner.py",
    "bootstrap/runtime_bootstrap.py",
    "controller-provision.sql",
    "baseline_consumer.py",
    "baseline-inputs.json",
)
IDENTITY = {
    "scope": "REDIS8_CURRENT_ABSENCE_RECONCILIATION_V1",
    "review_sha256": "8e5b622e460ba564029d0e786b22fce8666879e280835d0efb1a26949dd09d75",
    "result_sha256": "d0277050aa931b1fa116271fc2cf83be3cbfeac1dee34307d0a04320f4425e8a",
    "terminal_sha256": "33ce28d0bd25e5f17f75747fcb184a507b651a21fb363ff8d9419c4084f6ad4b",
    "contract_sha256": "a083cb920e25875ac0c08f5454b3403ebf157e9939d2d0191d3519cc2af77abf",
}


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


ACTIVE = False


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
        raise AssertionError("Native admission test forbids real effects: " + event)


sys.addaudithook(guard)


class ReachedSlot(Exception):
    """Sentinel exception; no real slot is instantiated."""


class AdmissionTests(unittest.TestCase):
    def setUp(self):
        global ACTIVE
        ACTIVE = True
        self.addCleanup(lambda: globals().__setitem__("ACTIVE", False))
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "candidate"
        self.root.mkdir()
        self.scope = {
            "__name__": "inert_admission_test",
            "__file__": str(ROOT / "execute_packet.py"),
        }
        exec(
            compile((ROOT / "execute_packet.py").read_bytes(), self.scope["__file__"], "exec"),
            self.scope,
        )
        names = set(STATIC) | set(self.scope["PREP_CHECKS"])
        for name in names:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(
                (ROOT / name).read_bytes()
                if (ROOT / name).exists()
                else b"Synthetic test evidence only; never execution authority\n"
            )
        shutil.copytree(ROOT / "baseline-evidence", self.root / "baseline-evidence")
        (self.root / "independent-execution-review.md").write_text(
            "SYNTHETIC UNIT TEST REVIEW. NOT AUTHORITY.\n"
        )
        self.scope["ROOT"] = self.root
        self.lookups = []

        def slot_lookup():
            self.lookups.append("lookup")
            raise ReachedSlot()

        self.scope["_runtime_slot_class"] = slot_lookup
        self.scope["_execute_owned"] = lambda *args: self.fail("Native execution reached")
        self.freeze()

    def freeze(self):
        admission = {n: digest(self.root / n) for n in STATIC}
        admission.update(
            {
                str(p.relative_to(self.root)): digest(p)
                for p in (self.root / "baseline-evidence").iterdir()
                if p.is_file()
            }
        )
        self.pins = {
            "payload": {},
            "controller_sha256": digest(ROOT / "execute_packet.py"),
            "preparation_checks": {n: digest(self.root / n) for n in self.scope["PREP_CHECKS"]},
            "plan_sha256": digest(self.root / "execution-plan.json"),
            "admission_inputs": admission,
            "historical_baseline": dict(IDENTITY),
        }
        self.write_pins()

    def write_pins(self):
        (self.root / "execution-pins.json").write_text(json.dumps(self.pins))
        release = {
            "decision": "APPROVE_EXACT_ONCE",
            "pins_sha256": digest(self.root / "execution-pins.json"),
            "review_sha256": digest(self.root / "independent-execution-review.md"),
            "authority_reference": "SYNTHETIC TEST ONLY; NOT A USER GRANT",
            "attempt": 1,
            "fixture": self.scope["NAME"],
        }
        (self.root / "unit-test-release.json").write_text(json.dumps(release))

    def invoke(self, valid=False):
        self.lookups.clear()
        error = None
        try:
            self.scope["execute"]({}, self.root / "unit-test-release.json")
        except BaseException as caught:
            error = caught
        if valid:
            self.assertIsInstance(error, ReachedSlot)
            self.assertEqual(self.lookups, ["lookup"])
        else:
            self.assertEqual(self.lookups, [], "Invalid admission reached RuntimeSlot lookup")
            self.assertIsInstance(error, (ValueError, OSError))
        for name in ("attempt.claim", "runtime-r4", "runtime-slot-terminal.json"):
            self.assertFalse((self.root / name).exists())

    def test_effect_guard_is_active_for_each_admission_case(self):
        with (self.root / "guard-check").open("wb") as stream:
            with self.assertRaisesRegex(AssertionError, "forbids real effects: fcntl.flock"):
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_valid_exact_historical_inputs_reach_only_sentinel(self):
        self.invoke(valid=True)

    def test_all_missing_and_changed_baseline_files_refuse_before_slot(self):
        for p in sorted((self.root / "baseline-evidence").iterdir()):
            raw = p.read_bytes()
            with self.subTest(name=p.name, change="missing"):
                p.unlink()
                self.invoke()
                p.write_bytes(raw)
            with self.subTest(name=p.name, change="changed"):
                p.write_bytes(raw + b" ")
                self.invoke()
                p.write_bytes(raw)

    def test_rehashed_changed_static_inputs_still_refuse(self):
        for name in STATIC:
            with self.subTest(name=name):
                p = self.root / name
                raw = p.read_bytes()
                p.write_bytes(raw + b" ")
                self.freeze()
                self.invoke()
                p.write_bytes(raw)
                self.freeze()

    def test_altered_missing_or_extra_pin_entries_refuse(self):
        for change in ("missing", "extra", "wrong", "plan"):
            with self.subTest(change=change):
                self.freeze()
                if change == "missing":
                    self.pins["admission_inputs"].pop("baseline_consumer.py")
                elif change == "extra":
                    self.pins["admission_inputs"]["unreviewed"] = "0" * 64
                elif change == "wrong":
                    self.pins["admission_inputs"]["baseline_consumer.py"] = "0" * 64
                else:
                    self.pins["plan_sha256"] = "0" * 64
                self.write_pins()
                self.invoke()

    def test_historical_identity_replacement_and_f552_refuse(self):
        for field in IDENTITY:
            with self.subTest(field=field):
                self.freeze()
                self.pins["historical_baseline"][field] = (
                    "f5522643d5a3e4a6cb11a0c7e9ce7de6abd78c1897897979024e9cb8cd17655c"
                )
                self.write_pins()
                self.invoke()

    def test_wrong_authority_and_review_refuse_before_slot(self):
        path = self.root / "unit-test-release.json"
        for field, value in [
            ("attempt", 2),
            ("fixture", "borrowed"),
            ("decision", "NO"),
            ("authority_reference", ""),
            ("review_sha256", "0" * 64),
            ("pins_sha256", "0" * 64),
        ]:
            with self.subTest(field=field):
                self.freeze()
                release = json.loads(path.read_text())
                release[field] = value
                path.write_text(json.dumps(release))
                self.invoke()

    def test_symlink_file_parent_and_oversize_refuse(self):
        p = self.root / "baseline-evidence" / "001.bin"
        raw = p.read_bytes()
        target = self.root.parent / "same-evidence.bin"
        target.write_bytes(raw)
        p.unlink()
        p.symlink_to(target)
        self.invoke()
        p.unlink()
        p.write_bytes(raw)
        directory = self.root / "baseline-evidence"
        outside = self.root.parent / "same-evidence"
        directory.rename(outside)
        directory.symlink_to(outside, target_is_directory=True)
        self.invoke()
        directory.unlink()
        outside.rename(directory)
        p.write_bytes(b"x" * (2 * 1024 * 1024 + 1))
        self.invoke()

    def test_extra_baseline_file_refuses_without_reading_it(self):
        (self.root / "baseline-evidence" / "extra.bin").write_bytes(b"unreviewed")
        self.invoke()


if __name__ == "__main__":
    unittest.main(verbosity=2)
