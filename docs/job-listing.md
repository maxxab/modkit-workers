# Job listing SQL

W03 lists complete jobs in the caller's read-committed PostgreSQL transaction.
It accepts the existing namespace, optional (created_at, work_id) cursor, and limit
parameters. The namespace must be the bytes for jobs. Both cursor fields must be
present or absent, timestamps must be supported, and limits are 1 through 256.

The SQL filters the exact job kind before selecting the page, so inbox work in
the same namespace cannot consume the limit. Ordering is ascending by created_at
and work_id. The tuple cursor excludes the last returned row and preserves UUID
ordering for equal timestamps. Concurrent commits behind a passed cursor may
still be missed; listing is not a durable change feed or proof of non-commit.

The Events-owned work_jobs_created_page partial index supports both initial and
continuation scans. Installation checks its keys, method, predicate, ownership,
and validity. A limit bounds the number of checked families, not elapsed time or
all physical I/O. Applications still own timeouts and resource limits.

Each selected ID is joined to the complete Events reader and raw job material in
one statement snapshot. Missing or mismatched halves fail the entire call.
PostgreSQL buffers PL/pgSQL results until completion, so a corrupt final row does
not release a usable prefix. The Python decoder separately validates the full
page before returning it. Protected internal records still require application
authorization and explicit safe projection before external exposure.

W03 is STABLE, SECURITY DEFINER, uses a fixed search path, and neither writes nor
allocates a sequence value. It does not start or finish the caller's transaction.
PZ005 means unsupported isolation, PZ006 invalid arguments, PZ012 invalid stored
composition, and PZ011 an invalid installation boundary.

## Native aggregate-bounded overload

The additive private signature w03(bytea,timestamptz,uuid,int4,int8) accepts an explicit aggregate payload budget. It has no default SQL argument. The named Python prepare_list_jobs supplies a 16 MiB default and allows an exact integer override from 1 through 3,758,096,384 bytes. The four-argument function, its messages and the public business descriptor remain unchanged.

The bounded route first selects only ordered job keys. It reads each key through the existing STABLE W02 complete-record reader on the invoking statement snapshot, rechecks identity/order and all native variable-field caps, then checks the cumulative BIGINT payload before appending that row. Its preflight pins W02's exact one-row body, catalog shape and owner. It does not call the old four-argument W03 to materialize a page.

The aggregate sums these 14 BYTEA output occurrences independently: intent_evidence, semantic_input, replay_input, protected_binding, result, resolution_record_result, resolution_record_evidence, resolution_record_binding, job_protected_binding, job_semantic_input, protected_sidecar, protected_reference, protected_recovery_metadata and projection_metadata. Each has a 1 MiB field cap; NULL is zero, and duplicate/equal byte values count repeatedly. Native SQL separately bounds the complete source aggregate and suppresses variable cells before transport if that source breaks its contract.

An oversized valid page raises PZ013, "W03 page payload budget exceeded", as a whole, including overflow on its final row. Field-bound violations remain PZ012. No prefix, changed row limit, automatic budget increase or retry is returned. The caller owns recovery from the failed statement; the native issuer preserves the received exception and HELD/root UNKNOWN lifetime. This admitted-payload bound is not a backend/client RSS, CPU, physical-I/O or temporary-disk guarantee.

The new function immediately revokes PUBLIC access, then checks the exact five-argument function and schema ACLs for every nonowner grant, including installer default grants. It does not modify defaults or grant runtime access. Future authorized installation must use the caller's transaction so a failed boundary check rolls back DDL. Existing production manifests/grants remain absent; older installations without the overload fail rather than auto-installing or falling back.

See [Native job preparations](native-job-store.md) for retained-ticket capacity and caller-owned borrowing.

## Bounded qualification of the native five-argument route

Independent review accepted these actual checks on PostgreSQL 18.1, psycopg 3.3.8 and libpq 180006:

- The named preparation/common issuer returned 256 small records under the 16 MiB default, with ordered IDs and all 71 fields checked. Empty and non-null cursor pages and budget binding above INT4 through the maximum also passed.
- A lawful three-record page succeeded at its exact 3,149,128-byte payload budget. One byte less produced the original late PZ013, no exposed prefix, HELD/UNKNOWN and no backing refund.
- A genuine E04 claim changed only the second key while listing waited. The returned complete page retained both historical queued records; a fresh read observed the second job claimed. This proves the tested same-statement Work-state snapshot, not concurrent material mutation.
- Actual cancellation retained the original 57014 exception and its chain, one cursor-close attempt, HELD operation, UNKNOWN root and charged backing. Physical teardown was not a managed resolution or refund.
- Exact overload catalog/ABI/private ACL checks and default-EXECUTE, schema-USAGE and W02-volatility negatives passed with rollback restoration.

Owner-replaced SQL projection controls separately checked aggregate/cap/sentinel guards. They are not native issuer execution against faulted definitions or genuine resolved-lifecycle proof.

The original coordinated attempt failed after completing its earlier phases. Those successful phases remain separately accepted; later remaining-only snapshot/cancellation success does not relabel the failed attempt. The exact disposable fixture was subsequently stopped and removed under separately accepted disposition.

## Bounded qualification of the existing four-argument route

PostgreSQL 18.1 with psycopg 3.3.8 in a separate disposable Linux database passed:
- A genuine missing-body 42883 failure before W03 installation, followed by the
  exact source installation, canonical ABI and private ACL checks.
- Empty/inbox-only pages and three lawful jobs split across ordered pages.
  A real E01/E03 inbox in the jobs namespace did not consume the job page limit.
- Protected material, continuation/end pages, timestamp cursor boundaries with
  UUIDs below/equal/above a lawful row, and limit 256 against three rows.
- Invalid namespaces, limits, paired cursors, infinite time and isolation levels.
- A valid prefix followed by an incomplete final job failed the whole call.
  This rollback-only missing-half negative does not qualify arbitrary corruption.
- Complete table rows and sequence scalars stayed unchanged for each read.
  Default-privilege and malformed-index installation negatives rolled back.
- The discovery partial index was used for initial and continuation plans,
  including the tuple cursor as an index condition. The small-table default
  material join used a sequential scan; there is no physical-I/O bound claim.

Only three explicit W01 calls seeded jobs; listing did not submit jobs. Static
call-closure review found no E10 invocation, corroborated by zero completed E10
calls. The test transactions left no business rows or other sessions. Pure
controls separately cover tied multi-row ordering and mismatched material halves.

The whole product remains NOT_READY. Full-store behavior, W04/W05 native paths,
production migrations/manifests/runtime grants, installed artifacts, other
adapters/platforms and release readiness remain separate gates. Genuine resolved
lifecycles, native faulted-source execution, actual multi-row timestamp ties and
concurrent material overlap are not qualified. Small-fixture plans are not wire
capture, peak RSS, physical-I/O or performance/SLA guarantees; no universal
compatibility or release claim follows from these bounded results.
