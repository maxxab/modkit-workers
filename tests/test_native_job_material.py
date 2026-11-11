"""Real source material contracts; no native connection or driver required."""

import importlib
import importlib.util

import pytest
from modkit_events.persistence.models import MaterialState
from test_job_acquisition import frame, request
from test_job_persistence_contracts import full_job_row, job

from modkit_workers.persistence import rows


def module():
    assert importlib.util.find_spec("modkit_workers._native_job_lifecycle") is not None, (
        "source material implementation is missing"
    )
    return importlib.import_module("modkit_workers._native_job_lifecycle")


def claim(**changes):
    return rows.decode_acquire(
        request(limit=1), frame(full_job_row(job(**changes), state="claimed", attempt=0), visited=1)
    ).items[0]


def lease(m, *, payload=1048576, result=1048576, depth=32, short=False):
    needed = m._source_capacity(payload, result)
    return m._MaterialLease(
        capacity=needed - int(short), payload_limit=payload, result_limit=result, depth_limit=depth
    )


def test_exact_logical_reservation_and_one_short_before_copy():
    m = module()
    assert m._source_capacity(1048576, 1048576) == 1068883968
    good = lease(m)
    good.reserve()
    assert good.reserved
    bad = lease(m, short=True)
    with pytest.raises(m.MaterialCapacityError):
        bad.reserve()
    assert not bad.reserved


def test_detachment_requires_prepaid_envelope_and_copies_material():
    m = module()
    c = claim()
    paid = lease(m)
    with pytest.raises(m.MaterialCapacityError):
        m._detach_claim(c, paid)
    paid.reserve()
    detached = m._detach_claim(c, paid)
    assert detached.semantic_input == c.record.payload.semantic_input
    assert detached.semantic_input is not c.record.payload.semantic_input
    assert detached.fence == c.fence and detached.fence is not c.fence
    assert detached.scope.application == "app"
    assert detached.effect_id.startswith(b"modkit-db-local-effect-v1:")
    assert len(detached.effect_id) == 90 and len(detached.request_evidence) == 91
    assert not hasattr(detached, "record") and not hasattr(detached, "sidecar")


def test_actual_scope_context_and_dispatched_attempt_are_preserved():
    from modkit_events.persistence.scope import Scope

    m = module()
    paid = lease(m)
    paid.reserve()
    c = claim(scope=Scope("other-app", "tenant", "actual-owner"))
    d = m._detach_claim(c, paid)
    context = m._make_context(d, 1, paid)
    assert context.scope == Scope("other-app", "tenant", "actual-owner")
    assert context.attempt == 1 and context.payload["value"] == 1


def test_too_small_payload_and_depth_keep_reservation_until_known_release():
    m = module()
    c = claim(payload={"a": {"b": {"c": 1}}})
    for paid in (lease(m, payload=1), lease(m, depth=1)):
        paid.reserve()
        with pytest.raises(m.UnsupportedJobProfile):
            m._detach_claim(c, paid)
        assert paid.reserved
        with pytest.raises(m.MaterialCapacityError):
            paid.release(known=False, quiescent=True)
        assert paid.reserved
        paid.release(known=True, quiescent=True)
        assert not paid.reserved


def test_only_exact_absent_profile_is_eligible():
    m = module()
    c = claim()
    paid = lease(m)
    paid.reserve()
    # Tampering is defense-in-depth, not a claim this is a valid typed record.
    object.__setattr__(c.record.payload, "material_state", MaterialState.ERASED)
    with pytest.raises(m.UnsupportedJobProfile):
        m._detach_claim(c, paid)
    assert paid.reserved


def test_result_projection_requires_exact_bounded_bytes():
    m = module()
    paid = lease(m, result=4)
    paid.reserve()
    assert m._accept_result(b"done", paid) == b"done"
    for bad in (b"12345", bytearray(b"x"), None, "x"):
        with pytest.raises(m.UnsupportedJobProfile):
            m._accept_result(bad, paid)
