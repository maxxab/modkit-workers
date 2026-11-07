# Workers shutdown checkpoint: 2026-11-07


## Further source-only continuation: 2026-11-07

- `56e60ed1d35a32b12bfb27d3d0457396b2cb147a` restores the already-selected sdist exclusions for `docs/handoffs`, `docs/coordination`, and `docs/plans`. A real Hatchling build first leaked all three private sentinel paths, then excluded them after the fix while retaining nested/similarly named public guides. Independent review repeated this archive-only check successfully. Run it explicitly with `uv run --offline --no-project --with hatchling==1.33.0 python tests/check_sdist_contents.py`; it is not pytest-discovered.
- The retained three pure W04 family regressions are now included unchanged as `tests/test_job_find_atomicity.py`. They cover a corrupt final candidate, cancellation identity after the first row, and bounded overflow probing. Separate subprocess-only source mutations each caused the intended targeted failure; no repository production source was changed by those controls. Independent focused review/QA passed.
- Current complete pure suite: **132 passed, 96 subtests passed**. Full Ruff and diff checks pass. Earlier artifact hashes below remain historical for their explicitly named source revision, not this updated tree.

The authoritative remaining SQL order is W01 real fixture qualification, followed by integration/qualification of the retained W02/W04 drafts. W03 still requires the Events E30 physical access contract; W05 requires the Events E04 lifecycle contract. Common runtime work remains downstream of A/B/C and the selected ownership/materialization/resource/drain contracts. This continuation does not bypass those dependencies, execute SQL, import/install candidates, change release versions, or edit the live WIP/Events/ERP checkouts. See the scoped continuation plan for retained evidence.

## Resume update: 2026-11-07

The original shutdown record below is historical. Subsequent reviewed source commits:

- `936c25352bd469d402e23a1352b8c5da18a8177a`: bound partial-backed handler inspection. Native async/generator shapes behind partial-backed `__call__` now validate correctly. Partial-function and callable-entrypoint cycles fail closed; traversal has a finite 64-object bound. Regression failures were observed before the fix, including isolated timeout-guarded cycle cases.
- `c35f20f68d7076846d0e1b2587997e4491126327`: clear all 88 baseline Ruff findings. Import compatibility and the intentional SQL package initialization are preserved. Independent review confirmed identical non-import ASTs throughout this cleanup.

Fresh checks on this source: **129 tests passed, 96 subtests passed**, full `ruff check src tests` passed, and `git diff --check` passed. Use the same bounded pytest command below. Ruff 0.17.3 is available through `/home/faris/modkit-local-20261106/.venv/bin/python -m ruff`.

Offline artifact checks now pass for the source at `c35f20f`: direct wheel and sdist builds, wheel rebuilt from that sdist, and exact equality of all 21 wheel member payloads. An isolated `python -I -S` zipimport smoke check against the real wheel verified pure handler/root import without Events. The real archive resource loader raises the expected `FileNotFoundError` for the deliberately absent production manifest. This is a narrow archive smoke check, not a complete installed distribution or platform matrix qualification.

Temporary build evidence is in `/tmp/modkit-workers-qualification-20261107` and may not survive cleanup/reboot. SHA256:

- Original and rebuilt `modkit_workers-0.1.0-py3-none-any.whl`: `d6e941e997a8cfb0d8dfee2d6ae52686b92fe6348b2d875f7c252d13fa1e9188`.
- `modkit_workers-0.1.0.tar.gz`: `2c48838e0fac4f12f33bdd52e4f3c4de005018106033779893c39449cac8434a`.

A real offline, no-index, dry-run install of the local Workers wheel and the reviewed Events wheel **failed dependency resolution without installing anything**. Workers requires `modkit-events>=0.2,<0.3`; sibling Events at `e5165c2` still builds version `0.1.0`. Do not bypass this by silently changing package versions, lowering requirements, or installing with ignored dependencies into ERP. The intended compatible release closure must be established first.

Production SQL/manifest resources, runtime execution/shutdown drain, real PostgreSQL/Redis/driver/transaction qualification, ERP integration and the cross-platform Python matrix remain open. No remote is configured, no push/publication occurred, and no ERP installation or deployment was attempted. The live unborn `/home/faris/modkit-workers` checkout remains unchanged. Continue only in this reviewed isolated branch unless an integration plan is explicitly reviewed.

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
