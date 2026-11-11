# Restore selected artifact exclusions

Goal: carry forward the existing approved Workers source-distribution exclusions into the reviewed isolated branch. The accepted live package already excludes docs/handoffs, docs/coordination and docs/plans; the isolated branch lost this configuration.

Architecture: retain all public source, tests and documentation. Add only the three anchored Hatch sdist exclusion patterns already selected by the artifact design. A standalone archive test builds a real sdist from an owned temporary project copy with private and public sentinel documents. No candidate import/install, SQL execution, runtime implementation, shared Events or ERP changes.

- [x] Write the black-box sdist regression in tests/check_sdist_contents.py. Private sentinels must be absent; public nested and similarly named paths plus all normal public docs must remain.
- [x] Run against current pyproject and capture the expected privacy failure.
- [x] Add the three selected exclusion patterns in pyproject.toml; rerun the real artifact check.
- [x] Run the full pure suite, full Ruff and diff checks; independently review; commit only this fix and test.
- [x] Port the separately accepted three pure W04 family-atomicity regressions, verify their recorded contracts on current source, and commit separately.

Remaining runtime/SQL dependency gates are unchanged: W01 real qualification precedes W02/W04 integration; W03 depends on Events E30 physical access and W05 on E04 lifecycle. No production resource or installation readiness follows from these source checks.

Artifact red/green observed: baseline sdist leaked all three private sentinels; corrected sdist excludes all three and retains four similarly named/nested public sentinels plus source/tests/guides. Independent review repeated the exact offline Hatchling 1.33.0 checker and accepted this bounded result. This checker is standalone and must be invoked explicitly; it is not pytest-discovered.

W04 coverage port: the retained three-test test_job_find_atomicity.py is copied unchanged. All three pass against current source. Three isolated subprocess-only mutations independently caused the intended targeted failures: discard the final candidate, swallow cursor cancellation into NEW, and exhaust the overlong stream. Repository production source was not changed by these controls. This is pure decoder validation, not SQL execution or real driver qualification.
