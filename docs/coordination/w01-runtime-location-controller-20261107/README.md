# W01 runtime-location host controller: review candidate

SOURCE ONLY. No target command has run. This packet and every local record are audit
bindings, never authority. Independent parent acceptance of these exact bytes and
this exact invocation plus the Events owner's current, precise exclusive window
are prerequisites. The parent must verify their provenance and that V66 remains
the latest accepted runtime. No window is requested or reserved by this packet.

## Scope and preserved inputs

Workers source baseline: 81136786d471e4217e8252ebd5cc7a61409c47c6.
The original proposal, old fixture-v3, public checkout, live WIP, product/deployment
source and existing failure evidence are unchanged. No commit is made.
The proposal manifest remains
6f55397f3042bc333ad1d8354e2b42f772ecaa3bba875e327978ca7853fe1a61;
proposal JSON remains
6862bd5edfe0073ac34ba8f6bdaf76c1a248565053e7fe1b877924efe57a10c8.
Events V66 runtime manifest remains
18a103aa6e9d67277a71bab61c1f511b8fd01405dad126190e0cfbbab532c52b.
Every referenced Events runtime file is read and rehashed, bounded to 128 files,
2 MiB/file and 4 MiB total. The accepted container and catalog files are also
checked against proposal pins. No catalog query or SQL is executed.

The exact three argv lists come only from the SHA256-anchored original proposal:
selected before-container inspect, one postgres docker exec for command-v/fixed
path metadata, selected after-container inspect. No alternate executable is found
or executed. The host executable for each argv is explicitly /usr/bin/docker;
argv itself is unchanged. No Python, driver, pip, package import, filesystem copy,
service start, network change, DB connection, SQL or cleanup runs in the target.

## Bounds and fail-closed behavior

- 17 exact ordered output rows: 3 command, 6 path, 8 package-directory rows.
- 4096 bytes maximum retained per stream per process. Reads consume at most one
  overflow sentinel byte beyond that limit, then terminate the host client.
- Seven-second host process envelope, with capture ending at 6.75 seconds to leave
  up to 0.25 seconds to reap. POSIX real-time alarms also interrupt host launch and
  I/O calls. Nonblocking pipes and selectors avoid unbounded communicate buffers.
- The unmodified interior /usr/bin/timeout --signal=KILL 4s remains in exec argv.
- An independent GNU timeout --signal=KILL 25s process-group wrapper bounds the
  whole host invocation. A 24-second controller deadline leaves one second margin.
  Python and Docker clients inherit that group; the controller verifies its exact
  parent's argv and group before target actions. No new session is created.
- On overflow, timeout or host I/O/launch uncertainty, kill/reap the known host
  client within the remaining envelope. If launch/reaping remains uncertain, first
  save bounded evidence and then KILL the validated host process group. A failure
  during controller recording after the one-shot directory was created also kills
  that group. This is host cleanup, not proof of target exec cancellation.
- Process stdout/stderr, argv, start, return code, timeout/overflow flags, client
  reaping, frozen pins and overall status are captured in a new private 0700
  evidence directory. An existing directory is refused without modifying it.
- Any nonzero exit, stderr, malformed/truncated output, strict JSON type mismatch,
  pin drift, tool error or uncertainty ends the sequence immediately. No retries,
  alternate target or follow-up inspect after failed exec.
- A missing final outcome, outer KILL or failed controller is failure/uncertainty.
  Do not infer unchanged target state from a missing aftermath. Inform the Events
  owner before releasing exclusivity after a failed/uncertain exec.

Deadlines are OS scheduling limits, not hard real-time guarantees. Mock tests check
controller decisions; they do not qualify real kernel signals, Docker cancellation,
target state, host binary provenance or uninterruptible kernel I/O. The independent
review must assess the exact installed host launcher/interpreter/Docker route.
No real child-process timing experiment was run because preparation is mock-only.

## Meaning of findings

A negative means no route found in the checked conventional set, never globally
absent. Positive command/directory metadata proves visibility only. Unexpected
absolute command paths and directories are retained as evidence, never followed
or executed. Versions, provenance, importability, ABI, exact psycopg3.3.8 closure,
native connections and the eventual full W01 fixture remain unresolved.

## Exact future invocation, not to run now

The machine-readable authority is host-invocation.json, whose Windows argv invokes
WSL Ubuntu-24.04 directly. Run from PowerShell with login:false only after the
independent parent acceptance and exact Events exclusive window exist.

    wsl.exe -d Ubuntu-24.04 -- /usr/bin/timeout --signal=KILL 25s /home/faris/modkit-local-20261106/.test-venv/bin/python -I -S -B /home/faris/modkit-local-20261106/baseline-plan-20261107-standalone-only/commits-v3/workers/docs/coordination/w01-runtime-location-controller-20261107/controller.py --execute-reviewed-once

Running controller.py with no arguments cannot launch anything and returns the
source-only status. Tests never call the real execution form or launch a process.

The two future record paths and one fixed future evidence path are specified in
host-invocation.json. None exists from preparation. Parent acceptance record must
have status ACCEPTED_EXACT_SOURCE_AND_INVOCATION, reviewer and acceptance_id. The
window record must have status EXCLUSIVE_WINDOW_GRANTED, owner, lease_id, matching
acceptance_id, valid_from_unix, valid_until_unix, no_other_target_work exactly true,
and latest_accepted_runtime_sha256 equal to the V66 anchor. The initial window must
have at least 25 seconds remaining and remain unexpired at completion. Both bind:
artifact_manifest_sha256 (hash of this packet's artifact-pins.json),
invocation_sha256 (hash of host-invocation.json), proposal_manifest_sha256,
accepted_events_runtime_sha256 and the exact target_container_id. These checks
prevent accidental stale/mismatched records; files are not cryptographic identity
proof, do not grant authority, and cannot replace actual parent/owner coordination.
If the accepted target advances, stop and prepare a reviewed revision instead.

## Offline verification

The test suite replaces every process-launch dependency and uses synthetic clocks,
pipe readiness, reads, exits and cancellation. It inspects frozen source files.
Temporary files test only bounded reads and symlink rejection. Gate tests use
in-memory dictionaries, not real grants/leases. No runtime evidence directory,
grant, lease or attempt marker is created. Existing package tests remain pure.
See verification.json for exact commands, counts and red/green history.

Independent review and real runtime qualification are still pending.
