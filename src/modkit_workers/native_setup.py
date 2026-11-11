"""Explicit once-only native configuration provenance and resource ownership.

No connection, SQL, attachment or adoption is performed on import. The sole
resource domain and every resource counter remain owned by Events.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from threading import Lock
from typing import TYPE_CHECKING, cast

from .native_contracts import NativeJobConfig, NativeJobResources

if TYPE_CHECKING:
    from modkit_events.persistence.managed_lifecycle import LifecycleLimits
    from modkit_events.persistence.resource_registry import ResourceDomain

__all__ = ["NativeJobConfigurationReceipt", "configure_native_job_profile"]


class NativeJobConfigurationReceipt:
    __slots__ = ("_stamp",)
    _stamp: object

    def __new__(cls):
        raise TypeError("Configuration receipts are issued internally")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("Configuration receipts cannot be subclassed")

    def __setattr__(self, name, value):
        raise AttributeError("Configuration receipts are immutable")

    def __delattr__(self, name):
        raise AttributeError("Configuration receipts are immutable")

    def __copy__(self):
        raise TypeError("Configuration receipts cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("Configuration receipts cannot be copied")

    def __reduce__(self):
        raise TypeError("Configuration receipts cannot be serialized")


@dataclass(slots=True)
class _Configuration:
    receipt: NativeJobConfigurationReceipt
    stamp: object
    domain: ResourceDomain
    limits: tuple[tuple[str, int], ...]
    association: tuple[NativeJobResources, object, tuple[object, ...]] | None = None


_lock = Lock()
_attempted = False
_configuration: _Configuration | None = None

# Accepted conservative full-family native vector. Source E remains scalable.
_MINIMUM_LIMITS = {
    "retained_cells": 2,
    "admitted_live": 2,
    "checkouts": 2,
    "roots": 3,
    "roots_per_checkout": 2,
    "executions": 2,
    "preparations": 2,
    "preparations_per_execution": 1,
    "prepare_bytes": 1049857,
    "prepare_bytes_per_execution": 1049857,
    "results": 2,
    "results_per_ticket": 1,
    "result_bytes": 44129507,
    "result_bytes_per_ticket": 44129507,
    "cleanup_bundles": 2,
    "cleanup_bytes": 8192,
    "construction_slots": 6,
}


def configure_native_job_profile(*, limits: LifecycleLimits) -> NativeJobConfigurationReceipt:
    from modkit_events.persistence.ledger import ExecutionLedger
    from modkit_events.persistence.managed_lifecycle import (
        LifecycleLimits,
        configure_managed_registry,
    )
    from modkit_events.persistence.resource_registry import resource_domain

    global _attempted, _configuration
    if type(limits) is not LifecycleLimits:
        raise ValueError("Expected exact LifecycleLimits")
    checked = tuple((item.name, getattr(limits, item.name)) for item in fields(LifecycleLimits))
    if any(type(value) is not int or value <= 0 for _, value in checked):
        raise ValueError("Invalid lifecycle limits")
    copied = LifecycleLimits(**dict(checked))
    with _lock:
        if _attempted:
            raise RuntimeError("Native job configuration is once-only")
        _attempted = True
    # A failed/uncertain call cannot be retried to manufacture provenance.
    configure_managed_registry(limits=copied, execution_ledger=ExecutionLedger())
    receipt = object.__new__(NativeJobConfigurationReceipt)
    stamp = object()
    object.__setattr__(receipt, "_stamp", stamp)
    record = _Configuration(receipt, stamp, resource_domain(), checked)
    with _lock:
        _configuration = record
    return receipt


def _record(configuration: NativeJobConfigurationReceipt) -> _Configuration:
    """Caller holds _lock. Provenance only, including after domain stop."""
    from modkit_events.persistence.resource_registry import resource_domain

    current = _configuration
    try:
        stamp = (
            configuration._stamp if type(configuration) is NativeJobConfigurationReceipt else None
        )
    except AttributeError:
        raise ValueError("Invalid native configuration receipt") from None
    if (
        type(configuration) is not NativeJobConfigurationReceipt
        or current is None
        or configuration is not current.receipt
        or stamp is not current.stamp
        or resource_domain() is not current.domain
    ):
        raise ValueError("Invalid native configuration receipt")
    return current


def _checked_limits(configuration: NativeJobConfigurationReceipt, /) -> LifecycleLimits:
    from modkit_events.persistence.managed_lifecycle import LifecycleLimits

    with _lock:
        checked = _record(configuration).limits
    return LifecycleLimits(**dict(checked))


def _native_connection_type():
    from modkit_events.persistence.native_sync import ManagedConnection

    return ManagedConnection


def _resource_identities(resources: NativeJobResources) -> tuple[object, ...]:
    return (
        resources.configuration,
        resources.data_connection,
        resources.renewal_connection,
        resources.data_ledger,
        resources.renewal_ledger,
    )


def _resource_facts(resources: NativeJobResources, source: object) -> None:
    """Supported current facts only; historical freshness is cooperative.

    Canonical reserve/attach after adoption enforces prior-use restrictions.
    No private Events ledger or resource-registry state is inspected here.
    """
    from modkit_events.persistence.ledger import ExecutionLedger

    if type(resources) is not NativeJobResources or source is None:
        raise ValueError("Expected exact resource carrier and source identity")
    connection_type = _native_connection_type()
    data, renewal = resources.data_connection, resources.renewal_connection
    first, second = resources.data_ledger, resources.renewal_ledger
    if (
        type(data) is not connection_type
        or type(renewal) is not connection_type
        or data is renewal
        or data.pgconn is renewal.pgconn
        or type(first) is not ExecutionLedger
        or type(second) is not ExecutionLedger
        or first is second
    ):
        raise ValueError("Expected distinct exact native resources")
    for connection in (data, renewal):
        if (
            connection.closed
            or connection.autocommit
            or connection.pgconn.transaction_status != 0
            or connection.pgconn.pipeline_status != 0
        ):
            raise ValueError("Native resources must be clean and idle")
    for ledger in (first, second):
        if ledger.uncertainty.present:
            raise ValueError("Native ledger has unresolved uncertainty")


def _association_matches(record: _Configuration, resources: NativeJobResources) -> bool:
    association = record.association
    if association is None:
        return False
    old_resources, _, identities = association
    if resources is not old_resources or any(
        current is not prior for current, prior in zip(_resource_identities(resources), identities)
    ):
        raise ValueError("Adopted carrier identities do not match")
    return True


def _validate_resources(
    resources: NativeJobResources,
    /,
    *,
    config: NativeJobConfig,
    source: object,
) -> None:
    if type(config) is not NativeJobConfig:
        raise ValueError("Expected exact NativeJobConfig")
    config.__post_init__()
    _resource_facts(resources, source)
    limits = _checked_limits(resources.configuration)
    if any(getattr(limits, name) < minimum for name, minimum in _MINIMUM_LIMITS.items()):
        raise ValueError("Configured native capacity is insufficient")
    with _lock:
        record = _record(resources.configuration)
        if record.domain.stopped or record.association is not None:
            raise RuntimeError("Native resources cannot be adopted")


def _adopt_resources(resources: NativeJobResources, source: object, /) -> None:
    _resource_facts(resources, source)
    identities = _resource_identities(resources)
    association = (resources, source, identities)
    with _lock:
        record = _record(resources.configuration)
        if record.domain.stopped or record.association is not None:
            raise RuntimeError("Native resources cannot be adopted")
        # Single publication is the ownership linearization point. No SQL.
        record.association = association


def _resources_adopted(resources: NativeJobResources, source: object, /) -> bool:
    if type(resources) is not NativeJobResources or source is None:
        raise ValueError("Expected exact resource carrier and source identity")
    with _lock:
        record = _record(resources.configuration)
        if not _association_matches(record, resources):
            return False
        # _association_matches proved non-null and exact carrier identities under _lock.
        return (
            cast("tuple[NativeJobResources, object, tuple[object, ...]]", record.association)[1]
            is source
        )
