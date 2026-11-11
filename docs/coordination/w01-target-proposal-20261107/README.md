# W01 target-specific execution proposal

Status: **NON-EXECUTABLE, SOURCE-ONLY, REVIEW REQUIRED. Native transport unresolved.**

This proposal continues the accepted da529d0c7951d6cded7ef64584fe30d29cb59dae bounded pure result. It creates no runnable packet, launch command, grant, lease, attempt marker or new qualification receipt. It does not authorize probes. The original fixture-v3 packet, runner, setup/disposal SQL and live fixture are preserved. No application code or deployment definition changes are proposed: eventual endpoints, credentials and qualification routing belong in reviewed test configuration.

## Decision needed before a runnable proposal

The Events owner reports that this target lane has qualified only container-local psql/libpq/timeout. There is no accepted evidence for host psycopg transport or an interpreter/psycopg 3.3.8 route inside the network-none container. This is **unresolved, not proof of absence**. psql is not a replacement for the W01 native psycopg claim.

First obtain owner-supplied existing, non-secret frozen evidence of an available route: interpreter location/version/ABI and library closure, psycopg 3.3.8 and psycopg_binary artifacts with hashes, connection execution namespace, exact endpoint/database/user, and how immutable fixture/source/SQL bytes are available in that namespace. Current container evidence has no mounts, bind mappings or published ports. Host 127.0.0.1 is not container 127.0.0.1. A host venv file pin is not proof its binaries can execute or reach this target.

If no such existing evidence exists, the next deliverable is a separately scoped **read-only discovery proposal**, with exact allowed fields, commands, bounds and owner/independent approval before execution. Do not infer permission to probe, import, copy/install tooling, alter networking, start another container, or substitute another target. Any route requiring changes needs a new explicit design decision and authorization; this document does not choose or authorize it.

## Evidence status and target comparison

The accepted capture is v59-fix1-e12-queued-terminal-execution/v59-fix1-e12-queued-terminal-once/after, pinned by e12-queued-terminal-runtime-v60/runtime-pins.json (c877823dd9290a3e178c8839fe02735b4a3a89ef7daa1c4812b6bcac263463f4). Its bounded independent acceptance is author-preserved in e12-claimed-fence-fixture-v61/v60-review-reported.json. This is an accepted historical capture, not present exclusivity or a renewed grant.

At preparation, V62 aftermath was pending. Subsequent V63 bounded independent acceptance is now reconciled explicitly: e12-claimed-fence-runtime-v63/runtime-pins.json (544028b256b6476e811f7cedf03472b8d16b36f7d2433251a1fddaa1e72d56a5), artifact manifest be8e14b99a8cff76794cb1886c6b1ea3499ebdadc30b3e66f28066ed67c3cf3e, and the author-preserved acceptance e12-running-held-fixture-v64/v63-review-reported.json (0a707f3157efbc4e9a929fb39b3c4fcb683f671f55081b758da949ddcdbb5e10). The V62 aftermath catalog/container files match these raw pins. Full comparison against V60 changes backend_pid, locks, sessions and only pg_control_last_modified within control_system (20:11:44 to 20:42:03 UTC). System identifier, postmaster start and all remaining catalog fields are unchanged; container bytes are identical. This is not physical rollback or present exclusivity. target-evidence.json retains the earlier capture and pending-status history, with a separate latest accepted aftermath record. Events reports no active target operation and source preparation underway; that report does not grant Workers target access.

Old W01 assumptions:
- host 172.26.0.3:5432, database modkit_native_qualification, postgres; target ID 5d58dd666eeec045c79f3e8732e015c8d3ba77278229e52f7c1897e07150a274.
- PostgreSQL 18.1, shared_buffers 16MB, max_connections 12; no non-system schema beyond public/information_schema, no modkit_ roles, no other target-database sessions.
- No physical container/system-ID/start-time verification in the old state check.

