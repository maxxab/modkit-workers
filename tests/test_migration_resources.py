"""TEST-ONLY in-memory resource fixtures; never production SQL or migrations."""

import dataclasses
import hashlib
import importlib
import io
import json
import unittest

PACKAGE = "modkit_workers"
COMPONENT = "workers"
IDS = dict(
    catalog_contract_id="modkit-pg-ab-2", scope_format_id="MKSC-1", intent_format_id="MKPF-1"
)


# Independent frame oracle: no production hashing helper used.
def aggregate(resources):
    frames = [b"MKMF\x01", len(resources).to_bytes(4, "big")]
    for item in sorted(resources, key=lambda r: r["path"].encode("utf-8")):
        path = item["path"].encode("utf-8")
        frames.extend((len(path).to_bytes(4, "big"), path, bytes.fromhex(item["sha256"])))
    return hashlib.sha256(b"".join(frames)).hexdigest()


class Tree:
    def __init__(self, files, path="", calls=None):
        self.files, self.path = files, path
        self.calls = [] if calls is None else calls

    def joinpath(self, name):
        return Tree(self.files, name, self.calls)

    def read_bytes(self):
        self.calls.append(self.path)
        if self.path not in self.files:
            raise FileNotFoundError(self.path)
        value = self.files[self.path]
        if isinstance(value, Exception):
            raise value
        return value

    def open(self, mode="rb"):
        assert mode == "rb"
        return io.BytesIO(self.read_bytes())


