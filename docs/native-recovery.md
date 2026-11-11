# Restricted job recovery: S2 adapter source boundary

S2 adds the one-lane native adapter to the accepted S1 scalar owner. It consumes
Events-owned recovery requirements and exact native E33/E13 issuers, not generic
SQL/prepare, guessed M/R constants or a production test double. Unavailable
profile/driver/issuer support fails closed before supported setup/adoption.
There is no installation, connection factory, reconnect or domain reset.

This source is qualified only by connection-free tests with immutable baseline
imports and private future-interface stand-ins. Those tests do not prove actual
native capability, transaction outcomes, process-death survival, authority,
deployment or WS-7. Combined Events/Workers source review and a common supported
profile precede separately authorized native/runtime qualification.

## Public leaves and supported startup

- `native_recovery_contracts`: NativeRecoveryConfig, NativeRecoveryResources,
  RecoverySnapshot and closed enums; required_recovery_source_material_bytes.
- `native_recovery_setup`: preflight_native_recovery,
  configure_native_recovery_profile and opaque provenance receipt.
- `native_recovery`: create_job_recovery, JobRecoveryOwner, run_recovery_host.

Pure module imports do not import optional drivers or start a process,
thread, connection or resource domain. Explicit capability preflight defers the
native import; missing dependencies/issuer or unaccepted semantic/profile
integration rejects. E33 availability is not capability certification.

The application bootstrap must construct/validate NativeRecoveryConfig first,
with exact bytes `b"jobs"` and required source_material_bytes; then perform
preflight_native_recovery(config, limits=limits); only then invoke the unchanged limits-only
configure_native_recovery_profile, create fresh resources and construct/run the
owner. The limits-only function cannot independently validate a namespace it
was not given. It also checks capability before consuming its once-only latch.
Factory revalidation rejects a forged wrong namespace before its own effects;
it cannot retrospectively undo prior external configuration.

Namespace `b"jobs"` is canonical for W01/W04/W03/W05 and job/work SQL composition.
Other namespaces, coerced strings/bytes subclasses and per-application or tenant
prefixes reject. First profile kind is job and limit is1, discovery defaults128
and is bounded1..4096. Generic native E13 remains a five-argument operation; no
namespace/SQL change is implied by this narrower consumer.

NativeRecoveryResources is an inert exact identity carrier for one configured
receipt, one fresh unpooled ManagedConnection and one ExecutionLedger. Existing
canonical provenance/adoption remains authoritative. Factory construction rechecks
config and the exact receipt limits through Events requirements/driver verification
before its own material admission. This explicit factory call can load the driver;
module import cannot. Run rechecks again before adoption. No external caller order
is inferred from the limits-only configure function.

## Authority and external host

The cooperative application supplies validate_profile(namespace)->None and
an authorize_root(connection,namespace) context manager. It must establish
current authority for ALL jobs in the exact configured database/schema across
application/tenant/owner scopes. A per-job Scope, E33 or namespace label alone
cannot establish it. Context entry precedes root creation, and authorization
must remain effective through commit or rollback acknowledgement. Hooks cannot
commit, roll back, replace connections, retain borrowed native resources after
settlement, invoke handlers/providers or reenter Events from observers.

Unknown root outcomes retain the owner and entered authorization context rather
than calling its exit and pretending disposition is known. No automatic retry,
replay, rollback guess, context release or logical/native refund is allowed.
Keep unresolved owners alive. Application authorization/context allocation is
application-owned, outside the scalar source-material envelope. Process death
can lose in-memory observations and is never a clean drain or a durable journal.
Known COMMITTED followed by context-exit/root-release failure preserves committed
counts/cursor and reports cleanup-unresolved. Context exit cannot suppress failure.

Application deployment must use a separately started fresh interpreter/service
with its own configuration/domain/resources, not execution-process threads or
forked live capabilities. The library starts no processes. Configure independent
service lifetime/cgroup and no automatic restart after uncertainty. A host kill
before acknowledged cleanup is UNKNOWN, not clean_stop. An example30-second
host timeout may preempt a30-second drain budget due to scheduling/signal delay;
provide a reviewed margin without claiming a finite quiescence guarantee.

