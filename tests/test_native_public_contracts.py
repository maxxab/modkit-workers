"""Shared public contracts without optional-driver import or product placeholders."""

from dataclasses import FrozenInstanceError
from importlib import import_module, util

import pytest


def contracts():
    name = "modkit_workers.native_contracts"
    assert util.find_spec(name) is not None, "real shared native contracts are absent"
    return import_module(name)


def pins():
    from modkit_events.persistence.bindings import ReadinessExpectation
    from modkit_events.persistence.observations import SchemaStatus

    return ReadinessExpectation(
        components=tuple(
            SchemaStatus(
                component=component,
                version=1,
                migration_digest=b"x" * 32,
                catalog_contract_id="modkit-pg-ab-2",
                scope_format_id="MKSC-1",
                intent_format_id="MKPF-1",
            )
            for component in ("events", "workers")
        )
    )


def config_values():
    return dict(
        readiness=pins(),
        lease_seconds=30,
        max_acquire_page_payload_bytes=2**32,
        max_payload_bytes=1048576,
        max_payload_depth=32,
        max_result_bytes=1048576,
        source_material_bytes=1073741824,
    )


def test_shared_types_reexport_private_identity_without_new_definitions():
    public = contracts()
    private = import_module("modkit_workers._native_control_contracts")
    for name in (
        "NativeWorkerSettings",
        "WorkerReason",
        "WorkerState",
        "JobSourcePhase",
        "JobSourceSnapshot",
        "WorkerSnapshot",
        "RenewalQuiescence",
        "NativeAdmissionKind",
    ):
        assert getattr(public, name) is getattr(private, name)


def test_config_accepts_full_canonical_domain_and_preserves_exact_field():
    c = contracts()
    value = c.NativeJobConfig(**config_values())
    assert value.source_material_bytes == 1073741824
    assert value.lease_seconds == 30.0 and type(value.lease_seconds) is float
    with pytest.raises(FrozenInstanceError):
        value.max_payload_bytes = 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_payload_bytes", 1048577),
        ("max_result_bytes", 0),
        ("max_acquire_page_payload_bytes", 2**32 + 1),
        ("max_payload_depth", 33),
        ("lease_seconds", True),
        ("lease_seconds", float("inf")),
        ("lease_seconds", 3601),
        ("source_material_bytes", 1068883967),
    ],
)
def test_config_rejects_invalid_or_insufficient_capacity(field, value):
    c = contracts()
    values = config_values()
    values[field] = value
    with pytest.raises(ValueError):
        c.NativeJobConfig(**values)


def test_smaller_source_profile_uses_exact_accepted_formula():
    c = contracts()
    values = config_values()
    values.update(max_payload_bytes=100, max_result_bytes=50)
    expected = 4 * (1024 * (1 + 100 // 9) + 8 * 100) + 16 * 33 * 100 + 262144 + 4 * 50 + 4096
    values["source_material_bytes"] = expected
    c.NativeJobConfig(**values)
    values["source_material_bytes"] -= 1
    with pytest.raises(ValueError):
        c.NativeJobConfig(**values)


def test_resource_carrier_is_inert_frozen_and_has_no_adoption_side_effect():
    c = contracts()
    values = dict(
        configuration=object(),
        data_connection=object(),
        renewal_connection=object(),
        data_ledger=object(),
        renewal_ledger=object(),
    )
    resources = c.NativeJobResources(**values)
    assert resources.configuration is values["configuration"]
    with pytest.raises(FrozenInstanceError):
        resources.data_connection = object()
    assert "data_connection" not in repr(resources)
