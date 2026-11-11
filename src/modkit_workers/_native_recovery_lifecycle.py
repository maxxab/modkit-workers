"""Pure bounded owner retention; this module never opens a native connection."""

from __future__ import annotations

from uuid import UUID

from .native_recovery_contracts import (
    UINT64_MAX,
    PendingRecoverySummary,
    RecoveryMaterialState,
    RecoverySnapshot,
    _integer,
    required_recovery_source_material_bytes,
)


class _RecoveryMaterialLease:
    __slots__ = ("capacity", "required", "state", "busy")

    def __init__(self, capacity):
        required = required_recovery_source_material_bytes()
        _integer(capacity, required, UINT64_MAX)
        self.capacity, self.required = capacity, required
        self.state = RecoveryMaterialState.CONFIGURED
        self.busy = False

    def admit(self):
        if self.state is not RecoveryMaterialState.CONFIGURED or self.busy:
            raise RuntimeError("Recovery material cannot be readmitted")
        self.state = RecoveryMaterialState.ADMITTED

    def require(self, *, projection=False):
        if self.state not in (RecoveryMaterialState.ADMITTED, RecoveryMaterialState.HELD):
            raise RuntimeError("Recovery material is not admitted")
        if projection and self.state is not RecoveryMaterialState.ADMITTED:
            raise RuntimeError("Recovery material is held")

    def enter(self, *, projection=False):
        self.require(projection=projection)
        if self.busy:
            raise RuntimeError("Recovery material builder cannot reenter")
        self.busy = True

    def leave(self):
        if not self.busy:
            raise RuntimeError("No recovery material builder")
        self.busy = False

    def hold(self):
        self.require()
        self.state = RecoveryMaterialState.HELD

    def release(self, *, known, quiescent):
        self.require()
        if known is not True or quiescent is not True or self.busy:
            raise RuntimeError("Recovery material disposition is unresolved")
        self.state = RecoveryMaterialState.RELEASED


def _snapshot_values(s):
    return (
        s.phase,
        s.reason,
        s.latest_page_outcome,
        s.ready,
        s.startup_verified,
        s.domain_active,
        s.stop_requested,
        s.admission_closed,
        s.native_in_flight,
        s.cleanup_unresolved,
        s.unresolved,
        s.clean_stop,
        s.has_committed_page,
        s.last_committed_raw_cursor,
        s.next_scan_after,
        s.last_committed_pass_exhausted,
        s.last_committed_visited,
        s.last_committed_queued,
        s.last_committed_expired,
        s.last_committed_failed,
        s.last_committed_held,
        s.committed_pages,
        s.committed_sweeps,
        s.committed_visited,
        s.committed_queued,
        s.committed_expired,
        s.committed_failed,
        s.committed_held,
        s.progress_sequence,
        s.progress_age_ms,
        s.counters_saturated,
    )


def _build_snapshot(values):
    if type(values) is not tuple or len(values) != 31:
        raise ValueError("Invalid scalar snapshot draft")
    # Fixed slots, no kwargs/dict/dataclasses.replace or application callback.
    result = object.__new__(RecoverySnapshot)
    for index, name in enumerate(RecoverySnapshot.__slots__):
        object.__setattr__(result, name, values[index])
    return result


def _project_page(page, *, incoming, discovery_budget):
    """Private consumption of native-validated output, never a public decoder.

    The actual native adapter must enforce exact complete native page identity.
    Unit tests patch the private lane, not a supported production adapter.
    """
    visited, cursor, exhausted, items = (
        page.visited,
        page.next_cursor,
        page.pass_exhausted,
        page.items,
    )
    _integer(visited, 0, discovery_budget)
    if type(exhausted) is not bool or type(items) is not tuple or len(items) > 1:
        raise ValueError("Invalid recovery page")
    if cursor is not None and type(cursor) is not UUID:
        raise ValueError("Invalid raw recovery cursor")
    raw = None if cursor is None else cursor.int
    if raw is not None:
        _integer(raw, 0, 2**128 - 1)
    if len(items) > visited:
        raise ValueError("Invalid recovery cardinality")
    if visited == 0:
        if items or raw != incoming or not exhausted:
            raise ValueError("Invalid empty recovery page")
    elif raw is None or incoming is not None and raw <= incoming:
        raise ValueError("Recovery cursor did not advance")
    if exhausted:
        if visited >= discovery_budget or items:
            raise ValueError("Recovery exhausted at a cap")
    elif visited != discovery_budget and len(items) != 1:
        raise ValueError("Unexplained recovery termination")
    state = None if not items else items[0].state
    if state is not None and (
        type(state) is not str or state not in ("queued", "expired", "failed", "held")
    ):
        raise ValueError("Invalid recovery postimage state")
    draft = (
        visited,
        raw,
        exhausted,
        int(state == "queued"),
        int(state == "expired"),
        int(state == "failed"),
        int(state == "held"),
    )
    result = object.__new__(PendingRecoverySummary)
    for index, name in enumerate(PendingRecoverySummary.__slots__):
        object.__setattr__(result, name, draft[index])
    return result


def _recovery_api():
    from modkit_events.persistence import managed_lifecycle, native_execution

    return managed_lifecycle, native_execution


