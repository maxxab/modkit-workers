"""Pure private contract tests; no native driver imports."""
from dataclasses import FrozenInstanceError
from importlib import import_module, util

import pytest


def contracts():
    name = "modkit_workers._native_control_contracts"
    assert util.find_spec(name) is not None, "private control contracts are not implemented"
    return import_module(name)


@pytest.mark.parametrize("value", [True, 0, -1, float("inf"), float("nan"), "1"])
def test_settings_reject_invalid_time(value):
    c = contracts()
    with pytest.raises(ValueError):
        c.NativeWorkerSettings(renewal_interval_seconds=value)


def test_contracts_are_immutable_and_health_defaults_fail_closed():
    c = contracts()
    settings = c.NativeWorkerSettings(renewal_interval_seconds=1)
    with pytest.raises(FrozenInstanceError):
        settings.poll_interval_seconds = 2
    source = c.JobSourceSnapshot()
    assert not source.startup_verified
    assert not source.cleanup_complete
    assert source.phase is c.JobSourcePhase.NEW
    assert c.RenewalQuiescence(False, False, False).quiescent is False


def test_quiescence_requires_exact_booleans():
    c = contracts()
    with pytest.raises(ValueError):
        c.RenewalQuiescence(1, False, False)

@pytest.mark.parametrize("fields", [
    {"confirmed_succeeded": -1}, {"renewal_commits": 2**64},
    {"slot_occupied": 1}, {"phase": "running"}, {"reason": "unknown"},
    {"last_progress_monotonic": float("nan")},
])
def test_source_snapshot_rejects_unbounded_or_malformed_observation(fields):
    c = contracts()
    with pytest.raises(ValueError):
        c.JobSourceSnapshot(**fields)
