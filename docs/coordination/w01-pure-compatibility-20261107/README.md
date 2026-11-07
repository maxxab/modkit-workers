# W01 pure compatibility candidate

Status: **PASS, bounded pure compatibility slice only.** Independent review accepted the exact revised source and scope before execution. Run 02 matched all 84 required original/current records and passed six comparator sensitivity controls. No product implementation changed. This is not a replacement W01 packet, SQL qualification, target authorization, or production release.

## Exact scope and inputs

- Frozen fixture-v3 packet remains unchanged: SHA-256 897fccd0a1bcc34756ad77b9cb9d0e61dccea3c683576e63ca00bb278b77563d, 189 entries.
- Authoritative source-only reconciliation is ../w01-reconciliation-20261107 at the e2bbd3a reviewed baseline. The candidate pins its reconciliation.json and observed-inputs.json, checks all 190 observed entries, checks 181 unchanged original entries, verifies seven recovered originals against frozen hashes, and verifies the original SQL prefix by bytes. Reading those pins is not importing fixtures/drivers or executing SQL.
- Original/current comparisons use identical unchanged packet-pinned LIVE Workers files from /home/faris/modkit-workers/src, never the isolated checkout's modified handlers.
- source-manifest.json enumerates 33 required Python modules derived by static transitive import inspection, including real package initializers. It includes an exact case-name inventory. Seven recovered Events originals overlay only the original root. No SQL/resources, adapters, migrations, native_sync, or native_codec is copied or allowed to import.
- Neither package source nor fixture/test modules are modified, imported during preparation, or used as executable fixtures. Existing test_job_persistence_contracts.py was read as source to derive independent literal field/order/error assertions.

## Execution mechanics and bounds

compare_pure.py is a stdlib coordinator. It verifies pins before staging/imports, buffers verified bytes, writes only two private temporary roots beneath the system temporary directory, and starts exactly two sequential child interpreters with -I -S -B. Children run the same pure_payload.py. Environment is reduced to PATH=/usr/bin:/bin, LANG=C.UTF-8, TZ=UTC; stdin is DEVNULL. No lease, attempt marker, target configuration, connection, SQL, service, install, or external network operation is involved.

Child limits before product imports: address space 256 MiB, CPU 8 seconds, each stdout/stderr file 1 MiB, no core dumps, 32 descriptors, parent-enforced 15-second wall timeout each. Coordinator caps each inspected input at 16 MiB and summed observed inputs at 64 MiB; exact source counts and approved source paths bound staging. The candidate command additionally limits the coordinator to 512 MiB virtual memory, 25 CPU seconds and 45 seconds aggregate wall time. On inequality the comparator reports at most five differing top-level case names, each capped at 80 characters, without values. Outputs exceeding limits, nonzero exits, stderr, invalid JSON, missing/extra cases, unexpected exception types, and inequality all fail closed. Pin drift is checked again after both children.

Child imports: only named manifest product modules and interpreter stdlib/builtin modules. Real package initializers import asyncio; importing stdlib socket/subprocess support is harmless and allowed, while audited socket, subprocess, exec/spawn/fork, ctypes, process launch, filesystem mutation and environment mutation operations are denied. Audit open permits read-only paths beneath its temporary root and interpreter stdlib directory; all writes through open are denied. This is a guard against accidental operations in pinned trusted pure source, not an adversarial OS security sandbox. Starting threads through lower-level stdlib primitives is not a separately proven sandbox property; reviewed source makes no such calls.

Allowed product calls: Event/freeze; Scope/canonical_scope/decode_canonical_scope; public protected material constructors and canonical/decoder functions; JobInput/JobSubmitRequest/submit; public ReturnContext/freeze_request; canonical_intent; decode_submit. read_job/JobReadRequest and a cloned StatementSpec are used solely to present invalid W01 descriptor inputs, not to test W02 behavior. Existing public functions may call their own private implementation internally; the harness never substitutes private raw context/freezer APIs. object.__setattr__ is used only on an in-memory synthetic FrozenRequest negative case.

## Coverage matrix

| Area | Cases and assertions |
| --- | --- |
| Event/freeze | Nested mutable source snapshot; immutable fields; full event and canonical evidence; cyclic/nonfinite/non-JSON values; non-string keys; bool schema version; empty name; exact TypeError/ValueError classes |
| Scope | Literal minimal/full MKSC bytes and roundtrip; whitespace, oversized UTF-8 input, surrogate, wrong type, empty field and trailing frame rejection |
| W01 construction | Full 29-parameter request, full StatementSpec/ResultSpec/ParameterSpec metadata, nonempty AdmissionInput context, all canonical/replay/protected/intent bytes and digests retained in normalized records |
| Protected material | Absent, present sidecar, present reference; expiry/cleanup/recovery/projection data; both material halves and ERASED input rejected |
| Public freezing | Explicit ReturnContext plus list-parameter snapshot; mutable caller parameter list independence; empty/duplicate/wrong-container context rejection |
| Request coupling | Wrong UUID, namespace, semantic bytes, material sidecar, attempts and replay semantic content rejected for every material variant |
| Replay and versions | Alternate lawful whitespace replay spelling retained without changing intent/semantic bytes; int4-wide schema version; managed oversize version rejection; explicit deadline, attempts, idempotency, replay policy |
| W01 returned rows | Exact two-column UUID/bool records; same-ID inserted=True, same/alternate-ID inserted=False; zero/two/short/long rows; canonical UUID string acceptance; malformed/braced noncanonical and null UUID rejection; integer/null bool; mismatched inserted UUID; text/mapping row rejection |
| Decoder boundary | Wrong/cloned descriptor; mutated request revalidation; bounded iterator consumes exactly two records; ordinary iterator failure translates to INVALID_OBSERVATION/unconfirmed=True; BaseException identity preserved; ambient exception detached |
| Comparator | Both outputs compared as canonical JSON, distinguishing true from 1; independent expected values and exact error contracts asserted; required case inventory enforced; two in-memory negative controls replace a parameter-bearing result or row-error result; four comparator-only synthetic controls distinguish bool/int, tuple/list, frozenset/set and mappingproxy/dict. All must be detected; child normalizer assertions independently require each corresponding distinction |

