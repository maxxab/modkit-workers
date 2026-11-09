"""Only in-process host control. No child process or service launch."""

from threading import Event

import pytest
from test_native_recovery_contracts import config, module, profile_double
from test_native_recovery_owner import owner, page


def test_invalid_limits_precede_dependency_checks(monkeypatch):
    setup = module("native_recovery_setup")
    monkeypatch.setattr(setup, "_profile_api", lambda: pytest.fail("profile lookup"))
    with pytest.raises(ValueError, match="exact complete lifecycle limits"):
        setup.preflight_native_recovery(config(), limits=object())
    assert not setup._attempted


def test_unavailable_profile_does_not_consume_setup(monkeypatch):
    setup, limits, events = profile_double(monkeypatch)

    def unavailable():
        raise setup.RecoveryUnavailable("Supported recovery profile unavailable")

    monkeypatch.setattr(setup, "_profile_api", unavailable)
    with pytest.raises(setup.RecoveryUnavailable, match="profile unavailable"):
        setup.preflight_native_recovery(config(), limits=limits)
    assert not setup._attempted
    assert events == []


def test_wrong_namespace_precedes_deferred_import(monkeypatch):
    setup = module("native_recovery_setup")
    value = config()
    object.__setattr__(value, "namespace", b"app")
    monkeypatch.setattr(setup, "_load_native_capability", lambda: pytest.fail("native import"))
    with pytest.raises(ValueError, match="namespace"):
        setup.preflight_native_recovery(value, limits=object())
    assert not setup._attempted


def test_host_exit_codes_truthful(monkeypatch):
    m = module("native_recovery")
    o, lane, app, events = owner(monkeypatch, [page(visited=0, cursor=None, exhausted=True)])
    assert m.run_recovery_host(o, stop_event=Event()) == 0
    o, lane, app, events = owner(
        monkeypatch, [page(visited=1, cursor=7, exhausted=False, state="held")]
    )
    lane.commit_unknown = True
    assert m.run_recovery_host(o, stop_event=Event()) == 70
