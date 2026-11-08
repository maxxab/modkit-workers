"""Caller-owned W03 native checks, with no connections or execution at import."""

from pathlib import Path
from uuid import UUID

LIST = """SELECT * FROM modkit_workers.w03(%(namespace)s::bytea,
 %(after_created_at)s::timestamptz,%(after_work_id)s::uuid,%(limit)s::int4)"""
HELD = {
    "multi_row_timestamp_ties": "Native producers use immutable clock timestamps; pure tied-page controls only.",
    "concurrent_material_change": "Concurrent snapshot overlap is not exercised by this bounded fixture.",
    "physical_io_budget": "Index eligibility is checked, not worst-case physical IO or wall-clock cost.",
}


def params(request):
    return dict(zip((p.name for p in request.statement.parameters), request.parameters))


def run_listing(connect, *, lease_reference, protocol):
    """No target selection, setup DDL, commit, retry, or runtime permission change."""
    h = protocol
    sql = h.statements()

    def scenario(pool):
        from modkit_events.persistence.models import WorkCursor

        from modkit_workers.persistence import bindings, models, rows

        c = pool.open()
        baseline = h.footprint(c, sql)

        def request(after=None, limit=2):
            return bindings.list_jobs(models.JobListRequest(after=after, limit=limit))

        def listed(after=None, limit=2):
            frozen = request(after, limit)
            before = h.footprint(c, sql)
            result = rows.decode_list(frozen, h.execute(c, LIST, params(frozen)))
            h.no_write(before, h.footprint(c, sql))
            return result

        assert listed() == ()
        seed = Path(__file__).with_name("sql_specs").joinpath("w03_inbox_seed.sql").read_text()
        h.execute(c, seed)
        assert h.execute(c, "SELECT kind,namespace FROM modkit_events.work") == [("inbox", b"jobs")]
        assert listed() == ()  # Inbox-only namespace must not be emitted as jobs.
        values = [h.job(protected=h.material(index == 1)) for index in range(3)]
        for value in values:
            assert h.submit(c, sql, h.prepared(value)) == (value.work_id, True)
        page = listed()
        assert tuple(str(record.work.work_id) for record in page) == tuple(
            v.work_id for v in values[:2]
        )
        assert page[1].payload.sidecar == b"fixture-material"
        cursor = WorkCursor(created_at=page[-1].work.created_at, work_id=page[-1].work.work_id)
        final = listed(cursor, 1)
        assert tuple(str(record.work.work_id) for record in final) == (values[2].work_id,)
        end = WorkCursor(created_at=final[0].work.created_at, work_id=final[0].work.work_id)
        assert listed(end) == ()
        assert len(listed(limit=256)) == 3

        # Equal timestamp cursor boundaries without changing immutable producer data.
        first = page[0].work
        for cursor_id, wanted in (
            (UUID(int=0), values[0].work_id),
            (first.work_id, values[1].work_id),
            (UUID(int=(1 << 128) - 1), values[1].work_id),
        ):
            boundary = WorkCursor(created_at=first.created_at, work_id=cursor_id)
            assert str(listed(boundary, 1)[0].work.work_id) == wanted

        prepared = h.prepared(values[0])
        bad_inputs = [
            {"namespace": None},
            {"namespace": b"events"},
            {"namespace": b"JOBS"},
            {"limit": None},
            {"limit": 0},
            {"limit": 257},
            {"after_created_at": first.created_at},
            {"after_work_id": first.work_id},
            {"after_created_at": "infinity", "after_work_id": first.work_id},
        ]
        for change in bad_inputs:
            raw = params(request())
            raw.update(change)
            h.expected_error(c, {**sql, "submit": LIST}, prepared, "PZ006", raw=raw)

        # This incomplete Work sorts after the valid prefix. It stays uncommitted.
        missing = h.job()
        h.execute(c, sql["naked_work_negative_only"], h.parameters(h.prepared(missing)))
        h.expected_error(
            c, {**sql, "submit": LIST}, prepared, "PZ012", raw=params(request(limit=4))
        )
        c.rollback()
        assert h.footprint(c, sql).rows == baseline.rows, "Listing fixture leaked transaction rows"
        c.rollback()
        for isolation in ("REPEATABLE READ", "SERIALIZABLE"):
            other = pool.open(isolation)
            h.expected_error(
                other, {**sql, "submit": LIST}, prepared, "PZ005", raw=params(request())
            )
            other.rollback()

    h.scenario(connect, lease_reference, scenario)
