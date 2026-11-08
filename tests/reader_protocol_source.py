"""Caller-owned W02/W04 native fixture; no CLI or import side effects.

The caller owns isolated installation, connection limits and disposal. The
fixture covers read/find behavior; it does not confer production readiness.
"""

from dataclasses import replace
from uuid import uuid4

READ = "SELECT * FROM modkit_workers.w02(%(work_id)s::uuid)"
FIND = """SELECT * FROM modkit_workers.w04(%(work_id)s::uuid,%(kind)s::text,
 %(subscription_id)s::bytea,%(namespace)s::bytea,%(command_type)s::bytea,
 %(scope_evidence)s::bytea,%(idempotency_key)s::bytea)"""
HELD = {
    "foreign_inbox": "Requires genuine separately approved E03 producer; no handbuilt committed inbox."
}


def params(request):
    return dict(zip((p.name for p in request.statement.parameters), request.parameters))


def corrupt_last_family(protocol):
    """Build lawful inputs selecting a valid first row and incomplete final row."""
    from modkit_workers.persistence import bindings
    from modkit_workers.persistence.models import JobFindRequest

    good = protocol.job(
        work_id="00000000-0000-4000-8000-000000000101",
        idempotency_key="reader-corrupt-last-good",
        payload={"value": 1},
    )
    missing_half = protocol.job(
        work_id="00000000-0000-4000-8000-000000000102",
        idempotency_key="reader-corrupt-last-bad",
        payload={"value": 99},
    )
    lookup = bindings.find_jobs(JobFindRequest(job=replace(good, work_id=missing_half.work_id)))
    return good, missing_half, lookup


def run_readers(connect, *, lease_reference, protocol):
    """Caller owns approved install/disposal; reused Pool owns returned resources."""
    h = protocol
    sql = h.statements()

    def scenario(pool):
        from modkit_workers.persistence import bindings, rows
        from modkit_workers.persistence.models import JobFindRequest, JobReadRequest
        from modkit_workers.persistence.observations import JobIdentityDecision

        c = pool.open()
        baseline = h.footprint(c, sql)

        def read(value):
            request = bindings.read_job(JobReadRequest(work_id=value.work_id))
            before = h.footprint(c, sql)
            result = rows.decode_read(request, h.execute(c, READ, params(request)))
            h.no_write(before, h.footprint(c, sql))
            return result

        def find(value):
            request = bindings.find_jobs(JobFindRequest(job=value))
            before = h.footprint(c, sql)
            # expected_submission is comparison-only, NEVER executed by find.
            result = rows.decode_find(request, h.execute(c, FIND, params(request.lookup)))
            h.no_write(before, h.footprint(c, sql))
            return result

        first = h.job(protected=h.material(True))
        assert read(first) is None
        assert find(first).decision is JobIdentityDecision.NEW
        request = h.prepared(first)
        assert h.submit(c, sql, request) == (first.work_id, True)
        record = read(first)
        assert str(record.work.work_id) == first.work_id
        assert record.work.semantic_input == request.parameters[13]
        assert record.work.protected_binding == request.parameters[15]
        assert record.payload.sidecar == b"fixture-material"
        for candidate in (first, replace(first, work_id=str(uuid4()))):
            result = find(candidate)
            assert result.decision is JobIdentityDecision.MATCH
            assert result.original_work_id == first.work_id and len(result.candidates) == 1
        assert find(replace(first, payload={"value": 2})).decision is JobIdentityDecision.CONFLICT
        second = h.job()
        assert h.submit(c, sql, h.prepared(second)) == (second.work_id, True)
        split = find(replace(second, work_id=first.work_id))
        assert split.decision is JobIdentityDecision.CONFLICT and len(split.candidates) == 2
        assert [str(x.work.work_id) for x in split.candidates] == sorted(
            [first.work_id, second.work_id]
        )
        # Existing expected_error preserves primary plus savepoint cleanup failures.
        h.expected_error(c, {**sql, "submit": READ}, request, "PZ006", raw={"work_id": None})
        find_request = bindings.find_jobs(JobFindRequest(job=first))
        for key, value in [
            ("kind", "inbox"),
            ("namespace", b"wrong"),
            ("scope_evidence", b"broken"),
        ]:
            raw = params(find_request.lookup)
            raw[key] = value
            h.expected_error(c, {**sql, "submit": FIND}, request, "PZ006", raw=raw)
        naked = h.job()
        naked_request = h.prepared(naked)
        h.execute(c, sql["naked_work_negative_only"], h.parameters(naked_request))
        h.expected_error(
            c, {**sql, "submit": READ}, naked_request, "PZ012", raw={"work_id": naked.work_id}
        )
        nf = bindings.find_jobs(JobFindRequest(job=naked))
        h.expected_error(c, {**sql, "submit": FIND}, naked_request, "PZ012", raw=params(nf.lookup))
        # The valid keyed row sorts first. Its corrupt direct-ID partner sorts
        # last, so complete-family validation must win before any usable result.
        good, last, family_lookup = corrupt_last_family(h)
        good_request = h.prepared(good)
        assert h.submit(c, sql, good_request) == (good.work_id, True)
        h.execute(c, sql["naked_work_negative_only"], h.parameters(h.prepared(last)))
        h.expected_error(
            c, {**sql, "submit": FIND}, good_request, "PZ012", raw=params(family_lookup.lookup)
        )
        assert str(read(good).work.work_id) == good.work_id
        c.rollback()  # Never commit deliberately incomplete Work.
        h.rollback_rows(baseline, h.footprint(c, sql))
        c.rollback()
        for isolation in ("REPEATABLE READ", "SERIALIZABLE"):
            other = pool.open(isolation)
            h.expected_error(
                other, {**sql, "submit": READ}, request, "PZ005", raw={"work_id": first.work_id}
            )
            h.expected_error(
                other, {**sql, "submit": FIND}, request, "PZ005", raw=params(find_request.lookup)
            )
            other.rollback()

    h.scenario(connect, lease_reference, scenario)
