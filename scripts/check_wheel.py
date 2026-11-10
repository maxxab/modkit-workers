"""Verify local package wheels, then test an isolated installed pair, without services."""

import argparse
import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import tomllib
import venv
import xml.etree.ElementTree as ET
import zipfile
from email.parser import BytesParser
from pathlib import Path

from packaging.requirements import Requirement

PORTABLE_TESTS = (
    "test_async_source_batch.py",
    "test_events_shared_seam.py",
    "test_handler_partials.py",
    "test_job_acquisition.py",
    "test_job_binding_types.py",
    "test_job_catalog_contract.py",
    "test_job_find_atomicity.py",
    "test_job_listing.py",
    "test_job_persistence_contracts.py",
    "test_job_scope_projection.py",
    "test_native_control.py",
    "test_native_control_contracts.py",
    "test_native_job_acquisition.py",
    "test_native_job_contract.py",
    "test_native_job_find.py",
    "test_native_job_lifecycle.py",
    "test_native_job_material.py",
    "test_native_job_store.py",
    "test_native_public_contracts.py",
    "test_native_recovery_contracts.py",
    "test_native_recovery_host.py",
    "test_native_recovery_owner.py",
    "test_native_setup.py",
    "test_native_supervisor.py",
    "test_native_worker_factory.py",
    "test_package_exports.py",
    "test_source_batch.py",
    "test_worker_contracts.py",
    "test_worker_startup.py",
)
SOURCE_ONLY_TESTS = (
    "test_acquisition_bounds_source.py",
    "test_acquisition_source_contract.py",
    "test_bounded_job_listing_source_contract.py",
    "test_installation_closure.py",
    "test_native_acquisition_source.py",
    "test_reader_case_data.py",
    "test_reader_source_contract.py",
    "test_ci_checks.py",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def selected_tests(platform):
    return PORTABLE_TESTS + (
        "test_migration_resources.py"
        if platform == "posix"
        else "test_migration_resources.py::Resources",
    )


def clean_environment(original):
    env = {k: v for k, v in original.items() if not k.startswith(("PYTHON", "PYTEST_", "MODKIT_"))}
    env.update(
        PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHONDONTWRITEBYTECODE="1", PYTHONNOUSERSITE="1"
    )
    return env


def require_complete_tests(path):
    suites = list(ET.parse(path).getroot().iter("testsuite"))
    require(bool(suites) and sum(int(x.get("tests", "0")) for x in suites) > 0, "no tests executed")
    require(
        not any(int(x.get(k, "0")) for x in suites for k in ("errors", "failures", "skipped")),
        "test lane has failures, errors or skips",
    )


def audit_wheel(root, wheel, version, package="modkit_workers"):
    require(
        wheel.is_file() and not wheel.is_symlink() and wheel.stat().st_size < 268435456,
        "invalid wheel file",
    )
    require(wheel.name == f"{package}-{version}-py3-none-any.whl", "unexpected wheel filename")
    source = root / "src" / package
    expected = {}
    for path in source.rglob("*"):
        require(not path.is_symlink(), "source symlink")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
            expected[package + "/" + path.relative_to(source).as_posix()] = path.read_bytes()
    require(bool(expected), "empty package source")
    info = f"{package}-{version}.dist-info/"
    metadata = {info + name for name in ("METADATA", "WHEEL", "RECORD", "licenses/LICENSE")}
    with zipfile.ZipFile(wheel) as archive:
        entries = archive.infolist()
        require(len(entries) == len({i.filename for i in entries}), "duplicate ZIP members")
        require(sum(i.file_size for i in entries) < 268435456, "oversized wheel")
        require(set(archive.namelist()) == set(expected) | metadata, "unexpected wheel members")
        require(
            all(
                not i.is_dir() and (i.external_attr >> 16) & 0o170000 in (0, 0o100000)
                for i in entries
            ),
            "nonregular wheel member",
        )
        payload = {i.filename: archive.read(i) for i in entries}
    require(all(payload[k] == v for k, v in expected.items()), "wheel/source byte mismatch")
    require(
        payload[info + "licenses/LICENSE"] == (root / "LICENSE").read_bytes(), "license mismatch"
    )
    meta = BytesParser().parsebytes(payload[info + "METADATA"])
    require(
        meta.get_all("Name") == [package.replace("_", "-")]
        and meta.get_all("Version") == [version],
        "distribution identity mismatch",
    )
    require(meta["Requires-Python"] == ">=3.12", "Python requirement mismatch")
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    deps = {Requirement(x) for x in config.get("dependencies", [])}
    for extra, values in config.get("optional-dependencies", {}).items():
        deps.update(Requirement(x + "; extra == " + repr(extra)) for x in values)
    actual = meta.get_all("Requires-Dist", [])
    require(
        len(actual) == len(deps) and {Requirement(x) for x in actual} == deps,
        "dependency metadata mismatch",
    )
    require(
        b"Root-Is-Purelib: true" in payload[info + "WHEEL"]
        and b"Tag: py3-none-any" in payload[info + "WHEEL"],
        "wheel platform mismatch",
    )
    rows = list(csv.reader(io.StringIO(payload[info + "RECORD"].decode())))
    require(
        all(len(r) == 3 for r in rows)
        and len(rows) == len(payload)
        and {r[0] for r in rows} == set(payload),
        "invalid RECORD inventory",
    )
    for name, digest, size in rows:
        if name == info + "RECORD":
            require(digest == size == "", "RECORD self hash")
        else:
            raw = payload[name]
            expected_digest = (
                base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
            )
            require(
                size == str(len(raw)) and digest == "sha256=" + expected_digest,
                "RECORD byte mismatch",
            )
    return {
        name: hashlib.sha256(raw).hexdigest()
        for name, raw in payload.items()
        if name != info + "RECORD"
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("events_wheel", type=Path)
    parser.add_argument("--events-root", type=Path, required=True)
    parser.add_argument("--expect-profile", default="")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    from check_source import verify_dependency

    pin = verify_dependency(root, args.events_root.resolve())
    wheel, events = args.wheel.resolve(), args.events_wheel.resolve()
    hashes = audit_wheel(root, wheel, "0.1.0")
    hashes.update(audit_wheel(args.events_root.resolve(), events, pin["version"], "modkit_events"))
    with tempfile.TemporaryDirectory(prefix="modkit-workers-wheel-") as directory:
        temp = Path(directory)
        venv.EnvBuilder(with_pip=True).create(temp / "venv")
        python = temp / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = clean_environment(os.environ)

        def run(*command):
            subprocess.run([str(python), "-I", "-B", *command], cwd=temp, env=env, check=True)

        # Local pair is installed without an index before test-only tools are added.
        run("-m", "pip", "install", "--no-index", str(events), str(wheel))
        run(
            "-m",
            "pip",
            "install",
            "pytest==9.2.0",
            "pytest-asyncio==1.4.1",
            "psycopg[binary]==3.3.8",
        )
        tests = temp / "tests"
        tests.mkdir()
        for name in (*PORTABLE_TESTS, "test_migration_resources.py", "_resource_fixtures.py"):
            shutil.copyfile(root / "tests" / name, tests / name)
        shutil.copyfile(root / "scripts/check_installation.py", temp / "check_installation.py")
        (temp / "expected.json").write_text(
            json.dumps({"hashes": hashes, "events": pin, "profile": args.expect_profile})
        )
        (temp / "pytest.ini").write_text(
            "[pytest]\nasyncio_mode=auto\nasyncio_default_fixture_loop_scope=function\n"
        )
        # Child tests can import their test helpers, never checkout source directories.
        env["PYTHONPATH"] = str(tests)
        (tests / "conftest.py").write_text(
            "import sys, sysconfig\nfrom pathlib import Path\n"
            "def pytest_sessionfinish(session, exitstatus):\n"
            "    site = Path(sysconfig.get_path('purelib')).resolve()\n"
            "    for name, module in tuple(sys.modules.items()):\n"
            "        if name.startswith(('modkit_workers', 'modkit_events')) and getattr(module, '__file__', None):\n"
            "            assert Path(module.__file__).resolve().is_relative_to(site), name\n"
        )
        run("check_installation.py")
        run("-m", "pip", "check")
        run(
            "-m",
            "pytest",
            "-p",
            "pytest_asyncio.plugin",
            "-q",
            *("tests/" + name for name in selected_tests(os.name)),
            "--junitxml=installed.xml",
        )
        require_complete_tests(temp / "installed.xml")
        run("check_installation.py")
    print("PASS: installed pair and explicit platform contract; no live/native qualification")


if __name__ == "__main__":
    main()
