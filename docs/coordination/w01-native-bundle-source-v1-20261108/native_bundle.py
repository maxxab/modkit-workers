"""Local packager source. No runtime, shell, Docker or DB execution adapter."""

import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath

MAX_FILES = 2048
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_MANIFEST = 1024 * 1024
KINDS = {"interpreter", "loader", "elf", "python", "metadata", "data"}
SHA = re.compile(r"[0-9a-f]{64}")
NAME = re.compile(r"[A-Za-z0-9_+.,@=-]+")
FORBIDDEN = {"sitecustomize.py", "usercustomize.py", "__pycache__", ".env", "id_rsa", "id_ed25519"}
TOP = {"schema", "status", "provenance", "dynamic_closure", "files"}
ENTRY = {"source", "destination", "bytes", "sha256", "mode", "kind", "soname", "needed"}
D_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
F_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class Rejected(ValueError):
    """A fixed rejection code, without arbitrary file contents."""


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise Rejected("duplicate_json_key")
            result[key] = value
        return result

    def nonfinite(_):
        raise Rejected("nonfinite_json")
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=nonfinite)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise Rejected("invalid_json") from exc


def forbidden_component(part):
    return (part in FORBIDDEN or part.endswith((".pth", ".pyc", ".pyo"))
            or part.split(".", 1)[0] in {"sitecustomize", "usercustomize"})


def relative(value):
    if not isinstance(value, str) or not value or len(value) > 300:
        raise Rejected("relative_path")
    parts = value.split("/")
    if any(not part or part in {".", ".."} or not NAME.fullmatch(part) for part in parts):
        raise Rejected("relative_path")
    if any(forbidden_component(part) for part in parts):
        raise Rejected("forbidden_startup_or_secret_file")
    return PurePosixPath(value)


def absolute(value):
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 4096:
        raise Rejected("absolute_path")
    parts = value.split("/")[1:]
    if any(not p or p in {".", ".."} or "\\" in p or any(ord(c) < 32 or ord(c) == 127 for c in p) for p in parts):
        raise Rejected("absolute_path")
    return Path(value)


def parse_manifest(raw, expected_sha):
    if not isinstance(raw, bytes) or len(raw) > MAX_MANIFEST or not isinstance(expected_sha, str):
        raise Rejected("manifest_size_or_type")
    if not SHA.fullmatch(expected_sha) or digest(raw) != expected_sha:
        raise Rejected("manifest_pin")
    d = strict_json(raw)
    if not isinstance(d, dict) or set(d) != TOP:
        raise Rejected("manifest_schema")
    if (type(d["schema"]) is not int or d["schema"] != 1 or d["status"] != "SOURCE_ONLY"
            or d["provenance"] != "KNOWN_INSTALLED_BYTES_NOT_PUBLISHER_ATTESTED"
            or d["dynamic_closure"] != "UNPROVEN"):
        raise Rejected("manifest_scope")
    files = d["files"]
    if not isinstance(files, list) or not 1 <= len(files) <= MAX_FILES:
        raise Rejected("manifest_inventory")
    destinations = set()
    sources = set()
    providers = {}
    total = 0
    kinds = []
    for e in files:
        if not isinstance(e, dict) or set(e) != ENTRY:
            raise Rejected("entry_schema")
        source = str(absolute(e["source"]))
        if any(forbidden_component(p) for p in Path(source).parts):
            raise Rejected("forbidden_source_hook_or_secret")
        dest = str(relative(e["destination"]))
        if dest.split("/")[0] in {"manifest.json", "receipt.json"} or source in sources or dest in destinations:
            raise Rejected("duplicate_or_reserved_path")
        sources.add(source)
        destinations.add(dest)
        if type(e["bytes"]) is not int or not 0 <= e["bytes"] <= MAX_FILE:
            raise Rejected("file_size")
        total += e["bytes"]
        if total > MAX_TOTAL:
            raise Rejected("total_size")
        if not isinstance(e["sha256"], str) or not SHA.fullmatch(e["sha256"]):
            raise Rejected("file_hash")
        if type(e["mode"]) is not int or e["mode"] not in {0o444, 0o555}:
            raise Rejected("file_mode")
        if not isinstance(e["kind"], str) or e["kind"] not in KINDS:
            raise Rejected("file_kind")
        kinds.append(e["kind"])
        if e["kind"] in {"interpreter", "loader"} and e["mode"] != 0o555:
            raise Rejected("missing_executable_mode")
        if e["kind"] not in {"interpreter", "loader", "elf"} and e["mode"] != 0o444:
            raise Rejected("non_elf_executable")
        if not isinstance(e["needed"], list) or len(e["needed"]) > 128:
            raise Rejected("needed_shape")
        for n in e["needed"]:
            if not isinstance(n, str) or not NAME.fullmatch(n) or "/" in n:
                raise Rejected("needed_name")
        if len(set(e["needed"])) != len(e["needed"]):
            raise Rejected("needed_duplicate")
        soname = e["soname"]
        if soname is not None:
            if e["kind"] not in {"elf", "loader"} or not isinstance(soname, str) or not NAME.fullmatch(soname):
                raise Rejected("soname")
            if soname in providers:
                raise Rejected("ambiguous_soname")
            providers[soname] = dest
    if kinds.count("interpreter") != 1 or kinds.count("loader") != 1:
        raise Rejected("interpreter_loader_inventory")
    for dest in destinations:
        if any(str(parent) in destinations for parent in PurePosixPath(dest).parents):
            raise Rejected("destination_prefix_collision")
    if any(n not in providers for e in files for n in e["needed"]):
        raise Rejected("missing_needed_provider")
    return d


