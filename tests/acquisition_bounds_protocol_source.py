"""Exact W05 upper limits in an already-active caller-owned native transaction.

Only lawful W01 producers; no connection, root transaction, setup or disposal
ownership. The caller must provide a fresh disposable database and roll back.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID

PAGE_LIMIT = 256
DISCOVERY_BUDGET = 4096
TOTAL_JOBS = DISCOVERY_BUDGET + PAGE_LIMIT + 1
ACQUIRE = """SELECT * FROM modkit_workers.w05(
 %s::bytea,%s::bytea[],%s::int4[],%s::int4,%s::float8,%s::uuid,%s::int4)"""


def _read_request(work_id):
    from modkit_workers.persistence import bindings, models

    return bindings.read_job(models.JobReadRequest(work_id=str(work_id)))


def run_acquisition_bounds(conn, *, protocol):
    """Caller supplies an active READ COMMITTED root and owns its rollback."""
    from modkit_events.persistence.models import Capability, Fence

    from modkit_workers.persistence import bindings, models, rows

    h = protocol
    sql = h.statements()
    assert conn.info.transaction_status.name == "INTRANS"
    baseline = h.footprint(conn, sql)
    assert not baseline.rows["work"], "Fresh disposable fixture required"
    triples = []
    for index in range(1, TOTAL_JOBS + 1):
        eligible = DISCOVERY_BUDGET < index < TOTAL_JOBS
        value = h.job(
            work_id=str(UUID(int=index)),
            command_type="fixture-w01" if eligible else "unsupported",
            schema_version=1 if eligible else 2,
            original_available_at=datetime(2020, 1, 1, tzinfo=UTC),
            protected=h.material(eligible),
        )
        prepared = h.prepared(value)
        assert h.submit(conn, sql, prepared) == (value.work_id, True)
        triples.append(h.pair(conn, sql, prepared))
    seeded = h.footprint(conn, sql)
    h.inserted_delta(baseline, seeded, triples)
    assert sum(seeded.rows["work"].values()) == TOTAL_JOBS
    print("W05_BOUNDS_4353_LAWFUL_PRODUCERS", flush=True)

    def acquire(after=None):
        request = bindings.acquire(
            models.JobAcquireRequest(
                capabilities=[Capability(command_type="fixture-w01", schema_version=1)],
                limit=PAGE_LIMIT,
                lease_seconds=10,
                scan_after=after,
                discovery_budget=DISCOVERY_BUDGET,
            )
        )
        params = list(request.parameters)
        params[1], params[2] = list(params[1]), list(params[2])
        raw = h.execute(conn, ACQUIRE, params)
        page = rows.decode_acquire(request, raw)
        assert len(raw) == len(page.items) + 1
        assert all(len(row) == 75 for row in raw)
        return raw, page

    raw, first = acquire()
    assert len(raw) == 1 and not first.items
    assert (first.visited, first.next_cursor, first.pass_exhausted) == (
        DISCOVERY_BUDGET,
        UUID(int=DISCOVERY_BUDGET),
        False,
    )
    h.no_write(seeded, h.footprint(conn, sql))
    print("W05_BOUNDS_4096_VISITED_NO_WRITES", flush=True)

    raw, page = acquire(first.next_cursor)
    expected_ids = tuple(UUID(int=i) for i in range(DISCOVERY_BUDGET + 1, TOTAL_JOBS))
    assert tuple(item.fence.work_id for item in page.items) == expected_ids
    assert tuple(row[4] for row in raw[1:]) == expected_ids
    assert (len(page.items), page.visited, page.next_cursor, page.pass_exhausted) == (
        PAGE_LIMIT,
        PAGE_LIMIT,
        UUID(int=TOTAL_JOBS - 1),
        False,
    )
    expected = {name: values.copy() for name, values in seeded.rows.items()}
    history_ids = []
    for returned, claim in zip(raw[1:], page.items, strict=True):
        key = {"work_id": claim.fence.work_id}
        (work,) = h.records(conn, sql["work"], key)
        (payload,) = h.records(conn, sql["half"], key)
        history = h.records(conn, sql["history"], key)
        assert len(history) == 2
        admitted, claimed = history
        original_work, original_payload, original_history = triples[key["work_id"].int - 1]
        assert admitted == original_history and payload == original_payload
        assert set(name for name in work if work[name] != original_work[name]) == {
            "state",
            "token",
            "ownership_revision",
            "lease_until",
            "updated_at",
        }
        assert work["state"] == "claimed" and work["attempt_count"] == 0
        assert work["token"] is not None and work["ownership_revision"] == 1
        assert work["lease_until"] - work["updated_at"] == timedelta(seconds=10)
        record_row = tuple(work.values()) + (False,) + (None,) * 16 + tuple(payload.values())
        assert returned[4:] == record_row
        observed = rows.decode_read(
            _read_request(key["work_id"]),
            [record_row],
        )
        assert claim.record == observed
        assert claim.record.payload.sidecar == b"fixture-material"
        assert claim.fence == Fence(
            work_id=work["work_id"],
            token=work["token"],
            ownership_revision=work["ownership_revision"],
            cycle=work["cycle"],
            expected_attempt=work["attempt_count"],
        )
        assert claimed == {
            "history_id": claimed["history_id"],
            "work_id": work["work_id"],
            "cycle": work["cycle"],
            "attempt": 0,
            "transition": "claim",
            "reason": "claim",
            "token": work["token"],
            "ownership_revision": 1,
            "evidence": b"",
            "recorded_at": work["updated_at"],
        }
        assert claimed["history_id"] > admitted["history_id"]
        history_ids.append(claimed["history_id"])
        old_row = h.normalized(tuple(original_work.values()))
        assert expected["work"][old_row] == 1
        del expected["work"][old_row]
        expected["work"][h.normalized(tuple(work.values()))] += 1
        expected["work_history"][h.normalized(tuple(claimed.values()))] += 1
    assert len(set(history_ids)) == PAGE_LIMIT
    claimed = h.footprint(conn, sql)
    assert expected == claimed.rows, "Complete claim rows differ from exact expected delta"
    for name in h.SEQUENCES:
        if name != "work_history_history_id_seq":
            assert seeded.sequences[name] == claimed.sequences[name]
    # Retain all sequence scalars; history allocation/cache is not gapless.
    assert claimed.sequences["work_history_history_id_seq"][0] >= max(history_ids)
    print("W05_BOUNDS_256_COMPLETE_RECORDS_FENCES_HISTORY", flush=True)

    raw, last = acquire(page.next_cursor)
    assert len(raw) == 1 and not last.items
    assert (last.visited, last.next_cursor, last.pass_exhausted) == (
        1,
        UUID(int=TOTAL_JOBS),
        True,
    )
    h.no_write(claimed, h.footprint(conn, sql))
    raw, end = acquire(last.next_cursor)
    assert len(raw) == 1 and not end.items
    assert (end.visited, end.next_cursor, end.pass_exhausted) == (
        0,
        UUID(int=TOTAL_JOBS),
        True,
    )
    h.no_write(claimed, h.footprint(conn, sql))
    print("W05_BOUNDS_FINAL_INELIGIBLE_AND_EMPTY_NO_WRITES", flush=True)