Accepted target:
- container 51a93b781c024f29372e44643db26447d4d367fa4a1aa255abd8e665c90270f3, image sha256:1090bc3a8ccfb0b55f78a494d76f8d603434f7e4553543d6e807bc7bd6bbd17f.
- network none; inside-container 127.0.0.1:5432, database modkit_qualification (OID 16384), postgres; system identifier 7705523520844832822; postmaster start 2026-11-07T20:06:44.138392+00:00.
- PostgreSQL 18.1 Debian build; max_connections 12; shared_buffers 2048 * 8kB = 16MB. Container memory 384MiB, 0.5 CPU, PID limit 128, 256MiB tmpfs at /var/lib/postgresql, no mounts/binds/port publishing.
- Only public/system schemas, no non-system relations/functions/standalone objects, no modkit roles, default ACLs or database-role settings. Only plpgsql extension; no foreign wrappers/servers/user mappings, event triggers, publications, subscriptions or prepared transactions.
- One capture client backend plus PostgreSQL background processes. This demonstrates no other client in that capture, not continuing exclusivity.
- UTF8, Etc/UTC, ISO MDY; origin-sensitive trigger behavior must be checked for the future run. Capture transaction_read_only=on was a session observation; default_transaction_read_only=off. Do not copy the capture session's read-only setting into writer assumptions.

Old endpoint, database-specific GRANT/REVOKE statements, target identifier, physical checks, route and source pins therefore cannot be reused as authorization. Matching three server settings does not make these targets interchangeable.

## Required gates, in order

1. Resolve route evidence and reconcile the newest independently accepted target aftermath with the owner. Retain old and new captures and their acceptance limits.
2. Review exact test-only design, full source/SQL surface, setup/disposal inventory, permissions and all connection/controller budgets. Retain current product code and deployment definitions. Author a new runnable packet only after this design scope is accepted, not by changing hashes in the old packet.
3. Independent review of the exact runnable bytes, interpreter/driver/library provenance, input closure, launch fence, resource limits and failure evidence. Review E10 and namespace pending status explicitly. Accepted pure comparison and unrelated Events staged receipts do not close those gates.
4. Events owner must authorize the exact new target/packet, one exclusive window, bounded identity checks, setup commits, all scenarios and disposal. No concurrent Events or ERP writer. No grant is requested or created by this proposal; coordination belongs to the parent.
5. After separate authorization, fresh bounded physical/logical identity and exclusivity checks must precede writes. Recheck identity before disposal and afterward. An attempt fence is replay prevention, never authority.
6. Stop on any mismatch, stale scope, unexpected session/object, input drift, native error, uncertain launch/commit/cancel/close or missing receipt. No automatic retry, replay, cleanup repair or lease renewal.

Physical checks must bind container ID/image/network/mount/resource settings to database system identifier, postmaster start, database name/OID/owner, server address/port, build and effective settings. A recreated/restarted target requires reconciliation, not a tolerated identifier change. Full logical prestate must include schemas and owners/ACLs; roles, attributes and memberships; default privileges; database-role settings; extension/event trigger/foreign object inventory; objects in public and other schemas; sessions, prepared transactions and relevant locks. Check cluster-wide role dependencies, since roles are cluster objects. Distinguish the authorized observer backend and expected background processes from unrelated client sessions. No termination of outsiders is authorized.

Fresh checks are proposals only. Reserve their connections within a newly proven budget; do not silently add probes beyond 37 total attempts. Full setup/disposal identity checks should share their existing connections where possible; extra controller sessions require explicit budgeting. A captured blank target does not permit dropping anything subsequently found there.

## Source and SQL scope

source-inventory.json rechecks the 190 reconciled inputs without imports. The old 189 inputs remain represented by the preserved packet; 181 were unchanged, seven Events Python files and the SQL resource changed. Current SQL preserves the exact old 241339-byte prefix, plus 49244 bytes adding E04-E07 (total 290583, SHA-256 6cf0c7d1fb6baaccf98b5aaf0e3ed15c55c12941c4e73d45d083d948ec9a5534). Current native_codec.py is inventory, not proven fixture reachability. The pure result compares 84 records with six comparator controls; it does not qualify SQL/native concurrency or the entire dependency closure.

The old runner loads LIVE Workers sources, not this isolated checkout. Its exact fixture and Workers SQL are pinned here. The isolated repository contains unrelated accepted product changes; replacing live sources with checkout sources would change scope and require a new comparison and pins. No such substitution is made.