class Resources(unittest.TestCase):
    def setUp(self):
        try:
            self.m = importlib.import_module(PACKAGE + ".persistence.migrations")
        except ModuleNotFoundError:
            self.fail("released migration reader is missing")
        self.files = {
            "0001_initial.sql": b"-- TEST ONLY \xc3\xa9\r\n",
            "grants_runtime.sql": b"-- TEST ONLY grants\n",
        }
        resources = [
            dict(path=COMPONENT + "/" + name, sha256=hashlib.sha256(data).hexdigest())
            for name, data in self.files.items()
        ]
        deps = (
            []
            if COMPONENT == "events"
            else [dict(component="events", version=1, migration_digest="a" * 64)]
        )
        self.record = dict(
            component=COMPONENT,
            version=1,
            resources=resources,
            migration_digest=aggregate(resources),
            depends_on=deps,
            **IDS,
        )
        self.document = dict(
            format_version=1, package=PACKAGE.replace("_", "-"), migrations=[self.record]
        )
        self.tree = Tree(self.files)
        original = self.m._io.open_lease
        self.addCleanup(setattr, self.m._io, "open_lease", original)
        tree = self.tree
        backend = self.m._io

        class MemoryLease:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def read(self, name, limit=None):
                raw = tree.joinpath(name).read_bytes()
                bound = backend._limit(name, limit)
                if len(raw) > bound:
                    backend._large(name)
                return raw

        self.m._io.open_lease = lambda anchor: MemoryLease()
        self.save()

    def save(self):
        self.files["manifest.json"] = json.dumps(self.document).encode()

    def invalid(self, call):
        with self.assertRaisesRegex(ValueError, "^invalid migration descriptor$"):
            call()

    def test_valid_independent_descriptors_and_exact_text(self):
        (item,) = self.m.manifest()
        clone = dataclasses.replace(item)
        resource = dataclasses.replace(item.resources[0])
        self.assertIsNot(item, clone)
        self.assertEqual(self.m.read_sql(clone, resource), "-- TEST ONLY é\r\n")
        with self.assertRaises(dataclasses.FrozenInstanceError):
            clone.version = 2
        self.assertIs(type(item.resources), tuple)
        self.assertIs(type(item.depends_on), tuple)

    def test_scalar_types_nested_mutability_and_ids(self):
        (item,) = self.m.manifest()

        class Int(int):
            pass

        class Text(str):
            pass

        class Tuple(tuple):
            pass

        for bad in (True, False, 1.0, "1", Int(1), 0, -1, 2):
            self.invalid(lambda: dataclasses.replace(item, version=bad))
            self.invalid(
                lambda: self.m.MigrationDependency(
                    component="events", version=bad, migration_digest="a" * 64
                )
            )
        for bad in ([], list(item.resources), Tuple(item.resources)):
            self.invalid(lambda: dataclasses.replace(item, resources=bad))
        self.invalid(lambda: dataclasses.replace(item, depends_on=[]))
        for key in IDS:
            self.invalid(lambda: dataclasses.replace(item, **{key: "wrong"}))
        for bad in (b"events", None, Text(COMPONENT)):
            self.invalid(lambda: dataclasses.replace(item, component=bad))

    def test_paths_digest_graph_and_aggregate(self):
        (item,) = self.m.manifest()
        r = item.resources[0]
        for bad in (
            "../0001_initial.sql",
            "/events/0001_initial.sql",
            "events/other.sql",
            "events/\x00.sql",
        ):
            self.invalid(lambda: dataclasses.replace(r, path=bad))
        for bad in ("a" * 63, "a" * 65, "A" * 64, "g" * 64, b"a" * 64):
            self.invalid(lambda: dataclasses.replace(r, sha256=bad))
        for bad in (item.resources[::-1], (r, r), (r,), (object(), r)):
            self.invalid(lambda: dataclasses.replace(item, resources=bad))
        self.invalid(lambda: dataclasses.replace(item, migration_digest="0" * 64))
        dep = self.m.MigrationDependency(component="workers", version=1, migration_digest="b" * 64)
        self.invalid(lambda: dataclasses.replace(item, depends_on=(dep,)))

    def test_forged_bool_and_hooks_rejected_before_io(self):
        (item,) = self.m.manifest()
        forged = dataclasses.replace(item)
        object.__setattr__(forged, "version", True)
        self.tree.calls.clear()
        self.invalid(lambda: self.m.read_sql(forged, item.resources[0]))
        self.assertEqual(self.tree.calls, [])

        class Evil:
            def __eq__(self, other):
                raise AssertionError("equality hook executed")

            def __str__(self):
                raise AssertionError("string hook executed")

        self.invalid(lambda: self.m.read_sql(Evil(), item.resources[0]))
        self.invalid(lambda: dataclasses.replace(item.resources[0], path=Evil()))
        blank = object.__new__(self.m.Migration)
        self.invalid(lambda: self.m.read_sql(blank, item.resources[0]))
        self.assertEqual(self.tree.calls, [])

    def test_foreign_and_unlisted_descriptors(self):
        (item,) = self.m.manifest()
        resource = dataclasses.replace(item.resources[0], sha256="f" * 64)
        self.invalid(lambda: self.m.read_sql(item, resource))

    def test_json_strictness_and_bound(self):
        for raw in (
            b'{"format_version":1,"format_version":1}',
            b'{"x":NaN}',
            b"[]",
            b"\xff",
            b"[" * 2000,
            b" " * 65537,
        ):
            self.files["manifest.json"] = raw
            with self.assertRaises(ValueError):
                self.m.manifest()
        for key, bad in (("format_version", True), ("package", "wrong"), ("migrations", [])):
            original = self.document[key]
            self.document[key] = bad
            self.save()
            with self.assertRaises(ValueError):
                self.m.manifest()
            self.document[key] = original
        self.document["extra"] = 1
        self.save()
        with self.assertRaises(ValueError):
            self.m.manifest()

    def test_missing_and_tampered_resources(self):
        (item,) = self.m.manifest()
        self.files["0001_initial.sql"] += b"changed"
        with self.assertRaises(ValueError):
            self.m.read_sql(item, item.resources[0])
        del self.files["grants_runtime.sql"]
        del self.files["manifest.json"]
        with self.assertRaises(FileNotFoundError):
            self.m.manifest()

    def test_invalid_utf8_and_oserror(self):
        self.files["0001_initial.sql"] = b"\xff"
        self.record["resources"][0]["sha256"] = hashlib.sha256(b"\xff").hexdigest()
        self.record["migration_digest"] = aggregate(self.record["resources"])
        self.save()
        (item,) = self.m.manifest()
        with self.assertRaises(ValueError):
            self.m.read_sql(item, item.resources[0])
        self.files["manifest.json"] = PermissionError("fixture only")
        with self.assertRaises(PermissionError):
            self.m.manifest()

    def test_record_subclasses_and_missing_sql(self):
        (item,) = self.m.manifest()

        class ForgedResource(self.m.SQLResource):
            def __eq__(self, other):
                raise AssertionError("subclass equality must not run")

        self.invalid(
            lambda: ForgedResource(path=item.resources[0].path, sha256=item.resources[0].sha256)
        )
        nested = dataclasses.replace(item.resources[0])
        object.__setattr__(nested, "sha256", True)
        forged = dataclasses.replace(item)
        object.__setattr__(forged, "resources", (nested, item.resources[1]))
        self.tree.calls.clear()
        self.invalid(lambda: self.m.read_sql(forged, item.resources[0]))
        self.assertEqual(self.tree.calls, [])
        del self.files["grants_runtime.sql"]
        with self.assertRaises(FileNotFoundError):
            self.m.manifest()

    def test_manifest_nested_unknown_keys_and_shapes(self):
        self.record["resources"][0]["extra"] = 1
        self.save()
        with self.assertRaises(ValueError):
            self.m.manifest()
        del self.record["resources"][0]["extra"]
        self.record["version"] = True
        self.save()
        with self.assertRaises(ValueError):
            self.m.manifest()
        self.record["version"] = 1
        self.record["resources"] = self.record["resources"][::-1]
        self.save()
        with self.assertRaises(ValueError):
            self.m.manifest()