## Scalar retained accounting

source_material_bytes is required; there is no4096 default. On the inspected
CPython3.12.3, 64-bit non-debug scalar layout, pure source checks evaluate the
reviewed E_summary formula to6212 logical occurrence bytes. Profile checks
reject unsupported implementation/layout/coefficients. This numeric result is
only the scalar model, not qualification of native drivers or all builds.

S=1312 for the31-field current snapshot; P=300 for the7-field pending summary;
C31=1320 and C7=308 for exact scalar drafts; L=212 for the4-slot material lease;
Q=444 for bounded scalar/clock scratch. The configured minimum is
L+Q+max(S+C31,S+P+C7,2S+P+C31,3S+P+C31,3S+C31+152)=6212.
The Enum singleton shallow coefficient is48 on this inspected interpreter.
References count conservatively per occurrence, without savings for aliasing.
Static type/enum metadata and fixed config/resource identities have their
separate configuration/native ownership. This is not malloc backing, a bound on
all temporary/frame/native allocation, application allocations, or process RSS.

The pure material lease is admitted BEFORE initial snapshot construction.
One short lock serializes scalar projection, publication/export and disposal;
no lock spans native I/O and there is no per-page history/subscription queue.
Current+pending+draft/replacement/export overlap follows the declared equation.
Snapshots contain only fixed enums, bools and bounded ints/None, never Work,
payload, credentials, exceptions, UUID objects or native handles. Caller-owned
returned copies cannot mutate the owner's current snapshot. Caller accumulation
after ownership handoff is outside source_material_bytes.

The material reservation stays live while terminal current state is retained.
Uncertainty holds it; clean STOPPED alone does not release it. dispose() requires
known cleanup/quiescence, no pending/reserved page or builder, drops the current
leaf and releases only that owner's logical state. Subsequent use rejects.
Native result B is independently charged through projection and until all
borrowed page/item aliases are dropped by the S2 adapter before release.

## Page scheduling and observations

A startup scan is immediately due after readiness. One page is admitted per
turn; no catch-up queue or parallel scan. Raw next cursor advances on committed
empty-but-progressing pages. Only actual canonical exhaustion resets cursor to
None. Budget hits require another bounded page even if coincidentally at physical
end. After nonexhaustion wait turn_interval; after exhaustion wait fallback<=5s.
The cadence is not guaranteed per-row latency under backlog, locks or blocked I/O.

No successful cursor/count update occurs before the lane's actual COMMITTED
acknowledgement. Invalid results, unknown commit or unproven cleanup fail closed.
Snapshots distinguish latest-page outcome from older committed history, and
known committed work from unresolved cleanup. Counters/age saturate uint64
without first constructing arbitrary-size integer totals. Current domain stop
removes observed readiness. Observer freshness is not database outcome evidence.

Stop and new-page reservation share a lock. Already reserved work may physically
send after stop. A stop during pure startup preflight prevents later adoption;
already admitted adoption remains this owner's obligation. Stop/timeout is not
native cancellation, quiescence or refund. A synchronous blocked native call can
outlive a caller's wait or host deadline. Clean stop requires actual known cleanup.

run_recovery_host returns0 only for clean STOPPED;78 for known pre-start refusal;
70 for unresolved/runtime failure. OS termination without final observation is
UNKNOWN regardless of shell status. Repeated run fails; stopped owners do not
restart. Unit stand-ins do not make these exit codes operational qualification.

## Verification and remaining gates

Only the three named connection-free unit modules are authorized in S2. They use
private in-memory lane stand-ins, fake monotonic progression and no real process
host, native connection, fixture, socket, database, service or broker. Bytecode
writes and plugin autoload are disabled; a separate unused pycache prefix avoids
reading retained excluded bytecode. pytest cacheprovider and Ruff caches are off.

Connection-free adapter regressions also use complete canonical WorkObservation
postimages for queued, expired, failed and held, not only empty pages. They check
that page, tuple, item and payload aliases end before result release, counters and
cursor remain unpublished until COMMITTED, and unknown acknowledgment retains the
root and authority without cleanup or disposal. These interface-double tests do
not prove that SQL produced those postimages or that native reservations settled.

