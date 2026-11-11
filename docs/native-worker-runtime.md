# Restricted native job worker

This is a one-slot synchronous DB-local execution profile. It is not a general
worker, automatic recovery service, or production-readiness declaration. Native
startup/combined runtime qualification remains separately gated.

## Imports and construction

Use explicit leaves, not new root-package exports:

- native_contracts: NativeJobConfig, NativeJobResources, NativeWorkerSettings and
  the existing control observation/type identities.
- native_setup: configure_native_job_profile and its opaque
  NativeJobConfigurationReceipt.
- native_worker: create_job_worker and JobWorker.
- native_job: the actual JobWorkSource and application-owned binding contracts.

Importing these user-facing leaves must not connect, configure a resource domain,
start threads or import an optional driver merely to inspect pure definitions.
Explicit native resource validation/startup requires the supported Events native
profile and its optional driver. A missing driver is a real prerequisite failure,
not permission to install one or substitute a fake connection.

The construction order is:

1. Supply reviewed LifecycleLimits and call configure_native_job_profile once.
   It wraps the existing canonical Events configuration, not a second domain.
   A domain configured elsewhere without this receipt is unsupported. No reset
   or second configuration attempt recovers an uncertain or stopped domain.
2. Application creates exactly two fixed fresh/unpooled ManagedConnections and
   two distinct ExecutionLedgers. Both connections must target the SAME exact
   application database and authority. No automatic connection factory/pool or
   replacement connection is supplied.
3. Construct caller-pinned NativeJobConfig and inert NativeJobResources.
4. Call create_job_worker with the actual HandlerRegistry, application, config,
   resources, explicit AcquireRequest(limit=1), and NativeWorkerSettings.
   Factory construction is inert. _SupervisorCore is the sole source/renewal
   binder; the factory must not prebind those callbacks.
5. start begins the bounded supervised lifecycle. Startup validates application
   profile and resource facts, adopts resources at its explicit ownership point,
   checks E33 pins, then enables acquisition.

The public JobWorker wrapper exposes start(), request_stop(),
stop(timeout=...), and snapshot(). It is one-shot; it cannot restart a failed or
stopped source. Repeated stop calls observe/wait on the same retained owner.

## Application authority and protected material

DbLocalApplication.validate_profile(request) is pure preflight. Its successful
None return is the application's cooperative assertion that it currently has
claim/dispatch authority over the ENTIRE command/version capability population,
supports this DB-local ABSENT-only profile and requires no protected retrieval.
An exception, non-None return, generator or awaitable rejects startup.

This assertion does not grant or prove authorization. Application bind must
additionally authorize each actual acquired job Scope against current DB state,
bind the exact business connection/root, invoke the unchanged handler(context)
contract, and project a bounded exact bytes result. JobContext is observational;
neither it nor a ledger grants scope/transaction authority. Multiple actual job
Scopes may use the same fixed ledgers under those explicit authorization rules.

The binding entry must synchronously return an object with a callable result
method. Awaitable/generator or malformed entry results reject before handler
invocation. Binding exit must synchronously return None or an exact bool;
unsupported exit results prevent application success. Suppression never turns a
failed handler into success. A handler interruption remains unresolved even when
unbinding also fails. Accidentally returned unstarted Python coroutines
and generators are closed, not awaited; this does not cancel running async work.

Only MaterialState.ABSENT with the exact accepted absent-material shape is
supported. PRESENT, ERASED and required sidecar/reference retrieval fail closed
before E06/handler. Full-family transport capacity is not permission to execute
protected payloads. Applications must not silently drop protected dependencies.

Handler/binding code must not commit, roll back, open independent native
connections, mutate managed lifetime state, perform providers/outgoing events,
or retain borrowed business handles past their approved scope. Application
allocation and diagnostic retention are separate from the library's logical
resource envelope.

## Capacities and reservations

NativeJobConfig fields are exactly readiness, lease_seconds,
max_acquire_page_payload_bytes, max_payload_bytes, max_payload_depth,
max_result_bytes and source_material_bytes.

Q is the W05 all-variable-material allowance, independently configurable within
1..2**32. L and R each cover accepted canonical bytes within 1..1048576; depth is
1..32. An application-selected lower bound restricts support: capability
registration does not filter queued size or protected material. Q is not a
semantic-payload bound.

The accepted logical source formula is:

G(L) = 1024 * (1 + floor(L / 9)) + 8L
E(L,R) = 4G(L) + 16 * 33 * L + 262144 + 4R + 4096

source_material_bytes must be at least E(L,R). Full canonical L=R=1048576 needs
E=1068883968; a 1073741824-byte logical reservation suffices. This does not
allocate a GiB, bound application callbacks, or claim an RSS/allocator limit.

Setup enforces the accepted conservative full-family native vector even for a
smaller source profile: P/V/C/X=2, R=3, roots_per_checkout=2, A/B=2 with one
preparation per execution and one result per ticket, AB=1049857,
BB=44129507, K=2, KB=8192 and D=6. Existing LifecycleLimits field identities and
per-owner values remain authoritative. Inadequate capacity rejects before W05;
there is no silent fallback after claim.

