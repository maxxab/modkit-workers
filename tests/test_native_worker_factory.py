"""Real factory composition with explicit test-only native startup seams."""

import os
import subprocess
import sys
from importlib import import_module, util
from pathlib import Path

import pytest
from test_native_public_contracts import config_values


def factory():
    name = "modkit_workers.native_worker"
    assert util.find_spec(name) is not None, "actual native worker factory is absent"
    return import_module(name)


def arguments(*, asynchronous=False, limit=1):
    from modkit_events.persistence.models import Capability

    from modkit_workers import AcquireRequest, HandlerKind, HandlerRegistration, HandlerRegistry
    from modkit_workers.native_contracts import (
        NativeJobConfig,
        NativeJobResources,
        NativeWorkerSettings,
    )

    def sync(context):
        raise AssertionError("construction invoked handler")

    async def async_handler(context):
        raise AssertionError("construction invoked handler")

    class Application:
        called = 0

        def validate_profile(self, request):
            self.called += 1

        def bind(self, root, context):
            raise AssertionError("construction invoked binding")

    registry = HandlerRegistry(
        [
            HandlerRegistration(
                command_type="job",
                schema_version=1,
                handler=async_handler if asynchronous else sync,
                kind=HandlerKind.ASYNC if asynchronous else HandlerKind.SYNC,
            )
        ]
    )
    return dict(
        registry=registry,
        application=Application(),
        config=NativeJobConfig(**config_values()),
        resources=NativeJobResources(
            configuration=object(),
            data_connection=object(),
            renewal_connection=object(),
            data_ledger=object(),
            renewal_ledger=object(),
        ),
        request=AcquireRequest(
            capabilities=[Capability(command_type="job", schema_version=1)],
            limit=limit,
            discovery_budget=max(1, limit),
        ),
        settings=NativeWorkerSettings(renewal_interval_seconds=1),
    )


def test_factory_constructs_actual_source_and_core_is_the_only_binder():
    public = factory()
    from modkit_workers.native_contracts import WorkerState
    from modkit_workers.native_job import JobWorkSource

    kwargs = arguments()
    worker = public.create_job_worker(**kwargs)
    assert type(worker) is public.JobWorker
    assert type(worker._core._source) is JobWorkSource
    source, control = worker._core._source, worker._core._control
    assert source._control is control
    assert control._source is source and control._renew.__self__ is source
    assert control._renewal_thread is None
    assert kwargs["application"].called == 0
    assert worker.snapshot().state is WorkerState.NEW
    assert not source.snapshot().resources_adopted
    with pytest.raises(RuntimeError):
        control.bind_source(source)
    with pytest.raises(RuntimeError):
        control.bind_renewal(source.renew)


@pytest.mark.parametrize("asynchronous,limit", [(True, 1), (False, 2)])
def test_factory_rejects_unsupported_handler_or_multiple_slots(asynchronous, limit):
    public = factory()
    with pytest.raises(ValueError):
        public.create_job_worker(**arguments(asynchronous=asynchronous, limit=limit))


def test_factory_rejects_renewal_interval_not_inside_lease():
    public = factory()
    from modkit_workers.native_contracts import NativeWorkerSettings

    kwargs = arguments()
    kwargs["settings"] = NativeWorkerSettings(renewal_interval_seconds=30)
    with pytest.raises(ValueError):
        public.create_job_worker(**kwargs)


def test_public_worker_cannot_be_constructed_with_unbound_source():
    public = factory()
    with pytest.raises(TypeError):
        public.JobWorker(object())


def test_factory_leaf_import_is_driver_free_without_importing_source():
    factory()
    root = Path(__file__).parents[1]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env["PYTHONPATH"] = str(root / "src") + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import sys; import modkit_workers.native_worker; "
            "assert 'psycopg' not in sys.modules; "
            "assert 'modkit_workers.native_job' not in sys.modules",
        ],
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_factory_startup_poll_and_stop_with_native_io_seams(monkeypatch):
    from threading import Event

    from test_native_job_lifecycle import acquired_page, setup_startup_seams

    from modkit_workers import _native_job_lifecycle as life

    worker = factory().create_job_worker(**arguments())
    source = worker._core._source
    trace, association = setup_startup_seams(monkeypatch, source)
    monkeypatch.setattr(source, "_domain_active", lambda: True)
    entered, release = Event(), Event()

    def acquire(lane, request, *, budget, project, check):
        check()
        trace.append("W05")
        entered.set()
        assert release.wait(3), "test did not release acquisition"
        check()  # Already reserved continuation remains lawful after stop.
        return project(acquired_page(empty=True))

    monkeypatch.setattr(life._NativeLane, "acquire", acquire, raising=False)
    try:
        worker.start()
        assert entered.wait(3)
        assert association == [source]
        assert trace.count("E33") == 2
        assert source.snapshot().startup_verified
        snapshot = worker.stop(timeout=0)
        assert snapshot.stop_requested and not snapshot.clean_stop
        assert worker._core._control.acquisition_in_flight
        release.set()
        assert worker._core.join(3)
        snapshot = worker.snapshot()
        assert snapshot.clean_stop and not snapshot.ready
        assert not snapshot.source.unresolved
        assert trace.count("W05") == 1 and trace.count("close") == 2
        assert snapshot.source.acquisition_pages == 1
    finally:
        release.set()
        worker.request_stop()
        assert worker._core.join(3), "test leaked coordinator/data/renewal threads"


@pytest.mark.parametrize("failure", ["profile", "attach"])
def test_real_factory_startup_failure_preserves_adoption_boundary(monkeypatch, failure):
    from test_native_job_lifecycle import setup_startup_seams

    from modkit_workers.native_contracts import WorkerState

    kwargs = arguments()
    if failure == "profile":
        kwargs["application"].validate_profile = lambda request: False
    worker = factory().create_job_worker(**kwargs)
    source = worker._core._source
    trace, association = setup_startup_seams(monkeypatch, source, attach_fail=failure == "attach")
    monkeypatch.setattr(source, "_domain_active", lambda: True)
    try:
        worker.start()
        assert worker._core.join(3)
        state = worker.snapshot()
        assert state.state is WorkerState.FAILED and not state.ready
        assert state.source.resources_adopted is (failure == "attach")
        assert state.source.unresolved is (failure == "attach")
        assert association == ([source] if failure == "attach" else [])
        assert "E33" not in trace and "close" not in trace
        assert not worker._core._control.acquisition_in_flight
    finally:
        worker.request_stop()
        assert worker._core.join(3), "test leaked startup threads"
