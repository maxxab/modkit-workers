"""Only in-process host control. No child process or service launch."""
from threading import Event

import pytest
from test_native_recovery_contracts import config, module
from test_native_recovery_owner import owner, page


def test_production_capability_is_unavailable_before_setup():
    setup = module("native_recovery_setup")
    with pytest.raises(setup.RecoveryUnavailable):
        setup.preflight_native_recovery(config(), limits=object())
    assert not setup._attempted


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
    o, lane, app, events = owner(monkeypatch, [page(visited=1, cursor=7, exhausted=False, state="held")])
    lane.commit_unknown = True
    assert m.run_recovery_host(o, stop_event=Event()) == 70
