"""Pure native W05 consumer checks; no database or driver qualification."""

from uuid import UUID

import pytest
from modkit_events.persistence.errors import _ValidationReject
from modkit_events.persistence.models import Capability
from test_job_acquisition import claims, frame, request
from test_job_persistence_contracts import ID, OTHER_ID

from modkit_workers.persistence import bindings, models, native_store, rows


def logical(**changes):
    values = dict(
        capabilities=(Capability(command_type="send", schema_version=1),),
        limit=2,
        lease_seconds=10,
        scan_after=None,
        discovery_budget=16,
    )
    values.update(changes)
    return models.JobAcquireRequest(**values)


def native_frame(*records, **options):
    return tuple(frame(*records, **options))


def test_raw_request_matches_public_snapshot():
    value = logical(
        capabilities=(
            Capability(command_type="send", schema_version=2),
            Capability(command_type="poll", schema_version=1),
        )
    )
    raw = bindings._acquire_raw(value)
    pure = bindings.acquire(value)
    assert raw.parameters == pure.parameters
    assert raw.context.expected == () and raw.context.readiness is None
    assert type(raw.parameters[4]) is float


def test_raw_complete_page_matches_public_and_fences():
    fetched = native_frame(*claims())
    raw = rows._decode_acquire_raw(request(), fetched)
    pure = rows.decode_acquire(request(), fetched)
    assert raw == pure
    rows._validate_acquire_result_raw(request(), raw)
    for claim in raw.items:
        assert claim.fence.expected_attempt == claim.record.work.attempt_count
        assert claim.fence.token == claim.record.work.token


@pytest.mark.parametrize(
    "slot,bad",
    [
        (56, None),
        (57, b"wrong"),
        (60, b"wrong"),
        (61, b"{}"),
        (62, "present"),
        (39, True),
        (40, UUID(ID)),
    ],
)
def test_late_corruption_rejects_entire_page(slot, bad):
    first, last = claims()
    changed = list(last)
    changed[slot] = bad
    with pytest.raises(_ValidationReject):
        rows._decode_acquire_raw(request(), native_frame(first, tuple(changed)))


@pytest.mark.parametrize(
    "fetched",
    [
        (),
        (("header",),),
        tuple(frame(visited=0, cursor=None, exhausted=True)) * 2,
        tuple(reversed(frame(*claims()))),
    ],
)
def test_invalid_complete_frames_rejected(fetched):
    with pytest.raises(_ValidationReject):
        rows._decode_acquire_raw(request(), fetched)


def test_capability_pairs_and_cursor_order():
    selected = request(
        pairs=[
            Capability(command_type="send", schema_version=2),
            Capability(command_type="poll", schema_version=1),
        ]
    )
    with pytest.raises(_ValidationReject):
        rows._decode_acquire_raw(selected, native_frame(claims()[0]))
    with pytest.raises(_ValidationReject):
        rows._decode_acquire_raw(request(), native_frame(*reversed(claims())))


def test_empty_progress_and_exhaustion():
    raw = rows._decode_acquire_raw(request(limit=1, budget=2, after=UUID(ID)), native_frame())
    assert raw.items == () and raw.next_cursor == UUID(OTHER_ID)
    end = rows._decode_acquire_raw(
        request(after=UUID(OTHER_ID)),
        native_frame(visited=0, cursor=UUID(OTHER_ID), exhausted=True),
    )
    assert end.pass_exhausted


def test_wrapper_passes_default_and_explicit_budget(monkeypatch):
    import sys
    from types import ModuleType

    calls = []
    stub = ModuleType("modkit_events.persistence.native_execution")
    stub.prepare_component = lambda *a, **kw: calls.append((a, kw))
    monkeypatch.setitem(sys.modules, stub.__name__, stub)
    value = logical()
    ledger = object()
    execution = object()
    native_store.prepare_acquire(execution, value, execution_ledger=ledger)
    assert calls[-1][0] == (execution, native_store._ACQUIRE, value)
    assert calls[-1][1] == dict(execution_ledger=ledger, max_page_payload_bytes=16777216)
    native_store.prepare_acquire(
        execution, value, execution_ledger=ledger, max_page_payload_bytes=6
    )
    assert calls[-1][1]["max_page_payload_bytes"] == 6