The fixture directly uses JobInput, JobSubmitRequest, submit, decode_submit, Scope, ReplayPolicy, ProtectedBindingInput, MaterialState, CleanupPolicy and public Events canonical_intent/ReturnContext/freeze_request; replay_variant uses Workers _admission to construct lawful replay variants. Real package initializers and transitive pure modules matter. Existing pure source-manifest is evidence for that bounded Python slice, not the entire runtime. The runtime additionally imports psycopg/tuple_row, fixture stdlib threading/time/UUID modules, reads named SQL and installs both complete SQL resources.

sql-surface.json records every CREATE/ALTER/GRANT/REVOKE source line, all function source spans and lexical references, and fixture AST import inventory. These are review navigation aids, not a SQL semantic parser or proof of dynamic closure. Full exact resource hashes define the installed scope, including objects not exercised by W01.

W01 direct callable helpers: Events _intent_valid, _protected_frame_valid, _protected_valid, _instant_bytes and e15. Direct data path: work, job_payloads, work_history and work_history_history_id_seq. E15 also depends on inbox, subscriptions, attempts, finalization_guards and mutation_operations and their integrity/provenance checks. The three bridge triggers (_work_admission_immutable, _job_payload_record_check and _inbox_record_check), shared table constraints, identity/FK/unique-index rules, canonical/JSON/scope/protected validators and E15's 56-column OUT ABI are part of the shared surface. The resource also installs unrelated Events functions, including E10 and appended E04-E07, even though W01 does not call all of them. Approval must cover installation of the full resource, not just five direct helpers.

Workers installation checks restricted role ancestry/ownership/privileges; helper ABI, volatility/security/strictness/language/search_path/PUBLIC exposure; E15 types/names/modes; shared relation ownership and RLS; full row type/nullability profiles; validated nondeferrable keys/checks; exact partial NULLS NOT DISTINCT identity index; enabled ordinary triggers; history identity sequence and origin replication role. It then creates only modkit_workers schema and W01 with owner-only ACL checks. These structural checks are not source identity, production grants, E33/MKMF readiness or runtime evidence.

## Proposed setup and disposal boundaries

Subject to all gates, retain the fixture's two-schema/four-role model on modkit_qualification only if the fresh inventory proves every proposed name absent. Setup would create modkit_w01_owner, modkit_runtime, modkit_reconciler and modkit_operator as NOLOGIN/NOSUPERUSER/NOBYPASSRLS/NOCREATEROLE/NOCREATEDB/NOREPLICATION; grant database CREATE to the owner; SET LOCAL ROLE; execute complete pinned Events then Workers SQL within one READ COMMITTED transaction, then commit. Database identifier changes belong to a newly reviewed fixture configuration, not product SQL. Capture setup commit acknowledgement and post-install identity/complete object-owner/ACL inventory. Never modify preexisting names to make setup pass.

The fixture is not rollback-only overall. Four commit-race winners and two split-race winners persist. Disposal therefore needs distinct explicit scope approval: after success, stable pins, confirmed closed handles and no outside sessions/dependencies, drop exactly modkit_workers then modkit_events with CASCADE, revoke only the granted database CREATE and drop exactly the four created roles in one transaction. No DROP OWNED, row DELETE/TRUNCATE, trigger bypass or finally-disposal. Pre-disposal checks must verify every object to be removed and dependency closure, not merely two schema owners: unexpected cross-schema dependents, foreign ownership, memberships or cluster/database role dependencies stop disposal. Do not learn destructive scope by trying CASCADE.

After acknowledged disposal, verify the original full logical baseline and physical identity, no fixture sessions and no residual privileges/roles/schemas. Logical cleanup does not restore OIDs, sequence/WAL/transaction counters or imply physical rollback. The retained evidence must distinguish acknowledged commit from verified aftermath. A failed/uncertain disposal is a held state for separate reconciliation, not a reason to repeat it.

See execution-trace.md for exact scenarios, budgets, observables, and failure paths. No new runtime or target qualification has been performed.
