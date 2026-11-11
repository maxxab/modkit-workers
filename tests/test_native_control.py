"""Real thread tests of private control; no database."""

from contextlib import contextmanager
from importlib import import_module, util
from queue import Queue
from threading import Event, Thread
from time import monotonic

import pytest


def modules():
    name = "modkit_workers._native_control"
    assert util.find_spec(name) is not None, "private control is not implemented"
    return import_module(name), import_module("modkit_workers._native_control_contracts")


@contextmanager
def control_harness(renew=None, unblock=None, *, ready=True):
    module, c = modules()

    class Source:
        def renew(self, work, fence):
            return renew(work, fence) if renew is not None else None

    source = Source()
    settings = c.NativeWorkerSettings(renewal_interval_seconds=0.01)
    control = module._SourceControl(settings)
    control.bind_source(source)
    control.bind_renewal(source.renew)
    control.register_lane("coordinator")
    queue = Queue(maxsize=1)
    boot = Event()

    def run():
        control.register_lane("data")
        boot.set()
        while True:
            item = queue.get()
            if item is None:
                return
            call, done, result = item
            try:
                result.append((True, call()))
            except BaseException as error:
                result.append((False, error))
            finally:
                done.set()

    thread = Thread(target=run, name="test-data", daemon=False)
    thread.start()
    assert boot.wait(2)
    control.start_renewal()
    if ready:
        control.publish_ready(source)

    def on_data(call):
        done, result = Event(), []
        queue.put((call, done, result), timeout=2)
        assert done.wait(3), "test data command did not finish"
        ok, value = result[0]
        if not ok:
            raise value
        return value

    try:
        yield control, source, on_data, c
    finally:
        if unblock is not None:
            unblock.set()
        control.request_stop()
        control.request_renewal_exit()
        assert control.join_renewal(3), "renewal test thread leaked"
        queue.put(None, timeout=2)
        thread.join(3)
        assert not thread.is_alive(), "data test thread leaked"


def test_reservation_before_stop_remains_admitted_but_second_is_rejected():
    with control_harness() as (control, source, data, _):
        reservation = data(lambda: control.reserve_acquisition(source))
        # Deterministically between admission and native call: stop may finish.
        control.request_stop()
        assert control.acquisition_in_flight
        work = object()
        data(lambda: control.publish_acquisition(reservation, work))
        assert control.current_work is work
        with pytest.raises(RuntimeError):
            data(lambda: control.reserve_acquisition(source))


def test_stop_before_reservation_prevents_admission():
    with control_harness() as (control, source, data, _):
        control.request_stop()
        with pytest.raises(RuntimeError):
            data(lambda: control.reserve_acquisition(source))
        assert not control.acquisition_in_flight


def test_foreign_thread_and_forged_reservation_rejected():
    with control_harness() as (control, source, data, _):
        with pytest.raises(RuntimeError):
            control.reserve_acquisition(source)
        reservation = data(lambda: control.reserve_acquisition(source))
        with pytest.raises(RuntimeError):
            data(lambda: control.publish_acquisition(object(), object()))
        data(lambda: control.publish_acquisition(reservation, None))


def test_duplicate_publication_cannot_execute_second_work():
    with control_harness() as (control, source, data, _):
        token = data(lambda: control.reserve_acquisition(source))
        data(lambda: control.publish_acquisition(token, None))
        with pytest.raises(RuntimeError):
            data(lambda: control.publish_acquisition(token, object()))


def test_blocked_renewal_quiescence_timeout_does_not_stop_callback():
    entered, release, completed = Event(), Event(), Event()

    def renew(work, fence):
        entered.set()
        assert release.wait(3)
        completed.set()

    try:
        with control_harness(renew, release) as (control, source, data, _):
            work, fence = object(), object()
            token = data(lambda: control.reserve_acquisition(source))
            data(lambda: control.publish_acquisition(token, work))
            data(lambda: control.activate(work, fence))
            assert entered.wait(2)
            drain = data(lambda: control.close_renewal(work))
            q = data(lambda: control.await_renewal_quiescent(drain, deadline_monotonic=monotonic()))
            assert not q.quiescent
            assert control.renewal_in_flight
            assert not completed.is_set()
            release.set()
            q = data(
                lambda: control.await_renewal_quiescent(drain, deadline_monotonic=monotonic() + 2)
            )
            assert q.quiescent and q.outcome_known and q.domain_active
            data(lambda: control.retire_work(work))
    finally:
        release.set()


def test_two_jobs_share_lifetime_lease_and_reject_stale_generation():
    with control_harness() as (control, source, data, c):
        lease = data(lambda: control.require_admission(source, kind=c.NativeAdmissionKind.ACQUIRE))
        old_drain = None
        for _ in range(2):
            work = object()
            token = data(lambda: control.reserve_acquisition(source))
            data(lambda: control.publish_acquisition(token, work))
            data(lambda: control.activate(work, object()))
            drain = data(lambda: control.close_renewal(work))
            q = data(
                lambda: control.await_renewal_quiescent(drain, deadline_monotonic=monotonic() + 2)
            )
            assert q.quiescent and q.outcome_known
            data(lambda: control.retire_work(work))
            assert (
                data(lambda: control.require_admission(source, kind=c.NativeAdmissionKind.ACQUIRE))
                is lease
            )
            if old_drain is not None:
                with pytest.raises(RuntimeError):
                    data(
                        lambda: control.await_renewal_quiescent(
                            old_drain, deadline_monotonic=monotonic()
                        )
                    )
            old_drain = drain