def test_raw_callbacks_preserve_unexpected_baseexception(monkeypatch):
    class Cancellation(BaseException):
        pass

    error = Cancellation()

    def cancel(*a, **kw):
        raise error

    monkeypatch.setattr(rows, "_decode_job_half_raw", cancel)
    with pytest.raises(Cancellation) as caught:
        rows._decode_acquire_raw(request(), native_frame(claims()[0]))
    assert caught.value is error


@pytest.mark.parametrize("budget", [None, True, 0, -1, 2**32 + 1, 6.0])
def test_exact_budget_domain(budget):
    from modkit_events.persistence import native_profile

    with pytest.raises(_ValidationReject):
        native_profile.result_capacity(
            native_store._ACQUIRE, request=request(), max_page_payload_bytes=budget
        )


@pytest.mark.parametrize("budget", [1, 2, 3, 4, 5, 6, 2**32])
def test_header_only_occurrence_budget(budget):
    from modkit_events.persistence import native_profile

    req = request()
    page = rows._decode_acquire_raw(req, native_frame(visited=0, cursor=None, exhausted=True))
    if budget < 6:
        with pytest.raises(_ValidationReject):
            native_profile._result_size(
                req, page, native_store._ACQUIRE, max_page_payload_bytes=budget
            )
    else:
        size = native_profile._result_size(
            req, page, native_store._ACQUIRE, max_page_payload_bytes=budget
        )
        assert size <= native_profile.result_capacity(
            native_store._ACQUIRE, request=req, max_page_payload_bytes=budget
        )


def test_full_256_claim_graph_and_exact_occurrence_budget():
    from modkit_events.persistence import native_profile
    from test_job_persistence_contracts import full_job_row, job

    records = tuple(
        full_job_row(
            job(work_id=f"00000000-0000-4000-8000-{i:012x}", max_attempts=3),
            state="claimed",
            attempt=1,
        )
        for i in range(1, 257)
    )
    req = request(limit=256, budget=4096)
    fetched = native_frame(
        *records, visited=256, cursor=UUID("00000000-0000-4000-8000-000000000100")
    )
    result = rows._decode_acquire_raw(req, fetched)
    assert len(result.items) == 256
    # Charge each canonical variable cell occurrence, even equal/aliased values.
    charge = sum(
        len(v) if type(v) is bytes else len(v.encode("utf-8"))
        for row in fetched
        for v in row
        if type(v) in (bytes, str)
    )
    size = native_profile._result_size(
        req, result, native_store._ACQUIRE, max_page_payload_bytes=charge
    )
    assert size <= native_profile.result_capacity(
        native_store._ACQUIRE, request=req, max_page_payload_bytes=charge
    )
    with pytest.raises(_ValidationReject):
        native_profile._result_size(
            req, result, native_store._ACQUIRE, max_page_payload_bytes=charge - 1
        )


def test_required_null_provenance_rejects_before_typed_graph(monkeypatch):
    first, last = claims()
    last = list(last)
    last[40] = UUID(ID)

    def forbidden(*a, **kw):
        pytest.fail("typed graph constructed before complete provenance preflight")

    monkeypatch.setattr(rows.common_rows, "_decode_work_observation_raw", forbidden)
    with pytest.raises(_ValidationReject):
        rows._decode_acquire_raw(request(), native_frame(first, tuple(last)))


def test_forged_fence_rejected_at_result_boundary():
    result = rows._decode_acquire_raw(request(), native_frame(*claims()))
    object.__setattr__(result.items[-1].fence, "expected_attempt", 0)
    with pytest.raises(_ValidationReject):
        rows._validate_acquire_result_raw(request(), result)


def test_no_public_copy_or_sanitizing_boundary(monkeypatch):
    from modkit_workers.persistence import observations

    req = logical()
    fetched = native_frame(*claims())

    def forbidden(*a, **kw):
        pytest.fail("public constructor/copy boundary used")

    monkeypatch.setattr(bindings, "replace", forbidden)
    monkeypatch.setattr(bindings, "acquire", forbidden)
    monkeypatch.setattr(observations, "replace", forbidden)
    monkeypatch.setattr(rows.common_rows, "split_scan_rows", forbidden)
    result = rows._decode_acquire_raw(bindings._acquire_raw(req), fetched)
    assert len(result.items) == 2