class Source4(unittest.TestCase):
    """Focused source controls; origin seams are not installed-loader proof."""

    def setUp(self):
        from _resource_fixtures import Sandbox

        self.sandbox = Sandbox(COMPONENT)
        self.addCleanup(self.sandbox.close)
        self.m = importlib.import_module(PACKAGE + ".persistence.migrations")
        try:
            self.backend = importlib.import_module(PACKAGE + ".persistence._resource_io")
        except ModuleNotFoundError:
            self.fail("released anchored POSIX/Z1 backend is missing")

    def test_posix_locator_and_leaf_policy(self):
        if self.sandbox.link_error is not None:
            self.skipTest("BLOCKED link fixture: " + str(self.sandbox.link_error))
        for root in (
            self.sandbox.root,
            self.sandbox.base / "root-link",
            self.sandbox.base / "container/ancestor",
        ):
            with self.backend.PosixLease(root) as lease:
                self.assertEqual(
                    lease.read("0001_initial.sql"), self.sandbox.files["0001_initial.sql"]
                )
        for name in ("manifest", "0001_initial", "grants_runtime"):
            with self.backend.PosixLease(self.sandbox.base / (name + "-link")) as lease:
                with self.assertRaisesRegex(ValueError, "containment failure"):
                    lease.read(name + (".json" if name == "manifest" else ".sql"))

    def test_public_single_lease_and_descriptor_before_io(self):
        calls = []
        original = self.backend.open_lease
        self.addCleanup(setattr, self.backend, "open_lease", original)

        def opened(anchor):
            calls.append(anchor)
            return self.backend.PosixLease(self.sandbox.root)

        self.backend.open_lease = opened
        (item,) = self.m.manifest()
        calls.clear()
        self.assertEqual(
            self.m.read_sql(item, item.resources[0]),
            self.sandbox.files["0001_initial.sql"].decode(),
        )
        self.assertEqual(calls, [PACKAGE + ".persistence.sql"])
        calls.clear()
        with self.assertRaises(ValueError):
            self.m.read_sql(True, item.resources[0])
        self.assertEqual(calls, [])

    def test_unknown_origin_rejected_before_provider(self):
        import sys

        module = sys.modules[PACKAGE + ".persistence.sql"]
        old = module.__loader__
        self.addCleanup(setattr, module, "__loader__", old)

        class Unknown:
            def get_resource_reader(self, *args):
                raise AssertionError("provider invoked")

        module.__loader__ = Unknown()
        with self.assertRaisesRegex(ValueError, "unsupported migration resource backend"):
            self.backend.open_lease(PACKAGE + ".persistence.sql")

    def test_zip_stored_deflated_and_descriptor(self):
        from _resource_fixtures import archive

        prefix = PACKAGE + "/persistence/sql/"
        for method in (0, 8):
            for descriptor in (False, True):
                with self.subTest(method=method, descriptor=descriptor):
                    with self.backend.ZipLease(
                        archive(self.sandbox.files, method, prefix, descriptor), prefix
                    ) as lease:
                        for name, raw in self.sandbox.files.items():
                            self.assertEqual(lease.read(name), raw)

    def test_zip_malformed_profile_and_crc(self):
        import struct

        from _resource_fixtures import archive

        prefix = PACKAGE + "/persistence/sql/"
        raw = archive({"0001_initial.sql": b"abcdef"}, 8, prefix)
        for broken in (raw[:-1], b"X" + raw, raw + b"X"):
            with self.assertRaises(ValueError):
                self.backend.ZipLease(broken, prefix)
        mutated = bytearray(raw)
        central = raw.index(b"PK\x01\x02")
        # Independent central/local claim describes only prefix; stream is longer.
        crc = __import__("zlib").crc32(b"abc") & 0xFFFFFFFF
        struct.pack_into("<I", mutated, 14, crc)
        struct.pack_into("<I", mutated, 22, 3)
        struct.pack_into("<I", mutated, central + 16, crc)
        struct.pack_into("<I", mutated, central + 24, 3)
        with self.backend.ZipLease(bytes(mutated), prefix) as lease:
            with self.assertRaisesRegex(ValueError, "invalid migration resource archive"):
                lease.read("0001_initial.sql")
        for name in ("../0001_initial.sql", "/x", "a\\b", "x\x00z"):
            with self.assertRaises(ValueError):
                self.backend.ZipLease(archive({name: b"x"}, 0, ""), prefix)

    def test_budget_and_missing(self):
        with self.backend.PosixLease(self.sandbox.root) as lease:
            with self.assertRaisesRegex(ValueError, "resource too large"):
                lease.read("0001_initial.sql", limit=2)
            with self.assertRaises(ValueError):
                lease.read("../outside")
        from _resource_fixtures import archive

        prefix = PACKAGE + "/persistence/sql/"
        with self.backend.ZipLease(
            archive({"grants_runtime.sql": b"x"}, 0, prefix), prefix
        ) as lease:
            with self.assertRaises(FileNotFoundError):
                lease.read("manifest.json")

    def test_root_rename_does_not_change_anchor(self):
        with self.backend.PosixLease(self.sandbox.root) as lease:
            self.sandbox.move_root()
            self.assertEqual(lease.read("manifest.json"), self.sandbox.files["manifest.json"])

    def test_checkout_origin_real_candidate_resources_are_verified(self):
        # IC-REG-1: candidate-only transition, not installed-artifact qualification.
        from pathlib import Path

        (item,) = self.m.manifest()
        self.assertEqual(item.component, COMPONENT)
        root = Path(self.m.__file__).parent / "sql"
        for resource in item.resources:
            raw = (root / resource.path.split("/")[1]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), resource.sha256)
            self.assertEqual(self.m.read_sql(item, resource).encode("utf-8"), raw)

    def test_missing_manifest_still_fails_through_public_api(self):
        missing = self.sandbox.directory(
            "missing-manifest",
            {name: raw for name, raw in self.sandbox.files.items() if name != "manifest.json"},
        )
        original = self.backend.open_lease
        self.addCleanup(setattr, self.backend, "open_lease", original)
        self.backend.open_lease = lambda anchor: self.backend.PosixLease(missing)
        with self.assertRaises(FileNotFoundError):
            self.m.manifest()

    def test_zip_origin_known_loader_with_metadata_seam(self):
        import sys
        import zipimport
        from types import SimpleNamespace

        from _resource_fixtures import archive

        prefix = "vendor/" + PACKAGE + "/persistence/sql/"
        files = dict(self.sandbox.files, **{"__init__.py": b""})
        path = self.sandbox.write_archive(archive(files, 8, prefix))
        loader = zipimport.zipimporter(str(path) + "/vendor/" + PACKAGE + "/persistence/")
        module = sys.modules[PACKAGE + ".persistence.sql"]
        old = (module.__loader__, module.__spec__)
        self.addCleanup(setattr, module, "__loader__", old[0])
        self.addCleanup(setattr, module, "__spec__", old[1])
        module.__loader__ = loader
        module.__spec__ = SimpleNamespace(
            name=PACKAGE + ".persistence.sql",
            loader=loader,
            origin=str(path) + "/" + prefix + "__init__.py",
            submodule_search_locations=[str(path) + "/" + prefix.rstrip("/")],
        )
        (item,) = self.m.manifest()
        self.assertEqual(
            self.m.read_sql(item, item.resources[0]),
            self.sandbox.files["0001_initial.sql"].decode(),
        )
        module.__spec__.origin = str(path) + "/wrong/__init__.py"
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.m.manifest()