class _NativeRecoveryLane:
    """Single serialized lane. Exceptions retain handles and prohibit replacement.

    Result graphs are Events-paid until scalar projection returns and its local
    alias is dropped. No native failure triggers rollback, refund or retry here.
    """

    __slots__ = (
        "connection",
        "ledger",
        "requirements",
        "execution",
        "checkout",
        "root",
        "preparation",
        "ticket",
        "result",
        "cleanup",
        "close_receipt",
        "closed",
        "failed",
        "root_committed",
    )

    def __init__(self, resources, requirements):
        self.connection, self.ledger = resources.connection, resources.ledger
        self.requirements = requirements
        self.execution = self.checkout = self.root = None
        self.preparation = self.ticket = self.result = None
        self.cleanup = self.close_receipt = None
        self.closed = self.failed = self.root_committed = False

    def _live(self):
        if self.failed or self.closed:
            raise RuntimeError("Recovery lane is not available")

    def attach(self):
        self._live()
        if self.execution is not None or self.checkout is not None:
            raise RuntimeError("Recovery lane attachment is once-only")
        managed, _ = _recovery_api()
        self.failed = True
        self.execution = managed.reserve_execution(self.ledger)
        self.checkout = managed.attach_native(
            self.connection, self.execution, execution_ledger=self.ledger
        )
        self.failed = False

    def begin(self):
        self._live()
        if self.root is not None or self.checkout is None:
            raise RuntimeError("Recovery root is not available")
        self.failed = True
        self.root = self.checkout.start_root(execution_ledger=self.ledger)
        self.root_committed = False
        self.failed = False

    def _consume(self, capacity, project):
        managed, native = _recovery_api()
        self.ticket = managed.admit(self.root, self.preparation, execution_ledger=self.ledger)
        self.result = managed.reserve_result(self.ticket, capacity, execution_ledger=self.ledger)
        native.execute(self.ticket, self.result, execution_ledger=self.ledger)
        value = managed.read_result(self.result, execution_ledger=self.ledger)
        try:
            if project is not None:
                if project(value) is not None:
                    raise ValueError("Recovery projection must not return material")
        finally:
            value = None
        managed.release_result(self.result, execution_ledger=self.ledger)
        self.result = None
        managed.release_ticket(self.ticket, execution_ledger=self.ledger)
        self.ticket = None
        managed.release_preparation(self.preparation, execution_ledger=self.ledger)
        self.preparation = None

    def startup(self, readiness):
        self.begin()
        _, native = _recovery_api()
        self.failed = True
        self.preparation = native.prepare_readiness(
            self.execution,
            "workers",
            readiness,
            execution_ledger=self.ledger,
            capacity=self.requirements.e33_preparation_min,
        )
        self._consume(self.requirements.e33_result_min, None)
        self.failed = False
        self.commit()
        self.finish_root()

    def scan(self, config, cursor, project):
        from modkit_events.persistence.observations import ScanPage, WorkObservation

        self._live()
        if self.root is None or self.preparation is not None:
            raise RuntimeError("Recovery scan has no sole root")
        _, native = _recovery_api()
        self.failed = True
        self.preparation = native.prepare_recovery(
            self.execution,
            execution_ledger=self.ledger,
            capacity=self.requirements.e13_preparation_min,
            namespace=config.namespace,
            kind="job",
            limit=1,
            scan_after=None if cursor is None else UUID(int=cursor),
            discovery_budget=config.discovery_budget,
        )
        cursor = None  # Caller scalar alias ends before result projection/publication.

        def project_validated(value):
            # Native execute/read_result already enforce complete canonical Work
            # validation and retained request coupling. No generic SQL decoder.
            if (
                type(value) is not ScanPage
                or type(value.items) is not tuple
                or len(value.items) > 1
            ):
                raise ValueError("Expected exact native recovery page")
            for item in value.items:
                if type(item) is not WorkObservation:
                    raise ValueError("Expected exact native recovery postimage")
            return project(value)

        self._consume(self.requirements.e13_result_min, project_validated)
        self.failed = False

    def commit(self):
        self._live()
        if self.root is None or self.preparation is not None or self.result is not None:
            raise RuntimeError("Recovery commit is not quiescent")
        managed, _ = _recovery_api()
        self.failed = True
        receipt = self.root.commit(execution_ledger=self.ledger)
        outcome = managed.acknowledge_commit_result(receipt, execution_ledger=self.ledger)
        if outcome is not managed.CommitOutcome.COMMITTED:
            raise RuntimeError("Recovery commit remains unknown")
        self.root_committed = True
        self.failed = False

    def finish_root(self):
        self._live()
        if self.root is None or not self.root_committed:
            raise RuntimeError("Recovery root outcome is not acknowledged")
        managed, _ = _recovery_api()
        self.failed = True
        managed.release_root(self.root, execution_ledger=self.ledger)
        self.root = None
        self.root_committed = False
        self.failed = False

    def close(self):
        self._live()
        if (
            self.root is not None
            or self.preparation is not None
            or self.ticket is not None
            or self.result is not None
            or self.checkout is None
        ):
            raise RuntimeError("Recovery resources are not known quiescent")
        managed, _ = _recovery_api()
        self.failed = True
        managed.retire(self.checkout, execution_ledger=self.ledger)
        intent = managed.prepare_cleanup(self.checkout, execution_ledger=self.ledger)
        self.cleanup = managed.reserve_cleanup(intent, 4096, execution_ledger=self.ledger)
        permit = managed.pin_cleanup(self.cleanup, execution_ledger=self.ledger)
        self.close_receipt = permit.close(execution_ledger=self.ledger)
        managed.acknowledge_physical_close(self.close_receipt, execution_ledger=self.ledger)
        managed.release_cleanup(self.cleanup, execution_ledger=self.ledger)
        self.cleanup = None
        managed.detach_terminal(self.checkout, execution_ledger=self.ledger)
        self.checkout = None
        managed.dispose_execution(self.execution, execution_ledger=self.ledger)
        self.execution = None
        self.closed = True
        self.failed = False
