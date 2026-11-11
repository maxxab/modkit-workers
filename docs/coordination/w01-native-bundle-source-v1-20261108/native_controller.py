"""Pure lifecycle and record checks. No Docker, process or cleanup adapter.

Caller-owned state and independent expected pins are trust inputs, not discovered
or persisted here. Passing a syntactic record is never execution authorization.
A future operational adapter must establish authority and durable single-use state.
"""
import hashlib
import json
import math
import re

SHA = re.compile(r"[0-9a-f]{64}")
ATTEMPT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}")
IDENTITY = {"cid", "image", "artifact_sha256", "invocation_sha256", "attempt_id"}
ACTIONS = ["create", "stage", "verify", "execute", "observe", "dispose"]
NEXT = {"NEW": ("create", "CREATED"), "CREATED": ("stage", "STAGED"),
        "STAGED": ("verify", "VERIFIED"), "VERIFIED": ("execute", "EXECUTED"),
        "EXECUTED": ("observe", "OBSERVED"), "OBSERVED": ("dispose", "DISPOSED"),
        "HELD": ("reconcile", "RECONCILED")}


class Rejected(ValueError):
    """Fixed lifecycle-contract rejection code."""


def pin(value):
    try:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise Rejected("invalid_record") from exc
    return hashlib.sha256(data).hexdigest()


def require_identity(value):
    if type(value) is not dict or set(value) != IDENTITY:
        raise Rejected("identity_schema")
    for key in ("cid", "artifact_sha256", "invocation_sha256"):
        if type(value[key]) is not str or not SHA.fullmatch(value[key]):
            raise Rejected("identity_pin")
    if type(value["image"]) is not str or not value["image"].startswith("sha256:") or not SHA.fullmatch(value["image"][7:]):
        raise Rejected("immutable_image")
    if type(value["attempt_id"]) is not str or not ATTEMPT.fullmatch(value["attempt_id"]):
        raise Rejected("attempt_identity")


def check_binding(actual, expected, excluded):
    require_identity(actual)
    require_identity(expected)
    if actual != expected:
        raise Rejected("identity_drift")
    if type(excluded) is not list or not 1 <= len(excluded) <= 32:
        raise Rejected("exclusion_inventory")
    if any(type(cid) is not str or not SHA.fullmatch(cid) for cid in excluded):
        raise Rejected("exclusion_shape")
    if len(set(excluded)) != len(excluded) or actual["cid"] in excluded:
        raise Rejected("excluded_target")


def advance(state, event):
    try:
        if type(state) is not str or state not in NEXT:
            raise Rejected("terminal_or_unknown_state")
        if type(event) is not dict or set(event) != {
            "schema", "action", "from_state", "identity", "expected_identity",
            "excluded_cids", "receipt", "expected_receipt_sha256",
        }:
            raise Rejected("event_schema")
        if type(event["schema"]) is not int or event["schema"] != 1:
            raise Rejected("event_version")
        action, next_state = NEXT[state]
        if event["action"] != action or event["from_state"] != state:
            raise Rejected("event_order")
        check_binding(event["identity"], event["expected_identity"], event["excluded_cids"])
        expected = {"schema": 1, "action": action, "from_state": state,
                    "identity": event["identity"], "outcome": "CONFIRMED"}
        receipt = event["receipt"]
        # Canonical hash comparison preserves bool/int distinctions and exact schemas.
        if type(receipt) is not dict or pin(receipt) != pin(expected):
            raise Rejected("unconfirmed_receipt")
        if type(event["expected_receipt_sha256"]) is not str or not SHA.fullmatch(event["expected_receipt_sha256"]) or pin(receipt) != event["expected_receipt_sha256"]:
            raise Rejected("receipt_pin")
        return next_state
    except Rejected:
        return "HELD"


def number(value):
    return (type(value) in {int, float} and -(2**53) <= value <= 2**53
            and math.isfinite(value))


def validate_release(record, expected, now):
    if type(expected) is not dict or set(expected) != {"identity", "excluded_cids", "release_sha256", "scope"}:
        raise Rejected("expected_scope")
    if type(record) is not dict or set(record) != {
        "schema", "scope", "identity", "not_before", "expires_at", "actions",
        "max_invocations", "execution_authorized",
    }:
        raise Rejected("release_schema")
    if type(record["schema"]) is not int or record["schema"] != 1:
        raise Rejected("release_version")
    if record["scope"] != "NO_DB_SMOKE_ONLY" or expected["scope"] != "NO_DB_SMOKE_ONLY":
        raise Rejected("release_scope")
    check_binding(record["identity"], expected["identity"], expected["excluded_cids"])
    if record["actions"] != ACTIONS or type(record["actions"]) is not list:
        raise Rejected("release_actions")
    if type(record["max_invocations"]) is not int or record["max_invocations"] != 1:
        raise Rejected("invocation_budget")
    if record["execution_authorized"] is not False:
        raise Rejected("stage_b_no_execution_authority")
    start, end = record["not_before"], record["expires_at"]
    if not all(number(v) for v in (start, end, now)) or not start <= now < end or not 0 < end - start <= 300:
        raise Rejected("release_time")
    if type(expected["release_sha256"]) is not str or not SHA.fullmatch(expected["release_sha256"]) or pin(record) != expected["release_sha256"]:
        raise Rejected("release_pin")
