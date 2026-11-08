"""Caller-owned native W01 fixture used for lawful reader setup.

A separately scoped disposable fixture caller supplies fresh native psycopg3
connections (autocommit=True, tuple rows) and explicit ownership evidence.
This module does not select a DSN, create roles/schema, install SQL, or qualify
production readiness. Importing does not open connections or import product code.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event, Thread
from time import monotonic
from uuid import uuid4

TABLES = (
    "attempts",
    "delivery_history",
    "finalization_guards",
    "inbox",
    "job_payloads",
    "mutation_operations",
    "outbox",
    "publication_history",
    "schema_versions",
    "subscriptions",
    "work",
    "work_history",
)
SEQUENCES = (
    "delivery_history_history_id_seq",
    "publication_history_history_id_seq",
    "work_history_history_id_seq",
)
NOW = datetime(2030, 1, 1, tzinfo=UTC)
HELD = {
    "absent_direct_orphan": "Immediate FK and intact triggers prohibit lawful orphan creation; source invariant only.",
    "foreign_inbox": "Requires separately approved genuine E03 parent/envelope producer fixture.",
    "lifecycle_overlap": "Requires separately approved cooperating lifecycle writer.",
    "terminal_duplicate": "Requires real transition producer; no hand-built committed terminal job.",
    "sha256_collision": "No genuine lawful collision bytes; supplementary NOT_RUN.",
    "commit_uncertainty": "Requires qualified fault injection/controller reconciliation; no autoreplay.",
    "postallocation_fault": "Requires approved native fault source; no product hooks/trigger changes.",
}


def statements():
    source = Path(__file__).with_name("sql_specs").joinpath("w01_admission.sql").read_text()
    parts = re.split(r"^-- name: ([a-z_]+)\n", source, flags=re.M)
    return dict(zip(parts[1::2], parts[2::2]))


def material(present=False):
    from modkit_events.persistence.models import CleanupPolicy, MaterialState, ProtectedBindingInput

    return ProtectedBindingInput(
        material_state=MaterialState.PRESENT if present else MaterialState.ABSENT,
        codec="fixture" if present else None,
        key_version="v1" if present else None,
        expires_at=None,
        cleanup_policy=CleanupPolicy.RETAIN,
        sidecar=b"fixture-material" if present else None,
        reference=None,
        content_binding=b"fixture-binding" if present else b"",
        recovery_metadata={} if present else b"",
        projection_metadata={},
    )


def job(**changes):
    from modkit_events.persistence.scope import Scope

    from modkit_workers.persistence.models import JobInput

    values = dict(
        work_id=str(uuid4()),
        command_type="fixture-w01",
        schema_version=1,
        scope=Scope("fixture-w01", None, "owner"),
        payload={"value": 1},
        idempotency_key="k-" + uuid4().hex,
        original_available_at=NOW,
        protected=material(),
    )
    values.update(changes)
    return JobInput(**values)


def prepared(value):
    from modkit_workers.persistence.bindings import submit
    from modkit_workers.persistence.models import JobSubmitRequest

    return submit(JobSubmitRequest(job=value))


def replay_variant(value):
    """Production AdmissionInput + freezer validate changed raw JSON spelling."""
    from modkit_events.persistence import bindings as common

    from modkit_workers.persistence.models import _admission

    original = prepared(value)
    admission = replace(_admission(value), replay_input=b' { "value" : 1 } \n')
    # Canonical intent excludes replay spelling; semantic equivalence still checked.
    assert common.canonical_intent(admission).content == original.parameters[12]
    p = list(original.parameters)
    p[14] = admission.replay_input
    return common.freeze_request(
        original.statement,
        tuple(p),
        context=common.ReturnContext(expected=(admission,), readiness=None),
    )


def parameters(request):
    assert request.statement.key == "W01" and len(request.parameters) == 29
    return dict(zip((p.name for p in request.statement.parameters), request.parameters))


def execute(conn, sql, params=None):
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall() if cursor.description else []


def records(conn, sql, params=None):
    with conn.cursor() as cursor:
        cursor.execute(sql, params)
        names = [c.name for c in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]


def normalized(value):
    # psycopg3 normally returns bytes; support memoryview without dropping bytes.
    if isinstance(value, memoryview):
        return bytes(value)
    if isinstance(value, (list, tuple)):
        return tuple(normalized(v) for v in value)
    return value


@dataclass(frozen=True)
class Footprint:
    rows: dict
    sequences: dict


def footprint(conn, sql):
    inventory = execute(conn, sql["inventory"])
    expected = sorted([(n, "r") for n in TABLES] + [(n, "S") for n in SEQUENCES])
    if inventory != expected:
        raise AssertionError("Shared relation inventory drift: re-review before fixture use")
    # Enumerated identifiers only. Preserve complete rows, duplicates and bytes.
    rows = {
        name: Counter(normalized(r) for r in execute(conn, f'SELECT * FROM modkit_events."{name}"'))
        for name in TABLES
    }
    # A sequence is not a composite ordinary table; select its scalar fields.
    sequences = {
        name: execute(conn, f'SELECT last_value, log_cnt, is_called FROM modkit_events."{name}"')[0]
        for name in SEQUENCES
    }
    return Footprint(rows, sequences)


def no_write(before, after):
    assert before == after, "Expected complete unchanged rows AND sequence scalars"


def no_allocation(before, after):
    """Compare all sequence scalars retained before any loser call started."""
    assert before.sequences == after.sequences, "Loser allocated or changed sequence state"


def rollback_rows(before, after):
    assert before.rows == after.rows, "Root rollback leaked transactional rows"
    for name in SEQUENCES:
        if name != "work_history_history_id_seq":
            assert before.sequences[name] == after.sequences[name]
    # History sequence can advance/cache; no setval, gapless or log_cnt delta rule.


class Pool:
    """Caller-owned fresh connections; bounded fixture transactions, no DSN."""

    def __init__(self, connect, lease_reference):
        if not lease_reference:
            raise ValueError("Separate exact disposable fixture release required")
        self.connect, self.connections, self.jobs = connect, [], []
        self.uncertain, self.cleanup_errors = [], []

    def open(self, isolation="READ COMMITTED", *, observer=False):
        c = self.connect()
        self.connections.append(c)
        assert c.autocommit is True, "Fresh autocommit native connection required"
        execute(c, "BEGIN ISOLATION LEVEL " + isolation)
        execute(c, "SET LOCAL statement_timeout = '8000ms'")
        execute(c, "SET LOCAL lock_timeout = '6000ms'")
        execute(c, "SET LOCAL idle_in_transaction_session_timeout = '12000ms'")
        if observer:
            # Each observer statement needs a fresh snapshot; read committed root.
            execute(c, "SET TRANSACTION READ ONLY")
        return c

    def commit(self, conn):
        try:
            conn.commit()
        except BaseException as error:
            self.uncertain.append((conn, error))
            # A lost acknowledgement is held. NEVER replay a request here.
            raise

    def start(self, conn, callback):
        task = Pending(conn, callback)
        self.jobs.append(task)  # Ownership precedes any callback launch.
        task.launch()
        return task

    def close(self):
        # Cancel before rollback, so no thread and main thread concurrently use a
        # live connection. cancel_safe is the actual psycopg3 bounded API.
        for task in self.jobs:
            if task.may_be_active():
                try:
                    task.conn.cancel_safe(timeout=2.0)
                except BaseException as error:
                    self.cleanup_errors.append(error)
                task.done.wait(10)
        for conn in reversed(self.connections):
            if any(task.conn is conn and task.may_be_active() for task in self.jobs):
                # Never issue rollback concurrently with an unconfirmed call.
                # Close is cancellation/disconnection, not proof of server cleanup.
                try:
                    conn.close()
                except BaseException as error:
                    self.cleanup_errors.append(error)
                self.cleanup_errors.append(
                    RuntimeError("Close forced with call termination unconfirmed")
                )
                continue
            try:
                conn.rollback()
            except BaseException as error:
                self.cleanup_errors.append(error)
            try:
                conn.close()
            except BaseException as error:
                self.cleanup_errors.append(error)
        for task in self.jobs:
            if task.may_be_active():
                task.done.wait(2)
                if task.may_be_active():
                    self.cleanup_errors.append(
                        RuntimeError("Native worker termination unconfirmed")
                    )
        if self.cleanup_errors:
            raise BaseExceptionGroup(
                "Fixture cleanup failures; preserve original diagnostics", self.cleanup_errors
            )


class Pending:
    def __init__(self, conn, callback):
        # Inert: pool registration must happen before even attempting launch.
        self.conn, self.value, self.error, self.done = conn, None, None, Event()
        self.callback, self.thread = callback, None
        self.launch_requested = False
        self.launch_state = "never_attempted"

    def _run(self):
        try:
            self.value = self.callback()
        except BaseException as error:
            self.error = error  # Exact original error, never reclassified.
        finally:
            self.done.set()  # Completion is independent of start() returning.

    def launch(self):
        if self.launch_requested:
            raise RuntimeError("Pending launch retry forbidden")
        self.launch_requested = True
        try:
            self.thread = Thread(target=self._run, daemon=True)
        except BaseException:
            # Standard Thread construction is inert; start was never attempted.
            self.launch_state = "known_prelaunch_failure"
            raise
        # A start exception, even before scheduling, cannot prove no callback.
        # Mark conservative ownership BEFORE calling start. No automatic retry.
        self.launch_state = "possibly_started"
        self.thread.start()
        self.launch_state = "start_returned"

    def may_be_active(self):
        return (
            self.launch_state not in ("never_attempted", "known_prelaunch_failure")
            and not self.done.is_set()
        )

    def finish(self, seconds=10):
        if not self.done.wait(seconds):
            raise TimeoutError("Bounded native call did not finish; cleanup required")
        if self.error is not None:
            raise self.error
        return self.value


def pid(conn):
    return execute(conn, "SELECT pg_catalog.pg_backend_pid()")[0][0]


def barrier(observer, sql, waiting_pid, allowed_blockers, task, seconds=4):
    """Observe the real uniqueness/transaction wait, never sleep to order a race."""
    deadline = monotonic() + seconds
    while monotonic() < deadline:
        blockers = set(execute(observer, sql["blockers"], {"pid": waiting_pid})[0][0])
        if blockers & set(allowed_blockers):
            return blockers
        if task.done.is_set():
            task.finish()
            raise AssertionError("Contender completed without observed uniqueness wait")
    raise TimeoutError("No coordinator-observed blocker before deadline")


def submit(conn, sql, request):
    from modkit_workers.persistence.rows import decode_submit

    raw = execute(conn, sql["submit"], parameters(request))
    result = decode_submit(request, raw)
    return result.work_id, result.inserted


def expected_error(conn, sql, request, state, *, raw=None, unchanged=True):
    before = footprint(conn, sql)
    execute(conn, "SAVEPOINT fixture_expected")
    primary = None
    try:
        execute(conn, sql["submit"], parameters(request) if raw is None else raw)
    except BaseException as error:
        primary = error
    cleanup_errors = []
    try:
        execute(conn, "ROLLBACK TO SAVEPOINT fixture_expected")
    except BaseException as error:
        cleanup_errors.append(error)
        # Failed rollback-to leaves root recovery unconfirmed. Do not RELEASE;
        # outer scenario cleanup owns full-root rollback/close.
    else:
        try:
            execute(conn, "RELEASE SAVEPOINT fixture_expected")
        except BaseException as error:
            cleanup_errors.append(error)
    if cleanup_errors:
        errors = ([primary] if primary is not None else []) + cleanup_errors
        raise BaseExceptionGroup("Expected-error primary and failed savepoint cleanup", errors)
    assert primary is not None, "Error path returned a receipt"
    if not isinstance(primary, Exception) or getattr(primary, "sqlstate", None) != state:
        raise primary  # Preserve cancellation/system-exit and unexpected native identity.
    if unchanged:
        no_write(before, footprint(conn, sql))
    return primary  # Savepoint recovery is NOT evidence of full business-root rollback.


def pair(conn, sql, request):
    """Following-command actual E15 plus complete raw pair/intake oracle."""
    p = parameters(request)
    key = {"work_id": p["work_id"]}
    assert len(execute(conn, sql["checked"], key)) == 1
    (w,) = records(conn, sql["work"], key)
    (j,) = records(conn, sql["half"], key)
    (h,) = records(conn, sql["history"], key)
    wide = int(p["schema_version_decimal"]) > 2147483647
    assert w["state"] == ("blocked_schema" if wide else "queued")
    assert w["runnable_version"] == (None if wide else int(p["schema_version_decimal"]))
    for name in (
        "kind",
        "subscription_id",
        "namespace",
        "command_type",
        "schema_version_decimal",
        "canonical_version",
        "scope_evidence",
        "scope_application",
        "scope_tenant",
        "scope_owner",
        "idempotency_key",
        "intent_evidence",
        "semantic_input",
        "replay_input",
        "protected_binding",
        "replay_policy",
        "max_attempts",
        "deadline",
        "original_available_at",
    ):
        assert normalized(w[name]) == p[name], name
    for name, source in (
        ("job_application", "scope_application"),
        ("job_tenant", "scope_tenant"),
        ("job_owner", "scope_owner"),
        ("job_protected_binding", "protected_binding"),
        ("job_semantic_input", "semantic_input"),
    ):
        assert normalized(j[name]) == p[source]
    for name in tuple(p)[20:]:
        assert normalized(j[name]) == p[name]
    assert w["created_at"] is not None  # T0; no wall-clock monotonic assumption.
    assert w["updated_at"] == h["recorded_at"]  # Same post-reservation T1.
    assert w["available_at"] == p["original_available_at"]
    assert (w["cycle"], w["attempt_count"], w["ownership_revision"]) == (1, 0, 0)
    assert w["token"] is None and w["dispatch_id"] is None and w["result"] is None
    assert not w["cancellation_requested"] and w["lease_until"] is None
    code = "intake_blocked" if wide else "intake_runnable"
    assert h["history_id"] > 0
    assert (
        h["cycle"],
        h["attempt"],
        h["transition"],
        h["reason"],
        h["token"],
        h["ownership_revision"],
        normalized(h["evidence"]),
    ) == (1, 0, code, code, None, 0, b"")
    return w, j, h


def inserted_delta(before, after, triples):
    """Exact added full rows and unchanged unrelated rows for successful roots."""
    expected = {name: values.copy() for name, values in before.rows.items()}
    ids = []
    for w, j, h in triples:
        # records preserve database column order from SELECT *, same as footprint.
        expected["work"][normalized(tuple(w.values()))] += 1
        expected["job_payloads"][normalized(tuple(j.values()))] += 1
        expected["work_history"][normalized(tuple(h.values()))] += 1
        ids.append(h["history_id"])
    assert len(ids) == len(set(ids))
    assert expected == after.rows
    for name in SEQUENCES:
        if name != "work_history_history_id_seq":
            assert before.sequences[name] == after.sequences[name]


def serial(pool, sql):
    from modkit_events.persistence.models import ReplayPolicy
    from modkit_events.persistence.scope import Scope

    c = pool.open()
    baseline = footprint(c, sql)
    triples = []
    first = job()
    r = prepared(first)
    assert submit(c, sql, r) == (first.work_id, True)
    triples.append(pair(c, sql, r))
    for duplicate in (r, prepared(replace(first, work_id=str(uuid4()))), replay_variant(first)):
        before = footprint(c, sql)
        assert submit(c, sql, duplicate) == (first.work_id, False)
        no_write(before, footprint(c, sql))
    # Every mismatch rebuilds canonical scope, intent, semantic and material using
    # actual production constructors. No arbitrary mutation of valid evidence.
    changes = (
        {"scope": Scope("fixture-w01-other", None, "owner")},
        {"scope": Scope("fixture-w01", "tenant", "owner")},
        {"scope": Scope("fixture-w01", None, None)},
        {"idempotency_key": "different"},
        {"idempotency_key": None},
        {"command_type": "other-command"},
        {"payload": {"value": 2}},
        {"protected": material(True)},
        {"schema_version": 2},
        {"replay_policy": ReplayPolicy.APPLICATION_SAFE},
        {"max_attempts": 2},
        {"deadline": NOW + timedelta(days=1)},
        {"original_available_at": NOW + timedelta(seconds=1)},
    )
    for change in changes:
        expected_error(c, sql, prepared(replace(first, **change)), "PZ002")
    # Indexed key contender also reaches the same full immutable comparator.
    for change in ({"payload": {"value": 2}}, {"schema_version": 2}, {"protected": material(True)}):
        expected_error(c, sql, prepared(replace(first, work_id=str(uuid4()), **change)), "PZ002")
    for options in (
        {"idempotency_key": None},
        {"schema_version": 2147483647},
        {"schema_version": 2147483648},
        {"schema_version": 10**40},
        {"protected": material(True)},
    ):
        value = job(**options)
        request = prepared(value)
        assert submit(c, sql, request) == (value.work_id, True)
        triples.append(pair(c, sql, request))
        before = footprint(c, sql)
        assert submit(c, sql, request) == (value.work_id, False)
        no_write(before, footprint(c, sql))
        if value.idempotency_key is None:
            distinct = replace(value, work_id=str(uuid4()))
            dr = prepared(distinct)
            assert submit(c, sql, dr) == (distinct.work_id, True)
            triples.append(pair(c, sql, dr))
    for name, value in (
        ("work_id", None),
        ("kind", "inbox"),
        ("namespace", b"wrong"),
        ("canonical_version", 2),
        ("schema_version_decimal", b"01"),
        ("replay_input", b"{broken"),
        ("material_state", "erased"),
        ("max_attempts", 0),
        ("intent_evidence", b"broken"),
    ):
        raw = parameters(r)
        raw[name] = value
        expected_error(c, sql, r, "PZ006", raw=raw)
    inserted_delta(baseline, footprint(c, sql), triples)
    c.rollback()  # Actual root rollback, independently audit all transactional rows.
    rollback_rows(baseline, footprint(c, sql))
    c.rollback()
    for level in ("REPEATABLE READ", "SERIALIZABLE"):
        isolation = pool.open(level)
        expected_error(isolation, sql, prepared(job()), "PZ005")
        isolation.rollback()


def corruption(pool, sql):
    c = pool.open()
    baseline = footprint(c, sql)
    low, high = sorted((str(uuid4()), str(uuid4())))
    winner = job(work_id=low)
    r = prepared(winner)
    assert submit(c, sql, r) == (winner.work_id, True)
    # Direct candidate's raw scope/key is an obvious conflict. Its missing half
    # must still win PZ012 over the valid keyed job's split/full PZ002.
    naked = job(work_id=high)
    execute(c, sql["naked_work_negative_only"], parameters(prepared(naked)))
    split = prepared(replace(winner, work_id=naked.work_id))
    expected_error(c, sql, split, "PZ012")
    expected_error(c, sql, prepared(replace(naked, payload={"value": 99})), "PZ012")
    # Absent direct plus corrupt keyed family also checks every candidate.
    expected_error(c, sql, prepared(replace(naked, work_id=str(uuid4()))), "PZ012")
    c.rollback()  # Deliberate incomplete Work MUST NEVER be committed.
    rollback_rows(baseline, footprint(c, sql))
    c.rollback()


def race(pool, sql, mode, *, same_id=False, conflict=False):
    a, b, observer = pool.open(), pool.open(), pool.open(observer=True)
    baseline = footprint(observer, sql)
    first = job()
    second = replace(
        first,
        work_id=first.work_id if same_id else str(uuid4()),
        payload={"value": 2} if conflict else first.payload,
        idempotency_key=("different-" + uuid4().hex)
        if same_id and conflict
        else first.idempotency_key,
    )
    ar, br = prepared(first), prepared(second)
    assert submit(a, sql, ar) == (first.work_id, True)
    first_triple = pair(a, sql, ar)
    apid, bpid = pid(a), pid(b)
    before_loser = footprint(observer, sql)
    if mode == "timeout":
        execute(b, "SET LOCAL lock_timeout = '1000ms'")
    elif mode == "statement_timeout":
        execute(b, "SET LOCAL statement_timeout = '1000ms'")
    task = pool.start(b, lambda: submit(b, sql, br))
    barrier(observer, sql, bpid, {apid}, task)
    if mode in ("timeout", "statement_timeout"):
        try:
            task.finish()
        except Exception as error:
            if getattr(error, "sqlstate", None) != ("55P03" if mode == "timeout" else "57014"):
                raise
        else:
            raise AssertionError("Native timeout returned a receipt")
        b.rollback()
        no_write(before_loser, footprint(observer, sql))
        a.rollback()
        rollback_rows(baseline, footprint(observer, sql))
        return
    if mode == "abort":
        a.rollback()
        assert task.finish() == (second.work_id, True)
        triple = pair(b, sql, br)
        b.rollback()
        rollback_rows(baseline, footprint(observer, sql))
        assert triple[0]["replay_input"] == br.parameters[14]
        return
    pool.commit(a)
    if conflict:
        try:
            task.finish()
        except Exception as error:
            if getattr(error, "sqlstate", None) != "PZ002":
                raise
        else:
            raise AssertionError("Conflicting loser returned a receipt")
    else:
        assert task.finish() == (first.work_id, False)
    b.rollback()
    settled = footprint(observer, sql)
    no_allocation(before_loser, settled)
    inserted_delta(baseline, settled, [first_triple])
    # Committed real W01 rows deliberately remain in disposable DB until approved
    # database disposal; no DELETE/TRUNCATE or fake cleanup assertion.


def split_race(pool, sql):
    a, c, b, observer = pool.open(), pool.open(), pool.open(), pool.open(observer=True)
    baseline = footprint(observer, sql)
    direct, key = job(), job()
    assert submit(a, sql, prepared(direct)) == (direct.work_id, True)
    assert submit(c, sql, prepared(key)) == (key.work_id, True)
    triples = [pair(a, sql, prepared(direct)), pair(c, sql, prepared(key))]
    request = prepared(replace(key, work_id=direct.work_id))
    apid, cpid, bpid = pid(a), pid(c), pid(b)
    # Both lawful contender histories are allocated, loser has not started.
    before_loser = footprint(observer, sql)
    task = pool.start(b, lambda: submit(b, sql, request))
    blockers = barrier(observer, sql, bpid, {apid, cpid}, task)
    # Both valid contenders are uncommitted during loser's empty capture.
    # Commit NONblocking member first; observed blocker last forces fresh
    # capture to include both. No pause hook/trigger bypass/index-order guess.
    if apid in blockers and cpid not in blockers:
        pool.commit(c)
        pool.commit(a)
    elif cpid in blockers and apid not in blockers:
        pool.commit(a)
        pool.commit(c)
    else:
        raise AssertionError("Unexpected split blocking graph; rollback, re-review")
    try:
        task.finish()
    except Exception as error:
        if getattr(error, "sqlstate", None) != "PZ002":
            raise
    else:
        raise AssertionError("Split identity returned a receipt")
    b.rollback()
    settled = footprint(observer, sql)
    no_allocation(before_loser, settled)
    inserted_delta(baseline, settled, triples)


def deadlock(pool, sql):
    a, b, observer = pool.open(), pool.open(), pool.open(observer=True)
    baseline = footprint(observer, sql)
    aj, bj = job(), job()
    assert submit(a, sql, prepared(aj)) == (aj.work_id, True)
    assert submit(b, sql, prepared(bj)) == (bj.work_id, True)
    apid, bpid = pid(a), pid(b)
    # Actual caller-prior uncommitted W01 reservations form the cycle.
    left = pool.start(a, lambda: submit(a, sql, prepared(replace(bj, work_id=str(uuid4())))))
    barrier(observer, sql, apid, {bpid}, left)
    right = pool.start(b, lambda: submit(b, sql, prepared(replace(aj, work_id=str(uuid4())))))
    deadline = monotonic() + 8
    victim = None
    while monotonic() < deadline:
        for task in (left, right):
            if task.done.is_set() and task.error is not None:
                if getattr(task.error, "sqlstate", None) != "40P01":
                    raise task.error
                victim = task
                break
        if victim is not None:
            break
    assert victim is not None, "Actual native deadlock detection not observed"
    assert victim.value is None
    victim.conn.rollback()  # Release victim prior W01 so survivor original insert proceeds.
    survivor = right if victim is left else left
    result = survivor.finish()
    assert result[1] is True
    survivor.conn.rollback()
    rollback_rows(baseline, footprint(observer, sql))


def scenario(connect, lease_reference, callback):
    """At most four native connections per bounded scenario, then release all."""
    pool = Pool(connect, lease_reference)
    primary = None
    try:
        callback(pool)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            pool.close()
        except BaseException as cleanup:
            if primary is not None:
                raise BaseExceptionGroup(
                    "Native fixture and cleanup both failed", [primary, cleanup]
                )
            raise


def run_source_fixture(connect, *, lease_reference):
    """Explicit future entry; never invoked by author or automatic discovery.

    Caller must approve exact schema/preflight/owner/native-driver pins,
    connection limits, lease/deadlines and disposable DB disposal first. The
    reference records external authority; it does not create/validate authority.
    Assertions are not an execution/readiness receipt. Committed winners stay in
    the disposable database until separately approved database disposal.
    """
    sql = statements()
    scenario(connect, lease_reference, lambda pool: serial(pool, sql))
    scenario(connect, lease_reference, lambda pool: corruption(pool, sql))
    for same_id in (False, True):
        for conflict in (False, True):
            scenario(
                connect,
                lease_reference,
                lambda pool: race(pool, sql, "commit", same_id=same_id, conflict=conflict),
            )
        scenario(connect, lease_reference, lambda pool: race(pool, sql, "abort", same_id=same_id))
    for mode in ("timeout", "statement_timeout"):
        scenario(connect, lease_reference, lambda pool: race(pool, sql, mode))
    scenario(connect, lease_reference, lambda pool: split_race(pool, sql))
    scenario(connect, lease_reference, lambda pool: deadlock(pool, sql))
