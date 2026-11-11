"""Check actual installed bytes, origins and inert migration APIs outside a checkout."""

import hashlib
import importlib
import importlib.metadata
import json
import os
import sys
import sysconfig
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    require(sys.flags.isolated and sys.dont_write_bytecode, "isolated interpreter required")
    expected = json.loads(Path("expected.json").read_text())
    site = Path(sysconfig.get_path("purelib")).resolve()
    rows = {}
    for component, version in (("workers", "0.1.0"), ("events", expected["events"]["version"])):
        package = "modkit_" + component
        require(
            importlib.metadata.version("modkit-" + component) == version,
            "wrong distribution version",
        )
        module = importlib.import_module(package)
        require(Path(module.__file__).resolve().is_relative_to(site), "checkout import leakage")
        sql = site / package / "persistence/sql"
        document = json.loads((sql / "manifest.json").read_bytes())
        (row,) = document["migrations"]
        rows[component] = row
        chunks = [b"MKMF\x01", len(row["resources"]).to_bytes(4, "big")]
        for resource in sorted(row["resources"], key=lambda r: r["path"].encode()):
            raw = (sql / resource["path"].split("/")[-1]).read_bytes()
            require(
                hashlib.sha256(raw).hexdigest() == resource["sha256"], "resource digest mismatch"
            )
            path = resource["path"].encode()
            chunks.extend((len(path).to_bytes(4, "big"), path, bytes.fromhex(resource["sha256"])))
        require(
            hashlib.sha256(b"".join(chunks)).hexdigest() == row["migration_digest"],
            "aggregate mismatch",
        )
        api = importlib.import_module(package + ".persistence.migrations")
        if os.name == "posix":
            (migration,) = api.manifest()
            for resource in migration.resources:
                require(
                    api.read_sql(migration, resource).encode()
                    == (sql / resource.path.split("/")[-1]).read_bytes(),
                    "installed API mismatch",
                )
        else:
            try:
                api.manifest()
            except ValueError as error:
                require(
                    str(error) == "unsupported migration resource backend", "wrong backend refusal"
                )
            else:
                raise ValueError("unsupported platform unexpectedly accepted")
    require(
        rows["events"]["migration_digest"] == expected["events"]["migration_digest"],
        "wrong Events pin",
    )
    require(
        rows["workers"]["depends_on"]
        == [
            {
                "component": "events",
                "version": 1,
                "migration_digest": rows["events"]["migration_digest"],
            }
        ],
        "pair dependency mismatch",
    )
    for name, digest in expected["hashes"].items():
        require(
            hashlib.sha256((site / name).read_bytes()).hexdigest() == digest,
            "installed byte mismatch: " + name,
        )
    if expected["profile"]:
        from modkit_events.persistence import recovery_profile

        require(
            recovery_profile._layout() == expected["profile"], "wrong finite interpreter profile"
        )
        recovery_profile._verify_driver()
    print("PASS: installed origins, bytes, dependency and supported/refusal resource API")


if __name__ == "__main__":
    main()
