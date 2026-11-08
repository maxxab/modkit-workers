"""Synthetic records only: no Docker or process adapter is imported."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).parent


def module():
    path = HERE / "native_controller.py"
    assert path.is_file(), "Stage B controller is missing"
    spec = importlib.util.spec_from_file_location("stageb_controller", path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def identity():
    return {"cid": "a" * 64, "image": "sha256:" + "b" * 64, "artifact_sha256": "c" * 64,
            "invocation_sha256": "d" * 64, "attempt_id": "synthetic-one"}


def event(state, action):
    binding = identity()
    receipt = {"action": action, "from_state": state, "identity": binding,
               "outcome": "CONFIRMED", "schema": 1}
    return {"schema": 1, "action": action, "from_state": state, "identity": copy.deepcopy(binding),
            "expected_identity": binding, "excluded_cids": ["e" * 64],
            "receipt": receipt, "expected_receipt_sha256": digest(receipt)}


def release_fixture():
    record = {"schema": 1, "scope": "NO_DB_SMOKE_ONLY", "identity": identity(),
              "not_before": 100.0, "expires_at": 110.0,
              "actions": ["create", "stage", "verify", "execute", "observe", "dispose"],
              "max_invocations": 1, "execution_authorized": False}
    expected = {"identity": identity(), "excluded_cids": ["e" * 64],
                "release_sha256": digest(record), "scope": "NO_DB_SMOKE_ONLY"}
    return record, expected


def test_all_legal_stages():
    m = module()
    state = "NEW"
    for action, next_state in [("create", "CREATED"), ("stage", "STAGED"), ("verify", "VERIFIED"),
                               ("execute", "EXECUTED"), ("observe", "OBSERVED"), ("dispose", "DISPOSED")]:
        state = m.advance(state, event(state, action))
        assert state == next_state


@pytest.mark.parametrize("state,action", [("NEW", "execute"), ("CREATED", "create"), ("STAGED", "dispose"),
                                        ("VERIFIED", "stage"), ("EXECUTED", "execute"), ("OBSERVED", "create"),
                                        ("DISPOSED", "create"), ("RECONCILED", "execute")])
def test_skipped_repeated_or_terminal_stages_hold(state, action):
    m = module()
    assert m.advance(state, event(state, action)) == "HELD"


@pytest.mark.parametrize("change", [
    lambda e: e.update(schema=True),
    lambda e: e.update(extra=True),
    lambda e: e.update(action="timeout"),
    lambda e: e.update(from_state="VERIFIED"),
    lambda e: e["identity"].update(cid="f" * 64),
    lambda e: e["identity"].update(image="sha256:" + "f" * 64),
    lambda e: e["identity"].update(artifact_sha256="f" * 64),
    lambda e: e["identity"].update(invocation_sha256="f" * 64),
    lambda e: e["identity"].update(attempt_id="other"),
    lambda e: e["identity"].pop("cid"),
    lambda e: e.update(expected_receipt_sha256="f" * 64),
    lambda e: e["receipt"].update(outcome="UNKNOWN"),
    lambda e: e["receipt"].update(outcome=0),
    lambda e: e.update(excluded_cids=["a" * 64]),
    lambda e: e.update(excluded_cids=[]),
])
def test_uncertainty_and_binding_drift_hold(change):
    m = module()
    e = event("NEW", "create")
    change(e)
    assert m.advance("NEW", e) == "HELD"


def test_reconciliation_requires_exact_pinned_identity_receipt():
    m = module()
    e = event("HELD", "reconcile")
    assert m.advance("HELD", e) == "RECONCILED"
    e["receipt"]["identity"]["cid"] = "f" * 64
    assert m.advance("HELD", e) == "HELD"


@pytest.mark.parametrize("action", ["create", "stage", "verify", "execute", "observe", "dispose", "retry"])
def test_held_has_no_automatic_retry_or_cleanup(action):
    m = module()
    assert m.advance("HELD", event("HELD", action)) == "HELD"


def test_lease_expiry_never_changes_ownership_state():
    m = module()
    assert m.advance("HELD", {"action": "lease_expired"}) == "HELD"


def test_valid_release_contract_is_not_execution_authority():
    m = module()
    record, expected = release_fixture()
    assert m.validate_release(record, expected, 105.0) is None


@pytest.mark.parametrize("change", [
    lambda r: r.update(schema=True),
    lambda r: r.update(extra=True),
    lambda r: r.update(scope="DB"),
    lambda r: r.update(max_invocations=2),
    lambda r: r.update(max_invocations=True),
    lambda r: r.update(execution_authorized=True),
    lambda r: r.update(expires_at=100.0),
    lambda r: r.update(not_before=110.0),
    lambda r: r.update(expires_at=float("inf")),
    lambda r: r.update(not_before=True),
    lambda r: r["actions"].append("retry"),
    lambda r: r["actions"].pop(),
    lambda r: r["identity"].update(cid="e" * 64),
    lambda r: r["identity"].update(image="postgres:latest"),
    lambda r: r["identity"].update(artifact_sha256="no"),
    lambda r: r["identity"].update(attempt_id="../other"),
])
def test_invalid_release_rejects_even_if_repinned(change):
    m = module()
    record, expected = release_fixture()
    change(record)
    expected["identity"] = copy.deepcopy(record["identity"])
    try:
        expected["release_sha256"] = digest(record)
    except ValueError:
        pass
    with pytest.raises(m.Rejected):
        m.validate_release(record, expected, 105.0)


@pytest.mark.parametrize("now", [99.0, 110.0, 111.0, float("nan"), float("inf"), True, "105"])
def test_time_boundaries_reject(now):
    m = module()
    record, expected = release_fixture()
    with pytest.raises(m.Rejected):
        m.validate_release(record, expected, now)


def test_release_pin_and_expected_scope_are_required():
    m = module()
    record, expected = release_fixture()
    expected["release_sha256"] = "f" * 64
    with pytest.raises(m.Rejected):
        m.validate_release(record, expected, 105.0)
    expected["release_sha256"] = digest(record)
    expected["scope"] = "ANY"
    with pytest.raises(m.Rejected):
        m.validate_release(record, expected, 105.0)


@pytest.mark.parametrize("field", ["now", "not_before", "expires_at"])
def test_huge_integer_time_rejected_without_overflow(field):
    m = module()
    record, expected = release_fixture()
    now = 10**1000 if field == "now" else 105.0
    if field != "now":
        record[field] = 10**1000
        expected["release_sha256"] = digest(record)
    with pytest.raises(m.Rejected):
        m.validate_release(record, expected, now)
