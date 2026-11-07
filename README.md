# modkit-workers

NEW unpublished source, proposed version0.1.0. MIT attribution is retained.
Pure root contracts provide explicit HandlerRegistry registration/lookup and acquisition/
subscription preflight, immutable JobContext, application-owned synchronous/async
WorkSource hooks, AcquireRequest and bounded WorkerSettings. See
[the pure contracts guide](docs/worker-contracts.md) for signatures and validation limits.
These contracts do not execute handlers or run workers. JobWorker/EventWorker,
supervisor loops and automatic services remain unavailable.

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
creates roles, manages transactions or opens services. Production manifest/SQL
are intentionally absent pending reviewed bytes. manifest() fails FileNotFoundError
until that separate gate closes; test-only in-memory fixtures are not packaged resources.

See docs/package-layout.md for resource framing, ordering, caller receipts and limits.
No build/install/release, real PostgreSQL84/Redis or full regression evidence is claimed.