Source reserves its detached-material envelope before copying a W05 page.
Native B and detached source bytes overlap while copying. All native borrowed
aliases/results/tickets/preparations must be released before acquisition COMMIT;
only its COMMITTED acknowledgement exposes work. Detached source charge remains
through execution, never an uncharged borrowed W05 payload.

## Resource ownership and readiness

The raw connections remain application-owned through pure factory construction
and rejected preflight. Source adoption publishes one receipt-plus-exact-carrier
association. After that point source owns partial startup and cleanup obligations.
A failed return does not establish that adoption did not happen; reconcile the
same association. No automatic retry, reset, reownership or refund is inferred.

Preflight checks supported current facts: exact distinct types/identities, idle
driver status, no current ledger uncertainty, receipt provenance, active domain
and accepted limits. Historical freshness is an explicit cooperative precondition,
not something pure preflight proves. Authoritative canonical reserve/attach
after adoption rejects prior-use violations. Such rejection retains post-adoption
partial-cleanup obligations and truthful NOT_READY state; it does not authorize
inspection/mutation of private Events history or closing another owner's object.

Matching E33 receipts do not prove both connections reach the same database.
Endpoint labels are not a universal identity test. The same-database/same-authority
condition remains application responsibility; native QA must establish it by
fixture construction and independent observation.

No acquisition is allowed before actual E33, source/profile/capacity validation
and live independent control. Direct source execution/run_batch without that
bound supervised lifecycle is unsupported. Generic run_batch behavior is unchanged.

## Dispatch, renewal and terminal outcomes

Acknowledged E06 commit is the durable replay barrier. Renewal activates only
after that commit with its returned dispatched fence; there is no predispatch
renewal or update_dispatch handoff. E08 still revalidates actual native authority
before binding/handler entry.

There are at most three owned non-daemon threads: coordinator, data lane and
independent source-owned renewal lane. A blocked handler does not occupy renewal's
execution lane or checkout. This does not guarantee progress against arbitrary
application SQL locks, CPU starvation or DB outage.

Before E10/E11, source closes renewal admission and waits for actual quiescence
and known disposition. RenewalQuiescence.domain_active is only the controller-side
nonfailure observation. Source must ALSO check the actual canonical Events
domain active/nonstopped before native terminal admission. Neither control state,
a completed Future nor timeout establishes native authority.

E10 and business writes commit in the exact guarded business root. A safely
acknowledged strict-original-root rollback followed by same-checkout E11 terminal
failure is an ordinary confirmed result: count failed once, retire lawfully and
return None. An aborted/replaced root or inferred rollback is insufficient proof.

Counters represent acknowledged durable outcomes, never handler returns or
staged rows. Confirmed success followed by uncertain cleanup remains success
with unresolved cleanup; it is not relabeled as business failure.

## Stop and uncertainty

Acquisition reservation and stop share one short lock. The retained in-flight
reservation is recorded BEFORE unlocking; no lock spans blocking W05. Stop
prevents NEW reservations. Already-reserved acquisition may physically send after
stop and remains admitted drain work. There is no promise of zero physical sends
after stop.

A confirmed returned handle drains E06/business/settlement while real authority
permits. The configured drain-admission deadline may bar a NEW E06 for unstarted
work, retaining that claim unresolved. Caller stop(timeout=0), or any expired
caller wait, only ends that wait. It does not stop a thread or disable lawful
renewal/settlement for an already-dispatched handler.

clean_stop requires actual thread/backend quiescence as applicable, legitimate
source cleanup and no unresolved obligations. Owners remain retained after an
unclean wait. Do not drop the worker, forcibly close its connections, refund
charges or assume interpreter exit cancels native operations. Non-daemon lanes
may intentionally keep the process alive while owned work remains in flight.

Known precommit rollback/no-claim uses the distinct refusal hook and preserves
PROFILE_UNSUPPORTED (or the truthful refusal reason). No durable outcome count
is invented; clean resource shutdown may eventually be true while worker state
is FAILED/not ready. Genuinely committed empty pages use normal empty publication.
Unknown acquisition/rollback/commit retains reservation/work and fails closed.

No domain reset, replacement-ledger escape, automatic retry/restart, E31 resolution,
automatic E13 recovery, or lossless cross-process incident handoff is promised.

## Evidence limits

Pure tests use real bounded threads and canonical pure configuration logic, with
explicit test-only driver/resource doubles where the optional driver is absent.
They do not qualify actual connections, E33 installation, business transactions,
native memory/accounting or combined runtime behavior. Independent source review
and a separately reviewed/released isolated native packet are still required.


## Bound startup admission

The supported supervisor data lane must pass one-shot admit_startup before the
source consumes its startup flag or invokes application/resource/native work.
Foreign or unstarted calls cannot steal initialization. This pre-ready gate
grants no claim or execution lease. Stop winning the gate is orderly nonadmission;
startup already admitted may finish initialization and clean up its actual
ownership, without publishing ready or claiming jobs. Native-domain checks and
post-adoption uncertainty remain source obligations.