def test_callback_failure_revokes_admission_without_false_known_outcome():
    entered = Event()

    def renew(work, fence):
        entered.set()
        raise RuntimeError("test renewal uncertainty")

    with control_harness(renew) as (control, source, data, _):
        work = object()
        token = data(lambda: control.reserve_acquisition(source))
        data(lambda: control.publish_acquisition(token, work))
        data(lambda: control.activate(work, object()))
        assert entered.wait(2)
        assert control.wait_failed(2)
        drain = data(lambda: control.close_renewal(work))
        q = data(lambda: control.await_renewal_quiescent(drain, deadline_monotonic=monotonic() + 1))
        assert q.quiescent and not q.outcome_known and not q.domain_active
        with pytest.raises(RuntimeError):
            data(lambda: control.retire_work(work))


def test_cannot_start_unbound_or_publish_ready_without_live_lanes():
    m, c = modules()
    control = m._SourceControl(c.NativeWorkerSettings(renewal_interval_seconds=0.01))
    with pytest.raises(RuntimeError):
        control.start_renewal()
    with pytest.raises(RuntimeError):
        control.publish_ready(object())


def test_renewal_callback_must_belong_to_the_bound_source():
    m, c = modules()
    control = m._SourceControl(c.NativeWorkerSettings(renewal_interval_seconds=0.01))
    control.bind_source(object())
    with pytest.raises(RuntimeError):
        control.bind_renewal(lambda work, fence: None)


def test_confirmed_refusal_retires_only_local_reservation_and_stops():
    with control_harness() as (control, source, data, c):
        token = data(lambda: control.reserve_acquisition(source))
        with pytest.raises(ValueError):
            data(lambda: control.refuse_acquisition(token, reason="bad"))
        with pytest.raises(RuntimeError):
            data(
                lambda: control.refuse_acquisition(
                    object(), reason=c.WorkerReason.CAPACITY_UNAVAILABLE
                )
            )
        data(lambda: control.refuse_acquisition(token, reason=c.WorkerReason.CAPACITY_UNAVAILABLE))
        assert not control.acquisition_in_flight
        assert control.known_refusal
        assert control.failure is c.WorkerReason.CAPACITY_UNAVAILABLE
        with pytest.raises(RuntimeError):
            data(lambda: control.reserve_acquisition(source))


def test_unknown_failure_retains_reservation_and_cannot_be_refunded_as_refusal():
    with control_harness() as (control, source, data, c):
        token = data(lambda: control.reserve_acquisition(source))
        control.fail(c.WorkerReason.OUTCOME_UNKNOWN)
        assert control.acquisition_in_flight
        assert not control.known_refusal
        with pytest.raises(RuntimeError):
            data(
                lambda: control.refuse_acquisition(
                    token, reason=c.WorkerReason.CAPACITY_UNAVAILABLE
                )
            )
        assert control.acquisition_in_flight


def test_reserved_continuation_survives_stop_but_not_failure_or_publication():
    with control_harness() as (control, source, data, c):
        token = data(lambda: control.reserve_acquisition(source))
        lease = data(lambda: control.require_reserved_acquisition(source, token))
        control.request_stop()
        assert data(lambda: control.require_reserved_acquisition(source, token)) is lease
        with pytest.raises(RuntimeError):
            data(lambda: control.require_reserved_acquisition(object(), token))
        with pytest.raises(RuntimeError):
            control.require_reserved_acquisition(source, token)
        data(lambda: control.publish_acquisition(token, None))
        with pytest.raises(RuntimeError):
            data(lambda: control.require_reserved_acquisition(source, token))


def test_reserved_continuation_rejects_unknown_failed_controller():
    with control_harness() as (control, source, data, c):
        token = data(lambda: control.reserve_acquisition(source))
        control.fail(c.WorkerReason.OUTCOME_UNKNOWN)
        with pytest.raises(RuntimeError):
            data(lambda: control.require_reserved_acquisition(source, token))


def test_profile_unsupported_has_distinct_stable_reason():
    _, c = modules()
    assert c.WorkerReason.PROFILE_UNSUPPORTED.value == "profile_unsupported"


def test_startup_is_exact_bound_pre_ready_data_lane_and_once_only():
    with control_harness(ready=False) as (control, source, data, _):
        with pytest.raises(RuntimeError):
            control.admit_startup(source)  # Foreign lane must not consume admission.
        with pytest.raises(RuntimeError):
            data(lambda: control.admit_startup(object()))
        assert data(lambda: control.admit_startup(source)) is None
        assert control._lease is None and not control.acquisition_in_flight
        with pytest.raises(RuntimeError):
            data(lambda: control.admit_startup(source))
        control.publish_ready(source)
        with pytest.raises(RuntimeError):
            data(lambda: control.admit_startup(source))


def test_startup_stop_winner_is_known_nonadmission():
    with control_harness(ready=False) as (control, source, data, c):
        control.request_stop()
        with pytest.raises(c._AdmissionClosed):
            data(lambda: control.admit_startup(source))
        assert not control._startup_admitted
        assert control.failure is None and control._lease is None


def test_startup_before_binding_or_registered_lane_is_inert():
    module, c = modules()
    control = module._SourceControl(c.NativeWorkerSettings(renewal_interval_seconds=1))
    with pytest.raises(RuntimeError):
        control.admit_startup(object())
    assert not control._startup_admitted and control._lease is None
