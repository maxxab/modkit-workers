"""Explicit inert factory and thin wrapper for the real native job source."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._native_control import _SourceControl
from ._native_supervisor import _SupervisorCore
from .handlers import HandlerKind, HandlerRegistry, InvalidWorkerConfiguration
from .native_contracts import (
    NativeJobConfig,
    NativeJobResources,
    NativeWorkerSettings,
    WorkerSnapshot,
)
from .work_source import AcquireRequest

if TYPE_CHECKING:
    from .native_job import DbLocalApplication

__all__ = ["JobWorker", "create_job_worker"]


class JobWorker:
    """One retained supervisor/source owner. Construct with create_job_worker."""

    __slots__ = ("_core",)

    def __new__(cls, *args, **kwargs):
        raise TypeError("Use create_job_worker")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("JobWorker cannot be subclassed")

    def start(self) -> None:
        self._core.start()

    def request_stop(self) -> None:
        self._core.request_stop()

    def stop(self, *, timeout: float | None = None) -> WorkerSnapshot:
        return self._core.stop(timeout=timeout)

    def snapshot(self) -> WorkerSnapshot:
        return self._core.snapshot()


def create_job_worker(
    *,
    registry: HandlerRegistry,
    application: DbLocalApplication,
    config: NativeJobConfig,
    resources: NativeJobResources,
    request: AcquireRequest,
    settings: NativeWorkerSettings,
) -> JobWorker:
    """Validate pure configuration and bind the actual source without starting it.

    Resource proof/adoption, application validate_profile and E33 belong to
    source startup. Exact raw resources remain caller-owned until that adoption.
    """
    if (
        type(registry) is not HandlerRegistry
        or type(config) is not NativeJobConfig
        or type(resources) is not NativeJobResources
        or type(settings) is not NativeWorkerSettings
    ):
        raise InvalidWorkerConfiguration("Expected exact native worker configuration")
    config.__post_init__()
    settings.__post_init__()
    if settings.renewal_interval_seconds >= config.lease_seconds:
        raise InvalidWorkerConfiguration("Renewal interval must be inside lease")
    checked = registry.validate_acquisition(request)
    if checked.limit != 1:
        raise InvalidWorkerConfiguration("Native jobs require exactly one slot")
    for capability in checked.capabilities:
        if (
            registry.get(capability.command_type, capability.schema_version).kind
            is not HandlerKind.SYNC
        ):
            raise InvalidWorkerConfiguration("Native jobs require synchronous selected handlers")
    if not callable(getattr(application, "validate_profile", None)) or not callable(
        getattr(application, "bind", None)
    ):
        raise InvalidWorkerConfiguration("Expected application profile and binding hooks")

    # Actual source only; never a fake fallback or a partially implemented port.
    from .native_job import JobWorkSource

    control = _SourceControl(settings)
    source = JobWorkSource(
        registry=registry,
        application=application,
        config=config,
        resources=resources,
        control=control,
    )
    core = _SupervisorCore(source, control, checked, settings)  # Sole binder.
    worker = object.__new__(JobWorker)
    worker._core = core
    return worker
