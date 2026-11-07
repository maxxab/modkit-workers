"""Prepared pure W01 compatibility payload. Not pytest-discovered."""

import dataclasses
import datetime
import enum
import hashlib
import json
import os
import pathlib
import resource
import sys
import uuid
from collections.abc import Mapping
from types import MappingProxyType

ROOT = pathlib.Path(sys.argv[1]).resolve()
ALLOW = frozenset(json.loads(sys.argv[2]))
# Limit before product imports. Parent supplies two sequential children, never a driver.
resource.setrlimit(resource.RLIMIT_AS, (268435456, 268435456))
resource.setrlimit(resource.RLIMIT_CPU, (8, 8))
resource.setrlimit(resource.RLIMIT_FSIZE, (1048576, 1048576))
resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
resource.setrlimit(resource.RLIMIT_NOFILE, (32, 32))
STDLIB = pathlib.Path(os.__file__).resolve().parent


def audit(event, args):
    if event == "open":
        path, mode, flags = args
        if not isinstance(path, (str, bytes, os.PathLike)):
            raise RuntimeError("Denied file descriptor open")
        p = pathlib.Path(os.fsdecode(path)).resolve()
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
            raise RuntimeError("Denied write")
        if not (p.is_relative_to(ROOT) or p.is_relative_to(STDLIB)):
            raise RuntimeError("Denied external read")
    if event.startswith(
        ("socket.", "subprocess.", "os.exec", "os.spawn", "os.fork", "ctypes.", "pty.")
    ) or event in {
        "os.system",
        "os.posix_spawn",
        "os.remove",
        "os.rename",
        "os.rmdir",
        "os.mkdir",
        "os.chmod",
        "os.chown",
        "os.truncate",
        "os.link",
        "os.symlink",
        "os.chdir",
        "os.putenv",
    }:
        raise RuntimeError("Denied side effect: " + event)


sys.addaudithook(audit)


class Imports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("modkit_events", "modkit_workers")):
            if fullname not in ALLOW:
                raise ImportError("Unapproved product module: " + fullname)
        elif fullname.split(".")[0] not in sys.stdlib_module_names:
            raise ImportError("Non-stdlib import: " + fullname)
        return None


sys.meta_path.insert(0, Imports())
sys.path.insert(0, str(ROOT))
from modkit_events.models import Event, freeze  # noqa: E402 - product imports require installed guards.
from modkit_events.persistence import bindings as common  # noqa: E402 - product imports require installed guards.
from modkit_events.persistence.errors import ErrorCode, PersistenceError  # noqa: E402 - product imports require installed guards.
from modkit_events.persistence.models import (  # noqa: E402 - product imports require installed guards.
    AdmissionInput,
    CleanupPolicy,
    MaterialState,
    ProtectedBindingInput,
    ReplayPolicy,
)
from modkit_events.persistence.scope import Scope, canonical_scope, decode_canonical_scope  # noqa: E402 - product imports require installed guards.

from modkit_workers.persistence.bindings import read_job, submit  # noqa: E402 - product imports require installed guards.
from modkit_workers.persistence.models import JobInput, JobReadRequest, JobSubmitRequest  # noqa: E402 - product imports require installed guards.
from modkit_workers.persistence.rows import decode_submit  # noqa: E402 - product imports require installed guards.


def normalize(v):
    if isinstance(v, enum.Enum):
        return {
            "enum": type(v).__module__ + "." + type(v).__qualname__,
            "value": normalize(v.value),
        }
    if v is None or type(v) in (str, bool, int):
        return v
    if type(v) is float:
        return {"float_hex": v.hex()}
    if type(v) is bytes:
        return {"bytes_hex": v.hex()}
    if type(v) is uuid.UUID:
        return {"uuid": str(v)}
    if type(v) is datetime.datetime:
        return {"datetime": v.isoformat(), "fold": v.fold}
    if dataclasses.is_dataclass(v) and not isinstance(v, type):
        return {
            "dataclass": type(v).__module__ + "." + type(v).__qualname__,
            "fields": [[f.name, normalize(getattr(v, f.name))] for f in dataclasses.fields(v)],
        }
    if isinstance(v, Mapping):
        # Preserve insertion order as well as all keys/values.
        return {
            "container_type": type(v).__module__ + "." + type(v).__qualname__,
            "mapping": [[normalize(k), normalize(x)] for k, x in v.items()],
        }
    if type(v) in (tuple, list):
        return {
            "container_type": type(v).__module__ + "." + type(v).__qualname__,
            "sequence": [normalize(x) for x in v],
        }
    if type(v) in (set, frozenset):
        return {
            "container_type": type(v).__module__ + "." + type(v).__qualname__,
            "set": sorted((normalize(x) for x in v), key=lambda x: json.dumps(x, sort_keys=True)),
        }
    raise AssertionError("Unnormalized type: " + str(type(v)))


