# Job acquisition SQL
W05 composes the shared Events E04 acquisition operation with complete job material.
Workers depends on Events; Events does not import or depend on Workers.
This source is NOT_READY. Native W05 qualification, production manifests/grants,
installed artifacts and adapter/runtime integration are not yet accepted.

## Contract
The existing seven inputs are namespace (exact bytes jobs), paired command/version
capabilities, limit1..256, lease duration, optional scan cursor and discovery budget.
E04 validates the common bounds and owns discovery, capability selection, Work locks,
claim state/token/revision/lease changes and history. W05 invokes it exactly once.
Acquisition does not increment attempts or authorize execution, E10 completion, secret
access or a second heartbeat. Applications retain authorization and transaction ownership.

The75-column result starts with one header and then at most limit complete claims.
Empty pages with positive visited preserve progress across locked or ineligible Work;
they do not prove queue exhaustion. The caller chooses when to continue or reset a pass.
Both SQL and the pure decoder check the full frame before a page is usable.

## Snapshot and lock boundary
E04 is VOLATILE and can see a producer committed after its invoking query began.
Therefore a direct outer join from E04 to job_payloads could use an older snapshot
and miss material for a successfully claimed job. A STABLE E15/W02 reread also cannot
replace E04's retained postimage.

W05 fully consumes E04, validates its header and claims, and stores all39 physical
Work fields in the existing shared composite type. Its17 additional resolution
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
checks do not execute PostgreSQL. Native tests must still prove fresh producer
visibility, actual claims/history, atomic late failure, locked-window progress,
paired capabilities, ACL/isolation and multi-row bounds without using E10.

A row limit is not a physical IO, latency or memory guarantee. The retained Work
array can duplicate large bounded inputs; practical resource budgets need qualification.
