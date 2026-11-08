# Native job preparations

This optional module supplies the fixed W01 submission, W02 complete protected-record read and W03 bounded listing profiles to Events' shared native issuer. It does not manage transactions, execute handlers, grant access to protected material, or qualify the broader Workers runtime. Native PostgreSQL qualification and final installed-resource/grant checks are separate gates.

**Qualification status: NOT_READY.** Independent review accepted the source and bounded W01/W02 native checks against Events revision 63b9f6c and Workers revision b44d1bf. Actual preparation functions and the common issuer passed submission, complete protected-record and missing reads, identical duplicate submission, and caller-owned rollback/commit checks. The tested profile retained PostgreSQL 18.1, psycopg 3.3.8, libpq 180006, a 256 KiB string value, 20-second statement limits and one CPU. The Events SQL fix closes the original timeout regression for this profile.

Both scoped-key and direct-ID conflicts produced real PZ002 errors. Checks preserved the exact received primary and exception context, HELD operations, UNKNOWN roots and charged backing. Successful cases checked the paid result-borrow/release sequence, local oversized-input rejection, and unchanged hostile input/output adapter maps. Physical connection close in a conflict case is not a managed cleanup or refund receipt.

Earlier timeout and QA oracle/permission failures remain historical failures; successful completed phases do not make those entire attempts pass. These bounded results do not qualify the full store/runtime, production migrations/grants, installed artifacts, other driver/platform combinations, or throughput, peak memory and latency guarantees.

