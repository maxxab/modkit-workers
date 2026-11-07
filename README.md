# modkit-workers

Development source, proposed version 0.1.0. **Status: NOT_READY for production or release.** MIT attribution is retained.
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
Compatibility with existing application dependency locks remains unqualified.

`modkit_workers.persistence.migrations` exposes immutable SQLResource,
MigrationDependency, Migration, manifest and read_sql. It never applies SQL,
creates roles, manages transactions or opens services. Production manifest/SQL
are intentionally absent pending reviewed bytes. manifest() fails FileNotFoundError
until that separate gate closes; test-only in-memory fixtures are not packaged resources.

See docs/package-layout.md for resource framing, ordering, caller receipts and limits.
No install/release, real PostgreSQL/Redis or full regression qualification is claimed.

## Dependency-independent source checks

[The source-check workflow](.github/workflows/source-checks.yml) runs on
Ubuntu 24.04 with Python 3.12. It installs only pinned test, lint and build
tools from [.github/requirements-source-ci.txt](.github/requirements-source-ci.txt),
not Workers or Events. Its exact checks are:

- Ruff lint over all of `src` and `tests`.
- `tests/test_package_exports.py`, `tests/test_migration_resources.py` and
  `tests/test_handler_partials.py`, using `PYTHONPATH=src` for source imports
  and child processes.
- `tests/check_sdist_contents.py`, which builds a temporary source distribution
  to verify private-document exclusions and required public files. It does not
  install or qualify a release artifact.

**The full suite remains blocked with the available public Events source.**
The inspected [Events 0.1.0 source](https://github.com/maxxab/modkit-events/tree/076bb3a275725f21d0f5f8594de64370bacf9505)
lacks `modkit_events.contracts` and `modkit_events.persistence`, so the complete
Workers suite fails collection against it. Full source qualification needs
compatible public Events APIs; installed-package qualification also requires a
released Events distribution satisfying the unchanged `>=0.2,<0.3` requirement.

A green dependency-independent check is not a full-suite, formatting, type-checking,
installed-package, runtime or release qualification. The planned Python/OS matrix,
optional adapters, native drivers, production SQL and real PostgreSQL/Redis gates
remain open. No service, deployment or release job is configured.
