# Pure worker contracts

Workers root imports use only the standard library through lazy loading. This does not make Workers independent of Events: the distribution requires Events, and persistence uses Events-owned contracts. Events itself must remain usable without Workers.

These unpublished interfaces provide explicit handler lookup, immutable execution observations, bounded acquisition arguments and application-owned source hooks. They do not run workers. `JobWorker` and `EventWorker`, runtime startup, adapters, services and durable execution qualification remain pending. Root imports require only the standard library; constructing `JobContext` or `AcquireRequest` explicitly uses the actual `modkit-events` pure shared contracts.

## Explicit handler registration

```python
from modkit_workers import HandlerKind, HandlerRegistration, HandlerRegistry


def send(context):
    # Application-owned source must authorize and establish its execution boundary first.
    pass


registry = HandlerRegistry([
    HandlerRegistration(command_type="send", schema_version=1,
                        handler=send, kind=HandlerKind.SYNC),
])
registration = registry.get("send", 1)  # Lookup only: no handler call.
assert registration.handler is send
```

`SyncJobHandler(context, /) -> None` describes synchronous callbacks; `AsyncJobHandler` describes native `async def` callbacks returning None when awaited. `HandlerKind` must match the actual direct or callable-instance entrypoint. Coroutine functions cannot register as SYNC, and generator/async-generator entrypoints cannot register in either mode. ASYNC requires a native coroutine entrypoint; a synchronous function producing an awaitable needs an explicit supported wrapper. Registration inspects entrypoints without invoking them. Exact built-in `functools.partial` wrappers are transparent to these shape checks, including when they bind arguments to callable instances; the original wrapper remains the registered callback. This additional unwrapping applies only to exact built-in partial wrappers, including partial-backed `__call__` entrypoints. Partial-linked callable chains are limited to 64 inspected callable/partial objects; cycles or longer chains fail with `InvalidWorkerConfiguration` without invoking the callback. Arbitrary decorators are not followed, and custom partial subclasses are outside this transparency guarantee. Dynamic descriptors can raise their original programmer errors.

The registry never calls handlers, validates return values, awaits/closes coroutines or chooses an executor. A source explicitly obtains a registration and calls its callback in the chosen execution environment. Synchronous calls run where called; blocking handlers require the application's explicit bounded executor policy. Applications enforce return/exception policy during execution. Callback state and thread safety remain application-owned.

Each registry belongs to one logical source/subscription. Independent subscribers use separate registries and can bind different callbacks for the same name/version. It snapshots at most4096 registrations, preserves registration order, and returns exact capabilities as a frozenset of `(command_type, schema_version)` pairs. Duplicates raise `DuplicateHandlerError`, including duplicate identical callbacks. All versions of a command require the same route (including None); conflicts raise `ConflictingHandlerRouteError`. Different commands may share routes. Jobs can omit route; Event preflight below requires matching named routes and exact capabilities. No Event runtime is supplied.

Identifiers are exact strings, nonblank, strict UTF8 and1..256 bytes without NUL; no trimming/normalization occurs. Logical versions are positive Python ints (bool rejected), including wide versions. Lookup distinguishes malformed configuration (`InvalidWorkerConfiguration`), unknown name (`UnknownCommandType`) and missing version of a known name (`UnsupportedHandlerVersion`). Registry capabilities are logical manifest entries, not automatically persistable acquisition capabilities.

## Pure preflight validation

`registry.validate_acquisition(request)` reconstructs an exact `AcquireRequest` through its existing constructor, then checks every selected name/version through `registry.get`. It returns a fresh canonical request with exactly the selected pairs and bounds. Unknown names raise `UnknownCommandType`; an unregistered version of a known name raises `UnsupportedHandlerVersion`. Selection can be a subset of the registry. There is no automatic capability selection, pair crossproduct, int4 conversion or dropping of wide logical versions.

For Events, construct shared `Subscription` and `ContractRegistry` values and register matching named Worker routes:

```python
checked_request = registry.validate_subscription(
    subscription, event_contracts, request=request,
)
```

