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

## Bounded qualification

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

This source remains NOT_READY. Production manifests and runtime grants are
absent. Actual multi-row timestamp ties, concurrent material overlap, a full
256-row page, physical-I/O/performance budgets, Events migration integration,
all supported adapters, installed artifacts and release readiness remain separate
qualification gates. The bounded checks above do not close those gates.
