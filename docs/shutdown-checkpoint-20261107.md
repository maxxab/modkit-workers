# Workers shutdown checkpoint: 2026-11-07


## Further source-only continuation: 2026-11-07

- `56e60ed1d35a32b12bfb27d3d0457396b2cb147a` restores the already-selected sdist exclusions for `docs/handoffs`, `docs/coordination`, and `docs/plans`. A real Hatchling build first leaked all three private sentinel paths, then excluded them after the fix while retaining nested/similarly named public guides. Independent review repeated this archive-only check successfully. Run it explicitly with `uv run --offline --no-project --with hatchling==1.33.0 python tests/check_sdist_contents.py`; it is not pytest-discovered.
- The retained three pure W04 family regressions are now included unchanged as `tests/test_job_find_atomicity.py`. They cover a corrupt final candidate, cancellation identity after the first row, and bounded overflow probing. Separate subprocess-only source mutations each caused the intended targeted failure; no repository production source was changed by those controls. Independent focused review/QA passed.
- Current complete pure suite: **132 passed, 96 subtests passed**. Full Ruff and diff checks pass. Earlier artifact hashes below remain historical for their explicitly named source revision, not this updated tree.

The authoritative remaining SQL order is W01 real fixture qualification, followed by integration/qualification of the retained W02/W04 drafts. W03 still requires the Events E30 physical access contract; W05 requires the Events E04 lifecycle contract. Common runtime work remains downstream of A/B/C and the selected ownership/materialization/resource/drain contracts. This continuation does not bypass those dependencies, execute SQL, import/install candidates, change release versions, or edit the live WIP/Events/ERP checkouts. See the scoped continuation plan for retained evidence.

### W01 bounded pure compatibility

The independently reviewed offline harness in `docs/coordination/w01-pure-compatibility-20261107/` matched **84 required normalized records** between the frozen original and reconciled current Events Python sources, with identical packet-pinned live Workers source on both sides. Six comparator-only controls confirmed sensitivity to semantic/result, bool/int and mutable/immutable container differences. Post-run input pins and the original packet remained stable. Static Ruff lint/format checks passed. No production source was changed.

The first run stopped on an incorrect harness oracle: the public decoder lawfully accepts canonical UUID strings. That expectation was corrected and independently reviewed before the successful rerun; malformed/braced spellings are rejected. This evidence covers the documented public preparation, canonical/protected bytes, snapshots and W01 submit-result decoding cases only. It does not establish exhaustive Python compatibility, real admission/SQL/transactions, target identity/setup/disposal, native/runtime readiness or ERP compatibility. Full-project suite results below remain historical; the existing frozen W01 packet is still not repinned or released.

### W01 source-only reconciliation

`docs/coordination/w01-reconciliation-20261107/README.md` records independently accepted source evidence, not runtime compatibility or a replacement packet. Of 189 frozen inputs, 181 still match and eight Events inputs changed; all Workers, fixture/runner and pinned driver files match. Seven changed Python originals were recovered by exact hash, and all nine diffs (including new, not proven reachable `native_codec.py`) were reproduced independently. The old SQL prefix remains exact. All 190 current observed pins were stable at the final recorded source-only check.

Do not blindly refresh the frozen fixture-v3 hashes. W01 preparation, nonempty admission context, canonical bytes, protected bindings and result decoding require reviewed compatibility checks against the changed Events public paths. The new private raw context helpers are not substitutes for W01. The frozen runner also targets a different host/database than the captured Events v58 container. Any future native run needs target-specific reviewed identity/prestate, setup/disposal scope and exact authorization. No fixture/package/driver import, test suite, source-check script, SQL execution, target probe, lease or attempt marker occurred in this reconciliation; previous pure-suite results remain historical.

### Shared SQL freshness correction

Do not reuse the old statement that E04 has no implementation. Current live Events SQL is 290,583 bytes, SHA256 `6cf0c7d1fb6baaccf98b5aaf0e3ed15c55c12941c4e73d45d083d948ec9a5534`, and defines E04. The Events handoff records bounded independently accepted owner-mode first-claim and later boundary/pagination work; this is not complete lifecycle/driver/resource qualification. E30 remains absent from this exact source.

The frozen Workers W01 fixture-v3 packet still pins the earlier 241,339-byte Events SQL `5042eb8a0ce5715a573f0e5260b8761d8c7fbfbd0da13d412b51217582585d42` and reports `PROPOSED_NOT_RUN_NO_LEASE_E10_AND_NAMESPACE_BEHAVIOR_QA_PENDING`. The current file preserves that entire pinned prefix exactly, but its whole-file hash differs. Reconcile and independently review a new packet rather than editing or running the frozen one.

W05 still needs a reviewed complete Work/job-half capture boundary. Current E04 returns a 60-column header/retained-Work-postimage stream and intentionally does not call a STABLE reader after mutation. The Workers catalog requires the additional 15 job-half columns with its same-statement composition contract. Do not assume a later E15/raw-half read or an outer join to a volatile call supplies that contract; select and review the shared composition boundary with Events before implementing it. No shared source change or SQL experiment was performed here.

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
