"""Pure observation-contract tests. No native runtime or DB import."""
import copy
import importlib.util
from pathlib import Path

import pytest

HERE = Path(__file__).parent


def module():
    path = HERE / "native_bootstrap.py"
    assert path.is_file(), "Stage B bootstrap validator is missing"
    spec = importlib.util.spec_from_file_location("stageb_bootstrap", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def expected():
    root = "/synthetic/w01-runtime"
    return {
        "schema": 1,
        "source_sha256": "a" * 64,
        "bundle_manifest_sha256": "b" * 64,
        "bundle_root": root,
        "python_version": "3.12.3",
        "implementation": "cpython",
        "soabi": "cpython-312-x86_64-linux-gnu",
        "architecture": "x86_64",
        "package_versions": {"psycopg": "3.3.8", "psycopg_binary": "3.3.8", "typing_extensions": "4.16.0"},
        "pq_impl": "binary",
        "flags": {"isolated": 1, "no_site": 1, "dont_write_bytecode": 1},
        "executable": root + "/bin/python3.12",
        "prefix": root,
        "base_prefix": root,
        "sys_path": [root + "/lib/python3.12", root + "/lib/python3.12/lib-dynload", root + "/packages"],
        "modules": [
            {"name": "encodings", "origin": root + "/lib/python3.12/encodings/__init__.py"},
            {"name": "encodings.utf_8", "origin": root + "/lib/python3.12/encodings/utf_8.py"},
            {"name": "psycopg", "origin": root + "/packages/psycopg/__init__.py"},
            {"name": "psycopg.pq", "origin": root + "/packages/psycopg/pq/__init__.py"},
            {"name": "psycopg_binary", "origin": root + "/packages/psycopg_binary/__init__.py"},
            {"name": "psycopg_binary.pq", "origin": root + "/packages/psycopg_binary/pq.cpython-312-x86_64-linux-gnu.so"},
            {"name": "typing_extensions", "origin": root + "/packages/typing_extensions.py"},
        ],
        "native_libraries": [root + "/lib/ld-linux-x86-64.so.2", root + "/lib/libc.so.6"],
        "encodings_loaded_before_bootstrap": True,
        "dynamic_closure_review_sha256": "c" * 64,
        "provenance_acceptance_sha256": "d" * 64,
        "socket_attempts": 0,
        "db_attempts": 0,
    }


def test_valid_observation_is_data_only_not_runtime_proof():
    m = module()
    spec = expected()
    assert m.validate_observation(copy.deepcopy(spec), spec) == {
        "status": "SUPPLIED_OBSERVATION_MATCHES_NOT_RUNTIME_PROOF",
        "execution_authorized": False,
        "source_sha256": spec["source_sha256"],
        "bundle_manifest_sha256": spec["bundle_manifest_sha256"],
    }


@pytest.mark.parametrize("field", list(expected()))
def test_missing_or_different_observation_field_rejects(field):
    m = module()
    spec = expected()
    observed = copy.deepcopy(spec)
    del observed[field]
    with pytest.raises(m.Rejected):
        m.validate_observation(observed, spec)
    observed = copy.deepcopy(spec)
    observed[field] = None
    with pytest.raises(m.Rejected):
        m.validate_observation(observed, spec)


@pytest.mark.parametrize("change", [
    lambda d: d.update(schema=True),
    lambda d: d.update(extra="unexpected"),
    lambda d: d.update(python_version="3.12.4"),
    lambda d: d.update(implementation="pypy"),
    lambda d: d.update(soabi="cp311"),
    lambda d: d.update(architecture="aarch64"),
    lambda d: d["package_versions"].update(psycopg="3.3.7"),
    lambda d: d["package_versions"].update(extra="1"),
    lambda d: d.update(pq_impl="python"),
    lambda d: d["flags"].update(isolated=True),
    lambda d: d["flags"].update(no_site=0),
    lambda d: d["flags"].update(dont_write_bytecode=0),
    lambda d: d.update(executable="/usr/bin/python3.12"),
    lambda d: d.update(prefix="/usr"),
    lambda d: d.update(base_prefix="/usr"),
    lambda d: d["sys_path"].append(""),
    lambda d: d["sys_path"].append(d["sys_path"][0]),
    lambda d: d["modules"].pop(),
    lambda d: d["modules"].append(copy.deepcopy(d["modules"][0])),
    lambda d: d["modules"][0].update(origin="/usr/lib/python3.12/encodings/__init__.py"),
    lambda d: d["modules"][0].update(origin="/synthetic/w01-runtime/../outside"),
    lambda d: d["modules"][0].update(origin="/synthetic/w01-runtime//module.py"),
    lambda d: d["modules"][0].update(origin="/synthetic/w01-runtime/lib/sitecustomize.py"),
    lambda d: d["modules"][0].update(origin="frozen"),
    lambda d: d["native_libraries"].append("/usr/lib/libpq.so"),
    lambda d: d["native_libraries"].append(d["native_libraries"][0]),
    lambda d: d.update(native_libraries=[]),
    lambda d: d.update(encodings_loaded_before_bootstrap=False),
    lambda d: d.update(dynamic_closure_review_sha256="UNPROVEN"),
    lambda d: d.update(provenance_acceptance_sha256="KNOWN_INSTALLED_BYTES"),
    lambda d: d.update(socket_attempts=1),
    lambda d: d.update(db_attempts=1),
    lambda d: d.update(socket_attempts=False),
    lambda d: d.update(db_attempts=False),
])
def test_invalid_expected_cannot_make_invalid_observation_pass(change):
    m = module()
    spec = expected()
    change(spec)
    with pytest.raises(m.Rejected):
        m.validate_observation(copy.deepcopy(spec), spec)


def test_no_stage_b_release_can_authorize_native_execution():
    m = module()
    for release in (None, {}, {"approved": True, "source_sha256": "a" * 64}):
        with pytest.raises(m.Rejected, match="stage_b_has_no_execution_authority"):
            m.require_runtime_release(release, "a" * 64)


@pytest.mark.parametrize("field", ["sys_path", "modules", "native_libraries"])
def test_observation_tuple_cannot_impersonate_json_list(field):
    m = module()
    spec = expected()
    observed = copy.deepcopy(spec)
    observed[field] = tuple(observed[field])
    with pytest.raises(m.Rejected):
        m.validate_observation(observed, spec)


@pytest.mark.parametrize("suffix", ["sitecustomize/__init__.py", "usercustomize/__init__.py",
                                    "sitecustomize.cpython-312-x86_64-linux-gnu.so", "usercustomize.so"])
def test_bootstrap_origin_forbidden_hook_packages_reject(suffix):
    m = module()
    spec = expected()
    spec["modules"][0]["origin"] = spec["bundle_root"] + "/lib/python3.12/" + suffix
    with pytest.raises(m.Rejected):
        m.validate_observation(copy.deepcopy(spec), spec)
