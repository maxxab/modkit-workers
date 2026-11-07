"""Prepare-only candidate. Run only after independent review accepts exact hashes."""

import hashlib
import json
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
PACKET = pathlib.Path(
    "/home/faris/modkit-local-20261106/workers-continuation/w01-fixture-v3/packet.json"
)
PACKET_SHA = "897fccd0a1bcc34756ad77b9cb9d0e61dccea3c683576e63ca00bb278b77563d"
RECON = HERE.parent / "w01-reconciliation-20261107"
LIMIT = 1048576


def pin(raw):
    return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def read_pin(path, expected):
    path = pathlib.Path(path)
    assert path.is_file() and not path.is_symlink(), str(path)
    assert path.stat().st_size <= 16777216, "input too large"
    raw = path.read_bytes()
    assert pin(raw) == expected, "pin drift: " + str(path)
    return raw


def canonical_result(value):
    # JSON spellings preserve true versus 1; never use Python value equality here.
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )


def compare(a, b):
    if canonical_result(a) != canonical_result(b):
        names = []
        if type(a) is dict and type(b) is dict:
            for key in sorted(set(a) | set(b)):
                if (
                    key not in a
                    or key not in b
                    or canonical_result(a[key]) != canonical_result(b[key])
                ):
                    names.append(str(key)[:80])
                    if len(names) == 5:
                        break
        raise AssertionError("Meaningful result mismatch; first cases: " + ", ".join(names))


def main():
    assert sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode
    assert sys.argv[1:] == ["--reviewed-pure-only"], "explicit reviewed-only flag required"
    manifest = json.loads((HERE / "source-manifest.json").read_bytes())
    for name, expected in manifest["artifacts"].items():
        read_pin(HERE / name, expected)
    for name, expected in manifest["reconciliation"].items():
        read_pin(RECON / name, expected)
    raw_packet = PACKET.read_bytes()
    assert hashlib.sha256(raw_packet).hexdigest() == PACKET_SHA
    packet = json.loads(raw_packet)["files"]
    observed = json.loads((RECON / "observed-inputs.json").read_bytes())
    recon = json.loads((RECON / "reconciliation.json").read_bytes())
    assert len(packet) == 189 and len(observed) == 190
    assert recon["packet_sha256"] == PACKET_SHA and recon["counts"] == {
        "unchanged": 181,
        "changed": 8,
    }
    # Buffer every observed byte once, prove all drift before any package import/staging.
    current = {path: read_pin(path, expected) for path, expected in observed.items()}
    assert sum(map(len, current.values())) <= 67108864
    changed = {v["path"]: v for v in recon["changed_inputs"]}
    assert len(changed) == 8
    originals = {}
    for path, expected in packet.items():
        if path not in changed:
            assert pin(current[path]) == expected
        elif path.endswith(".py"):
            originals[path] = read_pin(changed[path]["original_source"], expected)
        else:
            assert path.endswith("/sql/0001_initial.sql")
            assert pin(current[path][: expected["size"]]) == expected
    assert len(originals) == 7
    assert set(originals) <= set(manifest["sources"].values())
    outputs = []
    # Only writes: temporary .py staging plus stdout/stderr captures, then cleanup.
    with tempfile.TemporaryDirectory(prefix="w01-pure-reviewed-") as temp:
        base = pathlib.Path(temp)
        for flavor in ("original", "current"):
            root = base / flavor
            root.mkdir()
            for module, path in manifest["sources"].items():
                assert path in observed and path.endswith(".py")
                assert "/src/" in path
                relative = pathlib.PurePosixPath(path.split("/src/", 1)[1])
                assert ".." not in relative.parts and not relative.is_absolute()
                assert not any(part in ("adapters", "sql") for part in relative.parts)
                assert relative.name not in (
                    "native_codec.py",
                    "native_sync.py",
                    "migrations.py",
                    "_resource_io.py",
                )
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(
                    originals.get(path, current[path]) if flavor == "original" else current[path]
                )
            payload = root / "pure_payload.py"
            payload.write_bytes(
                read_pin(HERE / "pure_payload.py", manifest["artifacts"]["pure_payload.py"])
            )
            stdout = base / (flavor + ".stdout")
            stderr = base / (flavor + ".stderr")
            with stdout.open("wb") as out, stderr.open("wb") as err:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-I",
                        "-S",
                        "-B",
                        str(payload),
                        str(root),
                        json.dumps(sorted(manifest["sources"])),
                    ],
                    cwd=root,
                    env={"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "TZ": "UTC"},
                    stdin=subprocess.DEVNULL,
                    stdout=out,
                    stderr=err,
                    timeout=15,
                    check=False,
                )
            assert stdout.stat().st_size <= LIMIT and stderr.stat().st_size <= LIMIT
            assert completed.returncode == 0, (
                flavor + ": child failed: " + stderr.read_text(errors="replace")[:4000]
            )
            assert stderr.read_bytes() == b"", flavor + ": unexpected stderr"
            result = json.loads(stdout.read_bytes())
            assert sorted(result) == manifest["expected_cases"], "Missing or extra cases"
            outputs.append(result)
    compare(*outputs)
    # Negative controls change semantic parameter and public error, never production source.
    for field, replacement in [
        ("submit_absent", {"changed_parameter": True}),
        ("row_reject_int_bool", {"wrong_error_code": True}),
    ]:
        altered = dict(outputs[1])
        altered[field] = replacement
        try:
            compare(outputs[0], altered)
        except AssertionError:
            pass
        else:
            raise AssertionError("Comparator negative control did not fail")
    # Comparator-only sensitivity controls over synthetic normalized records.
    # These are not product mutations or claims of a complete mutation suite.
    controls = (
        ({"value": True}, {"value": 1}),
        (
            {"container_type": "builtins.tuple", "sequence": [1]},
            {"container_type": "builtins.list", "sequence": [1]},
        ),
        (
            {"container_type": "builtins.frozenset", "set": [1]},
            {"container_type": "builtins.set", "set": [1]},
        ),
        (
            {"container_type": "builtins.mappingproxy", "mapping": [["v", 1]]},
            {"container_type": "builtins.dict", "mapping": [["v", 1]]},
        ),
    )
    for first, second in controls:
        try:
            compare(first, second)
        except AssertionError:
            pass
        else:
            raise AssertionError("Comparator type/mutability sensitivity control failed")
    # Recheck every observed pin after both children; no stale success on source drift.
    for path, expected in observed.items():
        read_pin(path, expected)
    assert hashlib.sha256(PACKET.read_bytes()).hexdigest() == PACKET_SHA
    print(
        json.dumps(
            {
                "status": "PASS_BOUNDED_PURE_SLICE_ONLY",
                "cases": len(outputs[0]),
                "result_sha256": hashlib.sha256(
                    json.dumps(outputs[0], sort_keys=True, separators=(",", ":")).encode()
                ).hexdigest(),
                "negative_controls": 6,
                "native_SQL_target": "NOT_RUN",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
