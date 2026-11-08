"""Pure supplied-observation validator, not a bootstrap or runtime attestation.

Expected contracts and review pins must be obtained independently by a future
reviewed caller. This module never captures observations or verifies on-disk
origins, loaded mappings, provenance, closure, or execution permission.
"""
import json
import re
from pathlib import PurePosixPath

SHA = re.compile(r"[0-9a-f]{64}")
PART = re.compile(r"[A-Za-z0-9_+.,@=-]+")
MODULES = {"encodings", "encodings.utf_8", "psycopg", "psycopg.pq",
           "psycopg_binary", "psycopg_binary.pq", "typing_extensions"}
VERSIONS = {"psycopg": "3.3.8", "psycopg_binary": "3.3.8", "typing_extensions": "4.16.0"}
FIELDS = {
    "schema", "source_sha256", "bundle_manifest_sha256", "bundle_root",
    "python_version", "implementation", "soabi", "architecture", "package_versions",
    "pq_impl", "flags", "executable", "prefix", "base_prefix", "sys_path", "modules",
    "native_libraries", "encodings_loaded_before_bootstrap", "dynamic_closure_review_sha256",
    "provenance_acceptance_sha256", "socket_attempts", "db_attempts",
}


class Rejected(ValueError):
    """Fixed source-contract rejection code."""


def canonical(value):
    def json_types(item, depth=0):
        if depth > 20:
            raise Rejected("contract_depth")
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                raise Rejected("contract_key_type")
            for child in item.values():
                json_types(child, depth + 1)
        elif type(item) is list:
            for child in item:
                json_types(child, depth + 1)
        elif type(item) not in {str, int, float, bool, type(None)}:
            raise Rejected("contract_type")
    json_types(value)
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError, RecursionError) as exc:
        raise Rejected("not_json_contract") from exc


def path(value):
    if type(value) is not str or not value.startswith("/") or len(value) > 500:
        raise Rejected("path_shape")
    parts = value[1:].split("/")
    if any(not PART.fullmatch(p) or p in {".", "..", "__pycache__", "sitecustomize.py",
                                         "usercustomize.py", ".env"}
           or p.endswith((".pth", ".pyc", ".pyo"))
           or p.split(".", 1)[0] in {"sitecustomize", "usercustomize"} for p in parts):
        raise Rejected("path_component")
    return PurePosixPath(value)


def inside(value, root):
    p = path(value)
    if p == root or not p.is_relative_to(root):
        raise Rejected("outside_bundle")
    return p


def validate_expected(d):
    if type(d) is not dict or set(d) != FIELDS:
        raise Rejected("expected_schema")
    if type(d["schema"]) is not int or d["schema"] != 1:
        raise Rejected("expected_version")
    for key in ("source_sha256", "bundle_manifest_sha256", "dynamic_closure_review_sha256",
                "provenance_acceptance_sha256"):
        if type(d[key]) is not str or not SHA.fullmatch(d[key]):
            raise Rejected("missing_review_pin")
    required = {"python_version": "3.12.3", "implementation": "cpython",
                "soabi": "cpython-312-x86_64-linux-gnu", "architecture": "x86_64",
                "pq_impl": "binary"}
    if any(type(d[k]) is not str or d[k] != v for k, v in required.items()):
        raise Rejected("runtime_contract")
    if canonical(d["package_versions"]) != canonical(VERSIONS):
        raise Rejected("package_contract")
    if canonical(d["flags"]) != canonical({"isolated": 1, "no_site": 1, "dont_write_bytecode": 1}):
        raise Rejected("startup_flags")
    root = path(d["bundle_root"])
    if d["executable"] != str(root / "bin/python3.12"):
        raise Rejected("executable_origin")
    if d["prefix"] != str(root) or d["base_prefix"] != str(root):
        raise Rejected("prefix_origin")
    required_paths = [str(root / "lib/python3.12"), str(root / "lib/python3.12/lib-dynload"),
                      str(root / "packages")]
    if type(d["sys_path"]) is not list or d["sys_path"] != required_paths:
        raise Rejected("getpath_contract")
    modules = d["modules"]
    if type(modules) is not list or len(modules) != len(MODULES):
        raise Rejected("module_inventory")
    names = set()
    origins = set()
    for item in modules:
        if type(item) is not dict or set(item) != {"name", "origin"}:
            raise Rejected("module_schema")
        if type(item["name"]) is not str or item["name"] not in MODULES or item["name"] in names:
            raise Rejected("module_name")
        origin = inside(item["origin"], root)
        if str(origin) in origins:
            raise Rejected("module_alias")
        names.add(item["name"])
        origins.add(str(origin))
    libraries = d["native_libraries"]
    if type(libraries) is not list or not 2 <= len(libraries) <= 256:
        raise Rejected("library_inventory")
    seen = set()
    for library in libraries:
        origin = str(inside(library, root))
        if origin in seen:
            raise Rejected("duplicate_library")
        seen.add(origin)
    if not {str(root / "lib/ld-linux-x86-64.so.2"), str(root / "lib/libc.so.6")} <= seen:
        raise Rejected("loader_libc_missing")
    if d["encodings_loaded_before_bootstrap"] is not True:
        raise Rejected("encodings_getpath_unproven")
    for name in ("socket_attempts", "db_attempts"):
        if type(d[name]) is not int or d[name] != 0:
            raise Rejected("connection_claim")


def validate_observation(observation, expected):
    validate_expected(expected)
    if type(observation) is not dict or canonical(observation) != canonical(expected):
        raise Rejected("observation_drift")
    return {"status": "SUPPLIED_OBSERVATION_MATCHES_NOT_RUNTIME_PROOF",
            "execution_authorized": False, "source_sha256": expected["source_sha256"],
            "bundle_manifest_sha256": expected["bundle_manifest_sha256"]}


def require_runtime_release(release, expected_source_sha):
    # No stage-B record, truthy approval, or successful synthetic test can release execution.
    raise Rejected("stage_b_has_no_execution_authority")
