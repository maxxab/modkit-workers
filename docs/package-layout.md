# Package layout and readiness

**Status: NOT_READY for production or package release.**

Typed source lives in `src/modkit_workers`. The `py.typed` marker does not certify completed type checking. Root and namespace initializers do not load optional adapters or apply migrations. Workers depends on Events; Events remains independent of Workers.

## Migration resources

`modkit_workers.persistence.migrations` exposes immutable `SQLResource`, `MigrationDependency`, `Migration`, `manifest()` and `read_sql(migration, resource)`. These APIs only validate and read bytes. They never connect to a service, apply SQL, create roles or own transactions.

Reviewed W01 admission and W02/W03/W04 read, list and find SQL source is present in `0001_initial.sql`, but it is **NOT_READY**. Production `manifest.json` and `grants_runtime.sql` are deliberately absent. `manifest()` raises `FileNotFoundError` until these resources are supplied and qualified. The SQL requires Events-owned functions and the `work_jobs_created_page` index, which are not yet integrated into the public Events migration resources. Test-only resource bytes are temporary fixtures, not production SQL. Workers component version 1 requires the exact Events component version 1 resource aggregate, not merely a matching Python dependency version. See [reader qualification](reader-qualification.md) and [job listing](job-listing.md) for bounded source/native evidence and the remaining gates.

Manifest resource digests use SHA-256. Aggregate framing is ASCII MKMF, byte 0x01, a big-endian uint32 resource count, followed by sorted component-prefixed UTF-8 paths. Each frame is a uint32 path-byte length, path bytes and the raw 32-byte resource digest. Initial and grants SQL participate; the manifest and separate receipt SQL do not.

Known initialized filesystem and zip import locators are supported on POSIX. Unknown providers and unsupported archive layouts fail closed. A single root lease covers manifest, resource hashes and selected read. Direct resource leaves must be regular files and cannot be symlinks. ZIP validation uses a bounded snapshot without extraction and checks local/central metadata, ranges, complete deflate output, size and CRC before resource digest and UTF-8 checks. ZIP64, executable prefixes, trailing or concatenated archives and unsupported descriptors/methods are not supported.

Limits: manifest 64 KiB; SQL resource 16 MiB; archive 256 MiB; central directory 16 MiB; 65,534 archive entries; name/extra/comment 4,096 bytes each. Oversize inputs are rejected, never truncated. These limits do not certify peak memory, concurrency, latency or distribution authenticity. Windows resource loading is not implemented and fails closed.

Missing resources raise `FileNotFoundError`. Invalid descriptors, manifests, hashes, encoding, containment, backends, archives and excessive sizes produce fixed `ValueError` messages. Unrelated OS errors propagate. Cleanup attempts each owned resource once; uncertain close outcomes are not retried. Applications must preserve uncertainty rather than infer successful release.

## Development tests and open gates

Source tests are in `tests/`. Resource fixtures use helper-owned temporary directories. `MODKIT_RESOURCE_TEST_BASE` can select a parent directory. Link-creation limitations must be reported rather than bypassed through permission changes. Tests exercise pure contracts and bounded resource controls, not a complete worker runtime or real services.

Python 3.12-3.15, Linux/Windows/macOS, optional dependency bounds, produced wheel/sdist installation, native libpq, PostgreSQL and Redis remain qualification targets. The declared dependency ranges and development pins are not installation or compatibility guarantees. Current production resources and `JobWorker`/`EventWorker` execution loops are absent.

Applications own authorization, transaction boundaries, durable outcomes, backup/recovery and reconciliation. Downgrading a package does not undo schema changes, external effects or uncertain commits. No destructive cleanup or down migration is supplied.
