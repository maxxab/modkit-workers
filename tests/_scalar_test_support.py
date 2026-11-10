"""Explicit test-only scalar-profile selection; never production admission."""

import platform
import sys
import sysconfig

import pytest


def declared_host(implementation, version, system, machine, disabled, debug, enabled):
    if implementation != "cpython":
        return False
    if version[:2] == (3, 12):
        return True
    return (
        version == (3, 13, 5, "final", 0)
        and system == "linux"
        and machine == "x86_64"
        and type(disabled) is int
        and disabled == 0
        and type(debug) is int
        and debug == 0
        and enabled is True
    )


def supported_host():
    return declared_host(
        sys.implementation.name,
        tuple(sys.version_info),
        sys.platform,
        platform.machine(),
        sysconfig.get_config_var("Py_GIL_DISABLED"),
        sysconfig.get_config_var("Py_DEBUG"),
        getattr(sys, "_is_gil_enabled", lambda: None)(),
    )


def pytest_addoption(parser):
    parser.addoption("--require-scalar-cases", action="store_true")


def pytest_configure(config):
    config._scalar_counts = (0, 0)
    config.addinivalue_line(
        "markers", "requires_scalar_profile: acceptance requires the declared real scalar host"
    )


def pytest_collection_modifyitems(config, items):
    acceptance = [item for item in items if item.get_closest_marker("requires_scalar_profile")]
    if config.getoption("--require-scalar-cases"):
        if not acceptance:
            raise pytest.UsageError("scalar acceptance cases are missing")
        if not any(
            item.name == "test_actual_host_scalar_acceptance_or_refusal"
            and not item.get_closest_marker("requires_scalar_profile")
            for item in items
        ):
            raise pytest.UsageError("mandatory actual-host scalar contract is missing")
    supported = supported_host()
    config._scalar_counts = (
        len(acceptance) if supported else 0,
        0 if supported else len(acceptance),
    )
    if not supported:
        items[:] = [
            item for item in items if not item.get_closest_marker("requires_scalar_profile")
        ]
        config.hook.pytest_deselected(items=acceptance)


def pytest_terminal_summary(terminalreporter):
    selected, deselected = terminalreporter.config._scalar_counts
    terminalreporter.write_line(
        f"Scalar host acceptance: {selected} selected, {deselected} explicitly deselected; "
        "portable/refusal cases remain selected. No native runtime qualification."
    )
