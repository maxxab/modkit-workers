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
