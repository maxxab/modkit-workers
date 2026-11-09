"""Source-owned logical material and native lifecycle helpers.

Logical occurrence reservations are not process RSS or application allocation bounds.
Native drivers are imported only when an explicit native operation is requested.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import TYPE_CHECKING, cast
from uuid import UUID

from .context import JobContext

if TYPE_CHECKING:
    from modkit_events.persistence.scope import Scope


class MaterialCapacityError(RuntimeError):
    """A logical reservation or its release proof is unavailable."""


class UnsupportedJobProfile(ValueError):
    """The selected job does not fit this explicit DB-local profile."""


def _source_capacity(payload_limit: int, result_limit: int) -> int:
    for value in (payload_limit, result_limit):
        if type(value) is not int or not 1 <= value <= 1048576:
            raise ValueError("Invalid material bound")
    graph = 1024 * (1 + payload_limit // 9) + 8 * payload_limit
    return 4 * graph + 16 * 33 * payload_limit + 262144 + 4 * result_limit + 4096


class _MaterialLease:
    __slots__ = ("capacity", "payload_limit", "result_limit", "depth_limit", "reserved")

    def __init__(self, *, capacity, payload_limit, result_limit, depth_limit):
        _source_capacity(payload_limit, result_limit)
        if type(capacity) is not int or capacity <= 0:
            raise ValueError("Invalid material capacity")
        if type(depth_limit) is not int or not 1 <= depth_limit <= 32:
            raise ValueError("Invalid material depth")
        self.capacity, self.payload_limit = capacity, payload_limit
        self.result_limit, self.depth_limit = result_limit, depth_limit
        self.reserved = False

    def reserve(self):
        if self.reserved or self.capacity < _source_capacity(self.payload_limit, self.result_limit):
            raise MaterialCapacityError("Source material reservation unavailable")
        self.reserved = True

    def require(self):
        if not self.reserved:
            raise MaterialCapacityError("Source material is not reserved")

    def release(self, *, known: bool, quiescent: bool):
        if known is not True or quiescent is not True:
            raise MaterialCapacityError("Material ownership remains unresolved")
        self.reserved = False


@dataclass(frozen=True, slots=True, repr=False)
class _DetachedJob:
    work_id: str
    command_type: str
    schema_version: int
    scope: Scope
    semantic_input: bytes
    fence: object
    deadline: datetime | None
    effect_id: bytes
    request_evidence: bytes


def _bounded_payload(raw: bytes, lease: _MaterialLease):
    from modkit_events.persistence.bindings import parse_canonical_json

    lease.require()
    if type(raw) is not bytes or len(raw) > lease.payload_limit:
        raise UnsupportedJobProfile("Unsupported job material")
    value = parse_canonical_json(raw)
    if not isinstance(value, Mapping):
        raise UnsupportedJobProfile("Unsupported job material")

    # Canonical parser has already enforced <=32 depth and finite total nodes.
    # Traverse a bounded frozen graph, never application Mapping implementations.
    def check(item, depth):
        if depth > lease.depth_limit:
            raise UnsupportedJobProfile("Unsupported job depth")
        if isinstance(item, Mapping):
            for child in item.values():
                check(child, depth + 1)
        elif type(item) is tuple:
            for child in item:
                check(child, depth + 1)

    check(value, 0)
    return value


def _detach_claim(claim, lease: _MaterialLease) -> _DetachedJob:
    from modkit_events.persistence.models import CleanupPolicy, Fence, MaterialState
    from modkit_events.persistence.scope import decode_scope_fields

    from .persistence.observations import JobClaimObservation

    lease.require()
    if type(claim) is not JobClaimObservation:
        raise UnsupportedJobProfile("Unsupported acquired job")
    record = claim.record
    payload, work = record.payload, record.work
    if (
        payload.material_state is not MaterialState.ABSENT
        or any(
            v is not None
            for v in (
                payload.sidecar,
                payload.reference,
                payload.codec,
                payload.key_version,
                payload.expires_at,
            )
        )
        or payload.recovery_metadata != b""
        or payload.cleanup_policy is not CleanupPolicy.RETAIN
    ):
        raise UnsupportedJobProfile("Protected job material is unsupported")
    if (
        type(payload.semantic_input) is not bytes
        or len(payload.semantic_input) > lease.payload_limit
    ):
        raise UnsupportedJobProfile("Unsupported job material")
    semantic = memoryview(payload.semantic_input).tobytes()
    _bounded_payload(semantic, lease)
    old = claim.fence
    fence = Fence(
        work_id=UUID(int=old.work_id.int),
        token=UUID(int=old.token.int),
        ownership_revision=old.ownership_revision,
        cycle=old.cycle,
        expected_attempt=old.expected_attempt,
    )
    scope = decode_scope_fields(work.scope_application, work.scope_tenant, work.scope_owner)
    effect = b"modkit-db-local-effect-v1:" + sha256(
        fence.work_id.bytes + fence.cycle.to_bytes(4, "big")
    ).hexdigest().encode("ascii")
    evidence = b"modkit-db-local-request-v1:" + sha256(work.intent_evidence).hexdigest().encode(
        "ascii"
    )
    return _DetachedJob(
        str(fence.work_id),
        work.command_type.decode("utf-8"),
        # Exact JobClaimObservation already validates a non-null runnable version.
        cast("int", work.runnable_version),
        scope,
        semantic,
        fence,
        work.deadline,
        effect,
        evidence,
    )


def _make_context(detached: _DetachedJob, attempt: int, lease: _MaterialLease) -> JobContext:
    lease.require()
    return JobContext(
        work_id=detached.work_id,
        command_type=detached.command_type,
        schema_version=detached.schema_version,
        scope=detached.scope,
        payload=_bounded_payload(detached.semantic_input, lease),
        attempt=attempt,
        deadline=detached.deadline,
    )


def _accept_result(value, lease: _MaterialLease) -> bytes:
    lease.require()
    if type(value) is not bytes or len(value) > lease.result_limit:
        import inspect

        if inspect.iscoroutine(value) or inspect.isgenerator(value):
            value.close()
        raise UnsupportedJobProfile("Unsupported job result")
    return memoryview(value).tobytes()


def _native_api():
    from modkit_events.persistence import bindings, catalog, managed_lifecycle, native_execution

    return managed_lifecycle, native_execution, bindings, catalog


class _NativeLane:
    """One fixed checkout and its exact native handles, never a connection factory.

    A failed operation deliberately leaves its current handles retained. Callers
    must not interpret an exception flag as proof of rollback or quiescence.
    """

    def __init__(self, connection, ledger):
        self.connection, self.ledger = connection, ledger
        self.execution = self.checkout = self.root = None
        self.preparation = self.ticket = self.result = None
        self.failed_root = self.rollback_receipt = None
        self.cleanup = self.close_receipt = None
        self.closed = False

    def attach(self, check):
        check()
        managed, _, _, _ = _native_api()
        self.execution = managed.reserve_execution(self.ledger)
        check()
        self.checkout = managed.attach_native(
            self.connection, self.execution, execution_ledger=self.ledger
        )

    def begin(self, check):
        check()
        if self.root is not None:
            raise RuntimeError("A native root is already retained")
        self.root = self.checkout.start_root(execution_ledger=self.ledger)

    def _consume(self, *, result_capacity, project, check):
        managed, native, _, _ = _native_api()
        check()
        self.ticket = managed.admit(self.root, self.preparation, execution_ledger=self.ledger)
        if result_capacity is None:
            result_capacity = managed.result_capacity(self.ticket, execution_ledger=self.ledger)
        self.result = managed.reserve_result(
            self.ticket, result_capacity, execution_ledger=self.ledger
        )
        check()
        native.execute(self.ticket, self.result, execution_ledger=self.ledger)
        value = managed.read_result(self.result, execution_ledger=self.ledger)
        refused = False
        answer = None
        try:
            answer = project(value)
        except UnsupportedJobProfile:
            refused = True
        value = None
        managed.release_result(self.result, execution_ledger=self.ledger)
        self.result = None
        managed.release_ticket(self.ticket, execution_ledger=self.ledger)
        self.ticket = None
        managed.release_preparation(self.preparation, execution_ledger=self.ledger)
        self.preparation = None
        if refused:
            raise UnsupportedJobProfile("Unsupported acquired material")
        return answer

    def statement(
        self,
        key,
        parameters,
        *,
        expected,
        capacity,
        result_capacity,
        project,
        check,
        failure_binding=None,
    ):
        managed, native, bindings, catalog = _native_api()
        check()
        self.preparation = native.prepare(
            self.execution,
            catalog.get_statement(key),
            parameters,
            execution_ledger=self.ledger,
            context=bindings.ReturnContext(expected=expected, readiness=None),
            capacity=capacity,
        )
        if failure_binding is not None:
            failed_root, receipt = failure_binding
            managed.bind_failure_settlement(
                self.preparation, failed_root, receipt, execution_ledger=self.ledger
            )
        return self._consume(result_capacity=result_capacity, project=project, check=check)

    def commit(self, check):
        managed, _, _, _ = _native_api()
        check()
        receipt = self.root.commit(execution_ledger=self.ledger)
        outcome = managed.acknowledge_commit_result(receipt, execution_ledger=self.ledger)
        if outcome is not managed.CommitOutcome.COMMITTED:
            raise RuntimeError("Native commit did not establish committed outcome")

    def rollback(self, check, *, strict=False):
        managed, _, _, _ = _native_api()
        check()
        receipt = self.root.rollback(execution_ledger=self.ledger, confirm_failure=strict)
        managed.acknowledge_root_end(receipt, execution_ledger=self.ledger)
        if strict:
            self.failed_root, self.root = self.root, None
            self.rollback_receipt = receipt
        return receipt

    def finish_root(self):
        managed, _, _, _ = _native_api()
        managed.release_root(self.root, execution_ledger=self.ledger)
        self.root = None

    def finish_failed_root(self):
        managed, _, _, _ = _native_api()
        managed.release_root(self.failed_root, execution_ledger=self.ledger)
        self.failed_root = self.rollback_receipt = None

    def acquire(self, request, *, budget, project, check):
        from .persistence.native_store import prepare_acquire

        check()
        self.preparation = prepare_acquire(
            self.execution, request, execution_ledger=self.ledger, max_page_payload_bytes=budget
        )
        return self._consume(result_capacity=None, project=project, check=check)

    def readiness(self, expectation, check):
        _, native, _, _ = _native_api()
        check()
        self.preparation = native.prepare_readiness(
            self.execution, "workers", expectation, execution_ledger=self.ledger, capacity=4096
        )
        self._consume(
            result_capacity=native.READINESS_RESULT_CAPACITY,
            project=lambda value: None,
            check=check,
        )

    def close(self, check):
        if self.closed:
            return
        check()
        if (
            self.root is not None
            or self.failed_root is not None
            or self.preparation is not None
            or self.ticket is not None
            or self.result is not None
            or self.checkout is None
        ):
            raise RuntimeError("Native resources are not proven quiescent")
        managed, _, _, _ = _native_api()
        managed.retire(self.checkout, execution_ledger=self.ledger)
        intent = managed.prepare_cleanup(self.checkout, execution_ledger=self.ledger)
        self.cleanup = managed.reserve_cleanup(intent, 4096, execution_ledger=self.ledger)
        permit = managed.pin_cleanup(self.cleanup, execution_ledger=self.ledger)
        check()
        self.close_receipt = permit.close(execution_ledger=self.ledger)
        managed.acknowledge_physical_close(self.close_receipt, execution_ledger=self.ledger)
        managed.release_cleanup(self.cleanup, execution_ledger=self.ledger)
        self.cleanup = None
        managed.detach_terminal(self.checkout, execution_ledger=self.ledger)
        self.checkout = None
        managed.dispose_execution(self.execution, execution_ledger=self.ledger)
        self.execution = None
        self.closed = True
