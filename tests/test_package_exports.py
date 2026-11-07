"""Worker scaffold is intentionally export-neutral."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


class Exports(unittest.TestCase):
    def test_no_unreleased_exports(self):
        script = r"""
import importlib
import sys

sys.path.insert(0, sys.argv[1])
root = importlib.import_module("modkit_workers")
assert getattr(root, "__all__", None) == []
for leaf in ("adapters", "persistence", "persistence.sql"):
    module = importlib.import_module("modkit_workers." + leaf)
    # Python binds explicitly imported child modules on their parent.
    allowed = {"sql", "migrations"} if leaf == "persistence" else set()
    public = {key for key in vars(module) if not key.startswith("_")}
    assert public <= allowed, (leaf, public, allowed)
    for name in public:
        assert getattr(module, name) is importlib.import_module(module.__name__ + "." + name)
"""
        with tempfile.TemporaryDirectory(prefix="modkit-worker-exports-") as directory:
            result = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    script,
                    str(Path(__file__).resolve().parents[1] / "src"),
                ],
                cwd=directory,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
