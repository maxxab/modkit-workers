# W01 fixture-v3 source reconciliation

Status: **source evidence accepted; not repinned, not runtime-qualified, not ready for ERP**.

## Result

The frozen packet is preserved byte-for-byte. Of its 189 inputs, 181 match and eight Events inputs changed: seven Python files and the SQL resource. Every Workers input, fixture/runner file and pinned driver file still matches. A new Events `native_codec.py` is recorded as discovered inventory, not proven W01 import reachability. No inspected production source or W01 fixture text references it; dynamic loading outside that inspected source remains unproven.

The original SQL is the exact first 241,339 bytes of current SQL, matching its original SHA-256. The 49,244-byte suffix adds E04, E05, E06 and E07 functions and their PUBLIC revocations. It does not amend the old prefix. All four functions are VOLATILE SECURITY DEFINER; append-only text does not establish behavior or grant safety. `reconciliation.json` includes exact pins and structural changes.

Seven hash-matching Python originals were recovered from the retained Events checkpoint. Each of the eight changed inputs and the new file has a reproducible unified diff here, encoded as a JSON line array. Joining `unified_diff_lines` and encoding UTF-8 recovers the exact bytes and their recorded size/SHA-256. This representation preserves required blank-context markers without violating repository whitespace checks; no hook was disabled. Independent review re-read all 189 original inputs and all 190 observed inputs and reproduced all nine diffs. See `independent-review.txt` for the bounded acceptance and required compatibility checks.

## Compatibility work remaining

Before a replacement packet is proposed, compare W01's public paths across original and current Events sources: Event/freeze/Scope boundary behavior; JobInput -> submit -> admission -> public ReturnContext/freeze_request metadata, parameter and canonical byte contracts; protected-binding coupling; and decode_submit cardinality, wire types and admission/result coupling. Cover malformed records and unexpected failures as well as valid inputs.

The new private raw context path accepts only empty contexts and is scoped to selected E14/E28 graphs. W01 retains a nonempty AdmissionInput context and currently calls public paths. Do not substitute the raw functions. Private validation rejection must be translated by the correct public boundary. These are identified tests to design and review, not tests run by this reconciliation.

## Frozen execution scope, not authorization

The existing runner verifies all input hashes before loading its lease gate, driver or fixture. The gate requires exact packet/target identifiers, expiry and a local exclusive attempt marker. That local replay fence is not authorization by itself. The proposed driver is psycopg 3.3.8; native imports remain behind the gate. The runner limits connections to four concurrently and 37 attempts total. The packet's 180-second timeout is an external execution requirement, not a timer implemented by the runner.

Its existing target is hardcoded as 172.26.0.3:5432, database modkit_native_qualification, user postgres. It checks PostgreSQL 18.1, shared_buffers 16MB, max_connections 12, empty non-system schema/modkit-role inventory and no other database sessions. Setup starts a READ COMMITTED transaction, creates modkit_w01_owner/modkit_runtime/modkit_reconciler/modkit_operator, grants database CREATE to the owner, switches local role, executes complete Events and Workers SQL resources and commits. Fixture scenarios use fresh bounded connections with the owner role.

Only after scenarios return, pins remain stable and all handles close does the runner check the expected two schemas/four roles and schema ownership. Disposal starts a transaction, drops exactly modkit_workers and modkit_events with CASCADE, revokes database CREATE, drops the four roles, commits and checks the clean baseline. There is no finally-disposal or retry. Any commit uncertainty stops without automatic repair. This describes existing code, not approval to execute it or proof that its checks meet a new target's requirements.

## Different captured target

`target-reference.json` records selected non-secret fields from frozen Events v58 artifacts, checked against their manifest. That capture uses a network-none container and inside-container 127.0.0.1:5432, database modkit_qualification, with a specific system identifier and postmaster start time. It is not the frozen W01 target. The preserved Events reviewer report accepted only a bounded captured profile and explicitly granted no runtime authorization. This reconciliation made no current target probe and makes no claim that the capture is still current.

A prospective native run needs separately reviewed target-specific connection route, identity/prestate checks, source pins, setup/disposal scope, resource bounds and exact-packet authorization. Do not edit a packet hash to hide source drift, reuse an old lease or point the old runner at the new container.

## Evidence and limits

- `input-comparison.json`: original expected pins and observed comparison for 189 inputs.
- `observed-inputs.json`: 190 observed input pins, **not a replacement executable packet**.
- `reconciliation.json` and nine diffs: byte and AST evidence, not semantic equivalence.
- `target-reference.json`: historical target comparison, not a probe or lease.
- `independent-review.txt`: author-preserved source-only reviewer result.
- `verification.json`: final source-only stability check.
- `artifact-pins.json`: local evidence manifest excluding itself.

No application, fixture or driver was imported; no source-check script, test suite, SQL, target probe or native runtime was executed for this reconciliation. No lease or attempt marker was created. The frozen packet and live sources were not edited. All files in this folder remain excluded from source distributions under the existing private coordination-document rule.
