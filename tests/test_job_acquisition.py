"""Complete-page W05 decoder controls; native SQL evidence is separate."""

from uuid import UUID

import pytest
from modkit_events.persistence.errors import ErrorCode, PersistenceError
from modkit_events.persistence.models import Capability
from test_job_persistence_contracts import ID, OTHER_ID, full_job_row, job

from modkit_workers.persistence import bindings, models, rows


def request(*, limit=2, budget=16, after=None, pairs=None):
    return bindings.acquire(
        models.JobAcquireRequest(
            capabilities=pairs or [Capability(command_type="send", schema_version=1)],
            limit=limit,
            lease_seconds=10,
            scan_after=after,
            discovery_budget=budget,
        )
    )


def frame(*records, visited=2, cursor=UUID(OTHER_ID), exhausted=False):
    return [("header", visited, cursor, exhausted) + (None,) * 71] + [
        ("item", None, None, None) + record for record in records
    ]


def claims():
    return (
        full_job_row(state="claimed", attempt=1),
        full_job_row(job(work_id=OTHER_ID, max_attempts=3), state="claimed", attempt=2),
    )


def test_retained_postimage_defines_exact_claim_fence_without_attempt_increment():
    # Break caught: reconstructing a preclaim row or treating acquisition as dispatch.
    first, last = claims()
    result = rows.decode_acquire(request(), frame(first, last))
    assert result.visited == 2 and not result.pass_exhausted
    assert tuple(item.fence.work_id for item in result.items) == (UUID(ID), UUID(OTHER_ID))
    for claim, expected in zip(result.items, (first, last)):
        assert claim.record.work.state == "claimed"
        assert claim.fence.token == expected[23]
        assert claim.fence.ownership_revision == expected[24]
        assert claim.fence.expected_attempt == expected[28]
        assert claim.record.work.dispatch_id is None


@pytest.mark.parametrize(
    "slot,bad",
    ((56, None), (57, b"wrong"), (60, b"wrong"), (61, b"{}"), (62, "present")),
)
def test_corrupt_final_material_invalidates_whole_claim_page(slot, bad):
    first, last = claims()
    changed = list(last)
    changed[slot] = bad
    with pytest.raises(PersistenceError) as caught:
        rows.decode_acquire(request(), frame(first, tuple(changed)))
    assert caught.value.code is ErrorCode.INVALID_OBSERVATION
    assert caught.value.unconfirmed


def test_capabilities_are_pairs_not_a_cross_product():
    # send/1 is absent even though send and version1 each occur in the selection.
    first, _ = claims()
    selected = [
        Capability(command_type="send", schema_version=2),
        Capability(command_type="poll", schema_version=1),
    ]
    with pytest.raises(PersistenceError):
        rows.decode_acquire(request(pairs=selected), frame(first))


def test_empty_claim_window_preserves_progress_and_end_of_pass():
    progress = rows.decode_acquire(request(limit=1, budget=2, after=UUID(ID)), frame(visited=2))
    assert progress.items == () and progress.visited == 2
    assert progress.next_cursor == UUID(OTHER_ID) and not progress.pass_exhausted
    end = rows.decode_acquire(
        request(after=UUID(OTHER_ID)),
        frame(visited=0, cursor=UUID(OTHER_ID), exhausted=True),
    )
    assert end.items == () and end.pass_exhausted


def test_scan_overflow_stops_after_one_probe_and_never_returns_prefix():
    first, last = claims()
    pulled = []

    def fetched():
        for item in frame(first, last):
            pulled.append(len(pulled))
            yield item
        pytest.fail("Acquisition fetched beyond header, limit and overflow probe")

    with pytest.raises(PersistenceError):
        rows.decode_acquire(request(limit=1), fetched())
    assert len(pulled) == 3


def test_scan_cancellation_propagates_identity_without_partial_claim_page():
    class CursorCancellation(BaseException):
        pass

    error = CursorCancellation()
    first, _ = claims()

    def fetched():
        yield from frame(first)
        raise error

    with pytest.raises(CursorCancellation) as caught:
        rows.decode_acquire(request(), fetched())
    assert caught.value is error
