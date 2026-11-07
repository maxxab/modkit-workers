"""Worker scaffold is intentionally export-neutral."""
import importlib
import unittest

class Exports(unittest.TestCase):
    def test_no_unreleased_exports(self):
        root = importlib.import_module("modkit_workers")
        self.assertEqual(getattr(root, "__all__", None), [])
        for leaf in ("adapters", "persistence", "persistence.sql"):
            module = importlib.import_module("modkit_workers." + leaf)
            # Python binds explicitly imported child modules on their parent.
            allowed = {"sql", "migrations"} if leaf == "persistence" else set()
            public = {key for key in vars(module) if not key.startswith("_")}
            self.assertLessEqual(public, allowed)
            for name in public:
                self.assertIs(getattr(module, name), importlib.import_module(module.__name__ + "." + name))
