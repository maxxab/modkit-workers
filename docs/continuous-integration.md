# Package CI design and verification plan

## Scope and approach

Use conventional GitHub Actions with immutable action and dependency source pins.
The Events checkout is verified before building; its exact migration dependency is
checked against Workers before tests. CI installs local wheels in a new environment
outside both checkouts, then checks origins, metadata, package bytes, resources and
portable behavior. These package lanes do not start databases or run recovery.
A separate [synthetic PostgreSQL composition lane](postgresql-ci.md) has its own
fixed fixture, authorization and qualification scope.

A source-only job cannot prove packaged behavior. A second custom native launcher
would add unnecessary complexity. The chosen approach therefore combines ordinary
pytest/build tools and a small installed-wheel check, following Events' existing CI.
The current operational/native evidence remains separate and immutable.

## Implementation plan

- Add regression tests for exact wheel membership/RECORD/source bytes, sanitized
  child environments and a nonempty zero-error/zero-failure/zero-skip XML gate.
- Add `scripts/check_wheel.py` and `scripts/check_installation.py`. Use an explicit
  portable test list, no source directory in the staged tree, and installed origin
  checks before and after tests. Keep source-oracle tests in the source lane.
- Add pinned Events source/digest configuration and a source runner which supplies
  required test-helper import paths and checks the dependency before pytest.
- Add full Linux/macOS Python 3.12/3.13 source and installed lanes, exact Linux
  3.12.3/3.13.5 profile rows, and a Windows portable/unsupported-backend lane.
- Include CI scripts in sdists and retain the existing private-document exclusion
  regression. Build and Twine checks do not imply rebuilt-sdist qualification.
- Independently review, run local full and installed checks, commit/push, and inspect
  hosted jobs. Report unexecuted platforms and native gates honestly.

## Review focus

Reject wrong dependency source/digest, forged wheel inventory/RECORD, checkout import
leakage, missing/empty/skipped tests and unsupported-platform success claims.
Windows runs portable behavior and the real unsupported resource-backend contract;
it is not full Windows product acceptance. Finite recovery profile observation is
not PostgreSQL execution. No all-process sandbox claim is made for pytest children.

## Local verification before publication

The exact Events dependency is `ef84ecbe3fdc65c7922ea954e619c1743efc7f67`,
with migration aggregate
`0a17c42c4abaade875770ddc587a3c80347259e2e29d4ad13a308cc244b9fe67`.
The corrected Workers wheel is
`9d6bdab44ab7806ea63cb69c09b2775c1e728d12ed2618e688dbfb01085da222`;
the paired Events wheel is
`4df4d6744a5fd88320bdb143685e8f844f58642f5bfc773c7912aea08d8cb25e`.

The initial tooling regression failed before the checker existed. Local full
Python 3.13.5 source verification and fresh Linux Python 3.12.14 installation
passed. The installed pair ran 702 tests and 96 subtests with no failures or skips;
both pre/post installed origin, byte and dependency checks passed. Build, Twine,
formatting, lint, both explicit consumer-type files and the sdist private-document exclusion regression passed.
Three existing Python 3.13 FutureWarnings about partial callable descriptors
were reported, not suppressed. This initial local checkpoint preceded the hosted
corrections and final result recorded below.

Use `python scripts/check_source.py --events-root PATH` for source tests and
`python scripts/check_wheel.py WORKERS_WHEEL EVENTS_WHEEL --events-root PATH`
for a fresh installed pair. PATH must be a clean checkout of the exact dependency
commit. No native readiness or full Windows acceptance follows from these checks.


## Hosted platform corrections

The first hosted run exposed three test/CI assumptions, not a native-profile
extension: its private standards checkout was unavailable to the repository token,
macOS aliases its temporary directory, and newer Python 3.13 patches are outside
the finite scalar recovery contract. Standards now uses the already public,
immutable Events checkout and verifies its exact commit. Test-owned temporary
roots are canonicalized once, with alias and escape regressions.

The scalar contract remains unchanged: CPython 3.12 retains its existing scope;
3.13 scalar acceptance requires exact Linux x86_64 GIL-enabled 3.13.5. Only tests
whose configuration or scalar material depends on that real host are explicitly
marked. The CI plugin deselects these individual acceptance cases on unsupported
hosts and reports the count. Other tests, including simulated boundary checks and
the mandatory actual-host acceptance/refusal check, remain selected. No whole
module is excluded and no failed test is converted into a skip. Supported lanes
must contain profile-dependent cases; both exact Linux lanes remain required.
The installed lane copies the same test metadata and checks the installed package
outside the checkout. Zero-error/failure/skip enforcement remains unchanged.

Broad unsupported rows are portable/refusal evidence, not full scalar acceptance.
Actual hosted results remain the authority for platform qualification. None of
these checks starts PostgreSQL, Redis or a native recovery operation.


## Verified package CI result

All nine jobs passed for commit `0c4933364cd474998327f7b7d361e475fa34a9fa`:
[hosted run 42760874019](https://github.com/maxxab/modkit-workers/actions/runs/42760874019).
This includes standards, Linux/macOS/Windows 3.12 and 3.13, and exact Linux 3.12.3
and 3.13.5. Each platform passed its declared source and installed-wheel contract;
unsupported scalar hosts ran portable/refusal checks, not scalar acceptance.

Local final source checks on actual CPython 3.13.5 passed 776 tests and 98 subtests,
with 88 scalar cases selected and no skips. The final fresh installed pair on
CPython 3.12.14 passed 717 tests and 98 subtests, with the same 88 scalar cases and
no skips. A controlled version simulation checked unsupported-host deselection;
it was not a new interpreter/platform qualification. Build, Twine, private-file
exclusion and both explicit consumer-type checks passed. The package wheel hashes
above remain unchanged. Genuine PostgreSQL installation/ACL, native recovery,
optional services, downstream ERP integration and release gates remain separate.
