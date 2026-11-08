import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

HERE = Path(__file__).parent


def module():
    p = HERE / "native_bundle.py"
    assert p.is_file(), "Stage B packager implementation is missing"
    spec = importlib.util.spec_from_file_location("stageb_bundle", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def encode(d):
    b = (json.dumps(d, sort_keys=True) + "\n").encode()
    return b, hashlib.sha256(b).hexdigest()


def fixture(tmp_path):
    root = tmp_path / "sources"
    root.mkdir()
    paths = [("python", b"ELF-PYTHON", "bin/python3.12", "interpreter", None, ["libc.so.6"]),
             ("loader", b"ELF-LOADER", "lib/ld-linux-x86-64.so.2", "loader", "ld-linux-x86-64.so.2", []),
             ("libc", b"ELF-LIBC", "lib/libc.so.6", "elf", "libc.so.6", ["ld-linux-x86-64.so.2"]),
             ("encodings", b"synthetic source\n", "lib/python3.12/encodings/__init__.py", "python", None, [])]
    files = []
    for name, data, dst, kind, soname, needed in paths:
        p = root / name
        p.write_bytes(data)
        files.append(dict(source=str(p), destination=dst, bytes=len(data),
                          sha256=hashlib.sha256(data).hexdigest(), mode=0o555 if kind in {"interpreter", "loader", "elf"} else 0o444,
                          kind=kind, soname=soname, needed=needed))
    d = dict(schema=1, status="SOURCE_ONLY", provenance="KNOWN_INSTALLED_BYTES_NOT_PUBLISHER_ATTESTED",
             dynamic_closure="UNPROVEN", files=files)
    return root, d


def test_copy_is_exact_and_explicitly_not_runtime(tmp_path):
    m = module()
    root, d = fixture(tmp_path)
    raw, sha = encode(d)
    out = tmp_path / "bundle"
    receipt = m.stage_bundle(raw, sha, (root,), out)
    assert receipt["status"] == "LOCAL_BYTES_STAGED_NOT_RUNTIME_QUALIFIED"
    assert receipt["execution_authorized"] is False
    assert receipt["immutable_against_owner"] is False
    assert receipt["manifest_sha256"] == sha
    assert m.verify_bundle(out, sha)["verified_files"] == 4
    for e in d["files"]:
        assert (out / e["destination"]).read_bytes() == Path(e["source"]).read_bytes()


@pytest.mark.parametrize("change", [
    lambda d: d.update(schema=True), lambda d: d.update(extra="unknown"),
    lambda d: d.update(dynamic_closure="QUALIFIED"), lambda d: d.update(files=[]),
    lambda d: d["files"][0].update(bytes=True), lambda d: d["files"][0].update(bytes=33 * 1024 * 1024),
    lambda d: d["files"][0].update(sha256="0" * 63), lambda d: d["files"][0].update(mode=0o4755),
    lambda d: d["files"][0].update(kind="secret"), lambda d: d["files"][0].update(needed=["missing.so"]),
    lambda d: d["files"][2].update(soname="ld-linux-x86-64.so.2"),
    lambda d: d["files"].append(copy.deepcopy(d["files"][0])),
])
def test_manifest_mutations_reject(tmp_path, change):
    m = module()
    _, d = fixture(tmp_path)
    change(d)
    raw, sha = encode(d)
    with pytest.raises(m.Rejected):
        m.parse_manifest(raw, sha)


@pytest.mark.parametrize("dst", ["../escape", "/absolute", "a/../b", "a//b", "./x",
                                 "a\\b", "manifest.json", "receipt.json", "lib/sitecustomize.py",
                                 "lib/usercustomize.py", "lib/hook.pth", "lib/__pycache__/x.pyc",
                                 "lib/x.pyc", "lib/.env", "lib/id_rsa", "lib/name\n"])
def test_bad_destination_rejects(tmp_path, dst):
    m = module()
    _, d = fixture(tmp_path)
    d["files"][0]["destination"] = dst
    raw, sha = encode(d)
    with pytest.raises(m.Rejected):
        m.parse_manifest(raw, sha)


def test_prefix_collision_rejects(tmp_path):
    m = module()
    _, d = fixture(tmp_path)
    d["files"][0]["destination"] = "lib"
    raw, sha = encode(d)
    with pytest.raises(m.Rejected):
        m.parse_manifest(raw, sha)


@pytest.mark.parametrize("raw", [b'{"schema":1,"schema":1}', b'{"x":NaN}', b"[]", b"not json"])
def test_strict_json_rejects(raw):
    m = module()
    with pytest.raises(m.Rejected):
        m.parse_manifest(raw, hashlib.sha256(raw).hexdigest())


def test_manifest_digest_required(tmp_path):
    m = module()
    _, d = fixture(tmp_path)
    raw, _ = encode(d)
    with pytest.raises(m.Rejected):
        m.parse_manifest(raw, "0" * 64)


@pytest.mark.parametrize("mutation", ["outside", "symlink_file", "symlink_parent", "hardlink", "fifo", "drift", "size"])
def test_sources_fail_before_destination_created(tmp_path, mutation):
    m = module()
    root, d = fixture(tmp_path)
    entry = d["files"][0]
    original = Path(entry["source"])
    if mutation == "outside":
        outside = tmp_path / "outside"
        outside.write_bytes(original.read_bytes())
        entry["source"] = str(outside)
    elif mutation == "symlink_file":
        link = root / "link"
        link.symlink_to(original)
        entry["source"] = str(link)
    elif mutation == "symlink_parent":
        link = tmp_path / "linked"
        link.symlink_to(root, target_is_directory=True)
        entry["source"] = str(link / original.name)
        root = link
    elif mutation == "hardlink":
        os.link(original, root / "alias")
    elif mutation == "fifo":
        original.unlink()
        os.mkfifo(original)
    elif mutation == "drift":
        original.write_bytes(b"XXXXXXXXXX")
    else:
        original.write_bytes(b"longer synthetic bytes")
    raw, sha = encode(d)
    out = tmp_path / "bundle"
    with pytest.raises(m.Rejected):
        m.stage_bundle(raw, sha, (root,), out)
    assert not out.exists()


def test_existing_destination_is_preserved(tmp_path):
    m = module()
    root, d = fixture(tmp_path)
    raw, sha = encode(d)
    out = tmp_path / "bundle"
    out.mkdir()
    marker = out / "keep"
    marker.write_text("unchanged")
    with pytest.raises(m.Rejected):
        m.stage_bundle(raw, sha, (root,), out)
    assert marker.read_text() == "unchanged"


@pytest.mark.parametrize("change", ["extra", "changed", "missing", "symlink", "receipt", "manifest"])
def test_staged_verification_rejects_drift(tmp_path, change):
    m = module()
    root, d = fixture(tmp_path)
    raw, sha = encode(d)
    out = tmp_path / "bundle"
    m.stage_bundle(raw, sha, (root,), out)
    p = out / d["files"][0]["destination"]
    if change == "extra":
        (out / "extra").write_text("x")
    elif change == "changed":
        p.chmod(0o600)
        p.write_bytes(b"tampered")
    elif change == "missing":
        p.unlink()
    elif change == "symlink":
        p.unlink()
        p.symlink_to(d["files"][0]["source"])
    elif change == "receipt":
        (out / "receipt.json").chmod(0o600)
        (out / "receipt.json").write_text("{}")
    else:
        (out / "manifest.json").chmod(0o600)
        (out / "manifest.json").write_text("{}")
    with pytest.raises(m.Rejected):
        m.verify_bundle(out, sha)


def test_no_execution_imports_in_packager():
    m = module()
    import ast
    t = ast.parse(Path(m.__file__).read_text())
    names = {n.name.split(".")[0] for x in ast.walk(t) if isinstance(x, ast.Import) for n in x.names}
    assert not names & {"subprocess", "socket", "ctypes", "psycopg"}


@pytest.mark.parametrize("mutation", ["reserved_prefix", "source_hook", "needed_unhashable", "needed_bool",
                                     "mode_kind", "source_control", "soname_slash"])
def test_additional_schema_boundaries(tmp_path, mutation):
    m = module()
    root, d = fixture(tmp_path)
    if mutation == "reserved_prefix":
        d["files"][0]["destination"] = "manifest.json/child"
    elif mutation == "source_hook":
        p = root / "sitecustomize.py"
        p.write_bytes(Path(d["files"][0]["source"]).read_bytes())
        d["files"][0]["source"] = str(p)
    elif mutation == "needed_unhashable":
        d["files"][0]["needed"] = [{}]
    elif mutation == "needed_bool":
        d["files"][0]["needed"] = [True]
    elif mutation == "mode_kind":
        d["files"][0]["mode"] = 0o444
    elif mutation == "source_control":
        d["files"][0]["source"] = str(root / "control\x7f")
    else:
        d["files"][1]["soname"] = "nested/loader"
    raw, sha = encode(d)
    with pytest.raises(m.Rejected):
        m.parse_manifest(raw, sha)


@pytest.mark.parametrize("name", ["sitecustomize/__init__.py", "usercustomize/__init__.py",
                                  "sitecustomize.cpython-312-x86_64-linux-gnu.so", "usercustomize.so"])
@pytest.mark.parametrize("side", ["source", "destination"])
def test_customization_packages_and_extensions_reject(tmp_path, name, side):
    m = module()
    root, d = fixture(tmp_path)
    d["files"][3][side] = str(root / name) if side == "source" else "lib/python3.12/" + name
    raw, sha = encode(d)
    with pytest.raises(m.Rejected):
        m.parse_manifest(raw, sha)


def test_source_change_after_its_read_prevents_completion(tmp_path, monkeypatch):
    m = module()
    root, d = fixture(tmp_path)
    raw, sha = encode(d)
    original = m.read_regular
    first = Path(d["files"][0]["source"])
    second = Path(d["files"][1]["source"])

    def change_earlier(path, *args, **kwargs):
        result = original(path, *args, **kwargs)
        if path == second:
            first.write_bytes(b"changed-before-staging")
        return result

    monkeypatch.setattr(m, "read_regular", change_earlier)
    out = tmp_path / "bundle"
    with pytest.raises(m.Rejected):
        m.stage_bundle(raw, sha, (root,), out)
    assert not (out / "receipt.json").exists()


def test_source_change_during_read_rejects(tmp_path, monkeypatch):
    m = module()
    root, d = fixture(tmp_path)
    raw, sha = encode(d)
    original = m.os.fstat
    source = Path(d["files"][0]["source"])
    calls = 0

    def mutate_after_first_stat(fd):
        nonlocal calls
        result = original(fd)
        calls += 1
        if calls == 1:
            source.write_bytes(b"changed-on-read")
        return result

    monkeypatch.setattr(m.os, "fstat", mutate_after_first_stat)
    with pytest.raises(m.Rejected):
        m.stage_bundle(raw, sha, (root,), tmp_path / "bundle")


def test_interrupted_output_is_preserved_and_not_retried(tmp_path, monkeypatch):
    m = module()
    root, d = fixture(tmp_path)
    raw, sha = encode(d)
    original = m.write_relative
    calls = 0

    def interrupted(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("synthetic interrupted write")
        return original(*args)

    monkeypatch.setattr(m, "write_relative", interrupted)
    out = tmp_path / "bundle"
    with pytest.raises(m.Rejected):
        m.stage_bundle(raw, sha, (root,), out)
    first = out / d["files"][0]["destination"]
    before = first.read_bytes()
    assert not (out / "receipt.json").exists()
    monkeypatch.setattr(m, "write_relative", original)
    with pytest.raises(m.Rejected):
        m.stage_bundle(raw, sha, (root,), out)
    assert first.read_bytes() == before


def test_destination_ancestor_symlink_rejects(tmp_path):
    m = module()
    root, d = fixture(tmp_path)
    raw, sha = encode(d)
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(m.Rejected):
        m.stage_bundle(raw, sha, (root,), link / "bundle")
    assert not (target / "bundle").exists()


@pytest.mark.parametrize("change", ["hardlink", "directory"])
def test_staged_aliases_and_extra_directories_reject(tmp_path, change):
    m = module()
    root, d = fixture(tmp_path)
    raw, sha = encode(d)
    out = tmp_path / "bundle"
    m.stage_bundle(raw, sha, (root,), out)
    if change == "hardlink":
        os.link(out / d["files"][0]["destination"], tmp_path / "external_alias")
    else:
        (out / "extra-directory").mkdir()
    with pytest.raises(m.Rejected):
        m.verify_bundle(out, sha)


def test_bundle_bytes_are_deterministic_at_two_destinations(tmp_path):
    m = module()
    root, d = fixture(tmp_path)
    raw, sha = encode(d)
    left, right = tmp_path / "first", tmp_path / "second"
    assert m.stage_bundle(raw, sha, (root,), left) == m.stage_bundle(raw, sha, (root,), right)
    for name in [e["destination"] for e in d["files"]] + ["manifest.json", "receipt.json"]:
        assert (left / name).read_bytes() == (right / name).read_bytes()