class Source4Cleanup(unittest.TestCase):
    """Boundary doubles validate bookkeeping, not actual OS cleanup outcomes."""

    def setUp(self):
        import os
        import stat
        from types import SimpleNamespace

        self.backend = importlib.import_module(PACKAGE + ".persistence._resource_io")
        self.closed = []
        self.opened = []
        self.close_errors = {}
        self.read_error = None
        self.stat_error = None
        self.open_error = None
        self.data = b"abc"
        case = self

        def opened(path, flags, dir_fd=None):
            if dir_fd is not None and case.open_error is not None:
                raise case.open_error
            fd = 10 + len(case.opened)
            case.opened.append(fd)
            return fd

        def closed(fd):
            case.closed.append(fd)
            if fd in case.close_errors:
                raise case.close_errors[fd]

        def fstat(fd):
            if fd != 10 and case.stat_error is not None:
                raise case.stat_error
            return SimpleNamespace(st_mode=stat.S_IFDIR if fd == 10 else stat.S_IFREG)

        def read(fd, count):
            if case.read_error is not None:
                raise case.read_error
            result = case.data[:count]
            case.data = case.data[count:]
            return result

        fake = SimpleNamespace(
            name="posix",
            open=opened,
            close=closed,
            fstat=fstat,
            read=read,
            O_RDONLY=os.O_RDONLY,
            O_DIRECTORY=os.O_DIRECTORY,
            O_NONBLOCK=os.O_NONBLOCK,
            O_NOFOLLOW=os.O_NOFOLLOW,
            supports_dir_fd={opened},
        )
        original = self.backend.os
        self.addCleanup(setattr, self.backend, "os", original)
        self.backend.os = fake

    def test_primary_and_independent_close_failures(self):
        primary = OSError("primary")
        self.read_error = primary
        self.close_errors = {11: OSError("leaf"), 10: OSError("root")}
        with self.assertRaises(OSError) as caught:
            with self.backend.PosixLease("/owned") as lease:
                lease.read("manifest.json")
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.closed, [11, 10])
        self.assertEqual(primary.__notes__, [self.backend._NOTE, self.backend._NOTE])

    def test_first_close_failure_no_success_or_retry(self):
        first = OSError("leaf")
        self.close_errors = {11: first, 10: OSError("root")}
        with self.assertRaises(OSError) as caught:
            with self.backend.PosixLease("/owned") as lease:
                lease.read("manifest.json")
        self.assertIs(caught.exception, first)
        self.assertEqual(self.closed, [11, 10])

    def test_failed_child_open_has_only_root_owner(self):
        self.open_error = FileNotFoundError("missing")
        with self.assertRaises(FileNotFoundError):
            with self.backend.PosixLease("/owned") as lease:
                lease.read("manifest.json")
        self.assertEqual(self.opened, [10])
        self.assertEqual(self.closed, [10])

    def test_baseexception_and_stat_failure_preserve_identity(self):
        class Stop(BaseException):
            pass

        primary = Stop("stop")
        self.stat_error = primary
        self.close_errors = {11: OSError("close")}
        with self.assertRaises(Stop) as caught:
            with self.backend.PosixLease("/owned") as lease:
                lease.read("manifest.json")
        self.assertIs(caught.exception, primary)
        self.assertEqual(self.closed, [11, 10])

    def test_regular_bounded_read_and_root_close(self):
        with self.backend.PosixLease("/owned") as lease:
            self.assertEqual(lease.read("manifest.json"), b"abc")
        self.assertEqual(self.closed, [11, 10])


