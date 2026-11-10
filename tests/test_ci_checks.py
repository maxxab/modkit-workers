"""Offline unit controls for CI tooling; never native/service operations."""

import base64
import csv
import hashlib
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def checker():
    path = SCRIPTS / "check_wheel.py"
    assert path.is_file(), "installed-wheel CI checker is missing"
    spec = importlib.util.spec_from_file_location("workers_ci_check_wheel", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wheel(tmp_path, *, extra=False, bad_record=False, duplicate=False):
    root = tmp_path / "project"
    source = root / "src/modkit_workers"
    source.mkdir(parents=True)
    (source / "__init__.py").write_bytes(b'"""fixture"""\n')
    (root / "LICENSE").write_bytes(b"MIT fixture\n")
    (root / "pyproject.toml").write_text('[project]\ndependencies = ["modkit-events>=0.2,<0.3"]\n')
    info = "modkit_workers-0.1.0.dist-info/"
    payload = {
        "modkit_workers/__init__.py": (source / "__init__.py").read_bytes(),
        info
        + "METADATA": b"Metadata-Version: 2.4\nName: modkit-workers\nVersion: 0.1.0\nRequires-Python: >=3.12\nRequires-Dist: modkit-events<0.3,>=0.2\n",
        info + "WHEEL": b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        info + "licenses/LICENSE": b"MIT fixture\n",
    }
    if extra:
        payload["private.txt"] = b"unexpected"
    rows = []
    for name, raw in payload.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(raw).digest()).decode().rstrip("=")
        rows.append((name, "sha256=" + ("x" * 43 if bad_record else digest), str(len(raw))))
    rows.append((info + "RECORD", "", ""))
    text = io.StringIO()
    csv.writer(text).writerows(rows)
    payload[info + "RECORD"] = text.getvalue().encode()
    artifact = tmp_path / "modkit_workers-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(artifact, "w") as archive:
        for name, raw in payload.items():
            archive.writestr(name, raw)
        if duplicate:
            with pytest.warns(UserWarning):
                archive.writestr("modkit_workers/__init__.py", b"duplicate")
    return root, artifact


def test_valid_wheel_matches_exact_source(tmp_path):
    root, artifact = wheel(tmp_path)
    assert checker().audit_wheel(root, artifact, "0.1.0")["modkit_workers/__init__.py"]


@pytest.mark.parametrize("mutation", ["extra", "bad_record", "duplicate"])
def test_tampered_wheel_is_rejected(tmp_path, mutation):
    root, artifact = wheel(tmp_path, **{mutation: True})
    with pytest.raises(ValueError):
        checker().audit_wheel(root, artifact, "0.1.0")


def test_source_byte_mismatch_is_rejected(tmp_path):
    root, artifact = wheel(tmp_path)
    (root / "src/modkit_workers/__init__.py").write_bytes(b"changed")
    with pytest.raises(ValueError):
        checker().audit_wheel(root, artifact, "0.1.0")


def test_child_environment_cannot_inherit_checkout_or_service_settings():
    cleaned = checker().clean_environment(
        {
            "PATH": "keep",
            "PYTHONPATH": "checkout",
            "PYTEST_ADDOPTS": "--skip",
            "MODKIT_REDIS_URL": "service",
        }
    )
    assert cleaned["PATH"] == "keep"
    assert "PYTHONPATH" not in cleaned and "MODKIT_REDIS_URL" not in cleaned
    assert "PYTEST_ADDOPTS" not in cleaned
    assert cleaned["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] == "1"


@pytest.mark.parametrize(
    "attributes",
    ['tests="0"', 'tests="1" skipped="1"', 'tests="1" errors="1"', 'tests="1" failures="1"'],
)
def test_incomplete_xml_fails(tmp_path, attributes):
    path = tmp_path / "results.xml"
    path.write_text("<testsuites><testsuite " + attributes + "/></testsuites>")
    with pytest.raises(ValueError):
        checker().require_complete_tests(path)


def test_success_xml_passes(tmp_path):
    path = tmp_path / "results.xml"
    path.write_text(
        '<testsuites><testsuite tests="2" errors="0" failures="0" skipped="0"/></testsuites>'
    )
    checker().require_complete_tests(path)


def test_portable_selection_is_explicit_and_preserves_source_oracles():
    module = checker()
    names = {p.name for p in (SCRIPTS.parent / "tests").glob("test_*.py")}
    assert names == set(module.PORTABLE_TESTS) | {"test_migration_resources.py"} | set(
        module.SOURCE_ONLY_TESTS
    )
    assert not (set(module.PORTABLE_TESTS) & set(module.SOURCE_ONLY_TESTS))
    assert module.selected_tests("nt")[-1] == "test_migration_resources.py::Resources"
    assert module.selected_tests("posix")[-1] == "test_migration_resources.py"


def test_workflow_keeps_reviewed_events_commit_and_finite_profiles():
    import json

    root = SCRIPTS.parent
    pin = json.loads((SCRIPTS / "ci_dependency.json").read_text())
    workflow = (root / ".github/workflows/ci.yml").read_text()
    assert "ref: " + pin["commit"] in workflow
    assert "'3.12.3'" in workflow and "'3.13.5'" in workflow
    assert "--expect-profile" in workflow
    assert "contents: read" in workflow
    assert "services:" not in workflow


def test_standards_uses_public_verified_dependency_without_extra_credentials():
    import json

    workflow = (SCRIPTS.parent / ".github/workflows/ci.yml").read_text()
    standards = workflow.split("  standards:\n", 1)[1].split("  package:\n", 1)[0]
    pin = json.loads((SCRIPTS / "ci_dependency.json").read_text())
    assert "repository: maxxab/modkit-events" in standards
    assert "ref: " + pin["commit"] in standards
    assert "git -C .ci-standards rev-parse HEAD" in standards
    assert "python .ci-standards/.development-standards/standards.py check" in standards
    assert "maxxab/development-standards" not in standards
    assert "secrets." not in standards and "token:" not in standards


def mode_wheel(artifact, kind):
    with zipfile.ZipFile(artifact) as archive:
        entries = [(entry, archive.read(entry)) for entry in archive.infolist()]
    with zipfile.ZipFile(artifact, "w") as archive:
        for entry, raw in entries:
            if entry.filename == "modkit_workers/__init__.py":
                entry.create_system = 3
                entry.external_attr = (kind | 0o600) << 16
            archive.writestr(entry, raw)


@pytest.mark.parametrize("kind", [0o010000, 0o020000, 0o060000, 0o120000, 0o140000])
def test_nonregular_member_modes_are_rejected(tmp_path, kind):
    root, artifact = wheel(tmp_path)
    mode_wheel(artifact, kind)
    with pytest.raises(ValueError, match="nonregular wheel member"):
        checker().audit_wheel(root, artifact, "0.1.0")


@pytest.mark.parametrize("kind", [0, 0o100000])
def test_regular_and_unspecified_member_modes_are_supported(tmp_path, kind):
    root, artifact = wheel(tmp_path)
    mode_wheel(artifact, kind)
    checker().audit_wheel(root, artifact, "0.1.0")
