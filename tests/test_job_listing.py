"""Complete W03 decoder controls; native SQL qualification is separate."""

from uuid import UUID

import pytest
from modkit_events.persistence.errors import ErrorCode, PersistenceError
from modkit_events.persistence.models import WorkCursor
from test_job_persistence_contracts import ID, NOW, OTHER_ID, full_job_row, job

from modkit_workers.persistence import bindings, models, rows


def page_request(*, after=None, limit=2):
    return bindings.list_jobs(models.JobListRequest(after=after, limit=limit))


def family():
    return [
        full_job_row(job(work_id=ID)),
        full_job_row(job(work_id=OTHER_ID, payload={"value": 2})),
    ]


def test_equal_timestamp_page_uses_uuid_order_and_cursor():
    # Break caught: timestamp-only ordering/cursor drops a lawful tied second row.
    first, last = family()
    result = rows.decode_list(page_request(), [first, last])
    assert tuple(str(item.work.work_id) for item in result) == (ID, OTHER_ID)
    cursor = WorkCursor(created_at=NOW, work_id=UUID(ID))
    request = page_request(after=cursor, limit=1)
    assert request.parameters == (b"jobs", NOW, UUID(ID), 1)
    result = rows.decode_list(request, [last])
    assert tuple(str(item.work.work_id) for item in result) == (OTHER_ID,)
    assert (
        rows.decode_list(page_request(after=WorkCursor(created_at=NOW, work_id=UUID(OTHER_ID))), [])
        == ()
    )


@pytest.mark.parametrize("variant", ("duplicate", "reversed", "cursor_equal"))
def test_nonadvancing_page_is_rejected(variant):
    first, last = family()
    request = page_request()
    fetched = {"duplicate": [first, first], "reversed": [last, first], "cursor_equal": [first]}[
        variant
    ]
    if variant == "cursor_equal":
        request = page_request(after=WorkCursor(created_at=NOW, work_id=UUID(ID)))
    with pytest.raises(PersistenceError) as caught:
        rows.decode_list(request, fetched)
    assert caught.value.code is ErrorCode.INVALID_OBSERVATION
    assert caught.value.unconfirmed


@pytest.mark.parametrize("slot,bad", ((56, None), (57, b"wrong"), (60, b"wrong"), (62, "present")))
def test_corrupt_final_job_half_invalidates_entire_page(slot, bad):
    first, last = family()
    assert len(rows.decode_list(page_request(), [first, last])) == 2
    changed = list(last)
    changed[slot] = bad
    with pytest.raises(PersistenceError) as caught:
        rows.decode_list(page_request(), [first, tuple(changed)])
    assert caught.value.code is ErrorCode.INVALID_OBSERVATION
    assert caught.value.unconfirmed


def test_oversized_page_stops_after_one_overflow_probe():
    first, last = family()
    pulls = []

    def fetched():
        for item in (first, last, last):
            pulls.append(len(pulls) + 1)
            yield item
        pulls.append(4)
        pytest.fail("Listing read beyond its bound plus one overflow probe")

    with pytest.raises(PersistenceError):
        rows.decode_list(page_request(), fetched())
    assert pulls == [1, 2, 3]


def test_cancelled_page_does_not_publish_a_prefix():
    class CursorCancellation(BaseException):
        pass

    first, _ = family()
    cancellation = CursorCancellation()

    def fetched():
        yield first
        raise cancellation

    with pytest.raises(CursorCancellation) as caught:
        rows.decode_list(page_request(), fetched())
    assert caught.value is cancellation
