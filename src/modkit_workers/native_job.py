"""Explicit application binding and one-slot DB-local job source.

Importing this module does not import a native driver or open a connection.
"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from modkit_events.persistence.native_sync import ManagedConnection

    from .context import JobContext
    from .work_source import AcquireRequest


class BoundJob(Protocol):
    def result(self) -> bytes: ...


class DbLocalApplication(Protocol):
    def validate_profile(self, request: AcquireRequest, /) -> None: ...
    def bind(
        self, root: DbLocalRoot, context: JobContext, /
    ) -> AbstractContextManager[BoundJob]: ...


class _Opaque:
    __slots__ = ()

    def __new__(cls):
        raise TypeError("Source-issued capability only")

    def __copy__(self):
        raise TypeError("Source capability cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("Source capability cannot be copied")

    def __reduce_ex__(self, protocol):
        raise TypeError("Source capability cannot be serialized")

    def __setattr__(self, name, value):
        raise TypeError("Source capability is immutable")

    def __repr__(self):
        return "<source-owned capability>"


class JobWork(_Opaque):
    __slots__ = ("_owner",)

    def __init_subclass__(cls, **kwargs):
        raise TypeError("JobWork is sealed")


def _issue_work(owner) -> JobWork:
    work = object.__new__(JobWork)
    object.__setattr__(work, "_owner", owner)
    return work


def _owns_work(work, owner) -> bool:
    return type(work) is JobWork and work._owner is owner


class DbLocalRoot(_Opaque):
    __slots__ = ("_connection", "_root_xid", "_active")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("DbLocalRoot is sealed")

    @property
    def connection(self) -> ManagedConnection:
        if not self._active:
            raise RuntimeError("Application root binding has ended")
        return self._connection

    @property
    def root_xid(self) -> int:
        if not self._active:
            raise RuntimeError("Application root binding has ended")
        return self._root_xid


def _issue_root(connection, root_xid: int) -> DbLocalRoot:
    if type(root_xid) is not int or not 1 <= root_xid <= 2**64 - 1:
        raise ValueError("Invalid business root identity")
    root = object.__new__(DbLocalRoot)
    object.__setattr__(root, "_connection", connection)
    object.__setattr__(root, "_root_xid", root_xid)
    object.__setattr__(root, "_active", True)
    return root


def _expire_root(root: DbLocalRoot) -> None:
    object.__setattr__(root, "_active", False)
    object.__setattr__(root, "_connection", None)


def _require_none(value) -> None:
    import inspect

    if value is None:
        return
    # Dispose an accidentally returned *unstarted* Python coroutine/generator;
    # this never purports to cancel a running native operation.
    if inspect.iscoroutine(value) or inspect.isgenerator(value):
        value.close()
    raise ValueError("Synchronous application hook must return None")


def _validate_application_profile(application, request) -> None:
    failed = False
    try:
        _require_none(application.validate_profile(request))
    except Exception:
        failed = True
    if failed:
        # Raise outside the callback exception handler, retaining no exception
        # object, traceback or application message in this internal error.
        raise ValueError("Application profile assertion rejected")


def _invoke_application(application, handler, connection, root_xid, context, lease):
    import sys

    from ._native_job_lifecycle import _accept_result

    root = _issue_root(connection, root_xid)
    binding = bound = result = None
    failed = False
    try:
        try:
            binding = application.bind(root, context)
            bound = binding.__enter__()
            try:
                _require_none(handler(context))
                result = _accept_result(bound.result(), lease)
            except BaseException as application_error:
                failed = True
                # Application owns its own diagnostic callback. Suppression
                # never converts a failed handler into successful completion.
                binding.__exit__(*sys.exc_info())
                if not isinstance(application_error, Exception):
                    raise
            else:
                binding.__exit__(None, None, None)
        except Exception:
            failed = True
    finally:
        # Never expose transaction controls through JobContext. Root view is
        # only live for application binding and is revoked on every exit.
        _expire_root(root)
        binding = bound = None
    if failed:
        result = None
        return False, None
    return True, result


class NativeJobUnresolved(RuntimeError):
    """Sanitized unresolved source outcome; original diagnostics are not retained."""


class JobWorkSource:
    """One-slot source; cooperative DB-local application binding is explicit."""

    def __init__(self, *, registry, application, config, resources, control):
        from threading import RLock

        from ._native_job_lifecycle import _MaterialLease
        from .handlers import HandlerRegistry
        from .native_contracts import JobSourceSnapshot, NativeJobConfig, NativeJobResources

        if type(registry) is not HandlerRegistry or type(config) is not NativeJobConfig:
            raise ValueError("Expected exact registry and native configuration")
        if type(resources) is not NativeJobResources:
            raise ValueError("Expected exact native resources")
        config.__post_init__()
        self._registry, self._application = registry, application
        self._config, self._resources, self._control = config, resources, control
        self._lock = RLock()
        self._state = JobSourceSnapshot()
        self._started = self._startup_called = self._stopped = False
        self._adoption_attempted = self._dispatch_committed = False
        self._data = self._renewal = None
        self._request = self._reservation = self._work = self._detached = self._fence = None
        self._context = self._guard = self._dispatch_id = None
        self._cancelled = False
        self._cursor = None
        self._material = _MaterialLease(
            capacity=config.source_material_bytes,
            payload_limit=config.max_payload_bytes,
            result_limit=config.max_result_bytes,
            depth_limit=config.max_payload_depth,
        )

    @property
    def renewal_owner(self):
        from .work_source import RenewalOwner

        return RenewalOwner.SOURCE

    def _publish(self, **changes):
        from dataclasses import replace
        from time import monotonic

        with self._lock:
            sequence = self._state.progress_sequence
            changes.setdefault("progress_sequence", min(2**64 - 1, sequence + 1))
            changes.setdefault("last_progress_monotonic", monotonic())
            if sequence == 2**64 - 1:
                changes["counters_saturated"] = True
            self._state = replace(self._state, **changes)

    def snapshot(self):
        from dataclasses import replace

        with self._lock:
            state = self._state
            attempted = self._adoption_attempted
        if attempted:
            from .native_setup import _resources_adopted

            adopted = _resources_adopted(self._resources, self)
            state = replace(state, resources_adopted=adopted)
        return state

    def request_stop(self) -> None:
        with self._lock:
            self._stopped = True
        self._publish(admission_closed=True)

    def _require_started(self):
        if not self._started:
            raise RuntimeError("Native source has not completed startup")

    def _domain_active(self):
        from modkit_events.persistence.resource_registry import resource_domain

        return not resource_domain().stopped

    def _check_domain(self):
        if not self._domain_active():
            raise NativeJobUnresolved("Canonical resource domain is stopped")

    def _check_reserved(self):
        self._check_domain()
        self._control.require_reserved_acquisition(self, self._reservation)

    def _increment(self, name):
        with self._lock:
            value = getattr(self._state, name)
            self._publish(
                **{name: min(2**64 - 1, value + 1)},
                counters_saturated=self._state.counters_saturated or value == 2**64 - 1,
            )

    def _unknown(self, reason):
        from .native_contracts import JobSourcePhase

        self._publish(
            phase=JobSourcePhase.FAILED,
            admission_closed=True,
            unresolved=True,
            domain_active=self._domain_active(),
            reason=reason,
        )
        self._increment("unknown_outcomes")
        self._control.fail(reason)
        raise NativeJobUnresolved("Native job outcome or ownership is unresolved")

    def _project_acquisition(self, page):
        from uuid import UUID

        from ._native_job_lifecycle import _detach_claim

        if len(page.items) > 1:
            raise ValueError("One-slot acquisition returned excess work")
        detached = _detach_claim(page.items[0], self._material) if page.items else None
        cursor = None if page.next_cursor is None else UUID(int=page.next_cursor.int)
        return detached, page.visited, cursor, page.pass_exhausted

    def acquire(self, request, /):
        from ._native_job_lifecycle import UnsupportedJobProfile
        from .native_contracts import JobSourcePhase, WorkerReason
        from .persistence.models import JobAcquireRequest

        self._require_started()
        if request != self._request or request.limit != 1:
            raise ValueError("Acquisition must match the validated one-slot request")
        self._reservation = self._control.reserve_acquisition(self)
        self._publish(phase=JobSourcePhase.ACQUIRING, slot_occupied=True)
        failed = refused = False
        projected = None
        try:
            self._material.reserve()
            logical = JobAcquireRequest(
                capabilities=request.capabilities,
                limit=1,
                lease_seconds=self._config.lease_seconds,
                scan_after=self._cursor,
                discovery_budget=request.discovery_budget,
            )
            self._publish(native_in_flight=True)
            self._data.begin(self._check_reserved)
            try:
                projected = self._data.acquire(
                    logical,
                    budget=self._config.max_acquire_page_payload_bytes,
                    project=self._project_acquisition,
                    check=self._check_reserved,
                )
            except UnsupportedJobProfile:
                refused = True
            if refused:
                self._data.rollback(self._check_reserved)
                self._data.finish_root()
            else:
                self._detached = projected[0]
                self._data.commit(self._check_reserved)
                self._data.finish_root()
        except BaseException:
            failed = True
        self._publish(native_in_flight=False)
        if failed:
            projected = None
            self._unknown(WorkerReason.OUTCOME_UNKNOWN)
        if refused:
            self._material.release(known=True, quiescent=True)
            self._control.refuse_acquisition(
                self._reservation, reason=WorkerReason.PROFILE_UNSUPPORTED
            )
            self._reservation = None
            self._publish(
                phase=JobSourcePhase.FAILED,
                slot_occupied=False,
                admission_closed=True,
                reason=WorkerReason.PROFILE_UNSUPPORTED,
            )
            return ()
        detached, visited, cursor, exhausted = projected
        projected = None
        self._cursor = None if exhausted else cursor
        self._increment("acquisition_pages")
        self._publish(scan_exhausted=exhausted, scan_progress=visited > 0)
        if detached is None:
            self._material.release(known=True, quiescent=True)
            self._control.publish_acquisition(self._reservation, None)
            self._reservation = None
            self._publish(phase=JobSourcePhase.IDLE, slot_occupied=False)
            return ()
        self._work = _issue_work(self)
        self._fence = detached.fence
        self._control.publish_acquisition(self._reservation, self._work)
        self._reservation = None
        self._publish(phase=JobSourcePhase.CLAIMED)
        return (self._work,)

    def _check_data(self):
        from .native_contracts import NativeAdmissionKind

        self._check_domain()
        self._control.require_admission(self, kind=NativeAdmissionKind.ADMITTED_EXECUTION)

    @staticmethod
    def _fence_parameters(fence):
        return (
            fence.work_id,
            fence.token,
            fence.ownership_revision,
            fence.cycle,
            fence.expected_attempt,
        )

    def _copy_guard(self, value):
        from uuid import UUID

        from modkit_events.persistence.models import GuardRef

        return GuardRef(
            guard_id=UUID(int=value.guard_id.int),
            work_id=UUID(int=value.work_id.int),
            root_xid=value.root_xid,
            token=UUID(int=value.token.int),
            ownership_revision=value.ownership_revision,
            cycle=value.cycle,
            expected_attempt=value.expected_attempt,
        )

    def _require_work(self, work):
        if not _owns_work(work, self) or work is not self._work:
            raise ValueError("Not the exact current source work")

    def cancel(self, work, /) -> None:
        self._require_work(work)
        with self._lock:
            self._cancelled = True
        self.request_stop()

    def execute(self, work, /) -> None:
        from dataclasses import replace
        from time import monotonic
        from uuid import uuid4

        from ._native_job_lifecycle import _make_context
        from .native_contracts import JobSourcePhase, WorkerReason

        self._require_started()
        self._require_work(work)
        if self._cancelled:
            self._unknown(WorkerReason.DRAIN_TIMEOUT)
        failed = False
        result = None
        try:
            self._check_data()
            self._publish(phase=JobSourcePhase.DISPATCHING, native_in_flight=True)
            self._dispatch_id = uuid4()
            self._data.begin(self._check_data)
            attempt = self._data.statement(
                "E06",
                self._fence_parameters(self._fence)
                + (
                    self._dispatch_id,
                    self._detached.effect_id,
                    self._detached.request_evidence,
                    None,
                ),
                expected=(self._fence,),
                capacity=1323,
                result_capacity=28,
                project=lambda value: value,
                check=self._check_data,
            )
            self._data.commit(self._check_data)
            self._data.finish_root()
            self._dispatch_committed = True
            self._fence = replace(self._fence, expected_attempt=attempt)
            self._control.activate(work, self._fence)
            self._data.begin(self._check_data)
            xid = self._data.statement(
                "E14",
                (),
                expected=(),
                capacity=184,
                result_capacity=36,
                project=lambda value: value,
                check=self._check_data,
            )
            self._guard = self._data.statement(
                "E08",
                self._fence_parameters(self._fence),
                expected=(self._fence,),
                capacity=920,
                result_capacity=648,
                project=self._copy_guard,
                check=self._check_data,
            )
            if self._guard.root_xid != xid:
                raise RuntimeError("Business root identity mismatch")
            self._context = _make_context(self._detached, attempt, self._material)
            registration = self._registry.get(
                self._context.command_type, self._context.schema_version
            )
            self._publish(phase=JobSourcePhase.RUNNING, native_in_flight=False)
            succeeded, result = _invoke_application(
                self._application,
                registration.handler,
                self._data.connection,
                xid,
                self._context,
                self._material,
            )
            self._publish(phase=JobSourcePhase.SETTLING)
            token = self._control.close_renewal(work)
            quiet = self._control.await_renewal_quiescent(
                token, deadline_monotonic=monotonic() + self._control.settings.drain_timeout_seconds
            )
            if not (quiet.quiescent and quiet.outcome_known and quiet.domain_active):
                raise RuntimeError("Renewal ownership is unresolved")
            self._check_data()  # Includes the actual canonical Events domain.
            self._publish(native_in_flight=True)
            if succeeded:
                guard = self._guard
                parameters = tuple(getattr(guard, name) for name in guard.__dataclass_fields__)
                self._data.statement(
                    "E10",
                    parameters + (result,),
                    expected=(guard,),
                    capacity=self._config.max_result_bytes + 1281,
                    result_capacity=28,
                    project=lambda value: None,
                    check=self._check_data,
                )
                self._data.commit(self._check_data)
                self._increment("confirmed_succeeded")
                self._data.finish_root()
            else:
                self._data.rollback(self._check_data, strict=True)
                self._data.begin(self._check_data)
                self._data.statement(
                    "E11",
                    self._fence_parameters(self._fence)
                    + (xid, "failed", None, "db_local_application_failure", b"db-local-v1"),
                    expected=(self._fence,),
                    capacity=2952,
                    result_capacity=28,
                    project=lambda value: None,
                    check=self._check_data,
                    failure_binding=(self._data.failed_root, self._data.rollback_receipt),
                )
                self._data.commit(self._check_data)
                self._increment("confirmed_failed")
                self._data.finish_root()
                self._data.finish_failed_root()
        except BaseException:
            failed = True
        self._publish(native_in_flight=False)
        if failed:
            result = None
            self._unknown(WorkerReason.OUTCOME_UNKNOWN)
        result = None
        # Control's source-owned fence reference is cleared while its source
        # envelope remains paid. The source then drops its final graph aliases.
        self._control.retire_work(work)
        guard = parameters = registration = token = quiet = xid = attempt = None
        self._context = self._guard = self._fence = self._detached = self._dispatch_id = None
        self._work = None
        self._dispatch_committed = False
        self._material.release(known=True, quiescent=True)
        self._publish(phase=JobSourcePhase.IDLE, slot_occupied=False)

    def startup(self, request, /) -> None:
        self._control.admit_startup(self)

        from ._native_job_lifecycle import _NativeLane
        from .handlers import HandlerKind
        from .native_contracts import JobSourcePhase, WorkerReason
        from .native_setup import _adopt_resources, _resources_adopted, _validate_resources

        with self._lock:
            if self._startup_called:
                raise RuntimeError("Native source startup is once-only")
            self._startup_called = True
        self._publish(phase=JobSourcePhase.STARTING)
        rejected = False
        try:
            checked = self._registry.validate_acquisition(request)
            if checked.limit != 1 or any(
                self._registry.get(c.command_type, c.schema_version).kind is not HandlerKind.SYNC
                for c in checked.capabilities
            ):
                raise ValueError("Only one-slot synchronous acquisition is supported")
            _validate_application_profile(self._application, checked)
            _validate_resources(self._resources, config=self._config, source=self)
        except BaseException:
            rejected = True
        if rejected:
            self._publish(
                phase=JobSourcePhase.FAILED,
                admission_closed=True,
                reason=WorkerReason.STARTUP_REJECTED,
            )
            raise ValueError("Native source startup preflight rejected")
        self._request = checked
        failed = False
        try:
            self._adoption_attempted = True
            _adopt_resources(self._resources, self)
            if not _resources_adopted(self._resources, self):
                raise RuntimeError("Resource adoption is unresolved")
            self._publish(resources_adopted=True, native_in_flight=True)
            self._data = _NativeLane(self._resources.data_connection, self._resources.data_ledger)
            self._renewal = _NativeLane(
                self._resources.renewal_connection, self._resources.renewal_ledger
            )
            for lane in (self._data, self._renewal):
                lane.attach(self._check_domain)
                lane.begin(self._check_domain)
                lane.readiness(self._config.readiness, self._check_domain)
                lane.commit(self._check_domain)
                lane.finish_root()
        except BaseException:
            failed = True
        self._publish(native_in_flight=False)
        if failed:
            self._unknown(WorkerReason.STARTUP_UNKNOWN)
        self._started = True
        self._publish(
            phase=JobSourcePhase.IDLE,
            startup_verified=True,
            domain_active=self._domain_active(),
            admission_closed=self._stopped,
        )

    def _check_renewal(self):
        from .native_contracts import NativeAdmissionKind

        self._check_domain()
        self._control.require_admission(self, kind=NativeAdmissionKind.RENEWAL)

    def renew(self, work, fence, /) -> None:
        from .native_contracts import WorkerReason

        self._require_started()
        self._require_work(work)
        if (
            not self._dispatch_committed
            or fence is not self._fence
            or fence.expected_attempt != self._detached.fence.expected_attempt + 1
        ):
            raise ValueError("Renewal requires the exact committed dispatched fence")
        failed = False
        self._publish(renewal_in_flight=True)
        try:
            self._renewal.begin(self._check_renewal)
            self._renewal.statement(
                "E05",
                self._fence_parameters(fence) + (self._config.lease_seconds,),
                expected=(fence,),
                capacity=952,
                result_capacity=48,
                project=lambda value: None,
                check=self._check_renewal,
            )
            self._renewal.commit(self._check_renewal)
            self._increment("renewal_commits")
            self._renewal.finish_root()
        except BaseException:
            failed = True
        self._publish(renewal_in_flight=False)
        if failed:
            self._unknown(WorkerReason.RENEWAL_FAILED)

    def shutdown(self) -> None:
        from .native_contracts import JobSourcePhase, WorkerReason
        from .native_setup import _resources_adopted

        self.request_stop()
        state = self.snapshot()
        if (
            state.unresolved
            or self._work is not None
            or self._reservation is not None
            or state.native_in_flight
            or state.renewal_in_flight
        ):
            self._publish(
                admission_closed=True,
                cleanup_complete=False,
                unresolved=True,
                reason=state.reason or WorkerReason.OUTCOME_UNKNOWN,
            )
            return
        adopted = self._adoption_attempted and _resources_adopted(self._resources, self)
        failed = False
        if adopted:
            try:
                self._check_domain()
                for lane in (self._data, self._renewal):
                    if lane is None:
                        raise RuntimeError("Partial native ownership remains")
                    lane.close(self._check_domain)
            except BaseException:
                failed = True
        if failed:
            self._publish(
                phase=JobSourcePhase.FAILED,
                unresolved=True,
                cleanup_complete=False,
                reason=WorkerReason.CONTROL_FAILED,
            )
            self._control.fail(WorkerReason.CONTROL_FAILED)
            return
        self._publish(
            phase=JobSourcePhase.STOPPED,
            cleanup_complete=True,
            admission_closed=True,
            startup_verified=False,
        )