# Normalizer sensitivity controls: synthetic values only, never product mutations.
for first, second in (
    (True, 1),
    ((1,), [1]),
    (frozenset({1}), {1}),
    (MappingProxyType({"v": 1}), {"v": 1}),
):
    assert json.dumps(normalize(first), sort_keys=True, separators=(",", ":")) != json.dumps(
        normalize(second), sort_keys=True, separators=(",", ":")
    )
out = {}


def record(name, value):
    assert name not in out
    out[name] = normalize(value)


def rejects(name, thunk, cls, code=None, unconfirmed=None):
    try:
        thunk()
    except Exception as e:
        assert type(e) is cls, (name, type(e), cls)
        if code is not None:
            assert e.code is code and e.unconfirmed is unconfirmed
            assert e.__cause__ is None and e.__context__ is None and e.__suppress_context__ is True
        record(
            name,
            {
                "class": type(e).__module__ + "." + type(e).__qualname__,
                "args": e.args,
                "code": getattr(e, "code", None),
                "unconfirmed": getattr(e, "unconfirmed", None),
                "cause": e.__cause__,
                "context": e.__context__,
                "suppress_context": e.__suppress_context__,
            },
        )
    else:
        raise AssertionError("Expected rejection: " + name)


def local(name, f):
    rejects(name, f, PersistenceError, ErrorCode.LOCAL_INVALID_ARGUMENT, False)


def badrow(name, f):
    rejects(name, f, PersistenceError, ErrorCode.INVALID_OBSERVATION, True)


ID = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
U, V = uuid.UUID(ID), uuid.UUID(OTHER)
NOW = datetime.datetime(2030, 1, 1, tzinfo=datetime.timezone.utc)


def material(kind="absent"):
    return ProtectedBindingInput(
        material_state=MaterialState.ABSENT if kind == "absent" else MaterialState.PRESENT,
        codec=None if kind == "absent" else "codec",
        key_version=None if kind == "absent" else "v1",
        expires_at=None if kind == "absent" else NOW + datetime.timedelta(days=1),
        cleanup_policy=CleanupPolicy.RETAIN
        if kind == "absent"
        else CleanupPolicy.ERASE_AFTER_TERMINAL,
        sidecar=b"sealed" if kind == "sidecar" else None,
        reference=b"reference" if kind == "reference" else None,
        content_binding=b"" if kind == "absent" else b"binding",
        recovery_metadata=b"" if kind == "absent" else {"recover": True},
        projection_metadata={"view": "public"},
    )


def job(**changes):
    args = dict(
        work_id=ID,
        command_type="send",
        schema_version=1,
        scope=Scope("app", None, "owner"),
        payload={"value": 1},
        original_available_at=NOW,
        protected=material(),
    )
    args.update(changes)
    return JobInput(**args)


def prepared(**changes):
    return submit(JobSubmitRequest(job=job(**changes)))


mutable = {"nested": [{"v": 1}]}
ev = Event("event-1", "send", mutable, metadata={"trace": [True, None]})
frozen = freeze(mutable)
j = job(payload=mutable)
mutable["nested"][0]["v"] = 9
mutable["nested"].append(3)
assert ev.payload["nested"][0]["v"] == frozen["nested"][0]["v"] == j.payload["nested"][0]["v"] == 1
assert len(ev.payload["nested"]) == len(frozen["nested"]) == len(j.payload["nested"]) == 1
record("event_snapshot", ev)
record("freeze_snapshot", frozen)
record("job_snapshot", j)
record("event_evidence", common.canonical_event(ev))
rejects("event_immutable", lambda: setattr(ev, "name", "changed"), dataclasses.FrozenInstanceError)
rejects("job_immutable", lambda: setattr(j, "schema_version", 2), dataclasses.FrozenInstanceError)
rejects("freeze_object", lambda: freeze(object()), TypeError)
rejects("freeze_nonfinite", lambda: freeze(float("nan")), ValueError)
rejects("freeze_bad_key", lambda: freeze({1: "x"}), ValueError)
cycle = []
cycle.append(cycle)
rejects("freeze_cycle", lambda: freeze(cycle), ValueError)
rejects("event_bool_version", lambda: Event("id", "send", {}, True), ValueError)
rejects("event_empty_name", lambda: Event("id", " ", {}), ValueError)
for name, scope, expected in (
    ("minimal", Scope("a"), b"MKSC\x01\x00\x01a\x00\x00"),
    (
        "full",
        Scope("app", "tenant", "owner"),
        b"MKSC\x01\x00\x03app\x01\x00\x06tenant\x01\x00\x05owner",
    ),
):
    assert canonical_scope(scope) == expected
    assert decode_canonical_scope(expected) == scope
    record("scope_" + name, (scope, expected))
