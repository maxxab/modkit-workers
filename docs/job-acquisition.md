# Job acquisition SQL
W05 composes the shared Events E04 acquisition operation with complete job material.
Workers depends on Events; Events does not import or depend on Workers.
This source is NOT_READY. The bounded native checks below passed; production
manifests/grants, installed artifacts and adapter/runtime integration remain open.

## Contract
The existing seven inputs are namespace (exact bytes jobs), paired command/version
capabilities, limit 1..256, lease duration, optional scan cursor and discovery budget.
E04 validates the common bounds and owns discovery, capability selection, Work locks,
claim state/token/revision/lease changes and history. W05 invokes it exactly once.
Acquisition does not increment attempts or authorize execution, E10 completion, secret
access or a second heartbeat. Applications retain authorization and transaction ownership.

The 75-column result starts with one header and then at most limit complete claims.
Empty pages with positive visited preserve progress across locked or ineligible Work;
they do not prove queue exhaustion. The caller chooses when to continue or reset a pass.
Both SQL and the pure decoder check the full frame before a page is usable.

## Snapshot and lock boundary
E04 is VOLATILE and can see a producer committed after its invoking query began.
Therefore a direct outer join from E04 to job_payloads could use an older snapshot
and miss material for a successfully claimed job. A STABLE E15/W02 reread also cannot
replace E04's retained postimage.

W05 fully consumes E04, validates its header and claims, and stores all 39 physical
Work fields in the existing shared composite type. Its 17 additional resolution
observation fields must be false/null, and those same values are returned unchanged.
After E04 finishes, one distinct SQL command LEFT JOINs those retained claims to
job_payloads in a fresh READ COMMITTED snapshot. No Work reread, duplicate claim
controller, new table/type, temporary table or helper codec is introduced.

E04's Work row locks stay held until the caller's transaction ends. The current
cooperative producer commits Work and its exact job subtype together. The subtype
trigger takes the Work lock on insertion and rejects all updates/deletes. Immutable
identity, no replacement/deletion, and this lock order make the retained postimage
and fresh material one coherent family. Future erasure, rotation, replacement or
writer changes invalidate this proof and require review before use.

Every missing or mismatched job half fails rather than disappearing through an
inner join. Repeated IDs, scope, protected binding, semantic input and complete
protected material are checked using the Events validator. PL/pgSQL buffers results
until the function succeeds. A corrupt final row aborts the entire statement,
including its E04 claims and history. Sequence gaps may remain after rollback.
W05 has no transaction control, error-catching retry or uncertainty reconciliation.

## Installation and limits
Installation checks the exact E04 header/Work ABI against the already checked
Events reader, same restricted owner, volatility, security-definer mode, language,
fixed search path and private ACL boundary. The function immediately revokes PUBLIC
and rejects nonowner default grants. Structural metadata does not prove substituted
function bodies preserve lock semantics; reviewed exact dependency bytes are still
required. Runtime grants and ready resource receipts remain absent.

Source tests check ordered ABI, retained field mapping, fresh material query and
private ownership. Pure decoder tests cover complete claims, exact capability pairs,
corrupt-final material, empty progress, cancellation and bounded overflow. These
checks do not execute PostgreSQL. The separate native evidence below does not
replace broader adapter, lifecycle and resource qualification.

A row limit is not a physical IO, latency or memory guarantee. The retained Work
array can duplicate large bounded inputs; practical resource budgets need qualification.


## Bounded native qualification
The following broader and upper-bound runs remain historical evidence against
frozen Events revision 60eac7a. They were not rerun for the current helper change;
the targeted current-dependency checks are described separately below.

PostgreSQL 18.1 and psycopg 3.3.8 passed one job-only disposable test invocation
against the reviewed Events E04 implementation and exact Workers SQL source.
The test first observed undefined-function 42883 before installing W05, then checked:
- Canonical 75-column output, exact 39-field retained claim postimage, false/null
  provenance fields, complete material fields, token/revision/lease and exact claim history.
  Claiming preserved attempt counts and did not dispatch or execute a handler.
- Protected sidecar material, exact paired capabilities, two-item claims,
  one-row discovery windows, empty progress/end-of-pass, invalid raw arguments,
  unsupported isolation, private function ACLs and denied runtime access.
- A valid claimed prefix followed by a missing final job half caused E15 inside
  E04 to reject the statement. All row/history changes rolled back; claim-history
  sequence allocation remained, as PostgreSQL permits.
- A genuine two-session schedule held a history-table lock while producer B was
  uncommitted. The claimer was observed waiting for that relation inside active
  E04. After B committed, E04 discovered it and W05 returned complete claims for
  both A and B. The external caller snapshot still saw only A. This exercises a
  commit after E04's invoking query began, not a gate before W05 invocation.
- A locked first candidate yielded visited 1, no claim and nonexhaustion with no
  row changes. Full claim rollback preserved both acknowledged producer rows.

Static call-closure review found no E10 invocation; native statistics corroborated
E10 = 0. All database sessions closed. The isolated database contained only two
lawful producer jobs and their two intake records before clean container disposal.
No live/shared service, application data, production grants or network was changed.

A separate native upper-limit test used the same PostgreSQL/driver versions and
reviewed SQL with 4353 lawful W01 submissions in one caller-owned transaction:
- The first page visited 4096 unsupported candidates, returned no claims and
  preserved every table row and sequence value while advancing the cursor.
- Continuation returned 256 complete protected job claims. Every returned field,
  fence, ten-second lease and full history row matched the database. Only expected
  claim fields and history changed; attempts and job material remained unchanged.
- A final unsupported candidate and then an empty page reached exhaustion without
  writes. The caller rolled back every submitted job and claim, restoring all
  transactional rows. Sequence allocation remained permitted.
The caller-owned test helper has no connection, transaction, setup or disposal
ownership. Four W05 calls and zero E10 calls were corroborated by native statistics;
the reviewed call closure excludes E10. This covers maximum row/discovery counts
with small fixture payloads, not maximum payload bytes or resource/performance limits.

This is bounded native evidence, not full conformance. The post-E04 W05
material-error branch was not fault-injected: existing cooperative writers cannot
change material there, and E15 rejects malformed families earlier. The missing-half
test must not be described as a later W05 material-phase failure. Lease/revision
edge schedules, maximum-byte payloads, peak-memory/physical-IO budgets, other
driver/interpreter/platform combinations and installed artifacts remain open.


## Current shared-helper dependency checks
Independent review accepted two targeted W05 SQL checks against Events revision
63b9f6c and Workers revision b44d1bf after the shared JSON-validation change.
A valid protected acquisition matched all 75 named PostgreSQL values and the
exact Work/history claim delta. Caller rollback restored all 13 fixture tables
to their baseline; sequence allocation remained, as PostgreSQL permits.

A later selected Work row with malformed replay produced PZ012, invalid neutral
work composition, through E15/E04/W05 after an earlier real claim had allocated
history. The caller rolled back the root and all 13 tables again matched the
baseline. The negative row deliberately had no job subtype: the exact neutral
error establishes rejection before missing-half validation, not malformed
complete-family or post-E04 material-fault coverage.

These checks qualify only the changed shared-helper dependency. Their oracle uses
named SQL values, not binary column order, emission order, a Python W05 native
decoder/profile or a complete store operation. The broader concurrency and
upper-bound results above remain historical; no new performance, resource-budget,
platform, production-grant or release qualification is implied.
The whole product remains NOT_READY.
