"""Real sdist privacy regression; run separately with the declared Hatch backend.

    uv run --offline --no-project --with hatchling==1.33.0 \
        python tests/check_sdist_contents.py

The test builds only. It never installs, extracts, or imports a candidate archive.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import tempfile
import tomllib
from pathlib import Path


def main() -> None:
    source = Path(__file__).resolve().parents[1]
    config = tomllib.loads((source / "pyproject.toml").read_text(encoding="utf-8"))
    prefix = "modkit_workers-" + config["project"]["version"]
    private = (
        "docs/handoffs/private-sentinel.md",
        "docs/coordination/nested/private-sentinel.json",
        "docs/plans/private-sentinel.md",
        "docs/shutdown-checkpoint-20261107.md",
        "docs/shutdown-checkpoint-20991231.md",
    )
    public = (
        "docs/public/plans/guide.md",
        "docs/plans-help.md",
        "docs/handoffs-guide.md",
        "docs/coordination-guide.md",
        "docs/shutdown-checkpoint-guide.md",
        "docs/public/shutdown-checkpoint-20261107.md",
    )
    with tempfile.TemporaryDirectory(prefix="modkit-workers-sdist-") as directory:
        project = Path(directory) / "project"
        project.mkdir()
        for name in ("src", "tests", "docs"):
            shutil.copytree(
                source / name,
                project / name,
                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
            )
        for name in (
            "pyproject.toml",
            "README.md",
            "LICENSE",
            "CHANGELOG.md",
            "requirements-dev.txt",
        ):
            shutil.copyfile(source / name, project / name)
        for name in (*private, *public):
            target = project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("owned test sentinel\n", encoding="utf-8")
        subprocess.run(
            [sys.executable, "-m", "hatchling", "build", "-t", "sdist"],
            cwd=project,
            check=True,
            timeout=60,
        )
        with tarfile.open(project / "dist" / (prefix + ".tar.gz"), "r:gz") as archive:
            names = {member.name for member in archive.getmembers()}
        leaked = [name for name in private if prefix + "/" + name in names]
        if leaked:
            raise AssertionError("Private source-distribution documents leaked: " + repr(leaked))
        required = (
            *public,
            "docs/package-layout.md",
            "docs/job-persistence.md",
            "docs/worker-contracts.md",
            "tests/check_sdist_contents.py",
            "src/modkit_workers/py.typed",
            "tests/_resource_fixtures.py",
            "src/modkit_workers/persistence/sql/0001_initial.sql",
            "src/modkit_workers/persistence/sql/grants_runtime.sql",
            "src/modkit_workers/persistence/sql/manifest.json",
            "LICENSE",
        )
        missing = [name for name in required if prefix + "/" + name not in names]
        if missing:
            raise AssertionError("Public source-distribution files missing: " + repr(missing))
    print("PASS: private document trees excluded; public source, tests and guides retained")


if __name__ == "__main__":
    main()