for name, value in [
    ("empty", ""),
    ("space", "\u2003"),
    ("wide", "x" * 257),
    ("surrogate", "\ud800"),
    ("type", 1),
]:
    rejects("scope_reject_" + name, lambda value=value: Scope(value), ValueError)
rejects("scope_trailing", lambda: decode_canonical_scope(b"MKSC\x01\x00\x01a\x00\x00x"), ValueError)

NAMES = (
    "work_id kind subscription_id namespace command_type scope_evidence idempotency_key canonical_version schema_version_decimal scope_application scope_tenant scope_owner intent_evidence semantic_input replay_input protected_binding replay_policy max_attempts deadline original_available_at material_state protected_sidecar protected_reference protected_codec protected_key_version protected_expires_at protected_recovery_metadata protected_cleanup_policy projection_metadata"
).split()
for kind in ("absent", "sidecar", "reference"):
    req = prepared(protected=material(kind))
    assert [p.name for p in req.statement.parameters] == NAMES
    assert len(req.parameters) == 29
    p = req.parameters
    assert p[:5] == (U, "job", None, b"jobs", b"send")
    assert p[5] == b"MKSC\x01\x00\x03app\x00\x01\x00\x05owner"
    assert p[6:12] == (None, 1, b"1", b"app", None, b"owner")
    assert p[14] == b'{"value":1}'
    assert p[16:20] == ("disabled", 1, None, NOW)
    assert p[20] == ("absent" if kind == "absent" else "present")
    assert p[21:25] == (
        b"sealed" if kind == "sidecar" else None,
        b"reference" if kind == "reference" else None,
        None if kind == "absent" else b"codec",
        None if kind == "absent" else b"v1",
    )
    assert len(req.context.expected) == 1 and type(req.context.expected[0]) is AdmissionInput
    assert req.context.readiness is None
    assert (
        req.statement.key == "W01"
        and req.statement.contract_id == "modkit-pg-ab-2"
        and req.statement.mutation is True
    )
    assert [(c.name, c.wire_type.value, c.nullable) for c in req.statement.result.columns] == [
        ("work_id", "uuid", False),
        ("inserted", "bool", False),
    ]
    assert req.statement.result.cardinality.value == "exact_one"
    admission = req.context.expected[0]
    assert (
        admission.semantic_input == p[13]
        and admission.replay_input == p[14]
        and admission.protected_binding == p[15]
    )
    assert common.canonical_intent(admission).content == p[12]
    assert hashlib.sha256(p[12]).digest() == common.canonical_intent(admission).digest
    ctx = common.ReturnContext(expected=(admission,), readiness=None)
    again = common.freeze_request(req.statement, list(p), context=ctx)
    assert again == req
    record(
        "submit_" + kind,
        (req, common.canonical_intent(admission), common.decode_protected_binding(p[15])),
    )
    parameters = list(p)
    snap = common.freeze_request(req.statement, parameters, context=ctx)
    parameters[0] = V
    assert snap.parameters[0] == U
    record("parameter_snapshot_" + kind, snap)
    for field, wrong in [
        ("work_id", V),
        ("namespace", b"other"),
        ("semantic_input", b"bad"),
        ("protected_sidecar", b"wrong"),
        ("max_attempts", 2),
        ("replay_input", b'{"value":2}'),
    ]:
        changed = list(p)
        changed[NAMES.index(field)] = wrong
        local(
            "coupling_" + kind + "_" + field,
            lambda changed=changed: common.freeze_request(req.statement, changed, context=ctx),
        )