class Source4ZipEdges(unittest.TestCase):
    def setUp(self):
        self.backend = importlib.import_module(PACKAGE + ".persistence._resource_io")
        from _resource_fixtures import archive

        self.archive = archive
        self.prefix = PACKAGE + "/persistence/sql/"

    def test_metadata_rejects_before_zipinfo_allocation(self):
        import struct

        data = bytearray(self.archive({"manifest.json": b"{}"}, prefix=self.prefix))
        central = data.index(b"PK\x01\x02")
        struct.pack_into("<H", data, central + 28, 4097)
        original = self.backend.zipfile.ZipFile
        self.addCleanup(setattr, self.backend.zipfile, "ZipFile", original)
        self.backend.zipfile.ZipFile = lambda *a, **k: self.fail(
            "ZipInfo allocation before preflight"
        )
        with self.assertRaisesRegex(ValueError, "resource too large"):
            self.backend.ZipLease(bytes(data), self.prefix)

    def test_names_aliases_modes_and_unsupported_compression(self):
        import struct

        for files in ({"x": b"a", "x/y": b"b"}, {"x": b"a", "x/": b""}):
            with self.assertRaises(ValueError):
                self.backend.ZipLease(self.archive(files, prefix=""), self.prefix)
        data = self.archive({"manifest.json": b"{}"}, prefix=self.prefix)
        c = data.index(b"PK\x01\x02")
        for mode in (0xA000, 0x1000, 0x2000, 0xC000):
            raw = bytearray(data)
            struct.pack_into("<H", raw, c + 4, 0x314)
            struct.pack_into("<I", raw, c + 38, mode << 16)
            with self.assertRaisesRegex(ValueError, "containment"):
                self.backend.ZipLease(bytes(raw), self.prefix)
        raw = bytearray(data)
        struct.pack_into("<H", raw, c + 10, 99)
        with self.assertRaisesRegex(ValueError, "unsupported"):
            self.backend.ZipLease(bytes(raw), self.prefix)

    def test_exact_crc_and_actual_length(self):
        import struct

        data = self.archive({"manifest.json": b"abcdef"}, method=8, prefix=self.prefix)
        c = data.index(b"PK\x01\x02")
        for field in ("crc", "short_output", "long_output"):
            raw = bytearray(data)
            if field == "crc":
                struct.pack_into("<I", raw, 14, 123)
                struct.pack_into("<I", raw, c + 16, 123)
            else:
                n = 3 if field == "short_output" else 9
                struct.pack_into("<I", raw, 22, n)
                struct.pack_into("<I", raw, c + 24, n)
            with self.backend.ZipLease(bytes(raw), self.prefix) as lease:
                with self.assertRaisesRegex(ValueError, "invalid migration resource archive"):
                    lease.read("manifest.json")

    def test_zip_metadata_close_error_preserves_primary(self):
        # Controlled object-boundary double; no real ZipFile/native close failure.
        primary = ValueError("metadata primary")
        close_error = OSError("metadata close")
        original = self.backend.zipfile.ZipFile
        self.addCleanup(setattr, self.backend.zipfile, "ZipFile", original)

        class Archive:
            def __init__(self, *a, **k):
                pass

            def infolist(self):
                raise primary

            def close(self):
                raise close_error

            def __enter__(self):
                return self

            def __exit__(self, *a):
                self.close()

        self.backend.zipfile.ZipFile = Archive
        with self.assertRaises(ValueError) as caught:
            self.backend.ZipLease(
                self.archive({"manifest.json": b"{}"}, prefix=self.prefix), self.prefix
            )
        self.assertIs(caught.exception, primary)