Normalization preserves every dataclass field, enum type/value, byte value (hex), UUID, datetime/fold, float hex, mapping entries/order, sequence content and concrete container types (including mappingproxy/dict, tuple/list and frozenset/set). Canonical JSON comparison preserves bool/int distinctions. No semantic fields or mutability distinctions are dropped. Full failure records include exact class, args, error code, unconfirmed flag and exception-chain state. Unexpected exceptions are not converted to successful rejection results. The public persistence sanitizer contracts intentionally translate ordinary Exception; tests require their exact public error class/code, not the private original exception.

## Deliberately held coverage

This first slice does NOT claim all W01 behavior or all Events compatibility. It does not run database admission, SQL, concurrency, idempotency persistence, native drivers, adapters, lease gates, setup/disposal, targets, transactions, roles, migrations, performance, or complete fixture-v3. W01 returns an admission pair, not a full WorkObservation/JobRecord: W02/W04 full-record decoding, job-half coupling, scan/fence/claim paths, all catalog entries and private raw E14/E28 paths are held. Exhaustive malicious subclasses, Sequence/Mapping protocols, scalar sizes/depth boundaries, all Unicode/time zones, all protected metadata combinations and event replay-envelope permutations are also held.

Differential equality plus the included literal/structural oracles does not prove an exhaustive independent byte-format implementation. The full canonical records are compared across recovered/current Events, but the harness does not clone the complete MKPF serializer as an oracle. Six comparator negative controls prove mismatch detection for meaningful top-level records and synthetic primitive/container-type differences, not every individual field mutation. They are comparator sensitivity checks, not production mutations.

## Candidate command after exact-source review acceptance only

From Windows PowerShell, workdir C:\Users\faris:

    wsl.exe -d Ubuntu-24.04 -- bash -lc 'ulimit -v 524288; ulimit -t 25; timeout --signal=TERM --kill-after=2s 45s /usr/bin/python3 -I -S -B /home/faris/modkit-local-20261106/baseline-plan-20261107-standalone-only/commits-v3/workers/docs/coordination/w01-pure-compatibility-20261107/compare_pure.py --reviewed-pure-only'

The previous candidate run failed on the UUID-string oracle described above. After independent review of the correction, run 02 executed this bounded command successfully. File names are deliberately not pytest-discovered. Review must verify candidate/manifest hashes externally, then assess guard boundaries and expected assertions before authorizing this command. A successful pure comparison still leaves native/target/fixture/SQL authorization gates closed. No commit is made by this candidate or its preparation.

Static style verification: Ruff check and Ruff format --check passed after import/format cleanup. Product imports remain after installed audit/import guards, with narrowly scoped E402 annotations. Neither tool imported or executed candidate/product code.

UUID wire-oracle correction: source inspection of both recovered original rows.py (_wire_scalar) and current rows.py (_wire_scalar_core) confirms public UUID wire conversion accepts an exact canonical string after UUID parsing and str(parsed) equality. The revised slice asserts this lawful decoding and rejects malformed and braced spellings. The 84-case inventory replaces the incorrect row_reject_string_uuid case; no product-source change or compatibility-drift claim is made.

## Recorded execution outcome

- run-01.json preserves the original-child failure on the incorrect UUID-string rejection oracle. It is not evidence of product incompatibility.
- run-02.json preserves the successful tool output and exact executable/manifest pins. Result SHA-256: 7fe50c5cc596c813cf122d52ad4d7af2e60bb7771e43f2f85b112d9ad5820860.
- All 84 required normalized records match, six comparator-only controls passed, and current input pins plus the frozen packet were rechecked after both children.
- review-summary.json records the accepted source/scope and corrected findings. static-checks.json records independent Ruff lint/format verification.
- The full project test suite was not rerun for this isolated harness-only change; earlier full-suite counts remain historical. Native/runtime/target/fixture/SQL and ERP readiness requirements remain unresolved; those executions remain held.
- artifact-pins.json covers this completed evidence folder, excluding itself. README status was updated after execution; the code and source-manifest bytes remain exactly those accepted and executed.
