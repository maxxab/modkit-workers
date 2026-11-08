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


def test_raw_list_decodes_whole_page_without_public_boundaries(monkeypatch):
    from modkit_workers.persistence import observations

    first, last = family()
    request = bindings._list_jobs_raw(models.JobListRequest(after=None, limit=2))
    expected = rows.decode_list(page_request(), (first, last))

    def forbidden(*args, **kwargs):
        pytest.fail("native page entered public sanitizer or replacement")

    monkeypatch.setattr(rows, "_full", forbidden)
    monkeypatch.setattr(rows, "decode_list", forbidden)
    monkeypatch.setattr(rows, "replace", forbidden)
    monkeypatch.setattr(observations, "replace", forbidden)
    for cls in (observations.JobRecord, observations.JobDetails, observations.JobPayload):
        monkeypatch.setattr(cls, "__post_init__", forbidden)
    result = rows._decode_list_raw(request, (first, last))
    assert result == expected
    assert type(result) is tuple
    references = tuple((item, item.work, item.details, item.payload) for item in result)
    rows._validate_list_result_raw(request, result)
    for before, item in zip(references, result):
        assert all(left is right for left, right in zip(
            before, (item, item.work, item.details, item.payload)
        ))
    assert rows._decode_list_raw(request, ()) == ()


def test_raw_list_cursor_advances_equal_timestamp_uuid():
    _, last = family()
    request = bindings._list_jobs_raw(models.JobListRequest(
        after=WorkCursor(created_at=NOW, work_id=UUID(ID)), limit=1
    ))
    result = rows._decode_list_raw(request, (last,))
    assert tuple(item.work.work_id for item in result) == (UUID(OTHER_ID),)
    rows._validate_list_result_raw(request, result)


@pytest.mark.parametrize("variant", ["outer_list", "row_list", "row_short", "row_long", "over_limit"])
def test_raw_list_preflights_all_row_shapes_before_decoding(monkeypatch, variant):
    from modkit_events.persistence import rows as shared_rows
    from modkit_events.persistence.errors import _ValidationReject

    first, last = family()
    request = bindings._list_jobs_raw(models.JobListRequest(after=None, limit=2))
    fetched = {
        "outer_list": [first, last],
        "row_list": (first, list(last)),
        "row_short": (first, last[:-1]),
        "row_long": (first, last + (None,)),
        "over_limit": (first, last, last),
    }[variant]

    def forbidden(*args):
        pytest.fail("invalid page shape reached any record decoder")

    monkeypatch.setattr(shared_rows, "_decode_work_observation_raw", forbidden)
    with pytest.raises(_ValidationReject):
        rows._decode_list_raw(request, fetched)


@pytest.mark.parametrize("variant", ["duplicate", "reversed", "cursor_equal", "before_cursor"])
def test_raw_list_rejects_nonadvancing_pages(variant):
    from modkit_events.persistence.errors import _ValidationReject

    first, last = family()
    after = None
    fetched = (first, first) if variant == "duplicate" else (last, first)
    if variant in ("cursor_equal", "before_cursor"):
        after = WorkCursor(created_at=NOW, work_id=UUID(OTHER_ID))
        fetched = (last,) if variant == "cursor_equal" else (first,)
    request = bindings._list_jobs_raw(models.JobListRequest(after=after, limit=2))
    with pytest.raises(_ValidationReject):
        rows._decode_list_raw(request, fetched)


@pytest.mark.parametrize("slot,bad", [(3, b"wrong"), (56, None), (57, b"wrong"),
                                     (60, b"wrong"), (62, "invalid"), (70, b"bad-json")])
def test_raw_list_corrupt_final_record_rejects_whole_page(slot, bad):
    from modkit_events.persistence.errors import _ValidationReject

    first, last = family()
    changed = list(last)
    changed[slot] = bad
    request = bindings._list_jobs_raw(models.JobListRequest(after=None, limit=2))
    with pytest.raises(_ValidationReject):
        rows._decode_list_raw(request, (first, tuple(changed)))


@pytest.mark.parametrize("boundary", ["decode", "validate"])
@pytest.mark.parametrize("error", [
    ValueError("late list primary"), RuntimeError("late list primary"),
    KeyboardInterrupt("late list primary"),
    PersistenceError(ErrorCode.DATABASE_FAILURE, unconfirmed=True),
])
def test_raw_list_late_failure_preserves_exact_error_chain(monkeypatch, boundary, error):
    from modkit_events.persistence import rows as shared_rows

    from modkit_workers.persistence import observations

    request = bindings._list_jobs_raw(models.JobListRequest(after=None, limit=2))
    source = tuple(family())
    target = shared_rows if boundary == "decode" else observations
    name = "_decode_work_observation_raw" if boundary == "decode" else "_validate_job_record_raw"
    original = getattr(target, name)
    result = None if boundary == "decode" else rows._decode_list_raw(request, source)
    calls = 0
    cause = RuntimeError("cause")
    context = RuntimeError("context")
    error.__cause__ = cause
    error.__context__ = context
    error.__suppress_context__ = True

    def fail_second(value):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise error
        return original(value)

    monkeypatch.setattr(target, name, fail_second)
    with pytest.raises(type(error)) as caught:
        if boundary == "decode":
            rows._decode_list_raw(request, source)
        else:
            rows._validate_list_result_raw(request, result)
    assert calls == 2
    assert caught.value is error
    assert error.__cause__ is cause
    assert error.__context__ is context
    assert error.__suppress_context__ is True


def test_raw_list_decodes_all_records_before_page_order_check(monkeypatch):
    from modkit_events.persistence import rows as shared_rows

    first, last = family()
    request = bindings._list_jobs_raw(models.JobListRequest(after=None, limit=3))
    original = shared_rows._decode_work_observation_raw
    error = RuntimeError("last record wins before page-order rejection")
    calls = 0

    def fail_last(value):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise error
        return original(value)

    monkeypatch.setattr(shared_rows, "_decode_work_observation_raw", fail_last)
    with pytest.raises(RuntimeError) as caught:
        rows._decode_list_raw(request, (first, first, last))
    assert caught.value is error
    assert calls == 3


@pytest.mark.parametrize("variant", ["outer_list", "over_limit", "record_type", "duplicate",
                                     "reverse", "wrong_namespace", "nested_mutable"])
def test_raw_list_result_validation_rejects_without_replacement(variant):
    from modkit_events.persistence.errors import _ValidationReject

    request = bindings._list_jobs_raw(models.JobListRequest(after=None, limit=2))
    result = rows._decode_list_raw(request, tuple(family()))
    if variant == "outer_list":
        result = list(result)
    elif variant == "over_limit":
        result = result + (result[-1],)
    elif variant == "record_type":
        result = (result[0], object())
    elif variant == "duplicate":
        result = (result[0], result[0])
    elif variant == "reverse":
        result = result[::-1]
    elif variant == "wrong_namespace":
        object.__setattr__(result[-1].work, "namespace", b"wrong")
    else:
        buffer = bytearray(result[-1].payload.semantic_input)
        object.__setattr__(result[-1].payload, "semantic_input", buffer)
    with pytest.raises(_ValidationReject):
        rows._validate_list_result_raw(request, result)
    if variant == "nested_mutable":
        assert result[-1].payload.semantic_input is buffer
