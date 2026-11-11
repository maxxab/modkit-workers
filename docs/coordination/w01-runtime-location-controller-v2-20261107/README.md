# W01 runtime-location host controller v2: review candidate

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
  parent's argv and group before target actions. Both controller and parent PGIDs
  must equal the timeout parent's PID, not merely match each other. The parent PID
  must remain stable across validation. No new session is created.
- On overflow, timeout or host I/O/launch uncertainty, kill/reap the known host
  client within the remaining envelope. Reaping the direct client does not prove
  its descendants or inherited pipes are settled. The separate
  host_group_kill_required flag remains true after every incomplete/failed capture,
  including timeout, overflow and I/O failure even when client_reaped is true.
  The sequence preserves that flag and fails closed. First save bounded evidence,
  then KILL the validated host process group. A failure
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
WSL Ubuntu-24.04 using --exec, without a default Linux shell. Run from PowerShell with login:false only after the
independent parent acceptance and exact Events exclusive window exist.

    wsl.exe -d Ubuntu-24.04 --exec /usr/bin/timeout --signal=KILL 25s /home/faris/modkit-local-20261106/.test-venv/bin/python -I -S -B /home/faris/modkit-local-20261106/baseline-plan-20261107-standalone-only/commits-v3/workers/docs/coordination/w01-runtime-location-controller-v2-20261107/controller.py --execute-reviewed-once

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


## v2 changes and preserved v1

The immutable v1 directory remains ../w01-runtime-location-controller-20261107.
Its manifest SHA256 is
37d3781e845b5a890dfd332c7b93a9341e5c48177e4e30a2b46311fd8a9de7c3.
The independent v1 review required changes; passing its original 60 tests did not
settle descendant cleanup, WSL shell startup or isolation of the host process group.

This separate v2 makes only the three requested controller/launcher corrections:
1. Direct-child reaping no longer clears cleanup uncertainty after incomplete pipe
   capture. Mock regressions cover exited-client lingering pipes, overflow and I/O
   failure both at run_process and run_sequence boundaries.
2. The Windows invocation uses WSL --exec. Its exact script and future audit/evidence
   paths point to v2; none is created as runtime authority or evidence here.
3. The timeout parent must lead the inherited process group. Tests reject parent
   PID999 with both PGIDs111 as well as mismatched groups, and accept only the
   exact synthetic timeout-led group and expected command line.

All eight expected red regressions were observed before the corrections; the other
63 tests passed then. Eleven new tests cover these review findings. No target
commands or real process/signal experiments were used. Installed executable
identity/provenance, real cancellation and native runtime readiness remain
unqualified. This revision still requires independent review and actual parent
acceptance plus the Events owner's precise exclusive window before any target action.

Independent review and real runtime qualification are still pending.

## Lossless diff packaging correction

The review diff is stored as controller-v1-to-v2.diff.json, using UTF-8 lines with
line endings preserved. Concatenating unified_diff_lines and UTF-8 encoding them
reproduces the exact accepted 2292-byte raw diff, SHA256
35d6c75c8ef37926a837c95ad5af5e138fb1c00d82685b95a316c1b9ce928f8a.
This avoids Git whitespace rejection of ordinary unified-diff context lines without
altering the diff or disabling checks. Controller, tests, invocation and input pins
are unchanged. The exact original nine-file v2 packet, including raw diff and
manifest fa8e822033c009a89fccea65d8baec40adee4a6815d1ae8f4185dc76aba3e733,
was preserved before correction outside this repository at:

/home/faris/modkit-local-20261106/baseline-plan-20261107-standalone-only/commits-v3/workers-controller-v2-diff-preservation-20261107

This storage-only correction needs a narrow independent follow-up review and grants
no execution authority.
