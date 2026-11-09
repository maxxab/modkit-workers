# Restricted synchronous DB-local JobWorkSource

This source is a one-slot execution-and-containment profile, not a general production worker or automatic recovery system. It is consumed by the explicit native worker factory. Existing WorkSource, HandlerRegistry, JobContext and one-shot run_batch contracts are unchanged. The native module can be imported without psycopg; actual startup requires the selected Events native profile and separately qualified installation/readiness pins.

## Ownership and application contract

The application first configures the once-only Workers native profile, then supplies two distinct fresh unpooled ManagedConnections and ExecutionLedgers through NativeJobResources. Both connections MUST target the same exact application database and authority. E33 receipt matching or matching endpoint labels does not prove database identity. Freshness is cooperative until authoritative Events reserve/attach checks after adoption. A post-adoption rejection retains source ownership and reports partial cleanup honestly; no reset, replacement or inferred ownership return is allowed.

DbLocalApplication.validate_profile(request) runs once before adoption/native issuance and returns None synchronously. It asserts claim/dispatch authority across the ENTIRE selected command/version population, ABSENT-only DB-local support and no required protected retrieval dependency. It grants/proves no authority. ExecutionLedger has no job Scope and W05 has no scope filter. The same fixed ledgers process successive actual acquired Scopes.

DbLocalApplication.bind(root, context) returns a synchronous context manager. Its entry must perform current authorization against actual job Scope/current database state and install the application's transaction binding. The source invokes the registered handler(context) without changing its signature, then BoundJob.result() supplies exact bounded bytes for E10. Handler return is always None and is not a result or commit receipt. Exceptions cannot be suppressed into success. The source revokes DbLocalRoot on exit. JobContext remains observational and carries no connection or authorization capability.

DbLocalRoot.connection is the exact source-adopted business ManagedConnection. The application must not commit, roll back, close, change autocommit, replace connections, use concurrent cursors/threads, invoke managed lifecycle configuration, or retain the root/context/material beyond binding. DB-local application SQL is sequential in the handler lane. Application callback allocations, SQL resources, result production and diagnostics have separate application-owned budgets; a result-size check does not prevent an application from first allocating an oversized result. No external provider or outgoing-event completion promise is made.

## Supported material and logical bounds

Only exact ABSENT material is supported: no sidecar/reference/codec/key/expiry, empty recovery bytes and RETAIN cleanup, with no required retrieval dependency. PRESENT and ERASED refuse before E06. Full-family native transport Q is NOT protected-handler support; protected retrieval remains follow-on work. Existing typed Workers material already requires Mapping semantic/projection data.

Q bounds native output occurrences; L/R bound semantic input/result bytes, each at most 1MiB; depth at most32. source_material_bytes reserves logical retained/source-visible construction occurrences, not physical allocation or process RSS. For G=1024*(1+floor(L/9))+8L, require E=4G+16*33*L+262144+4R+4096. A full-domain profile reserves1GiB logically (exact E1068883968), Q2**32 and the independently accepted native vector. Smaller profiles explicitly restrict supported producers/capabilities.

Before W05, reserve the source envelope. While native B remains paid, detach permitted semantic/scalar material and cursor state. Drop borrowed page/record/protected graph references, release B/ticket/A, and only then COMMIT and acknowledge before exposing JobWork. Native and detached occurrences remain separately charged even if immutable identities alias. E08 guard transfer follows the same rule. One failed phase retains its envelope; no retry accumulation or timeout-based refund.

## Durable lifecycle and control

The core alone binds source/control and renewal callbacks. Source owns acquisition reservation/publication/refusal and terminal retirement. An issued reservation survives ordinary stop for continuation; no new reservation follows stop. Empty committed pages preserve cursor progress and are distinct from rollback refusal.

W05 COMMITTED -> E06 COMMITTED -> stable dispatched fence/renewal activation -> E14/E08 exact business root -> application binding/business writes -> actual renewal quiescence -> E10 in the SAME business root -> COMMITTED success. Only acknowledged durable terminal outcomes increment counters. Fresh W02 is a separately budgeted QA observation, not an automatic production reread.

A business exception can become ordinary confirmed_failed only after accepted strict original-root rollback and E11 on a new root of the SAME checkout while the strict-ended original root remains retained. It returns None and retires normally after known settlement/cleanup. SQL-aborted or replaced roots without strict proof do not authorize E11. Unknown outcomes fail closed with a sanitized NativeJobUnresolved; no application messages/tracebacks are stored in the bounded incident record. Source graphs retained by external aliases cannot be claimed released under the cooperative profile.

Known precommit profile refusal rolls back and acknowledges, then refuse_acquisition clears only the local reservation and stops admission with PROFILE_UNSUPPORTED. It is not a committed-empty page or a durable failed job. Unknown finalization retains reservation/claim/material. A known terminal result with uncertain cleanup retains the durable counter and reports unresolved cleanup separately.

## Renewal, health and shutdown

Renewal uses the separate fixed lane/checkout/ledger and starts only after E06 acknowledgement. It never shares the blocking handler lane, but SQL locks and CPU scheduling can still prevent progress. Closing renewal must prevent future admission and establish actual quiescence/known outcome before terminal settlement. Controller RenewalQuiescence.domain_active is only scheduling eligibility; source separately checks the canonical Events domain.

Stop blocks new W05; already-admitted work drains while deadline/fence/domain permit. Explicit cancellation before dispatch retains unresolved claim and reports unclean; it is not database cancellation. Timeout or cancellation never kills a native thread or proves rollback. Shutdown closes only proven-quiescent owned resources via managed receipts. Partial startup/native uncertainty remains retained and NOT_READY. Source snapshots report actual locally executing calls separately from unresolved backend ownership; false native_in_flight alone is not a quiescence guarantee.

No automatic retry, restart, E13 job recovery, E31 held resolution, provider reconciliation or detailed cross-process incident handoff is implemented. Unknown business outcomes remain conservatively unresolved; the source does not automatically issue E32 to manufacture settlement. Acknowledged E06 remains the durable replay barrier. Full product readiness and native worker qualification remain separately gated.

## Verification boundary

Pure tests exercise real source material/application/orchestration code and use explicit test-only collaborators at native I/O boundaries. They create no DB connections and are not native transaction evidence. Actual combined startup/claim/renewal/business/settlement QA requires the separately reviewed isolated packet and release. Source review, native QA and Git integration are distinct gates.

### Startup admission

The source first calls the bound control's one-shot `admit_startup(self)`, before changing its once-only flag or phase, invoking application validation, adopting resources, or issuing native work. Inert, unstarted, foreign-lane, and duplicate calls cannot consume legitimate startup. A stop that wins admission propagates the orderly admission-closed outcome without ownership transfer. Once admitted, startup may finish readiness and cleanly drain after stop; that admission never grants permission to claim jobs.
