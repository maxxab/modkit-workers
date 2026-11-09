# W02/W04 reader source and qualification

W02 reads a complete job record by UUID. A missing UUID returns no row. A present
non-job or incomplete job raises PZ012; null input raises PZ006.
W04 compares a requested job with the direct-ID and idempotency-key candidates.
It never submits a job. The returned family has at most two distinct UUID-ordered
records. Every candidate is validated before any result is exposed. Both readers
require READ COMMITTED (PZ005 otherwise), are STABLE SECURITY DEFINER, use a fixed
search path, and retain the private owner-only installation boundary.

The initial source preserves the previously reviewed W01 body and dependency
preflight, then adds the E15/E17 reader dependency guard, W02/W04, and a postflight
that rejects unexpected non-owner default grants. It neither changes installer
defaults nor grants runtime permissions. Applications own installation and work
transactions. That reader-only checkpoint preceded the installation-closure
candidate, which now includes the initial SQL, grants resource and verified
manifest. The inert manifest()/read_sql() API validates those resources; it does
not apply SQL or attest to a successful database installation. See
[installation closure](installation.md) for the current boundary and remaining
gates. Do not deploy this NOT_READY candidate.

## Historical reader-only bounded evidence

The following evidence covers the earlier staged reader SQL, not the complete
current installation closure. It used PostgreSQL 18.1 and psycopg 3.3.8 in an
isolated Linux disposable container:
- Both missing reader functions produced genuine 42883 RED failures before installation.
- Exact staged reader SQL/preflight installed successfully.
- Native fixture covered absent records, protected payloads, direct/key matches,
  semantic conflicts, split candidates, invalid inputs, incomplete halves,
  valid-first/corrupt-last family rejection, and unsupported isolation levels.
- Complete table rows and sequence state remained unchanged by each read/find.
  Full fixture rollback left no Work, job payload or history rows and no other sessions.
- Static reader call closure is W02 -> E15 and W04 -> E17 -> E15 plus immutable
  validation helpers. Readers invoke neither W01 nor E10. Exactly three W01
  calls were explicit lawful fixture setup, not hidden reader submission.
- Unintended default EXECUTE privileges must be rejected by PZ011. The regression
  changes only disposable fixture privileges/functions and rolls all DDL back.

Pure tests check ordered source ABI and real canonical corrupt-family construction.
Native helpers accept caller-owned isolated connections; they never select a DSN,
start a server, install a package, or claim release readiness.

## Remaining qualification

Foreign inbox collision coverage needs a real separately scoped E03 producer.
Lifecycle/concurrent writer coverage, all three adapter recipes, real runtime
grant acceptance and the full PostgreSQL matrix remain open. Exact current
Events/Workers migration digests are present and checked as inert resources;
successful database installation of that combined closure remains unqualified.
W03 and W05 have separate bounded evidence and limits in
[job listing](job-listing.md) and [job acquisition](job-acquisition.md).
Those results do not qualify the complete installation or PostgreSQL matrix.
E10 QA remains outside this reader qualification.
