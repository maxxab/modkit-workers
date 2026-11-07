# Workers shutdown checkpoint: 2026-11-07

## Resume target and preserved work

- Resume in `/home/faris/modkit-local-20261106/baseline-plan-20261107-standalone-only/commits-v3/workers` on `wip/reviewed-standalone-20261107`.
- Last reviewed implementation commit: `d6e3e83dbd542b3bd7428347d2735503e64bd882` (partial callable validation), following `ad029d82f6b67414693c41bf0c2723cda3cad7fb` (pure root contracts and startup preflight).
- This checkpoint adds documentation only. Use `git log -1` to identify its containing commit. No implementation, dependency, runtime, service, or deployment changes were made.
- The live `/home/faris/modkit-workers` checkout remains on unborn `feat/prerequisite-completion`, with untracked source and no commit. Its worktree and index were deliberately preserved; do not reset, clean, broad-stage, or overwrite it.
- Both Workers checkouts have no configured remote. No push was attempted and no publication is claimed. A verified intended GitHub repository is required before configuring a remote or pushing.

## Fresh verification at checkpoint

The following bounded pure source suite completed successfully before this documentation commit: **117 passed, 96 subtests passed** (1.86 seconds).

```sh
cd /home/faris/modkit-local-20261106/baseline-plan-20261107-standalone-only/commits-v3/workers
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:../events/src \
  /home/faris/modkit-local-20261106/.test-venv/bin/python \
  -m pytest -q -p no:cacheprovider
```

This explicitly uses sibling Events source, not an installed distribution. It does not prove dependency resolution, wheel/sdist installation, real PostgreSQL/Redis behavior, performance, runtime execution, the cross-platform Python matrix, or deployment readiness. System `python3` has no pytest module; use the recorded existing environment.

The last implementation evidence is `../workers-root-contract-verification.json`. Older `../final-verification-standalone.json` and `../commit-report-standalone.md` describe the earlier Workers `6edbd62` snapshot and must not be mistaken for the current implementation checkpoint.

## Outstanding gates

1. Confirm the intended remote repository and publication scope. Inspect `git remote -v` first; do not invent a remote. Push only reviewed commits, then verify the exact branch SHA on the remote.
2. Resolve Workers' required `modkit-events>=0.2,<0.3` against the intended Events distribution. Current source-path tests do not settle distribution compatibility.
3. Complete strict artifact/resource auditing and clean installation qualification. Production SQL/manifest resources remain intentionally absent pending reviewed bytes; do not fabricate them to pass a gate.
4. Runtime workers, source execution, shutdown drain, actual service qualification, native driver/transaction evidence, and full release qualification remain pending.
5. Workers has no standalone runtime or deployment unit in this reviewed package. No Kubernetes change or rollout was performed for this project. ERP/application deployment must be checked separately; passing pure Workers tests is not Kubernetes evidence.

## Safe resume sequence

1. Start the desktop/WSL and inspect `git status --short --branch` and `git log -3 --oneline` in the resume target.
2. Preserve and compare the live untracked checkout separately. Continue reviewed work in the isolated repository unless integration is explicitly planned and reviewed.
3. Read `docs/worker-contracts.md`, `docs/job-persistence.md`, and `docs/package-layout.md`, then rerun the bounded command above after any implementation change.
4. Commit each successful scoped fix with its relevant checks. Do not mix unreviewed baseline work or secrets into staging.
5. Resolve publication and deployment blockers independently. Do not claim an upstream backup or a successful Kubernetes rollout until verified.
