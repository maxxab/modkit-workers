"""Pure supplied-data checks, never rootfs construction or runtime authority.

Expected pins and observation records are external trust inputs. This module does
not inspect files, authenticate review evidence, capture runtime events, verify
publisher identity, or establish empirical closure. It has no operational adapter.

Provider lookup is a conservative direct-directory model, not a glibc emulator:
inherited RPATH, loader caches, hardware-capability variants and ambient search
paths are excluded. Ever-loaded dependency coverage does not prove temporal
co-residency, initialization order, real loader behavior, or trace completeness.
"""
import hashlib
import json
import posixpath
import re
from pathlib import PurePosixPath

MAX_RAW = 2 * 1024 * 1024
MAX_FILES = 2048
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
SHA = re.compile(r"[0-9a-f]{64}")
PART = re.compile(r"[A-Za-z0-9_+.,@=-]+")
MODULE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
ATTEMPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
REVIEWS = {"cpu_isa", "kernel", "abi", "provenance", "dynamic_facilities", "observer", "security", "sbom_licenses"}
RUNTIME = {"python": "3.12.3", "implementation": "cpython", "architecture": "x86_64",
           "elf_class": "ELF64", "soabi": "cpython-312-x86_64-linux-gnu"}
PACKAGES = {"psycopg": "3.3.8", "psycopg_binary": "3.3.8", "typing_extensions": "4.16.0"}
EXE = "/usr/bin/python3.12"
LOADER = "/lib64/ld-linux-x86-64.so.2"
OBSERVER = "/opt/w01/observer/observe.py"
ZIP = "/usr/lib/python312.zip"
SYS_PATH = [ZIP, "/usr/lib/python3.12", "/usr/lib/python3.12/lib-dynload", "/opt/w01/packages"]
MODULE_PATHS = {
    "encodings": "/usr/lib/python3.12/encodings/__init__.py",
    "encodings.utf_8": "/usr/lib/python3.12/encodings/utf_8.py",
    "psycopg": "/opt/w01/packages/psycopg/__init__.py",
    "psycopg.pq": "/opt/w01/packages/psycopg/pq/__init__.py",
    "psycopg_binary": "/opt/w01/packages/psycopg_binary/__init__.py",
    "psycopg_binary.pq": "/opt/w01/packages/psycopg_binary/pq.cpython-312-x86_64-linux-gnu.so",
    "psycopg_binary._psycopg": "/opt/w01/packages/psycopg_binary/_psycopg.cpython-312-x86_64-linux-gnu.so",
    "typing_extensions": "/opt/w01/packages/typing_extensions.py",
}
ROOTS = ("/usr/lib/python3.12", "/lib/x86_64-linux-gnu", "/usr/lib/x86_64-linux-gnu",
         "/opt/w01/packages", "/opt/w01/observer", "/opt/w01/config")
ELF_KINDS = {"interpreter", "loader", "elf"}
SEARCH_DIRS = {"/lib/x86_64-linux-gnu", "/usr/lib/x86_64-linux-gnu", "/lib64"}


class Rejected(ValueError):
    """A fixed rejection code; it never grants execution scope."""


def require(condition, code):
    if not condition:
        raise Rejected(code)


def keys(value, expected):
    require(type(value) is dict and set(value) == set(expected), "schema")


