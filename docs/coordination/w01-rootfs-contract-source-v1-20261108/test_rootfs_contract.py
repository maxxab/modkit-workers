"""Synthetic dictionaries only. No rootfs, artifact or native execution."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath

import pytest

HERE = Path(__file__).parent
REVIEWS = ("cpu_isa", "kernel", "abi", "provenance", "dynamic_facilities", "observer", "security", "sbom_licenses")
RUNTIME = {"python": "3.12.3", "implementation": "cpython", "architecture": "x86_64",
           "elf_class": "ELF64", "soabi": "cpython-312-x86_64-linux-gnu"}
PACKAGES = {"psycopg": "3.3.8", "psycopg_binary": "3.3.8", "typing_extensions": "4.16.0"}
EXE = "/usr/bin/python3.12"
LOADER = "/lib64/ld-linux-x86-64.so.2"
LIBC = "/lib/x86_64-linux-gnu/libc.so.6"
OBSERVER = "/opt/w01/observer/observe.py"
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


def module():
    p = HERE / "rootfs_contract.py"
    assert p.is_file(), "Successor rootfs contract implementation is missing"
    spec = importlib.util.spec_from_file_location("w01_rootfs_contract", p)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def sha(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    raw = (json.dumps(value, sort_keys=True, allow_nan=False) + "\n").encode()
    return raw, sha(raw)


def file(path, kind="python", soname=None):
    data = ("synthetic:" + path).encode()
    elf = None
    if kind in {"interpreter", "loader", "elf"}:
        elf = {"class": "ELF64", "machine": "x86_64", "interp": LOADER if kind == "interpreter" else None,
               "soname": soname, "needed": [], "versions_required": {},
               "versions_provided": [], "rpath": [], "runpath": []}
    return {"path": path, "source_id": sha(("source:" + path).encode()), "bytes": len(data),
            "sha256": sha(data), "mode": 0o555 if kind in {"interpreter", "loader"} else 0o444,
            "kind": kind, "uid": 0, "gid": 0, "nlink": 1, "xattrs": {}, "capabilities": [], "elf": elf}


def fixture():
    files = [file(EXE, "interpreter"), file(LOADER, "loader", "ld-linux-x86-64.so.2"),
             file(LIBC, "elf", "libc.so.6"), file("/usr/lib/python3.12/os.py"),
             file("/usr/lib/python3.12/lib-dynload/_contextvars.so", "elf"), file(OBSERVER)]
    files.extend(file(p, "elf" if p.endswith(".so") else "python") for p in MODULE_PATHS.values())
    for entry in files:
        if entry["elf"] and entry["path"] not in {LOADER, LIBC}:
            entry["elf"]["needed"] = ["libc.so.6"]
            entry["elf"]["versions_required"] = {"libc.so.6": ["GLIBC_2.2.5"]}
    files[2]["elf"]["needed"] = ["ld-linux-x86-64.so.2"]
    files[2]["elf"]["versions_provided"] = ["GLIBC_2.2.5"]
    parents = {str(p) for e in files for p in PurePosixPath(e["path"]).parents}
    return {"schema": 2, "status": "SOURCE_ONLY", "execution_authorized": False,
            "workload": "NO_DB_IMPORT", "runtime": dict(RUNTIME), "package_versions": dict(PACKAGES),
            "runtime_user": {"uid": 10001, "gid": 10001},
            "reviews": {name: "a" * 64 for name in REVIEWS},
            "directories": [{"path": p, "mode": 0o555, "uid": 0, "gid": 0} for p in sorted(parents)],
            "files": files}


def observation(inv, inventory_sha):
    files = {e["path"]: e for e in inv["files"]}
    modules = [{"name": name, "kind": "file", "path": p, "sha256": files[p]["sha256"]}
               for name, p in MODULE_PATHS.items()]
    libs = [{"path": e["path"], "sha256": e["sha256"]} for e in inv["files"] if e["elf"]]
    events = [{"seq": i + 1, "kind": "native_load", **e} for i, e in enumerate(libs)]
    events.extend({"seq": len(events) + i + 1, "kind": "module_import",
                   "path": e["path"], "sha256": e["sha256"]} for i, e in enumerate(modules))
    # Re-enumerate once: generator extension must not make seq depend on mutation.
    for i, e in enumerate(events):
        e["seq"] = i + 1
    return {"schema": 2, "inventory_sha256": inventory_sha, "source_sha256": "b" * 64,
            "attempt_id": "synthetic-one", "identity": {"cid": "c" * 64, "image": "sha256:" + "d" * 64},
            "excluded_cids": ["e" * 64], "runtime": dict(RUNTIME), "package_versions": dict(PACKAGES),
            "pq_impl": "binary", "executable": EXE, "prefix": "/usr", "base_prefix": "/usr",
            "flags": {"isolated": 1, "no_site": 1, "dont_write_bytecode": 1},
            "sys_path": ["/usr/lib/python312.zip", "/usr/lib/python3.12", "/usr/lib/python3.12/lib-dynload", "/opt/w01/packages"],
            "absent_paths": ["/usr/lib/python312.zip"], "encodings_before_bootstrap": True,
            "modules": modules, "native_libraries": libs,
            "trace": {"observer_path": OBSERVER, "observer_sha256": files[OBSERVER]["sha256"],
                      "review_sha256": inv["reviews"]["observer"], "complete": True, "lost_events": 0,
                      "descendants": [], "events": events},
            "security": {"runtime_user": dict(inv["runtime_user"]), "rootfs_read_only": True,
                         "unexpected_mounts": [], "inherited_fds": [0, 1, 2],
                         "writable_search_parents": [], "unexpected_executable_mappings": [],
                         "socket_syscalls": 0, "db_calls": 0}}


def test_valid_inventory_is_only_source_data():
    m = module()
    inv = fixture()
    raw, pin = encode(inv)
    assert m.parse_inventory(raw, pin) == inv


def test_pending_reviews_are_inventory_not_qualification():
    m = module()
    inv = fixture()
    inv["reviews"] = {k: None for k in REVIEWS}
    raw, pin = encode(inv)
    assert m.parse_inventory(raw, pin)["reviews"]["provenance"] is None
    observed = observation(inv, pin)
    with pytest.raises(m.Rejected):
        m.validate_observation(observed, copy.deepcopy(observed), raw, pin)


@pytest.mark.parametrize("change", [
    lambda x: x.update(schema=True), lambda x: x.update(extra=True),
    lambda x: x.update(execution_authorized=True), lambda x: x.update(status="QUALIFIED"),
    lambda x: x.update(workload="DB"), lambda x: x["runtime"].update(python="3.12.4"),
    lambda x: x["runtime"].update(architecture="aarch64"), lambda x: x["runtime"].update(soabi="cp311"),
    lambda x: x["package_versions"].update(psycopg="3.3.7"), lambda x: x["runtime_user"].update(uid=0),
    lambda x: x["runtime_user"].update(gid=True), lambda x: x["reviews"].pop("kernel"),
    lambda x: x["reviews"].update(provenance="trusted"),
    lambda x: x["files"][0].update(bytes=True), lambda x: x["files"][0].update(bytes=33554433),
    lambda x: x["files"][0].update(sha256="invalid"), lambda x: x["files"][0].update(mode=0o4755),
    lambda x: x["files"][0].update(mode=0o444), lambda x: x["files"][0].update(nlink=2),
    lambda x: x["files"][0].update(uid=10001), lambda x: x["files"][0].update(kind="device"),
    lambda x: x["files"][0].update(xattrs={"security.capability": "anything"}),
    lambda x: x["files"][0].update(capabilities=["CAP_SYS_ADMIN"]),
    lambda x: x["files"][0].update(source_id=x["files"][1]["source_id"]),
    lambda x: x["files"].append(copy.deepcopy(x["files"][0])),
    lambda x: x["directories"][0].update(mode=0o755),
    lambda x: x["directories"].pop(), lambda x: x["directories"].append({"path": "/extra", "mode": 0o555, "uid": 0, "gid": 0}),
    lambda x: x["files"][0]["elf"].update(interp="/host/loader"),
    lambda x: x["files"][0]["elf"].update(machine="aarch64"),
    lambda x: x["files"][0]["elf"].update(needed=["missing.so"]),
    lambda x: x["files"][0]["elf"].update(needed=["/lib/libc.so.6"]),
    lambda x: x["files"][0]["elf"].update(needed=[{}]),
    lambda x: x["files"][0]["elf"].update(versions_required={"libc.so.6": ["GLIBC_9.99"]}),
    lambda x: x["files"][1]["elf"].update(soname="libc.so.6"),
    lambda x: x["files"][0]["elf"].update(rpath=["/usr/lib"]),
    lambda x: x["files"][0]["elf"].update(rpath=["$ORIGIN/../../outside"]),
])
def test_inventory_schema_and_closure_mutations_reject(change):
    m = module()
    inv = fixture()
    change(inv)
    raw, pin = encode(inv)
    with pytest.raises(m.Rejected):
        m.parse_inventory(raw, pin)


@pytest.mark.parametrize("path", ["/usr/../bin/python", "/usr//bin/python", "/proc/self/root",
                                  "/home/user/secret", "/usr/lib/python3.12/sitecustomize/__init__.py",
                                  "/opt/w01/packages/usercustomize.so", "/opt/w01/packages/hook.pth",
                                  "/opt/w01/packages/__pycache__/x.pyc", "/opt/w01/packages/.env",
                                  "/opt/w01/packages/name\x7f", "relative", "/"])
def test_bad_inventory_paths_reject(path):
    m = module()
    inv = fixture()
    inv["files"][-1]["path"] = path
    raw, pin = encode(inv)
    with pytest.raises(m.Rejected):
        m.parse_inventory(raw, pin)


@pytest.mark.parametrize("raw", [b'{"schema":2,"schema":2}', b'{"schema":NaN}', b"[]", b"broken"])
def test_invalid_json_rejects(raw):
    m = module()
    with pytest.raises(m.Rejected):
        m.parse_inventory(raw, sha(raw))


def test_inventory_hash_is_required():
    m = module()
    raw, _ = encode(fixture())
    with pytest.raises(m.Rejected):
        m.parse_inventory(raw, "0" * 64)


def test_valid_observation_has_no_runtime_or_provenance_authority():
    m = module()
    raw, pin = encode(fixture())
    observed = observation(fixture(), pin)
    assert m.validate_observation(observed, copy.deepcopy(observed), raw, pin) == {
        "status": "SUPPLIED_ROOTFS_CONTRACT_MATCHES_NOT_RUNTIME_PROOF",
        "execution_authorized": False, "provenance_verified": False,
        "dynamic_closure_verified": False, "inventory_sha256": pin}


@pytest.mark.parametrize("field", list(observation(fixture(), "f" * 64)))
def test_missing_observation_field_rejects(field):
    m = module()
    inv = fixture()
    raw, pin = encode(inv)
    expected = observation(inv, pin)
    observed = copy.deepcopy(expected)
    del observed[field]
    with pytest.raises(m.Rejected):
        m.validate_observation(observed, expected, raw, pin)


@pytest.mark.parametrize("change", [
    lambda x: x.update(schema=True), lambda x: x.update(extra=True),
    lambda x: x.update(inventory_sha256="0" * 64), lambda x: x.update(source_sha256="no"),
    lambda x: x.update(attempt_id="../other"), lambda x: x["identity"].update(cid="e" * 64),
    lambda x: x["identity"].update(image="python:latest"), lambda x: x.update(excluded_cids=[]),
    lambda x: x["runtime"].update(python="3.13.0"), lambda x: x["package_versions"].update(psycopg="3.3.7"),
    lambda x: x.update(pq_impl="python"), lambda x: x.update(executable="/host/python"),
    lambda x: x.update(prefix="/host"), lambda x: x["flags"].update(isolated=True),
    lambda x: x["flags"].update(no_site=0), lambda x: x["sys_path"].append("/host/lib"),
    lambda x: x.update(sys_path=tuple(x["sys_path"])), lambda x: x.update(absent_paths=[]),
    lambda x: x.update(encodings_before_bootstrap=False), lambda x: x["modules"].pop(),
    lambda x: x["modules"].append(copy.deepcopy(x["modules"][0])),
    lambda x: x["modules"][0].update(path="/host/encodings.py"),
    lambda x: x["modules"][0].update(sha256="0" * 64),
    lambda x: x["modules"][0].update(kind="frozen", path=EXE),
    lambda x: x["native_libraries"].pop(),
    lambda x: x["native_libraries"].append({"path": "/host/lib.so", "sha256": "a" * 64}),
    lambda x: x["trace"].update(complete=False), lambda x: x["trace"].update(lost_events=1),
    lambda x: x["trace"].update(lost_events=False), lambda x: x["trace"].update(observer_sha256="0" * 64),
    lambda x: x["trace"].update(descendants=[123]), lambda x: x["trace"]["events"].pop(),
    lambda x: x["trace"]["events"][0].update(seq=2),
    lambda x: x["trace"]["events"][0].update(path="/host/lib.so"),
    lambda x: x["security"]["runtime_user"].update(uid=0),
    lambda x: x["security"].update(rootfs_read_only=False),
    lambda x: x["security"].update(unexpected_mounts=["/host"]),
    lambda x: x["security"].update(inherited_fds=[0, 1, 2, 3]),
    lambda x: x["security"].update(writable_search_parents=["/lib"]),
    lambda x: x["security"].update(unexpected_executable_mappings=["anonymous"]),
    lambda x: x["security"].update(socket_syscalls=1),
    lambda x: x["security"].update(db_calls=False),
])
def test_invalid_expected_cannot_approve_invalid_observation(change):
    m = module()
    inv = fixture()
    raw, pin = encode(inv)
    expected = observation(inv, pin)
    change(expected)
    with pytest.raises(m.Rejected):
        m.validate_observation(copy.deepcopy(expected), expected, raw, pin)


@pytest.mark.parametrize("review", REVIEWS)
def test_missing_review_pin_blocks_observation(review):
    m = module()
    inv = fixture()
    inv["reviews"][review] = None
    raw, pin = encode(inv)
    observed = observation(inv, pin)
    with pytest.raises(m.Rejected):
        m.validate_observation(observed, copy.deepcopy(observed), raw, pin)


def test_no_source_record_releases_execution():
    m = module()
    for record in (None, {}, {"approved": True, "sha256": "a" * 64}):
        with pytest.raises(m.Rejected, match="source_only_has_no_execution_authority"):
            m.require_execution_release(record)


def rebuild_directories(inv):
    parents = {str(p) for e in inv["files"] for p in PurePosixPath(e["path"]).parents}
    inv["directories"] = [{"path": p, "mode": 0o555, "uid": 0, "gid": 0} for p in sorted(parents)]


@pytest.mark.parametrize("destination", ["/opt/w01/config/libc.so.6", "/lib/x86_64-linux-gnu/wrong-basename.so"])
def test_provider_must_be_reachable_by_approved_search_and_basename(destination):
    m = module()
    inv = fixture()
    inv["files"][2]["path"] = destination
    rebuild_directories(inv)
    raw, pin = encode(inv)
    with pytest.raises(m.Rejected):
        m.parse_inventory(raw, pin)


@pytest.mark.parametrize("name", ["psycopg_binary.pq", "psycopg_binary._psycopg"])
def test_required_binary_module_cannot_be_disguised_as_python(name):
    m = module()
    inv = fixture()
    entry = next(e for e in inv["files"] if e["path"] == MODULE_PATHS[name])
    entry.update(kind="python", elf=None)
    raw, pin = encode(inv)
    with pytest.raises(m.Rejected):
        m.parse_inventory(raw, pin)


@pytest.mark.parametrize("kind", [[], {}])
def test_unhashable_module_kind_rejected_uniformly(kind):
    m = module()
    inv = fixture()
    raw, pin = encode(inv)
    observed = observation(inv, pin)
    observed["modules"][0]["kind"] = kind
    with pytest.raises(m.Rejected):
        m.validate_observation(observed, copy.deepcopy(observed), raw, pin)


def transient_fixture(include_dependency_event):
    inv = fixture()
    dependency = file("/lib/x86_64-linux-gnu/libtransientdep.so", "elf", "libtransientdep.so")
    temporary = file("/lib/x86_64-linux-gnu/libtransient.so", "elf", "libtransient.so")
    temporary["elf"]["needed"] = ["libtransientdep.so"]
    inv["files"].extend([dependency, temporary])
    rebuild_directories(inv)
    raw, pin = encode(inv)
    observed = observation(inv, pin)
    transient_paths = {dependency["path"], temporary["path"]}
    observed["native_libraries"] = [e for e in observed["native_libraries"] if e["path"] not in transient_paths]
    observed["trace"]["events"] = [e for e in observed["trace"]["events"] if e["path"] not in transient_paths]
    sequence = [(dependency, "native_load")] if include_dependency_event else []
    sequence += [(temporary, "native_load"), (temporary, "native_unload")]
    if include_dependency_event:
        sequence += [(dependency, "native_unload")]
    observed["trace"]["events"].extend(
        {"seq": 0, "kind": operation, "path": entry["path"], "sha256": entry["sha256"]}
        for entry, operation in sequence
    )
    for seq, entry in enumerate(observed["trace"]["events"], 1):
        entry["seq"] = seq
    return raw, pin, observed


def test_transient_dependency_must_appear_in_complete_load_evidence():
    m = module()
    raw, pin, observed = transient_fixture(False)
    with pytest.raises(m.Rejected):
        m.validate_observation(observed, copy.deepcopy(observed), raw, pin)


def test_transient_load_and_unload_with_dependency_evidence_is_data_only():
    m = module()
    raw, pin, observed = transient_fixture(True)
    result = m.validate_observation(observed, copy.deepcopy(observed), raw, pin)
    assert result["dynamic_closure_verified"] is False


@pytest.mark.parametrize("change", [
    lambda x: x.update(source_sha256="f" * 64),
    lambda x: x.update(attempt_id="different-valid-attempt"),
    lambda x: x["identity"].update(image="sha256:" + "f" * 64),
    lambda x: x["identity"].update(cid="f" * 64),
])
def test_valid_but_different_identity_cannot_replace_trusted_expected(change):
    m = module()
    inv = fixture()
    raw, pin = encode(inv)
    expected = observation(inv, pin)
    observed = copy.deepcopy(expected)
    change(observed)
    with pytest.raises(m.Rejected):
        m.validate_observation(observed, expected, raw, pin)


def test_raw_manifest_bound_is_checked_before_parsing():
    m = module()
    raw = b" " * (2 * 1024 * 1024 + 1)
    with pytest.raises(m.Rejected):
        m.parse_inventory(raw, sha(raw))


def test_inventory_file_count_bound():
    m = module()
    inv = fixture()
    inv["files"] = [copy.deepcopy(inv["files"][0]) for _ in range(2049)]
    raw, pin = encode(inv)
    with pytest.raises(m.Rejected):
        m.parse_inventory(raw, pin)


def test_inventory_aggregate_byte_bound():
    m = module()
    inv = fixture()
    for entry in inv["files"][:5]:
        entry["bytes"] = 32 * 1024 * 1024
    raw, pin = encode(inv)
    with pytest.raises(m.Rejected):
        m.parse_inventory(raw, pin)


def test_approved_origin_search_can_resolve_vendor_provider():
    m = module()
    inv = fixture()
    provider = file("/opt/w01/packages/psycopg_binary.libs/libvendor.so", "elf", "libvendor.so")
    inv["files"].append(provider)
    consumer = next(e for e in inv["files"] if e["path"] == MODULE_PATHS["psycopg_binary.pq"])
    consumer["elf"]["needed"].append("libvendor.so")
    consumer["elf"]["rpath"] = ["$ORIGIN/../psycopg_binary.libs"]
    rebuild_directories(inv)
    raw, pin = encode(inv)
    assert m.parse_inventory(raw, pin)["execution_authorized"] is False


def test_embedded_module_is_bound_to_the_pinned_interpreter():
    m = module()
    inv = fixture()
    raw, pin = encode(inv)
    observed = observation(inv, pin)
    interpreter_sha = next(e["sha256"] for e in inv["files"] if e["path"] == EXE)
    observed["modules"].append({"name": "sys", "kind": "builtin", "path": EXE, "sha256": interpreter_sha})
    observed["trace"]["events"].append({"seq": len(observed["trace"]["events"]) + 1,
                                       "kind": "embedded_import", "path": EXE, "sha256": interpreter_sha})
    assert m.validate_observation(observed, copy.deepcopy(observed), raw, pin)["execution_authorized"] is False


@pytest.mark.parametrize("kind", ["elf", "data"])
def test_search_directory_shadow_cannot_bypass_unique_soname(kind):
    m = module()
    inv = fixture()
    inv["files"].append(file("/usr/lib/x86_64-linux-gnu/libc.so.6", kind))
    rebuild_directories(inv)
    raw, pin = encode(inv)
    with pytest.raises(m.Rejected):
        m.parse_inventory(raw, pin)
