"""Pure root exports are additive; implementation namespaces remain inert."""

import importlib
import json
import subprocess
import sys
import unittest


class Exports(unittest.TestCase):
    def test_no_unreleased_exports(self):
        root = importlib.import_module("modkit_workers")
        self.assertEqual(
            set(root.__all__),
            {
                "AcquireRequest",
                "AsyncJobHandler",
                "AsyncWorkSource",
                "ConflictingHandlerRouteError",
                "DuplicateHandlerError",
                "HandlerKind",
                "HandlerRegistration",
                "HandlerRegistry",
                "InvalidWorkerConfiguration",
                "JobContext",
                "RenewalOwner",
                "SyncJobHandler",
                "UnknownCommandType",
                "UnsupportedHandlerVersion",
                "WorkerSettings",
                "WorkSource",
            },
        )
        self.assertFalse(hasattr(root, "JobWorker"))
        self.assertFalse(hasattr(root, "EventWorker"))
        # Collection may already import persistence children. Verify initializer
        # behavior in a clean process using the caller's exact import locations.
        script = """
import importlib
import json
import sys
import unittest

sys.path[:] = json.loads(sys.argv[1])
case = unittest.TestCase()
for leaf in ("adapters", "persistence", "persistence.sql"):
    module = importlib.import_module("modkit_workers." + leaf)
    # Python binds explicitly imported child modules on their parent.
    allowed = {"sql", "migrations"} if leaf == "persistence" else set()
    public = {key for key in vars(module) if not key.startswith("_")}
    case.assertLessEqual(public, allowed)
    for name in public:
        case.assertIs(
            getattr(module, name), importlib.import_module(module.__name__ + "." + name)
        )
"""
        result = subprocess.run(
            [sys.executable, "-I", "-S", "-B", "-c", script, json.dumps(sys.path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