def canonical(value):
    count = 0

    def visit(item, depth=0):
        nonlocal count
        count += 1
        require(count <= 100000 and depth <= 20, "json_bounds")
        if type(item) is dict:
            require(all(type(k) is str for k in item), "json_key_type")
            for child in item.values():
                visit(child, depth + 1)
        elif type(item) is list:
            for child in item:
                visit(child, depth + 1)
        elif type(item) is str:
            require(len(item) <= 8192, "json_string_bound")
        elif type(item) is int:
            require(-(2**63) <= item < 2**63, "json_integer_bound")
        else:
            require(item is None or type(item) is bool, "json_type")
    visit(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def hashed(value):
    require(type(value) is str and SHA.fullmatch(value) is not None, "sha256")


def integer(value, lower, upper):
    require(type(value) is int and lower <= value <= upper, "integer")


def name(value):
    require(type(value) is str and 0 < len(value) <= 200
            and PART.fullmatch(value) is not None and value not in {".", ".."}, "name")


def names(values, maximum=128):
    require(type(values) is list and len(values) <= maximum, "name_list")
    for value in values:
        name(value)
    require(len(set(values)) == len(values), "duplicate_name")


def path(value, root_allowed=False):
    require(type(value) is str and value.startswith("/") and len(value) <= 400, "absolute_path")
    if value == "/" and root_allowed:
        return value
    for part in value[1:].split("/"):
        name(part)
        require(part not in {"__pycache__", ".env", ".ssh", "id_rsa", "id_ed25519"}
                and not part.endswith((".pth", ".pyc", ".pyo"))
                and part.split(".", 1)[0] not in {"sitecustomize", "usercustomize"}, "forbidden_path")
    return value


def member_path(value):
    path(value)
    require(value in {EXE, LOADER} or any(value.startswith(root + "/") for root in ROOTS), "member_namespace")


def user(value):
    keys(value, {"uid", "gid"})
    integer(value["uid"], 1, 2**31 - 1)
    integer(value["gid"], 1, 2**31 - 1)


def parse_inventory(raw, expected_sha256):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_RAW, "raw_bound")
    hashed(expected_sha256)
    require(hashlib.sha256(raw).hexdigest() == expected_sha256, "inventory_pin")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    def constant(_):
        raise Rejected("nonfinite_json")
    try:
        inv = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, TypeError, UnicodeError, RecursionError) as exc:
        raise Rejected("invalid_json") from exc
    canonical(inv)
    keys(inv, {"schema", "status", "execution_authorized", "workload", "runtime",
               "package_versions", "runtime_user", "reviews", "directories", "files"})
    require(type(inv["schema"]) is int and inv["schema"] == 2
            and inv["status"] == "SOURCE_ONLY" and inv["execution_authorized"] is False
            and inv["workload"] == "NO_DB_IMPORT", "source_scope")
    require(canonical(inv["runtime"]) == canonical(RUNTIME), "runtime")
    require(canonical(inv["package_versions"]) == canonical(PACKAGES), "packages")
    user(inv["runtime_user"])
    keys(inv["reviews"], REVIEWS)
    for value in inv["reviews"].values():
        if value is not None:
            hashed(value)
    files = inv["files"]
    require(type(files) is list and 1 <= len(files) <= MAX_FILES, "file_count")
    members, sources, providers = {}, set(), {}
    total = 0
    for item in files:
        keys(item, {"path", "source_id", "bytes", "sha256", "mode", "kind", "uid", "gid",
                    "nlink", "xattrs", "capabilities", "elf"})
        member_path(item["path"])
        hashed(item["source_id"])
        hashed(item["sha256"])
        require(item["path"] not in members and item["source_id"] not in sources, "file_alias")
        members[item["path"]] = item
        sources.add(item["source_id"])
        integer(item["bytes"], 0, MAX_FILE)
        total += item["bytes"]
        require(total <= MAX_TOTAL, "total_size")
        require(type(item["kind"]) is str and item["kind"] in ELF_KINDS | {"python", "data", "metadata"}, "kind")
        require(type(item["mode"]) is int and item["mode"] in {0o444, 0o555}, "file_mode")
        if item["kind"] in {"interpreter", "loader"}:
            require(item["mode"] == 0o555, "executable_mode")
        elif item["kind"] != "elf":
            require(item["mode"] == 0o444, "non_elf_executable")
        require(type(item["uid"]) is int and item["uid"] == 0 and type(item["gid"]) is int and item["gid"] == 0, "artifact_owner")
        require(type(item["nlink"]) is int and item["nlink"] == 1
                and type(item["xattrs"]) is dict and not item["xattrs"]
                and type(item["capabilities"]) is list and not item["capabilities"], "privilege_or_link_metadata")
        elf = item["elf"]
        if item["kind"] not in ELF_KINDS:
            require(elf is None, "unexpected_elf")
            continue
        keys(elf, {"class", "machine", "interp", "soname", "needed", "versions_required",
                   "versions_provided", "rpath", "runpath"})
        require(elf["class"] == "ELF64" and elf["machine"] == "x86_64", "elf_architecture")
        require(elf["interp"] is None or elf["interp"] == LOADER, "elf_interpreter")
        if item["kind"] == "interpreter":
            require(item["path"] == EXE and elf["interp"] == LOADER and elf["soname"] is None, "interpreter_layout")
        if item["kind"] == "loader":
            require(item["path"] == LOADER, "loader_layout")
        names(elf["needed"])
        names(elf["versions_provided"], 1024)
        require(type(elf["versions_required"]) is dict, "symbol_requirements")
        for provider, versions in elf["versions_required"].items():
            name(provider)
            require(provider in elf["needed"], "symbol_provider_not_needed")
            names(versions, 1024)
        if elf["soname"] is not None:
            name(elf["soname"])
            require(elf["soname"] not in providers, "ambiguous_provider")
            providers[elf["soname"]] = item
        for field in ("rpath", "runpath"):
            require(type(elf[field]) is list and len(elf[field]) <= 8, "search_path")
            require(all(type(p) is str and p in {"$ORIGIN", "$ORIGIN/../psycopg_binary.libs"} for p in elf[field]), "unsafe_search_path")
            require(len(set(elf[field])) == len(elf[field]), "duplicate_search_path")
        require(not (elf["rpath"] and elf["runpath"]), "ambiguous_search_path")
    require(members.get(EXE, {}).get("kind") == "interpreter"
            and members.get(LOADER, {}).get("kind") == "loader", "missing_interpreter_loader")
    required = set(MODULE_PATHS.values()) | {"/usr/lib/python3.12/os.py"}
    require(required <= set(members), "missing_startup_or_package_member")
    for required_path in required:
        expected_kind = "elf" if required_path.endswith(".so") else "python"
        require(members[required_path]["kind"] == expected_kind, "required_member_kind")
    for filename in members:
        require(not any(str(p) in members for p in PurePosixPath(filename).parents), "file_prefix_collision")
    directories = inv["directories"]
    require(type(directories) is list and len(directories) <= 8192, "directory_count")
    seen = set()
    for directory in directories:
        keys(directory, {"path", "mode", "uid", "gid"})
        p = path(directory["path"], root_allowed=True)
        require(p not in seen, "duplicate_directory")
        seen.add(p)
        require(type(directory["mode"]) is int and directory["mode"] == 0o555
                and type(directory["uid"]) is int and directory["uid"] == 0
                and type(directory["gid"]) is int and directory["gid"] == 0, "writable_or_unowned_directory")
    expected_dirs = {str(p) for f in members for p in PurePosixPath(f).parents}
    require(seen == expected_dirs and "/usr/lib/python3.12/lib-dynload" in seen, "directory_inventory")
    for item in files:
        elf = item["elf"]
        if elf is None:
            continue
        require(all(n in providers for n in elf["needed"]), "missing_provider")
        for provider, required_versions in elf["versions_required"].items():
            require(set(required_versions) <= set(providers[provider]["elf"]["versions_provided"]), "symbol_version_missing")
        search_dirs = set(SEARCH_DIRS)
        for relative in elf["rpath"] + elf["runpath"]:
            resolved = posixpath.normpath(relative.replace("$ORIGIN", str(PurePosixPath(item["path"]).parent)))
            require(resolved in seen, "search_directory_missing")
            search_dirs.add(resolved)
        for soname in elf["needed"]:
            provider_path = PurePosixPath(providers[soname]["path"])
            require(provider_path.name == soname and str(provider_path.parent) in search_dirs,
                    "provider_not_directly_reachable")
            candidates = {str(PurePosixPath(directory) / soname) for directory in search_dirs
                          if str(PurePosixPath(directory) / soname) in members}
            require(candidates == {str(provider_path)}, "competing_search_candidate")
    return inv


