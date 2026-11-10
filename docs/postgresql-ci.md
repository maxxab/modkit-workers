# Workers PostgreSQL composition CI

## Design and scope

Use a fresh GitHub-hosted PostgreSQL 17.11 service to test the installed Workers
package over its verified Events dependency. This is a separate synthetic
installation/ACL gate, not a deployment or native recovery runner. The existing
local/cloud databases and historical native packets are not used.

The selected approach follows the already passing Events fixture at
`9362f0d318c762283f70b18c4f2907f1fda39f8b`. A standalone, Workers-specific checker
keeps the fixed repository/context/database guards explicit. Importing the Events
checker while bypassing its Events-only entry guard would obscure the scope;
installing PostgreSQL on a shared computer would add unnecessary persistent state.
Neither alternative is used. Events product bytes are identical to the earlier
`ef84ecbe3fdc65c7922ea954e619c1743efc7f67` pin.

Use the same immutable official image digest as Events, loopback-only access, a
ten-minute job limit, no persistent volumes and no existing secrets. Public
synthetic fixture credentials create only a fresh bootstrap login plus four
least-privileged fixture logins and their NOLOGIN product roles. Bootstrap closes
before installation. Actions owns teardown; no custom cleanup or uncertain retry
is allowed. The checker refuses existing roles, schemas and public objects,
inherited PostgreSQL environment values, arbitrary arguments and other targets.

## Implementation plan

> For agentic workers: use the existing assigned native worker and
> superpowers:executing-plans for implementation, with independent peer review.

Architecture: an isolated installed-pair checker against a disposable hosted
PostgreSQL service. Tech stack: GitHub Actions, Python3.13.5, psycopg3.3.8, SQL.
Spec: the Design and scope section above.

Goal: prove the exact installed pair's composition order, transaction/receipt and
least-privilege SQL boundaries on a fresh fixture.

Files: add `scripts/check_postgres.py` and `tests/test_postgres_ci.py`; update the
workflow, pinned dependency, source-only test inventory and this document. No
production source changes are planned. The existing package/finite-profile lanes
remain required and do not gain service access.

- [ ] Add failing offline controls for fixed CI context/target, clean-server
  refusal, the exact dependency digest, the seven Worker signatures and ACLs,
  and entry refusal before driver import. Preserve the empty-service regression.
- [ ] Implement the fixed fixture guard/bootstrap, then verify Workers SQL fails
  without Events under a correctly selected owner with CREATE and no-login flags.
  Require the intended PZ011 namespace/dependency error, acknowledged transaction
  rollback and an independent observer confirming no residual schema.
- [ ] Install Events SQL/grants and its six-field owner receipt in a transaction.
  Then install Workers SQL/grants and its receipt, prove intentional rollback,
  uncommitted isolation and acknowledged commit. Use Events' unchanged shared
  receipt template with Workers values; never rewrite packaged SQL placeholders.
- [ ] Compare the actual Workers catalog with all seven exact signatures and
  security attributes, not merely a count. Check the complete three-role execute
  matrix, actual receipt/W02 reads, forbidden table/schema/function access and
  owner/bootstrap role-switch refusal. This does not test all job semantics.
- [ ] Build and audit both wheels from verified source, install outside both
  checkouts, and run the checker using isolated exact Python 3.13.5/psycopg3.3.8.
- [ ] Run focused/full offline, lint/format/type, build/private-file checks;
  independently review the executable scope before publication. Commit and push,
  then inspect exact-commit hosted results and preserve failed evidence honestly.

## Acceptance and remaining limits

A successful run proves only this fresh installed-pair installation, receipt,
rollback and ACL scope. It does not qualify managed native transport, runtime job
semantics, fault/recovery scenarios, optional service combinations, deployment,
ERP integration or release readiness. Old UNKNOWN outcomes and consumed grants
remain unchanged. No real PostgreSQL result is claimed until the hosted job passes.


## First hosted execution and correction

[Run 42770801673](https://github.com/maxxab/modkit-workers/actions/runs/42770801673)
passed all nine package/standards jobs. The new PostgreSQL job passed fresh fixture
setup and the missing-Events refusal, then failed while parsing the packaged
Workers grants script. Both preflight and postflight used an unparenthesized CASE
expression in an IF condition; PL/pgSQL treated the inner THEN as the end of the
condition. Parenthesizing each complete CASE expression preserves the same ACL
checks and permits parsing. The manifest resource hash and aggregate are updated
for these exact bytes. No grants or function contracts are weakened.

The same hosted PostgreSQL composition job is the end-to-end regression. Offline
parser red/green checks reproduce the syntax failure and verify the narrow grammar
correction; they do not replace actual PostgreSQL 17 execution. A new hosted result
is required before claiming this installation gate passes.

The follow-up [run 42771956699](https://github.com/maxxab/modkit-workers/actions/runs/42771956699)
passed the corrected syntax boundary but exposed a name collision: the private
function ACL subquery used `role_row` as a table alias, also the name of a
PL/pgSQL record last populated with only an `oid` field. PostgreSQL resolved
`role_row.rolname` to that record and raised UndefinedColumn. Both preflight and
postflight now use the distinct `checked_role` SQL alias. The privilege predicates
are unchanged; the resource hash and migration aggregate reflect this correction.
The complete hosted installation regression must still pass before qualification.