Second-page fault regressions first acknowledge a nonempty queued page, then
inject failures from root creation through statement release, commit, acknowledgment,
root release and authority exit. They distinguish an unresolved second page from
a committed page with unresolved cleanup, preserve prior committed counters and
cursor, and check retained handles, authority, material and refusal of restart or
disposal. These checks use in-memory interfaces, not real transport faults.

A separate source integration check uses the actual pinned Events requirements,
lifecycle record types, capacity calculation and profile verifier. Only optional
driver fact inspection is simulated; native modules and registry configuration
are forbidden in that check. Exact supported finite hosts exercise all 17 real
minima; broader scalar hosts must refuse before driver inspection. This does not
certify an installed driver or admit native resources.

Independent source review/QA must compare exact scalar/profile/lifetime paths
and tests against the accepted design. The native positive capability/adapter,
M/R pre-issue enforcement, actual root/commit/close, supported driver profile,
real W01/W05/E06/E10/E05 cases and independent process-survival tests remain
unqualified. E31 and its fixture/runtime gate are unchanged. No runtime/WS-7,
deployment, full-product readiness or native closure is claimed by this source.

Correction v2 adds one optional monotonic continuity baseline and one sticky clock-fault boolean (+56 logical bytes). Q now charges seven clock/scratch occurrences and five booleans. Drain expiry at or after the deadline is authoritative after control returns, preserves committed counts, reports unresolved/nonclean host70; timely completed stops ignore later historical deadline expiry.

Correction v3 serializes clock sampling/comparison/baseline updates with the owner RLock. One sticky INTERNAL_FAILURE projection precedes every scalar export and locked host-success decision. Status publication uses one checked sample, never an unchecked second post-candidate sample. Fault projection preserves acknowledged cursor/counts and marks nonclean/unresolved without new retained state; Q444/E_summary6212 remains unchanged. No owner lock spans native I/O or application authority hooks.


## S2 serial adapter and preflight

preflight_native_recovery(config, *, limits) validates exact config first, obtains
RecoveryRequirements through the import-neutral Events recovery_profile module,
checks all17 LifecycleLimits minima and per-owner<=global relationships, then
calls verify_recovery_driver explicitly. Exact record types and same-object
requirements binding are required. Public preflight refuses after any setup
attempt; internal factory/run revalidation is not a reset. The unchanged
limits-only configure checks issuer availability and owns its once-only latch,
but cannot verify absent readiness/config inputs or guarantee external order.
Compatibility labels do not certify source semantics; installed trusted Events
source/version provenance and actual native issuer guards remain mandatory.

The lane reserves one execution, attaches one fresh checkout, starts E33 root,
prepares at e33_preparation_min and reserves e33_result_min, executes, drops its
read-result alias, releases result/ticket/preparation, commits, explicitly
acknowledges COMMITTED and releases the root. Only then can E13 start.
Each E13 uses prepare_recovery with namespace b"jobs", kind="job", limit=1,
raw UUID cursor and configured discovery1..4096. It uses the shared generic
E13 preparation minimum and full Work result minimum from Events. Native issuer
validation of the complete Work graph remains authoritative; the adapter also
requires exact ScanPage/WorkObservation identities before its internal scalar
projection. Projection occurs while B remains charged. No page escapes outward.

Successful projection drops the local page alias before releasing result,
ticket and preparation. The authority context encloses E13 root creation and
COMMITTED acknowledgement; cursor/count publication occurs afterward. Unknown
issuance/commit/projection/release stops without rollback/retry/refund. Native
handles and failed lane remain retained. Known commit facts survive later
cleanup failure. Startup E33 does not confer whole-namespace mutation authority.