def file_binding(record, members, kinds=None):
    keys(record, {"path", "sha256"})
    require(type(record["path"]) is str and record["path"] in members, "origin_missing")
    item = members[record["path"]]
    hashed(record["sha256"])
    require(record["sha256"] == item["sha256"], "origin_hash")
    if kinds is not None:
        require(item["kind"] in kinds, "origin_kind")
    return item


def validate_expected(expected, inv, inventory_sha):
    canonical(expected)
    keys(expected, {"schema", "inventory_sha256", "source_sha256", "attempt_id", "identity", "excluded_cids",
                    "runtime", "package_versions", "pq_impl", "executable", "prefix", "base_prefix", "flags",
                    "sys_path", "absent_paths", "encodings_before_bootstrap", "modules", "native_libraries",
                    "trace", "security"})
    require(type(expected["schema"]) is int and expected["schema"] == 2, "observation_schema")
    require(expected["inventory_sha256"] == inventory_sha, "observation_inventory_pin")
    hashed(expected["source_sha256"])
    require(type(expected["attempt_id"]) is str and ATTEMPT.fullmatch(expected["attempt_id"]) is not None, "attempt")
    keys(expected["identity"], {"cid", "image"})
    hashed(expected["identity"]["cid"])
    image = expected["identity"]["image"]
    require(type(image) is str and image.startswith("sha256:"), "image_identity")
    hashed(image[7:])
    excluded = expected["excluded_cids"]
    require(type(excluded) is list and 1 <= len(excluded) <= 32, "exclusion_scope")
    for cid in excluded:
        hashed(cid)
    require(len(set(excluded)) == len(excluded) and expected["identity"]["cid"] not in excluded, "excluded_target")
    for key, value in (("runtime", RUNTIME), ("package_versions", PACKAGES),
                       ("flags", {"isolated": 1, "no_site": 1, "dont_write_bytecode": 1}),
                       ("sys_path", SYS_PATH), ("absent_paths", [ZIP])):
        require(canonical(expected[key]) == canonical(value), "startup_contract")
    require(expected["pq_impl"] == "binary" and expected["executable"] == EXE
            and expected["prefix"] == "/usr" and expected["base_prefix"] == "/usr"
            and expected["encodings_before_bootstrap"] is True, "startup_identity")
    require(all(value is not None for value in inv["reviews"].values()), "review_evidence_missing")
    members = {item["path"]: item for item in inv["files"]}
    require(ZIP not in members, "absent_landmark_present")
    modules = expected["modules"]
    require(type(modules) is list and len(MODULE_PATHS) <= len(modules) <= 1024, "module_inventory")
    names_seen, file_modules = set(), set()
    embedded = False
    native_roots = {EXE, LOADER}
    for item in modules:
        keys(item, {"name", "kind", "path", "sha256"})
        n = item["name"]
        require(type(n) is str and MODULE.fullmatch(n) is not None and n not in names_seen
                and not {"sitecustomize", "usercustomize"} & set(n.split(".")), "module_name")
        names_seen.add(n)
        binding = {"path": item["path"], "sha256": item["sha256"]}
        require(type(item["kind"]) is str, "module_kind")
        if item["kind"] == "file":
            member = file_binding(binding, members, {"python", "elf"})
            require(item["path"] not in file_modules, "module_alias")
            file_modules.add(item["path"])
            if member["elf"] is not None:
                native_roots.add(item["path"])
        else:
            require(item["kind"] in {"builtin", "frozen"} and item["path"] == EXE, "embedded_origin")
            file_binding(binding, members, {"interpreter"})
            embedded = True
        if n in MODULE_PATHS:
            require(item["kind"] == "file" and item["path"] == MODULE_PATHS[n], "required_module_origin")
    require(set(MODULE_PATHS) <= names_seen, "required_module_missing")
    libraries = expected["native_libraries"]
    require(type(libraries) is list and 1 <= len(libraries) <= MAX_FILES, "native_inventory")
    native_paths = set()
    for item in libraries:
        file_binding(item, members, ELF_KINDS)
        require(item["path"] not in native_paths, "native_alias")
        native_paths.add(item["path"])
    require(native_roots <= native_paths, "native_root_missing")
    providers = {e["elf"]["soname"]: e["path"] for e in inv["files"] if e["elf"] and e["elf"]["soname"]}
    for p in native_paths:
        require(all(providers[n] in native_paths for n in members[p]["elf"]["needed"]), "loaded_dependency_missing")
    trace = expected["trace"]
    keys(trace, {"observer_path", "observer_sha256", "review_sha256", "complete", "lost_events", "descendants", "events"})
    require(trace["observer_path"] == OBSERVER, "observer_origin")
    file_binding({"path": trace["observer_path"], "sha256": trace["observer_sha256"]}, members, {"python"})
    require(trace["review_sha256"] == inv["reviews"]["observer"] and trace["complete"] is True
            and type(trace["lost_events"]) is int and trace["lost_events"] == 0
            and type(trace["descendants"]) is list and not trace["descendants"], "incomplete_trace")
    events = trace["events"]
    require(type(events) is list and 1 <= len(events) <= 8192, "event_count")
    loaded, imported, ever_loaded = set(), set(), set()
    embedded_event = False
    for seq, event in enumerate(events, 1):
        keys(event, {"seq", "kind", "path", "sha256"})
        require(type(event["seq"]) is int and event["seq"] == seq, "event_order")
        kind = event["kind"]
        require(type(kind) is str and kind in {"native_load", "native_unload", "module_import", "embedded_import", "data_read", "missing_probe"}, "event_kind")
        p = event["path"]
        if kind == "missing_probe":
            require(p in expected["absent_paths"] and event["sha256"] is None, "missing_probe_origin")
            continue
        member = file_binding({"path": p, "sha256": event["sha256"]}, members)
        if kind == "native_load":
            require(member["elf"] is not None and p not in loaded, "duplicate_or_non_native_load")
            loaded.add(p)
            ever_loaded.add(p)
        elif kind == "native_unload":
            require(p in loaded, "unobserved_load")
            loaded.remove(p)
        elif kind == "module_import":
            require(p in file_modules, "unexpected_module_event")
            imported.add(p)
        elif kind == "embedded_import":
            require(p == EXE and embedded, "unexpected_embedded_event")
            embedded_event = True
        else:
            require(member["kind"] in {"data", "metadata"}, "unexpected_data_read")
    for loaded_path in ever_loaded:
        require(all(providers[n] in ever_loaded for n in members[loaded_path]["elf"]["needed"]),
                "transient_dependency_evidence_missing")
    require(loaded == native_paths and file_modules <= imported
            and (not embedded or embedded_event), "trace_inventory_mismatch")
    security = {"runtime_user": inv["runtime_user"], "rootfs_read_only": True,
                "unexpected_mounts": [], "inherited_fds": [0, 1, 2], "writable_search_parents": [],
                "unexpected_executable_mappings": [], "socket_syscalls": 0, "db_calls": 0}
    require(canonical(expected["security"]) == canonical(security), "security_contract")


def validate_observation(observed, expected, raw, expected_sha256):
    inv = parse_inventory(raw, expected_sha256)
    validate_expected(expected, inv, expected_sha256)
    require(canonical(observed) == canonical(expected), "observation_drift")
    return {"status": "SUPPLIED_ROOTFS_CONTRACT_MATCHES_NOT_RUNTIME_PROOF",
            "execution_authorized": False, "provenance_verified": False,
            "dynamic_closure_verified": False, "inventory_sha256": expected_sha256}


def require_execution_release(record):
    raise Rejected("source_only_has_no_execution_authority")