def directory_fd(path):
    path = absolute(str(path))
    fd = os.open("/", D_FLAGS)
    try:
        for part in path.parts[1:]:
            next_fd = os.open(part, D_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        return fd
    except BaseException:
        os.close(fd)
        raise


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns,
            info.st_mode, info.st_nlink)


def read_regular(path, limit, expected_mode=None):
    parent = directory_fd(path.parent)
    fd = None
    try:
        fd = os.open(path.name, F_FLAGS, dir_fd=parent)
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or before.st_size > limit or before.st_mode & (stat.S_ISUID | stat.S_ISGID)):
            raise Rejected("not_bounded_unique_regular_file")
        if expected_mode is not None and stat.S_IMODE(before.st_mode) != expected_mode:
            raise Rejected("staged_mode_drift")
        with os.fdopen(fd, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        after = os.fstat(fd)
        current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if (len(data) > limit or fingerprint(before) != fingerprint(after)
                or fingerprint(before) != fingerprint(current)):
            raise Rejected("source_changed_during_read")
        return data, fingerprint(before)
    except OSError as exc:
        raise Rejected("filesystem_rejected") from exc
    finally:
        if fd is not None:
            os.close(fd)
        os.close(parent)


def receipt_for(d, manifest_sha):
    return {
        "status": "LOCAL_BYTES_STAGED_NOT_RUNTIME_QUALIFIED",
        "manifest_sha256": manifest_sha,
        "execution_authorized": False,
        "immutable_against_owner": False,
        "dynamic_closure": "UNPROVEN",
        "provenance": "KNOWN_INSTALLED_BYTES_NOT_PUBLISHER_ATTESTED",
        "files": {e["destination"]: {"bytes": e["bytes"], "sha256": e["sha256"], "mode": e["mode"]}
                  for e in d["files"]},
    }


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()


def write_relative(root_fd, name, data, mode):
    parts = relative(name).parts
    fd = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            try:
                os.mkdir(part, mode=0o700, dir_fd=fd)
            except FileExistsError:
                pass
            next_fd = os.open(part, D_FLAGS, dir_fd=fd)
            os.close(fd)
            fd = next_fd
        out = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                      mode, dir_fd=fd)
        with os.fdopen(out, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
    finally:
        os.close(fd)


def recheck_sources(inputs):
    for entry, original, captured in inputs:
        current, fingerprint_now = read_regular(absolute(entry["source"]), entry["bytes"])
        if current != original or fingerprint_now != captured:
            raise Rejected("source_changed_after_capture")


def stage_bundle(raw, expected_sha, allowed_roots, destination):
    d = parse_manifest(raw, expected_sha)
    destination = absolute(str(destination))
    if not isinstance(allowed_roots, tuple) or not allowed_roots:
        raise Rejected("source_allowlist_missing")
    roots = tuple(absolute(str(p)) for p in allowed_roots)
    inputs = []
    identities = set()
    try:
        for root in roots:
            fd = directory_fd(root)
            os.close(fd)
        for e in d["files"]:
            source = absolute(e["source"])
            if not any(source.is_relative_to(root) for root in roots):
                raise Rejected("source_outside_allowlist")
            data, identity = read_regular(source, e["bytes"])
            if len(data) != e["bytes"] or digest(data) != e["sha256"]:
                raise Rejected("source_pin_drift")
            if identity in identities:
                raise Rejected("source_inode_alias")
            identities.add(identity)
            inputs.append((e, data, identity))
        recheck_sources(inputs)
        parent = directory_fd(destination.parent)
        root_fd = None
        try:
            os.mkdir(destination.name, mode=0o700, dir_fd=parent)
            root_fd = os.open(destination.name, D_FLAGS, dir_fd=parent)
            for e, data, _ in inputs:
                write_relative(root_fd, e["destination"], data, e["mode"])
            write_relative(root_fd, "manifest.json", raw, 0o444)
            recheck_sources(inputs)
            receipt = receipt_for(d, expected_sha)
            write_relative(root_fd, "receipt.json", json_bytes(receipt), 0o444)
            os.fsync(root_fd)
        finally:
            if root_fd is not None:
                os.close(root_fd)
            os.close(parent)
    except OSError as exc:
        # Partial new output is preserved for review, never deleted or retried.
        raise Rejected("staging_failed_no_retry") from exc
    verify_bundle(destination, expected_sha)
    return receipt


def inventory(path):
    files, directories = set(), set()
    count = 0

    def walk(folder, prefix):
        nonlocal count
        fd = directory_fd(folder)
        try:
            with os.scandir(fd) as entries:
                for e in entries:
                    count += 1
                    if count > MAX_FILES * 8:
                        raise Rejected("staged_inventory_limit")
                    name = prefix + e.name
                    info = e.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        directories.add(name)
                        walk(folder / e.name, name + "/")
                    elif stat.S_ISREG(info.st_mode):
                        files.add(name)
                    else:
                        raise Rejected("staged_special_or_link")
        finally:
            os.close(fd)
    walk(path, "")
    return files, directories


def verify_bundle(destination, expected_sha):
    destination = absolute(str(destination))
    try:
        raw, _ = read_regular(destination / "manifest.json", MAX_MANIFEST, 0o444)
        d = parse_manifest(raw, expected_sha)
        expected_files = {e["destination"] for e in d["files"]} | {"manifest.json", "receipt.json"}
        expected_dirs = {str(p) for n in expected_files for p in PurePosixPath(n).parents if str(p) != "."}
        files, dirs = inventory(destination)
        if files != expected_files or dirs != expected_dirs:
            raise Rejected("staged_inventory_drift")
        identities = set()
        for e in d["files"]:
            b, identity = read_regular(destination / e["destination"], e["bytes"], e["mode"])
            if len(b) != e["bytes"] or digest(b) != e["sha256"] or identity in identities:
                raise Rejected("staged_pin_or_inode_drift")
            identities.add(identity)
        receipt, _ = read_regular(destination / "receipt.json", MAX_MANIFEST, 0o444)
        if receipt != json_bytes(receipt_for(d, expected_sha)):
            raise Rejected("receipt_drift")
        return {"verified_files": len(d["files"]), "execution_authorized": False,
                "dynamic_closure": "UNPROVEN", "immutable_against_owner": False}
    except OSError as exc:
        raise Rejected("verification_filesystem_rejected") from exc