The request is required. This method reconstructs the subscription, validates acquisition, checks every Worker registration route against subscription.route, then calls the existing shared `Subscription.validate` twice: for the full logical registry and for the selected active pairs. Both manifests must be supported by the shared contracts, and every subscribed name must have an active selected pair. Registered versions need not all be active. Logical wide versions remain legal when the full shared manifest supports them and the explicit active subset uses representable versions. Separate subscribers use separate registries. Collection identity/group checks still require Events `validate_subscriptions`; this method does not create/reset consumer groups.

Both methods FIRST reject a nonexact `HandlerRegistry` receiver with fixed `InvalidWorkerConfiguration("Expected HandlerRegistry")`, before imports, reconstruction or overridden metadata methods. Acquisition requires an exact `AcquireRequest`; Event preflight requires exact shared `Subscription` and `ContractRegistry`. Wrong classes raise fixed `InvalidWorkerConfiguration`; local route mismatch raises `InvalidWorkerConfiguration("Handler route does not match subscription")`. Canonical request/subscription constructor errors and shared `UnsupportedCapabilityError` remain unchanged. Event order is exact receiver/shared types, subscription reconstruction, acquisition reconstruction/lookup, local route scan, full logical validation, then active validation. First failure among several invalid logical pairs is unspecified because capabilities are a frozenset.

Preflight revalidates caller request/subscription inputs without mutating them; caller iterator errors and BaseException propagate unchanged. It consumes bounded constructor collections and returns an immutable current request snapshot. Existing registries retain their constructor-validated immutable trust boundary. Deliberate private/index corruption or `object.__setattr__` changes to stored registrations/contracts/callbacks are unsupported; preflight does not reconstruct registries or reinspect application descriptors. Later deliberate bypass of frozen dataclasses invalidates the snapshot assumptions.

Preflight never invokes handlers, payload validators, source hooks/properties, providers, transactions or IO. It owns no resources to close. Request/subscription reconstruction may consume supplied iteration code; arbitrary user code is not generally sandboxed. Root imports remain stdlib-only, with shared imports deferred until the explicit operations need them. Successful preflight is configuration validation only: startup execution, transaction-ownership negotiation, actual capability-filtered claims, blocked-schema scheduling, health, deployment and resource readiness remain pending.

## Immutable execution context

```python
from modkit_events.persistence.scope import Scope
from modkit_workers import JobContext

context = JobContext(work_id="application-owned-id", command_type="send",
                     schema_version=1, scope=Scope("example"),
                     payload={"message": "hello"}, attempt=1)
```

Context requires work ID, command type, logical schema version, shared `Scope`, payload Mapping and attempt1..1000. Optional deadline is an exact aware datetime normalized to UTC. IDs use the managed identifier profile above; a custom source retains its application identifiers, while the built-in store separately requires canonical UUIDs. Attempts/deadlines are observations, not an attempt increment or deadline extension. Scope retains the shared byte-preserving scope rules, including its distinct NUL/normalization policy, and is copied/revalidated.

Payload snapshots use the existing shared `canonical_json`/`parse_canonical_json` codec. Nested mappings/arrays become immutable mappings/tuples, preserving typed numbers. This context uses the managed JSON profile: canonical bytes<=1MiB, depth<=32, nodes<=262144, container items<=65536, finite floats and integer decimal representation<=4096 digits. It is narrower than logical `JobInput` payload construction. No second freezer, MKPF decoder or public serializer is introduced.

Invalid local scalars raise fixed-message `InvalidWorkerConfiguration`. Shared scope failures preserve detached `ValueError("Invalid scope")`; shared codec failures preserve fixed-code `PersistenceError(LOCAL_INVALID_ARGUMENT, unconfirmed=False)`. Invalid shared `Capability` scalars similarly preserve `PersistenceError`. Cancellation/BaseException follows the existing shared boundary behavior. New local errors do not promise detached exception chains; applications must control traceback/error exposure.

Context contains no protected binding, sidecar/reference, key metadata, provider, transaction/session, ownership fence or public projection. It conveys no authorization or transaction authority. Context payload and scope may still contain sensitive application data; `repr=False` avoids normal field repr but does not prevent reflection, custom serialization or logging. There is no default API projection. Applications authorize first and explicitly allowlist public fields; never fall back to context or protected records when a public projection is missing or mismatched. Protected material is resolved separately through the application's authorized private provider path.

## Bounded acquisition and settings

