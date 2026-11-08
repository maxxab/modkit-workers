# modkit-workers

NEW unpublished source, proposed version0.1.0. MIT attribution is retained.
Pure root contracts provide explicit HandlerRegistry registration/lookup and acquisition/
subscription preflight, immutable JobContext, application-owned synchronous/async
WorkSource hooks, AcquireRequest and bounded WorkerSettings. See
[the contracts and batch guide](docs/worker-contracts.md) for signatures and validation limits.
The explicit modkit_workers.runtime.run_batch and run_batch_async operations acquire
one application-owned batch, execute synchronous or native async hooks sequentially,
and attempt source shutdown once after acquisition begins. The async operation awaits
hooks in the caller task; cancellation can interrupt cleanup. Their counts are not
durable outcome or drain receipts.
JobWorker/EventWorker, supervisor loops and automatic services remain unavailable.

The sole ordinary dependency is modkit-events>=0.2,<0.3. Events and Workers are
separate generic packages: Workers requires Events; Events works with or without
Workers. Applications retain business rules, durable work and transaction ownership.

Python>=3.12 metadata retains the planned3.12–3.15 Linux/Windows/macOS matrix;
that matrix and all optional dependencies remain unqualified. Explicit candidate extras:
redis, sqlalchemy, native, postgresql-psycopg, postgresql-asyncpg, pydantic.
They select dependencies only and do not promise unreleased adapter functionality.
SQLAlchemy alone does not select a PostgreSQL driver or aiosqlite. Native psycopg
uses caller-provided libpq/system setup; no implicit binary installation or driver fallback.
ERP's older Redis/SQLAlchemy lock compatibility remains unresolved.

`modkit_workers.persistence.migrations` exposes immutable SQLResource,
MigrationDependency, Migration, manifest and read_sql. It never applies SQL,
creates roles, manages transactions or opens services. W01/W02/W03/W04/W05 SQL
source is present and explicitly NOT_READY. The production manifest and runtime
grants remain absent, so manifest() still fails FileNotFoundError until that
separate gate closes. See [reader qualification](docs/reader-qualification.md)
for bounded native evidence and remaining gates; test-only in-memory fixtures
are not packaged resources. The [job listing guide](docs/job-listing.md) describes W03's
job-only pagination, complete-page validation, and separate qualification gates.
The [job acquisition guide](docs/job-acquisition.md) describes W05's retained
Events claim postimages, fresh coherent material snapshot, and bounded job-only
native evidence, including a real two-session producer-visibility regression and
maximum 256-claim/4096-visited pages with small fixture payloads.

See docs/package-layout.md for resource framing, ordering, caller receipts and limits.
No build/install/release, Redis, or full 84-cell PostgreSQL conformance qualification is claimed.

## Resume checkpoint

See [the 2026-11-07 shutdown checkpoint](docs/shutdown-checkpoint-20261107.md)
for the reviewed branch, fresh bounded test evidence, publication blockers and safe restart steps.
