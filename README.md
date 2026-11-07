# modkit-workers

NEW unpublished package scaffold, proposed version0.1.0. MIT attribution is retained.
The sole ordinary runtime requirement is modkit-events>=0.2,<0.3. No worker runtime
root exports, supervisor loops or automatic services are provided by this partial source release.

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