```python
from modkit_events.persistence.models import Capability
from modkit_workers import AcquireRequest, WorkerSettings

settings = WorkerSettings(acquire_limit=1, discovery_budget=16)
request = AcquireRequest(capabilities=[Capability(command_type="send", schema_version=1)],
                         limit=settings.acquire_limit,
                         discovery_budget=settings.discovery_budget)
```

Both settings are required, with no default resource budget. Limits are exact ints (bool rejected): acquisition limit1..256 and discovery budget limit..4096. Unknown settings, including runtime knobs, fail TypeError. Settings are explicitly copied into a request by the caller; no runtime consumes them automatically.

AcquireRequest snapshots and sorts1..256 exact shared `Capability` values, rejecting duplicates. Persisted runnable versions are1..2147483647; the caller explicitly chooses this subset from potentially wider logical registry capabilities. There is no silent truncation or automatic dropping of unsupported versions. Unsupported stored work remains subject to the shared blocked-schema policy. Shared scalar revalidation never trusts a previously constructed but subsequently altered object.

These are logical request bounds, not physical IO, latency, peak-memory or database resource guarantees. Lease duration and durable cursor/page semantics remain source-owned. Execution slots, prefetch/tasks, thread queues/executor capacity, connection reservations, fairness, intervals, timeouts, shutdown drain, diagnostics and driver/profile capacities are held until a future runtime enforces their complete budgets before spawning work. Constructing settings is no startup/readiness certificate.

## Application-owned sources

`WorkSource[WorkT]` is synchronous; `AsyncWorkSource[WorkT]` has explicitly awaited hooks. Both are static structural protocols, not runtime readiness checks:

| Hook | Signature / responsibility |
| --- | --- |
| renewal_owner | property returning exactly `RenewalOwner.SOURCE` |
| acquire | `(request: AcquireRequest, /) -> tuple[WorkT, ...]`, at most request.limit opaque handles |
| execute | `(work: WorkT, /) -> None`, source-managed execution and durable outcome handling |
| cancel | `(work: WorkT, /) -> None`, cooperative cancellation request for that acquired handle |
| shutdown | `() -> None`, request drain/release of source-owned resources |

For async sources each hook except the property is `async def` with the same eventual return type. The protocols supply no implementation, invocation, offloading, controller or scheduler. Application handles need no package base class or duplicate application job record. Source owns cursor/scan progress; an empty acquisition tuple never proves queue/pass exhaustion. Built-in W05 complete-page/visited/cursor semantics stay inside its separately implemented source. A future engine must validate source output bounds before tasks and safely handle invalid output without abandoning acquired work.

SOURCE explicitly identifies the one authoritative renewal path. Application sources delegate to their existing executor/heartbeat. A common runtime must honor this negotiation and must not add another heartbeat. A future built-in source may use the existing shared lifecycle controller internally; this pure interface neither implements nor proves renewal. Alternative runtime delegation requires a separately reviewed contract.

The source/application owns actual authorization, fencing/deadline checks, provider access, credentials, quotas, dispatch intent/idempotency, authoritative attempts, transaction roots and uncertainty reconciliation. Native sync sources preserve caller-owned synchronous psycopg and paired business transactions; async sources choose their actual supported async driver/session explicitly. There are no hidden commits, fabricated receipts or new transaction authority. Current Events managed-root/factory requirements and qualification gates still apply.

On success, source owns observing its actual durable result. On business failure it rolls back the full business root before fenced failure recording in a separate caller-owned root. Uncertain commits/provider outcomes remain held for reconciliation. A returned None or raised exception is control flow, not commit/rollback proof or replay permission. No generic engine may infer provider replay safety from either.

Cancel requests do not prove persisted cancellation, authorization, rollback or that external work stopped. Shutdown does not prove threads stopped or shared application pools were released. A cancelled await cannot stop its backing thread; source and runtime must track real execution/drain and preserve uncertainty. Hooks must coordinate source-owned execution/renewal; resource ownership and partial-startup cleanup require future runtime/application integration. No timeout, cancellation token or drain deadline is implemented here.

The package does not invoke/wrap callbacks, swallow programmer errors, replace cancellation identity, close returned awaitables or log diagnostics. Applications own safe diagnostics; callback exception/traceback exposure must be controlled explicitly. Pure source examples are interface demonstrations, not real transaction, heartbeat, cancellation or shutdown qualification.