Bounded W03 native qualification is independently accepted on PostgreSQL 18.1, psycopg 3.3.8 and libpq 180006. The actual named preparation/common issuer passed the 256-small-record default page with complete 71-field comparisons, exact-budget success and late PZ013, high-INT8 budgets, a lawful second-key E04 snapshot, and original 57014 cancellation with HELD/UNKNOWN/no-refund containment. See [Job listing SQL](job-listing.md#bounded-qualification-of-the-native-five-argument-route) for the accepted scope, preserved failed coordination attempt and remaining limits.

Import the named preparation functions and fixed W01/W02 capacities from modkit_workers.persistence.native_store:

- prepare_submit(execution, request: JobSubmitRequest, /, *, execution_ledger)
- prepare_read_job(execution, request: JobReadRequest, /, *, execution_ledger)
- prepare_list_jobs(execution, request: JobListRequest, /, *, execution_ledger, max_page_payload_bytes=DEFAULT_LIST_PAGE_PAYLOAD_BYTES)
- SUBMIT_RESULT_CAPACITY
- READ_JOB_RESULT_CAPACITY
- DEFAULT_LIST_PAGE_PAYLOAD_BYTES (16,777,216 bytes)
- MAX_LIST_PAGE_PAYLOAD_BYTES (3,758,096,384 bytes)

The caller supplies its existing execution reservation, ledger and original active managed root. These functions reserve preparation backing before projecting the logical input. Native preparation uses the managed JSON bounds directly and never repeats JobInput's unrestricted logical snapshot. Existing pure builders remain unchanged.

## Explicit caller-owned operation

The following is the operation sequence inside an already configured caller-owned native lifecycle. Creation and termination of the root remain with the caller:

~~~python
from modkit_events.persistence import managed_lifecycle, native_execution
from modkit_workers.persistence.models import JobReadRequest
from modkit_workers.persistence.native_store import (
    READ_JOB_RESULT_CAPACITY,
    prepare_read_job,
)

preparation = prepare_read_job(
    execution, JobReadRequest(work_id=work_id), execution_ledger=ledger
)
ticket = managed_lifecycle.admit(root, preparation, execution_ledger=ledger)
result = managed_lifecycle.reserve_result(
    ticket, READ_JOB_RESULT_CAPACITY, execution_ledger=ledger
)
native_execution.execute(ticket, result, execution_ledger=ledger)
observation = managed_lifecycle.read_result(result, execution_ledger=ledger)

# Use this complete protected observation only within this paid borrow.
# None means absent in this read snapshot, not proof of an uncommitted mutation.
# Apply application authorization and an explicit allowlist before projecting it.

del observation  # Also stop using any aliases to its nested data.
managed_lifecycle.release_result(result, execution_ledger=ledger)
managed_lifecycle.release_ticket(ticket, execution_ledger=ledger)
managed_lifecycle.release_preparation(preparation, execution_ledger=ledger)
# The caller still owns root commit/rollback and connection cleanup.
~~~

Submission uses prepare_submit with JobSubmitRequest and SUBMIT_RESULT_CAPACITY, followed by the same common operation sequence. Its JobAdmissionObservation has work_id and inserted. This is a STAGED statement observation, never a commit acknowledgment. For a matching scoped key, inserted=False may report the existing original ID.

These are success-path releases, not an unconditional finally block. RUNNING or HELD operation backing must remain retained. Use Events' existing explicit failure and terminal-cleanup lifecycle, preserve the received primary and uncertainty, and never free a result while its observation or nested aliases remain borrowed. The package cannot revoke escaped Python aliases.

The native profile is cooperative and uses the installed package's fixed profiles, not application-supplied SQL or callbacks. Events remains independently usable without Workers. Pure imports do not import the optional native leaf or driver.

## Bounded job listing

W03 accepts JobListRequest(after=None or WorkCursor, limit=1..256). It returns one complete tuple of protected JobRecord objects, including an empty tuple. Every record, jobs namespace and strictly increasing (created_at, work_id) order after the optional cursor validate before the page is exposed. A corrupt final record or nonadvancing cursor invalidates the whole page.

Use the existing caller-owned execution, ledger and active root:

~~~python
from modkit_events.persistence import managed_lifecycle, native_execution
from modkit_workers.persistence.models import JobListRequest
from modkit_workers.persistence.native_store import prepare_list_jobs

preparation = prepare_list_jobs(
    execution, JobListRequest(after=after, limit=limit), execution_ledger=ledger,
    # Omit this keyword for the 16 MiB default; this example explicitly allows 32 MiB.
    max_page_payload_bytes=32 * 1024 * 1024,
)
ticket = managed_lifecycle.admit(root, preparation, execution_ledger=ledger)
capacity = managed_lifecycle.result_capacity(ticket, execution_ledger=ledger)
result = managed_lifecycle.reserve_result(ticket, capacity, execution_ledger=ledger)
native_execution.execute(ticket, result, execution_ledger=ledger)
page = managed_lifecycle.read_result(result, execution_ledger=ledger)

# Use the protected page only during this paid borrow.
del page  # Also drop all aliases to records and their nested data.
managed_lifecycle.release_result(result, execution_ledger=ledger)
managed_lifecycle.release_ticket(ticket, execution_ledger=ledger)
managed_lifecycle.release_preparation(preparation, execution_ledger=ledger)
~~~

Capacity comes from the exact retained request limit and payload budget, not an unverified caller count. There is no LIST_RESULT_CAPACITY constant. The full request-sized backing remains charged for short or empty pages until explicit release. These are success-path releases only; the failure, HELD and caller-owned root rules above still apply.

Only the named preparation supplies the 16 MiB default. An override must be an exact integer from 1 through MAX_LIST_PAGE_PAYLOAD_BYTES; explicit None, bool and out-of-range values reject under paid preparation. The budget counts the lengths of 14 large BYTEA output occurrences: intent_evidence, semantic_input, replay_input, protected_binding, result, resolution_record_result, resolution_record_evidence, resolution_record_binding, job_protected_binding, job_semantic_input, protected_sidecar, protected_reference, protected_recovery_metadata and projection_metadata. NULL contributes zero; repeated/equal fields count separately. Each field still has its existing 1 MiB cap. This is not a limit on logical JSON input, all wire bytes, Python graph size or process memory.

A larger override also requires sufficient configured result backing. On the measured Python 3.12.3 profile, limit 256 with the default requires about 59.18 MiB of conservative result backing, not a 64 MiB process-memory guarantee. Short scalar/carrier costs, simultaneous canonical/typed results, transport allowance and count/slot pools remain distinct. Capacity is queried from the retained ticket and independently enforced before SQL.

Native W03 requires the new private five-argument SQL overload with an explicit BIGINT budget. The four-argument pure listing API remains unchanged. An older installation without the overload fails normally; there is no fallback to the unbounded route or automatic installation.

If a valid selected page exceeds the budget, the server raises PZ013 with message "W03 page payload budget exceeded" before releasing any page. It never truncates the result, reduces the row limit or increases the budget. The received driver error and existing HELD/root UNKNOWN backing rules remain intact; the caller owns explicit recovery from PostgreSQL's statement-error state. No rollback, savepoint, retry or refund is implicit. This bounded qualification does not qualify the full store, W04/W05 native paths or production installation and grants.

## Observation and error boundaries

W02 returns JobRecord or None, including complete Work/Resolution provenance and job material from one invoking-query snapshot. It validates all fields before any record is exposed. Missing or mismatched halves, malformed protected metadata and wrong identities fail as a whole. ERASED records retain original binding evidence but cannot supply executable material.

Public pure builders/decoders keep fixed-code sanitized PersistenceError behavior. Inside native preparation/execution, only deliberate raw validation rejection is translated to the appropriate managed error. Unexpected received exceptions and cancellation preserve the common issuer's primary-error contract. Do not put a broad pure-codec decorator around native execution or log raw inputs, result records, credentials or exception text.

No successful later statement, missing lookup, savepoint cleanup or new connection clears sticky uncertainty or authorizes replay. No automatic begin, commit, rollback, connection replacement, close or retry is performed by these Workers entrypoints.

## W04 comparison-only lookup

The source API also provides
prepare_find_jobs(execution, request: JobFindRequest, /, *, execution_ledger)
and FIND_JOBS_RESULT_CAPACITY. W04 has no aggregate-page budget option. It
retains seven lookup parameters and a complete immutable admission comparison
context, using the same caller-owned root and paid preparation/result lifecycle.

The complete result is JobIdentityObservation: NEW for no candidates, MATCH for
one identical job admission, or CONFLICT for a different admission or two
candidates. A direct-ID inbox collision is a valid conflict with no job half.
All candidates are validated before any result is published. A match by key may
return a different original work ID. Original protected identity remains
comparable after material erasure; lookup never restores material, submits,
claims work, or establishes execution readiness.

The caller must reserve FIND_JOBS_RESULT_CAPACITY and retain the result borrow
while using any nested candidate data. Apply application authorization before
exposing protected data. This fixed capacity accounts for both candidates and
transport overflow detection, rather than only the small ordinary-case result.

**W04 bounded native qualification passed; full Workers remains NOT_READY.**
Seven real native lookup cases covered NEW, direct/key MATCH, and single/two-
candidate CONFLICT, including inbox and mixed inbox/job families, with all 72
fields compared. The checked fixed preparation/result reservations were
3,156,870 and 119,667,132 bytes. Caller-owned root identity, staged visibility,
rollback, and the original PZ005 error with held accounting passed. The same
run ended with graceful exit 0 and nonforced fixture/socket cleanup.

This bounded result does not qualify positive-resolution native records,
native concurrency, maximum-sized cells, upper-bound resource behavior, or
performance. It does not establish broader store/runtime, installation or
release readiness, and does not borrow W03 qualification.


## W05 bounded native acquisition

`prepare_acquire(execution, request: JobAcquireRequest, /, *, execution_ledger,
max_page_payload_bytes=DEFAULT_ACQUIRE_PAGE_PAYLOAD_BYTES)` prepares one complete
claim page. The default is 16 MiB. The override must be an exact integer in
1..4294967296; explicit `None`, `bool`, and floating-point values reject.
The seven business parameters and empty return context remain unchanged. The
budget is retained on the ticket and passed only as the eighth SQL argument.
Use the same admit/reserve/execute/borrow/release lifecycle shown above, deriving
capacity from the retained ticket. There is no fixed acquisition capacity constant.

Unlike W03, acquisition counts **every** nonnull BYTEA and UTF-8 TEXT occurrence
in the 75 canonical fields, including framing strings and repeated Work/job
values. NULL costs zero variable bytes; fixed containers and scalar objects are
accounted separately. Header-only costs six bytes, so budgets 1..5 deliberately
cannot return even an empty page. Exact-budget pages are accepted; a page one
byte over budget fails as a whole. No silent budget increase or partial page
is allowed. Limit 1..256, capability count 1..256 and discovery budget up to
4096 are unchanged. Capabilities remain paired, not a cross product.

The native path requires the new private eight-argument W05 and nine-argument
E04 overloads. Their old SQL bodies and the public pure APIs are unchanged.
E04 bounds its retained claims; W05 independently bounds retained Work,
preflights only material presence/lengths before the wide ordered material query,
and checks actual complete-page charge. Both fresh material commands rely on
held Work locks and immutable/no-delete job material. There is no postclaim
Work/E15 reread, cursor reset or lease extension. The result is a complete
ScanPage of JobClaimObservation records whose Fence matches the retained Work
postimage. A structural claim does not establish application execution readiness.

PZ005 denotes unsupported isolation, PZ006 invalid arguments, PZ012 invalid
framing/composition/field bounds and PZ013 aggregate acquisition-budget overflow.
A server statement failure rolls back that statement's claim/history changes;
sequence allocation may remain. A later transport/decoder failure does **not**
prove rollback: keep the caller-owned root, original error, HELD/UNKNOWN and
no-refund rules. No automatic transaction control, retry or recovery is added.

**The bounded W05 native run passed; independent result/document acceptance
is complete. Full Workers remains NOT_READY.** The one-shot reviewed packet
completed with exit 0 and empty stderr on PostgreSQL 18.1 using the selected
native issuer. Its evidence is pinned by runner SHA256
`bc9425741f936b3364fa0cff701d6851860355e4bc3528dc604e7785e27c2969`
and input-manifest SHA256
`805c043652ce8b041b148f91e4982faaf55dfc3baa000d29f87a107f989db36f`.

The bounded run covered:
- Header-only success at Q=6 and PZ013 at Q=5; 256 complete claims with
  256 paired capabilities, including maximum-width command identifiers and
  INT4 versions. The actual issuer checked all 75 binary column names, OIDs
  and formats plus the cap_ok transport column, with 257 header/item rows.
  Supported local arrays and fractional FLOAT8 lease binding were exercised.
- An independently measured exact occurrence budget accepted the complete
  256-row page; Q-1 raised PZ013 with statement rollback. A separate targeted
  E04 expected-postimage budget rejected the second candidate after the first
  claim had allocated history: transactional rows were restored and the history
  sequence advanced by exactly one. The whole-page Q-1 case alone does not
  identify its rejecting stage.
- Actual managed-issuer empty and 256-row success, including a repeat at exact
  Q, retained caller-root identity, uncommitted observer visibility, result
  borrowing and explicit release/rollback. PZ013 preserved the original driver
  exception and its cause/context/suppression, left the operation HELD and root
  UNKNOWN, and denied result reads/refunds without changing retained counts.
- A producer committed while acquisition waited inside E04: both complete
  protected claims became visible although the outer query snapshot saw only
  the first. A locked first candidate advanced visited progress without a
  claim or write. Corrupt late replay and missing material were rejected via
  the preclaim E15 path, not an injected post-E04 material fault.

The same disposable fixture then shut down gracefully with SIGTERM and exit 0;
nonforced removal and subsequent absence were verified. No runner replay was
needed. Historical evidence elsewhere remains tied to its original pins.

Independent consolidated source review and 69 scoped pure checks also passed.
The new adapter transients have finite bounds under construction ownership and
the inherited supported-driver assumptions. D remains a construction slot,
**not numeric byte admission or a total-memory bound**. Q and the result graph
formula are not RSS, native-allocator, backend-memory, latency or throughput
guarantees. PostgreSQL executor/TOAST/WAL, per-row scratch and temporary array
coexistence remain distinct. This run did not inject post-E04 material faults,
async cancellation/transport loss, natural cursor-close failure or unknown
commit outcomes, and did not exercise maximum multi-GiB payloads. It does not
establish production installation/grants or release readiness.
