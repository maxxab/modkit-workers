"""Portable host-profile refusal checks; no native resources or services."""

from types import SimpleNamespace

import pytest


def support():
    import _scalar_test_support

    return _scalar_test_support


@pytest.mark.parametrize(
    "version,system,machine,expected",
    [
        ((3, 12, 14, "final", 0), "win32", "AMD64", True),
        ((3, 13, 5, "final", 0), "linux", "x86_64", True),
        ((3, 13, 5, "final", 0), "darwin", "arm64", False),
        ((3, 13, 5, "final", 0), "win32", "AMD64", False),
        ((3, 13, 6, "final", 0), "linux", "x86_64", False),
        ((3, 14, 0, "final", 0), "linux", "x86_64", False),
    ],
)
def test_declared_host_scope(version, system, machine, expected):
    assert support().declared_host("cpython", version, system, machine, 0, 0, True) is expected


@pytest.mark.parametrize("disabled,debug,enabled", [(1, 0, False), (0, 1, True), (False, 0, True)])
def test_unknown_or_unqualified_build_is_not_accepted(disabled, debug, enabled):
    assert not support().declared_host(
        "cpython", (3, 13, 5, "final", 0), "linux", "x86_64", disabled, debug, enabled
    )


def test_deselection_is_per_test_and_preserves_refusal_checks(monkeypatch):
    helper = support()
    monkeypatch.setattr(helper, "supported_host", lambda: False)
    acceptance = SimpleNamespace(get_closest_marker=lambda name: True)
    refusal = SimpleNamespace(get_closest_marker=lambda name: None)
    reported = []
    config = SimpleNamespace(
        getoption=lambda name: False,
        hook=SimpleNamespace(pytest_deselected=lambda **kw: reported.extend(kw["items"])),
    )
    items = [acceptance, refusal]
    helper.pytest_collection_modifyitems(config, items)
    assert items == [refusal] and reported == [acceptance]


def test_supported_lane_requires_acceptance_cases(monkeypatch):
    helper = support()
    monkeypatch.setattr(helper, "supported_host", lambda: True)
    config = SimpleNamespace(getoption=lambda name: True)
    with pytest.raises(pytest.UsageError, match="scalar acceptance cases are missing"):
        helper.pytest_collection_modifyitems(config, [])


def test_supported_lane_keeps_acceptance_and_refusal(monkeypatch):
    helper = support()
    monkeypatch.setattr(helper, "supported_host", lambda: True)
    acceptance = SimpleNamespace(name="acceptance", get_closest_marker=lambda name: True)
    refusal = SimpleNamespace(
        name="test_actual_host_scalar_acceptance_or_refusal", get_closest_marker=lambda name: None
    )
    config = SimpleNamespace(getoption=lambda name: True)
    items = [acceptance, refusal]
    helper.pytest_collection_modifyitems(config, items)
    assert items == [acceptance, refusal] and config._scalar_counts == (1, 0)
    with pytest.raises(pytest.UsageError, match="mandatory actual-host scalar contract is missing"):
        helper.pytest_collection_modifyitems(config, [acceptance])


def test_actual_host_scalar_acceptance_or_refusal(monkeypatch):
    from modkit_workers import native_recovery_contracts as contracts
    from modkit_workers import native_recovery_setup as setup

    monkeypatch.setattr(setup, "_profile_api", lambda: pytest.fail("driver/profile effect"))
    if support().supported_host():
        assert contracts.required_recovery_source_material_bytes() == 6212
    else:
        with pytest.raises(ValueError, match="^Unsupported recovery scalar profile$"):
            contracts.required_recovery_source_material_bytes()
        with pytest.raises(ValueError, match="^Unsupported recovery scalar profile$"):
            contracts.NativeRecoveryConfig(
                namespace=b"jobs", readiness=object(), source_material_bytes=6212
            )
