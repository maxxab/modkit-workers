# Native job preparations

This optional module supplies the fixed W01 submission and W02 complete protected-record read profiles to Events' shared native issuer. It does not manage transactions, execute handlers, grant access to protected material, or qualify the broader Workers runtime. Native PostgreSQL qualification and final installed-resource/grant checks are separate gates.

**Qualification status: NOT_READY.** Independent review accepted the source and bounded W01/W02 native checks against Events revision 63b9f6c and Workers revision b44d1bf. Actual preparation functions and the common issuer passed submission, complete protected-record and missing reads, identical duplicate submission, and caller-owned rollback/commit checks. The tested profile retained PostgreSQL 18.1, psycopg 3.3.8, libpq 180006, a 256 KiB string value, 20-second statement limits and one CPU. The Events SQL fix closes the original timeout regression for this profile.

Both scoped-key and direct-ID conflicts produced real PZ002 errors. Checks preserved the exact received primary and exception context, HELD operations, UNKNOWN roots and charged backing. Successful cases checked the paid result-borrow/release sequence, local oversized-input rejection, and unchanged hostile input/output adapter maps. Physical connection close in a conflict case is not a managed cleanup or refund receipt.

Earlier timeout and QA oracle/permission failures remain historical failures; successful completed phases do not make those entire attempts pass. These bounded results do not qualify the full store/runtime, production migrations/grants, installed artifacts, other driver/platform combinations, or throughput, peak memory and latency guarantees.

Import the named preparation functions and fixed capacities from modkit_workers.persistence.native_store:

- prepare_submit(execution, request: JobSubmitRequest, /, *, execution_ledger)
- prepare_read_job(execution, request: JobReadRequest, /, *, execution_ledger)
- SUBMIT_RESULT_CAPACITY
- READ_JOB_RESULT_CAPACITY

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

## Observation and error boundaries

W02 returns JobRecord or None, including complete Work/Resolution provenance and job material from one invoking-query snapshot. It validates all fields before any record is exposed. Missing or mismatched halves, malformed protected metadata and wrong identities fail as a whole. ERASED records retain original binding evidence but cannot supply executable material.

Public pure builders/decoders keep fixed-code sanitized PersistenceError behavior. Inside native preparation/execution, only deliberate raw validation rejection is translated to the appropriate managed error. Unexpected received exceptions and cancellation preserve the common issuer's primary-error contract. Do not put a broad pure-codec decorator around native execution or log raw inputs, result records, credentials or exception text.

No successful later statement, missing lookup, savepoint cleanup or new connection clears sticky uncertainty or authorizes replay. No automatic begin, commit, rollback, connection replacement, close or retry is performed by these Workers entrypoints.
