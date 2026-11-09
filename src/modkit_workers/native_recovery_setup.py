"""Deferred Events-owned preflight and once-only recovery resource provenance.

No imports here load optional drivers. Missing supported native APIs fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from threading import Lock

from .native_recovery_contracts import NativeRecoveryResources, _validate_config


class RecoveryUnavailable(RuntimeError):
    """Required supported native E13 integration is unavailable."""


class NativeRecoveryConfigurationReceipt:
    __slots__ = ("_stamp",)

    def __new__(cls):
        raise TypeError("Recovery configuration receipts are issued internally")

    def __init_subclass__(cls, **kwargs):
        raise TypeError("Recovery configuration receipts are sealed")

    def __setattr__(self, name, value):
        raise AttributeError("Recovery configuration receipts are immutable")

    def __delattr__(self, name):
        raise AttributeError("Recovery configuration receipts are immutable")

    def __copy__(self):
        raise TypeError("Recovery configuration receipts cannot be copied")

    def __deepcopy__(self, memo):
        raise TypeError("Recovery configuration receipts cannot be copied")

    def __reduce_ex__(self, protocol):
        raise TypeError("Recovery configuration receipts cannot be serialized")


@dataclass(slots=True)
class _Configuration:
    receipt: NativeRecoveryConfigurationReceipt
    stamp: object
    domain: object
    limits: tuple
    association: tuple | None = None


_lock = Lock()
_attempted = False
_configuration = None


def _profile_api():
    try:
        from modkit_events.persistence import recovery_profile
    except ImportError:
        raise RecoveryUnavailable("Supported recovery profile unavailable") from None
    return recovery_profile


def _limits_type():
    try:
        from modkit_events.persistence.managed_lifecycle import LifecycleLimits
    except ImportError:
        raise RecoveryUnavailable("Supported lifecycle dependency unavailable") from None
    return LifecycleLimits


def _load_native_capability():
    profile = _profile_api()
    try:
        from modkit_events.persistence import native_execution
    except ImportError:
        raise RecoveryUnavailable("Supported native dependency unavailable") from None
    if (not callable(getattr(native_execution, "prepare_recovery", None))
            or not callable(getattr(native_execution, "prepare_readiness", None))
            or not callable(getattr(profile, "recovery_requirements", None))
            or not callable(getattr(profile, "verify_recovery_driver", None))):
        raise RecoveryUnavailable("Supported native E13 issuer unavailable")
    # Cooperative pinned package compatibility, not semantic attestation by name.
    # Supported bootstrap separately verifies the exact requirements/driver.
    return None


_LIMIT_FIELDS = (
    "retained_cells", "admitted_live", "checkouts", "roots", "roots_per_checkout",
    "executions", "preparations", "preparations_per_execution", "prepare_bytes",
    "prepare_bytes_per_execution", "results", "results_per_ticket", "result_bytes",
    "result_bytes_per_ticket", "cleanup_bundles", "cleanup_bytes", "construction_slots",
)


def _validate_limits(limits):
    limit_type = _limits_type()
    if (type(limits) is not limit_type
            or tuple(item.name for item in fields(limit_type)) != _LIMIT_FIELDS):
        raise ValueError("Expected exact complete lifecycle limits")
    checked = tuple((name, getattr(limits, name)) for name in _LIMIT_FIELDS)
    if any(type(value) is not int or value <= 0 for _, value in checked):
        raise ValueError("Invalid lifecycle limits")
    for child, parent in (("admitted_live", "retained_cells"),
            ("checkouts", "retained_cells"), ("roots_per_checkout", "roots"),
            ("preparations_per_execution", "preparations"),
            ("prepare_bytes_per_execution", "prepare_bytes"),
            ("results_per_ticket", "results"), ("result_bytes_per_ticket", "result_bytes")):
        if getattr(limits, child) > getattr(limits, parent):
            raise ValueError("Invalid lifecycle limit relationship")
    return checked


def _checked_profile(config, limits):
    _validate_config(config)
    _validate_limits(limits)
    api = _profile_api()
    requirements = api.recovery_requirements(readiness=config.readiness)
    if type(requirements) is not api.RecoveryRequirements:
        raise RecoveryUnavailable("Unsupported recovery requirements")
    limit_type = _limits_type()
    minimum = requirements.lifecycle_minimum
    if (type(limits) is not limit_type or type(minimum) is not limit_type
            or tuple(item.name for item in fields(limit_type)) != _LIMIT_FIELDS):
        raise ValueError("Expected exact complete lifecycle limits")
    for name in _LIMIT_FIELDS:
        value, required = getattr(limits, name), getattr(minimum, name)
        if type(value) is not int or type(required) is not int or not 0 < required <= value:
            raise ValueError("Insufficient recovery lifecycle limits")
    verified = api.verify_recovery_driver(requirements)
    if (type(verified) is not api.VerifiedRecoveryProfile
            or verified.requirements is not requirements):
        raise RecoveryUnavailable("Unsupported verified recovery profile")
    return requirements


def preflight_native_recovery(config, *, limits) -> None:
    """Pure validation, full17 minima, then explicitly deferred driver check.

    Repeatable before setup only. A descriptive result never grants authority.
    """
    _validate_config(config)
    with _lock:
        if _attempted:
            raise RuntimeError("Recovery setup was already attempted")
    _checked_profile(config, limits)


def _recheck_profile(config, resources):
    _validate_config(config)
    with _lock:
        checked = _record(resources).limits
    limits = _limits_type()(**dict(checked))
    return _checked_profile(config, limits)


def configure_native_recovery_profile(*, limits) -> NativeRecoveryConfigurationReceipt:
    """Never consumes the once-only attempt when required capability is absent.

    Caller must first perform preflight_native_recovery(config, limits=limits); this limits-only
    API cannot validate a namespace it was not given. No positive path is enabled
    until the accepted native integration supplies its contract.
    """
    checked = _validate_limits(limits)
    copied = _limits_type()(**dict(checked))
    _load_native_capability()
    from modkit_events.persistence.ledger import ExecutionLedger
    from modkit_events.persistence.managed_lifecycle import (
        configure_managed_registry,
    )
    from modkit_events.persistence.resource_registry import resource_domain

    global _attempted, _configuration
    with _lock:
        if _attempted:
            raise RuntimeError("Recovery configuration is once-only")
        _attempted = True
    configure_managed_registry(limits=copied, execution_ledger=ExecutionLedger())
    receipt = object.__new__(NativeRecoveryConfigurationReceipt)
    stamp = object()
    object.__setattr__(receipt, "_stamp", stamp)
    with _lock:
        _configuration = _Configuration(receipt, stamp, resource_domain(), checked)
    return receipt


def _record(resources):
    from modkit_events.persistence.resource_registry import resource_domain

    record = _configuration
    receipt = resources.configuration
    if (record is None or type(receipt) is not NativeRecoveryConfigurationReceipt
            or receipt is not record.receipt or receipt._stamp is not record.stamp
            or resource_domain() is not record.domain or record.domain.stopped):
        raise ValueError("Invalid current recovery provenance")
    return record


def _resource_facts(resources):
    from modkit_events.persistence.ledger import ExecutionLedger
    from modkit_events.persistence.native_sync import ManagedConnection

    if type(resources) is not NativeRecoveryResources:
        raise ValueError("Expected exact recovery resource carrier")
    connection, ledger = resources.connection, resources.ledger
    if (type(connection) is not ManagedConnection or type(ledger) is not ExecutionLedger
            or connection.closed or connection.autocommit
            or connection.pgconn.transaction_status != 0
            or connection.pgconn.pipeline_status != 0 or ledger.uncertainty.present):
        raise ValueError("Recovery requires clean fresh native resources")


def _validate_resources(resources, owner):
    _resource_facts(resources)
    with _lock:
        if owner is None or _record(resources).association is not None:
            raise ValueError("Recovery resources cannot be adopted")


def _adopt_resources(resources, owner):
    _resource_facts(resources)
    with _lock:
        record = _record(resources)
        if owner is None or record.association is not None:
            raise ValueError("Recovery resources cannot be adopted")
        record.association = (resources, owner, resources.configuration,
                              resources.connection, resources.ledger)