class Source4EOCD(unittest.TestCase):
    """Round1 only: real tiny wire fixtures and exact parser/taxonomy oracles."""

    def setUp(self):
        import struct

        from _resource_fixtures import archive

        self.b = importlib.import_module(PACKAGE + ".persistence._resource_io")
        self.struct = struct
        self.prefix = PACKAGE + "/persistence/sql/"
        self.raw = archive({"manifest.json": b"abc"}, prefix=self.prefix)
        self.c = self.raw.index(b"PK\x01\x02")
        self.e = len(self.raw) - 22

    def commented(self, comment):
        raw = bytearray(self.raw)
        self.struct.pack_into("<H", raw, self.e + 20, len(comment))
        return bytes(raw) + comment

    def test_false_signature_preflight_and_projection(self):
        fake = self.struct.pack("<4s4H2IH", b"PK\x05\x06", 1, 1, 0, 0, 0, 0, 0)
        raw = self.commented(fake)
        self.assertEqual(self.b._directory(raw), (self.c, self.e, 1))
        original = self.b.zipfile.ZipFile
        seen = []

        def capture(stream, *args, **kwargs):
            seen.append(stream.getvalue())
            return original(stream, *args, **kwargs)

        self.b.zipfile.ZipFile = capture
        self.addCleanup(setattr, self.b.zipfile, "ZipFile", original)
        with self.b.ZipLease(raw, self.prefix) as lease:
            self.assertEqual(lease.data, raw)
            self.assertEqual(lease.read("manifest.json"), b"abc")
        self.assertEqual(seen, [self.raw])
        # Actual stdlib on ORIGINAL bytes differs; projection is not optional.
        with original(io.BytesIO(raw)) as archive:
            self.assertEqual(archive.infolist(), [])

    def test_opaque_comment_unchanged_offsets(self):
        raw = self.commented(b"opaque PK\x05\x06 short and harmless")
        with self.b.ZipLease(raw, self.prefix) as lease:
            self.assertEqual(lease.read("manifest.json"), b"abc")
            self.assertEqual(lease.entries[self.prefix + "manifest.json"][6], 0)

    def test_true_central_candidate_ambiguity(self):
        central = self.raw[self.c : self.e]
        second_offset = len(self.raw)
        second_eocd = self.struct.pack(
            "<4s4H2IH", b"PK\x05\x06", 0, 0, 1, 1, len(central), second_offset, 0
        )
        raw = self.commented(central + second_eocd)
        with self.assertRaisesRegex(ValueError, "^invalid migration resource archive$"):
            self.b._directory(raw)

    def test_recognized_trailing_sfx_and_malformed(self):
        prefix = b"SFX!"
        sfx = bytearray(prefix + self.raw)
        self.struct.pack_into("<I", sfx, len(prefix) + self.c + 42, len(prefix))
        self.struct.pack_into("<I", sfx, len(prefix) + self.e + 16, len(prefix) + self.c)
        for raw in (self.raw + b"trailer", bytes(sfx)):
            with self.subTest(raw=raw[:4]):
                with self.assertRaisesRegex(ValueError, "^unsupported migration resource backend$"):
                    self.b.ZipLease(raw, self.prefix)
        for raw in (self.raw[:-1], prefix + self.raw, b"PK\x05\x06" + b"\0" * 18):
            with self.assertRaisesRegex(ValueError, "^invalid migration resource archive$"):
                self.b.ZipLease(raw, self.prefix)

    def test_recognized_descriptors_and_inconsistent(self):
        from _resource_fixtures import archive

        raw = archive({"manifest.json": b"abc"}, prefix=self.prefix, descriptor=True)
        c = raw.index(b"PK\x01\x02")
        e = len(raw) - 22
        d = c - 16
        unsigned = bytearray(raw[:d] + raw[d + 4 :])
        self.struct.pack_into("<I", unsigned, e - 4 + 16, c - 4)
        nonzero = bytearray(raw)
        nonzero[14:26] = raw[c + 16 : c + 28]
        for item in (bytes(unsigned), bytes(nonzero)):
            with self.assertRaisesRegex(ValueError, "^unsupported migration resource backend$"):
                self.b.ZipLease(item, self.prefix)
        bad = bytearray(unsigned)
        bad[d] ^= 1
        with self.assertRaisesRegex(ValueError, "^invalid migration resource archive$"):
            self.b.ZipLease(bytes(bad), self.prefix)

    def test_descriptor_crc_marker_alternatives(self):
        # Literal CRC preimage, independently checked; marker is also legal CRC.
        import zlib

        from _resource_fixtures import archive

        payload = bytes.fromhex("ac0a7ad5")
        self.assertEqual(zlib.crc32(payload), 0x08074B50)
        name = (self.prefix + "manifest.json").encode()
        for followed in (False, True):
            with self.subTest(followed_by_local=followed):
                files = {"manifest.json": payload}
                if followed:
                    files["grants_runtime.sql"] = b"X"
                signed = archive(files, prefix=self.prefix, descriptor=True)
                d = 30 + len(name) + 4
                self.assertEqual(signed[d : d + 8], b"PK\x07\x08" * 2)
                with self.b.ZipLease(signed, self.prefix) as lease:
                    self.assertEqual(lease.read("manifest.json"), payload)
                    if followed:
                        self.assertEqual(lease.read("grants_runtime.sql"), b"X")
                c = signed.index(b"PK\x01\x02") - 4
                e = len(signed) - 26
                unsigned = bytearray(signed[:d] + signed[d + 4 :])
                self.struct.pack_into("<I", unsigned, e + 16, c)
                if followed:
                    c2 = c + 46 + len(name)
                    second = self.struct.unpack_from("<I", unsigned, c2 + 42)[0] - 4
                    self.struct.pack_into("<I", unsigned, c2 + 42, second)
                    self.assertEqual(second, d + 12)
                    self.assertEqual(unsigned[d + 12 : d + 16], b"PK\x03\x04")
                else:
                    self.assertEqual(c, d + 12)
                self.assertEqual(self.struct.unpack_from("<3I", unsigned, d), (0x08074B50, 4, 4))
                with self.assertRaisesRegex(ValueError, "^unsupported migration resource backend$"):
                    self.b.ZipLease(bytes(unsigned), self.prefix)
                bad = bytearray(unsigned)
                bad[d + 4] ^= 1
                with self.assertRaisesRegex(ValueError, "^invalid migration resource archive$"):
                    self.b.ZipLease(bytes(bad), self.prefix)
                if followed:
                    # Central order need not be local order.
                    reversed_cd = unsigned[:c] + unsigned[c2:e] + unsigned[c:c2] + unsigned[e:]
                    with self.assertRaisesRegex(
                        ValueError, "^unsupported migration resource backend$"
                    ):
                        self.b.ZipLease(bytes(reversed_cd), self.prefix)
                    # Complete matching triple without contiguous record boundary.
                    gap = unsigned[: d + 12] + b"!" + unsigned[d + 12 :]
                    self.struct.pack_into("<I", gap, e + 1 + 16, c + 1)
                    self.struct.pack_into("<I", gap, c2 + 1 + 42, second + 1)
                    with self.assertRaisesRegex(ValueError, "^invalid migration resource archive$"):
                        self.b.ZipLease(bytes(gap), self.prefix)

    def test_parser_agreement_not_bypassed(self):
        original = self.b.zipfile.ZipFile

        class Disagree(original):
            def infolist(self):
                result = super().infolist()
                result[0].header_offset += 1
                return result

        self.b.zipfile.ZipFile = Disagree
        self.addCleanup(setattr, self.b.zipfile, "ZipFile", original)
        with self.assertRaisesRegex(ValueError, "^invalid migration resource archive$"):
            self.b.ZipLease(self.commented(b"ordinary"), self.prefix)

    def test_recognized_combined_layouts(self):
        # Second adjusted archive after a complete first archive: validated
        # second local range starts at a positive origin, never accepted.
        prefix = self.raw
        joined = bytearray(prefix + self.raw)
        self.struct.pack_into("<I", joined, len(prefix) + self.c + 42, len(prefix))
        self.struct.pack_into("<I", joined, len(prefix) + self.e + 16, len(prefix) + self.c)
        for raw in (bytes(joined), bytes(joined) + b"trailer"):
            with self.assertRaisesRegex(ValueError, "^unsupported migration resource backend$"):
                self.b.ZipLease(raw, self.prefix)

    def test_projection_cannot_hide_original_record_or_budget_error(self):
        original = self.b.zipfile.ZipFile

        def forbidden(*a, **k):
            self.fail("metadata allocation before original validation")

        self.b.zipfile.ZipFile = forbidden
        self.addCleanup(setattr, self.b.zipfile, "ZipFile", original)
        raw = bytearray(self.commented(b"opaque"))
        raw[14] ^= 1
        with self.assertRaisesRegex(ValueError, "^invalid migration resource archive$"):
            self.b.ZipLease(bytes(raw), self.prefix)
        raw = bytearray(self.commented(b"opaque"))
        self.struct.pack_into("<H", raw, self.c + 32, 4097)
        with self.assertRaisesRegex(ValueError, "^migration resource too large$"):
            self.b.ZipLease(bytes(raw), self.prefix)