At known quiescence only: retire -> prepare_cleanup -> reserve_cleanup(intent,
4096) -> pin_cleanup -> permit.close -> acknowledge_physical_close ->
release_cleanup -> detach_terminal -> dispose_execution. Exactly4096 is the
chosen logical cleanup reservation, even when configured capacity is larger.
An exception makes the lane permanently unavailable; no second cleanup bundle
or replacement lane is admitted. A synchronous native call can outlast host
shutdown and prevent a final report; external kill/absent acknowledgement is
UNKNOWN, never a guaranteed clean shutdown.

## S2 scalar accounting preservation

The CPython3.12/64-bit scalar profile remains S=1312, P=300, C31=1320,
C7=308, L=212, Q=444 and E_summary=6212. This is a logical owner-summary envelope,
not the entire adapter, native allocator, arbitrary application callbacks or RSS.
The lane holds a fixed14-slot handle/control record, no history or Work payload
field; Events configuration/requirements and paid registry handles are outside
this summary graph and remain subject to their own lifecycle/configuration scope.
No additional scalar is retained in the summary owner or its current/pending leaf.

The caller converts the scalar cursor to UUID before native prepare_recovery.
This is NOT inside native D. Conservatively count UUID64 + integer44 plus the
borrowed cursor integer occurrence44 =152 bytes for that non-projecting phase.
There is no pending summary before preparation. Even allowing the full three-S
observer/replacement peak and one C31 draft, 3*S+C31+152=5408 is below the
existing dominant 3*S+P+C31=5556. Add L+Q656:6064<=6212. The UUID argument passes
into Events paid preparation; the caller retains no UUID field. On preparation
return its raw cursor local is explicitly cleared before read/projection.
At projection, the original S+P+C7 path remains unchanged. Commit publication
and observer replacement retain the already accepted peak with no added cursor
transient. On preparation failure no result projection begins, and fail-stop
ownership remains unresolved; no capacity refund is inferred from exception
handling. This is finite logical scalar occurrence coverage, not a numeric
exception/frame/native temporary-byte allocation guarantee.


S2 correction v2 validates all seven universal relationships in one shared pure
limit validator: admitted_live/checkouts<=retained_cells, roots_per_checkout<=roots,
preparations_per_execution<=preparations, prepare_bytes_per_execution<=prepare_bytes,
results_per_ticket<=results, and result_bytes_per_ticket<=result_bytes. Both
preflight and limits-only configuration reject these detectable invalid vectors
before driver/capability checks or setup-latch consumption. The actual registry
configuration still begins only after _attempted is latched; an uncertain call
cannot retry. No new retained state or summary-accounting change is introduced.


## NR-D12 exact additional interpreter candidate

The scalar selector preserves the existing CPython3.12 family and its existing
platform scope, still subject to all prior exact layout/coefficient checks. Its
setup-report identifier is cpython-3.12-scalar-64. The additional candidate is
ONLY final CPython3.13.5 on Linux x86_64, pointer8, conventional GIL build with
Py_GIL_DISABLED exactly integer0, Py_DEBUG exactly integer0 and a present
_is_gil_enabled() returning exact True. Debug/refcount instrumentation and every
incompatible existing layout/coefficient remain rejected. Unknown build flags,
missing GIL observation, other machines, operating systems, patch versions and
prereleases refuse. No new restriction is applied to the preserved3.12 branch.

The new report identifier is cpython-3.13.5-linux-x86_64-gil-scalar-64; the separate
interpreter_version field reports the actual three-part version. These are pure
setup metadata, not retained per-page scalar fields or capability receipts.
They do not label3.13 as3.12, attest installed native code or grant authority.
The exact product snapshot/pending carrier basicsizes, enums, integer/tuple,
UUID and scalar guards and all accounting equations remain unchanged: Q444,
E_summary6212, cursor152/phase6064. No ABI,17-limit vector,D2,cleanup4096, driver,
SQL, authorization or adapter lifecycle change is introduced.

This source extension is a qualification candidate. Host3.12 monkeypatch tests
exercise selector branches and refusal behavior; they are NOT actual3.13 product
qualification. Independent source/pure review and an explicitly released
immutable actual3.13 product packet must establish complete product-carrier and
retained-graph compatibility before a support claim. Native/DB/process-loss
qualification remains a separate later gate.