req = prepared()
a = req.context.expected[0]
# Alternate valid replay spelling changes only replay bytes, not intent evidence.
alternate = dataclasses.replace(a, replay_input=b'{ "value" : 1 }')
p = list(req.parameters)
p[14] = alternate.replay_input
alternate_req = common.freeze_request(
    req.statement, p, context=common.ReturnContext(expected=(alternate,), readiness=None)
)
assert alternate_req.parameters[12:14] == req.parameters[12:14]
assert alternate_req.parameters[14] != req.parameters[14]
record("alternate_replay", alternate_req)
local(
    "empty_context",
    lambda: common.freeze_request(
        req.statement, req.parameters, context=common.ReturnContext(expected=(), readiness=None)
    ),
)
local("duplicate_context", lambda: common.ReturnContext(expected=(a, a), readiness=None))
local("bad_context_type", lambda: common.ReturnContext(expected=[a], readiness=None))
for name, changes in [
    ("bool_version", {"schema_version": True}),
    ("zero_version", {"schema_version": 0}),
    ("uuid_object", {"work_id": U}),
    ("bool_attempts", {"max_attempts": True}),
    ("nonfinite", {"payload": {"v": float("inf")}}),
    ("cycle", {"payload": {"v": cycle}}),
    ("bad_key", {"payload": {1: "x"}}),
]:
    local("job_reject_" + name, lambda changes=changes: job(**changes))
wide = prepared(
    schema_version=2147483648,
    replay_policy=ReplayPolicy.APPLICATION_SAFE,
    deadline=NOW + datetime.timedelta(hours=1),
    max_attempts=3,
    idempotency_key="key",
)
assert wide.parameters[8] == b"2147483648" and wide.parameters[16:19] == (
    "application_safe",
    3,
    NOW + datetime.timedelta(hours=1),
)
record("wide_version", wide)
huge = job(schema_version=10**4096)
local("managed_version_limit", lambda: submit(JobSubmitRequest(job=huge)))
local("material_both", lambda: dataclasses.replace(material("sidecar"), reference=b"ref"))
local(
    "material_erased", lambda: dataclasses.replace(material(), material_state=MaterialState.ERASED)
)
for name, row, expected_id, inserted in [
    ("inserted", (U, True), ID, True),
    ("duplicate_same", (U, False), ID, False),
    ("duplicate_other", (V, False), OTHER, False),
    ("canonical_string_uuid", (ID, True), ID, True),
]:
    result = decode_submit(req, [row])
    assert result.work_id == expected_id and result.inserted is inserted
    assert type(result.work_id) is str
    assert not hasattr(result, "committed")
    record("row_" + name, result)
for name, rows in [
    ("zero", []),
    ("two", [(U, True), (U, True)]),
    ("short", [(U,)]),
    ("long", [(U, True, "extra")]),
    ("malformed_uuid", [("not-uuid", True)]),
    ("noncanonical_uuid", [("{" + ID + "}", True)]),
    ("null_uuid", [(None, True)]),
    ("int_bool", [(U, 1)]),
    ("null_bool", [(U, None)]),
    ("wrong_inserted_id", [(V, True)]),
    ("text_row", ["xx"]),
    ("mapping_row", [{"work_id": U, "inserted": True}]),
]:
    badrow("row_reject_" + name, lambda rows=rows: decode_submit(req, rows))
badrow("wrong_statement", lambda: decode_submit(read_job(JobReadRequest(work_id=ID)), [(U, True)]))
# Structurally equal metadata is not canonical worker descriptor identity.
clone = common.freeze_request(
    dataclasses.replace(req.statement), req.parameters, context=req.context
)
badrow("cloned_statement", lambda: decode_submit(clone, [(U, True)]))
tampered = prepared()
object.__setattr__(tampered, "parameters", (V,) + tampered.parameters[1:])
badrow("request_revalidation", lambda: decode_submit(tampered, [(V, True)]))
count = [0]


def overflow():
    for _ in range(100):
        count[0] += 1
        yield (U, True)


badrow("bounded_row_consumption", lambda: decode_submit(req, overflow()))
assert count == [2]
record("bounded_count", count[0])


def broken_rows():
    yield (U, True)
    raise RuntimeError("opaque-iterator-failure")


badrow("iterator_failure", lambda: decode_submit(req, broken_rows()))
try:
    raise RuntimeError("ambient-private-marker")
except RuntimeError:
    local("ambient_error", lambda: job(schema_version=False))
marker = BaseException("sentinel")


def base_failure():
    raise marker
    yield


try:
    decode_submit(req, base_failure())
except BaseException as exc:
    assert exc is marker
    record("base_exception_identity", True)
else:
    raise AssertionError("BaseException was swallowed")
# The product closure must be exactly the prepared allowlist, not a substitute package.
loaded = sorted(n for n in sys.modules if n.startswith(("modkit_events", "modkit_workers")))
assert set(loaded) <= ALLOW
record("loaded_modules", loaded)
print(json.dumps(out, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
