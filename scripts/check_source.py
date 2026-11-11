"""Run declared source checks with a verified, explicitly pinned Events dependency."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from check_wheel import clean_environment, require, require_complete_tests, selected_tests


def verify_dependency(root, events):
    pin = json.loads((root / "scripts/ci_dependency.json").read_text())
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=events, text=True).strip()
    require(head == pin["commit"], "Events checkout does not match CI commit")
    require(
        not subprocess.check_output(
            ["git", "status", "--porcelain", "--untracked-files=all"], cwd=events
        ),
        "Events source checkout is dirty",
    )
    (row,) = json.loads((events / "src/modkit_events/persistence/sql/manifest.json").read_text())[
        "migrations"
    ]
    require(row["migration_digest"] == pin["migration_digest"], "Events migration pin mismatch")
    (own,) = json.loads((root / "src/modkit_workers/persistence/sql/manifest.json").read_text())[
        "migrations"
    ]
    require(
        own["depends_on"]
        == [{"component": "events", "version": 1, "migration_digest": pin["migration_digest"]}],
        "Workers dependency pin mismatch",
    )
    return pin


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--events-root", type=Path, required=True)
    parser.add_argument("--check-dependency-only", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    events = args.events_root.resolve()
    verify_dependency(root, events)
    if args.check_dependency_only:
        print("PASS: exact clean Events source and dependency digest")
        return
    env = clean_environment(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(
        str(p) for p in (root / "src", root / "tests", events / "src")
    )
    env["MODKIT_FROZEN_EVENTS_SQL"] = str(events / "src/modkit_events/persistence/sql")
    selection = (
        ["tests"] if os.name == "posix" else ["tests/" + name for name in selected_tests(os.name)]
    )
    subprocess.run(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            "-p",
            "pytest_asyncio.plugin",
            "-p",
            "_scalar_test_support",
            "--require-scalar-cases",
            "-q",
            *selection,
            "--junitxml=source.xml",
        ],
        cwd=root,
        env=env,
        check=True,
    )
    require_complete_tests(root / "source.xml")


if __name__ == "__main__":
    main()
