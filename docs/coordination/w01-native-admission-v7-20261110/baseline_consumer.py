"""Select one reviewed historical reconciliation baseline, without any external effects.

Callers supply bytes using opaque original evidence identifiers. This module never
opens a path or executes supplied source. The fixed review anchor deliberately
cannot be replaced by a caller's self-rehashed manifest. Selection grants no
runtime authority and asserts no present resource absence.
"""

import json
from dataclasses import dataclass
from hashlib import sha256

BASE = "/home/faris/modkit-local-20261106/"
EVENTS = BASE + "resume-events-20261109/fence-reconciliation-v1/"
WORKERS = BASE + "resume-workers-20261109/"
REVIEW = WORKERS + "fence-reconciliation-v1-result-review.json"
PINS = EVENTS + "pins.json"
POSTFLIGHT = EVENTS + "postflight-verification.json"
EXECUTION_REVIEW = WORKERS + "fence-reconciliation-v1-execution-review.json"
RESULT = EVENTS + "attempt/reconciliation-result.json"
TERMINAL = EVENTS + "attempt/runtime-slot-terminal.json"
AUTHORITY = EVENTS + "authority.json"
CONTRACT = WORKERS + "native-r4-reconciliation-baseline-v1/contract.json"
ANCHOR = "8e5b622e460ba564029d0e786b22fce8666879e280835d0efb1a26949dd09d75"
SCOPE = "REDIS8_CURRENT_ABSENCE_RECONCILIATION_V1"
FILE_LIMIT = 2 * 1024 * 1024
TOTAL_LIMIT = 8 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class VerifiedBaseline:
    """Historical selection only; never an authority token or live observation."""

    scope: str
    attempt_id: str
    targets: tuple[str, str]
    history: tuple[str, str, str]
    execution_window_utc: tuple[str, str]
    result_sha256: str
    terminal_sha256: str
    review_sha256: str
    verified_file_count: int
    native_authorized: bool = False
    live_absence_asserted: bool = False


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _document(data: bytes) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result

    def nonfinite(value):
        raise ValueError("Non-finite JSON value: " + value)

    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=nonfinite)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ValueError("Invalid evidence JSON") from error
    _require(type(value) is dict, "Expected evidence object")
    return value


def _merge(target: dict[str, str], additions: dict[str, str]) -> None:
    for key, digest in additions.items():
        _require(key not in target or target[key] == digest, "Conflicting evidence pin")
        target[key] = digest


def verify_baseline(bundle: dict[str, bytes]) -> VerifiedBaseline:
    """Verify the exact accepted 48-file closure; refuse all other input.

    This is intentionally not a generic validator for future attempts. A changed
    chain needs its own independent review and a separately reviewed selector.
    A future runtime caller still needs fresh slot/profile/QA/authority gates.
    It must invoke verification, not trust a caller-constructed receipt.
    """
    _require(type(bundle) is dict, "Expected a plain bytes dictionary")
    # Own the mapping before hashing/parsing; accepted values are immutable bytes.
    bundle = bundle.copy()
    _require(len(bundle) == 48, "Expected the complete exact 48-file closure")
    total = 0
    for key, data in bundle.items():
        _require(type(key) is str and type(data) is bytes, "Expected string identifiers and bytes")
        _require(len(data) <= FILE_LIMIT, "Oversized evidence")
        total += len(data)
    _require(total <= TOTAL_LIMIT, "Oversized evidence bundle")
    _require(
        REVIEW in bundle and sha256(bundle[REVIEW]).hexdigest() == ANCHOR,
        "Independent actual-review anchor mismatch",
    )
    review = _document(bundle[REVIEW])
    _require(
        review["scope"] == SCOPE
        and review["decision"] == "ACCEPT_ACTUAL_TYPED_RECONCILIATION_BASELINE_ONLY",
        "Wrong reviewed scope or decision",
    )
    _require(
        review["native_authorized"] is False and review["docker_mutations_authorized"] is False,
        "Unexpected authority",
    )

    expected = {
        REVIEW: ANCHOR,
        PINS: review["source_pins_sha256"],
        POSTFLIGHT: review["postflight_sha256"],
        EXECUTION_REVIEW: review["execution_review_sha256"],
    }
    _require(
        PINS in bundle and sha256(bundle[PINS]).hexdigest() == expected[PINS],
        "Source pin manifest mismatch",
    )
    pins = _document(bundle[PINS])
    _require(pins["scope"] == SCOPE and len(pins["files"]) == 32, "Wrong source closure")
    _merge(expected, pins["files"])
    _merge(expected, review["files"])
    _require(len(expected) == 48 and set(bundle) == set(expected), "Evidence closure mismatch")
    for key, digest in expected.items():
        _require(sha256(bundle[key]).hexdigest() == digest, "Evidence hash mismatch: " + key)
    for key, field in [
        (RESULT, "result_sha256"),
        (TERMINAL, "terminal_sha256"),
        (AUTHORITY, "authority_sha256"),
        (CONTRACT, "contract_sha256"),
    ]:
        _require(expected[key] == review[field], "Reviewed evidence link mismatch")

    result = _document(bundle[RESULT])
    terminal = _document(bundle[TERMINAL])
    postflight = _document(bundle[POSTFLIGHT])
    authority = _document(bundle[AUTHORITY])
    execution_review = _document(bundle[EXECUTION_REVIEW])
    _require(
        result["scope"] == authority["scope"] == execution_review["scope"] == SCOPE,
        "Typed scope mismatch",
    )
    _require(
        result["status"] == "CURRENT_RESOURCE_ABSENCE_CONFIRMED_HISTORICAL_OUTCOMES_UNKNOWN",
        "Wrong historical baseline status",
    )
    _require(
        result["original_create_outcome"]
        == result["original_removal_outcome"]
        == "UNKNOWN_UNCHANGED"
        and result["cause_of_current_absence"] == "UNKNOWN"
        and result["original_grant"] == "CONSUMED_UNCHANGED_NOT_REUSED",
        "Historical rewrite",
    )
    _require(
        result["native_authorized"] is False
        and result["docker_mutations"] is False
        and authority["native_authorized"] is False
        and authority["docker_mutations_authorized"] is False
        and authority["old_grant_reuse_authorized"] is False,
        "Runtime authority prohibited",
    )
    _require(
        result["attempt_id"]
        == terminal["attempt_id"]
        == postflight["attempt_id"]
        == review["attempt_id"],
        "Attempt mismatch",
    )
    _require(
        result["targets"] == terminal["targets"] == authority["targets"] == review["targets"],
        "Targets mismatch",
    )
    _require(
        terminal["status"] == "TERMINAL_RECONCILED"
        and terminal["disposition"] == "FAILED_DISCARDED_WITH_EXPLICIT_AUTHORITY"
        and terminal["evidence_path"] == RESULT
        and terminal["evidence_sha256"] == review["result_sha256"],
        "Wrong terminal binding",
    )
    _require(
        result["source_pins_sha256"]
        == terminal["pins_sha256"]
        == execution_review["pins_sha256"]
        == expected[PINS],
        "Source binding mismatch",
    )
    _require(
        result["provenance"]["bound_input_hashes"] == pins["files"]
        and postflight["files"] == review["files"],
        "Closure cross-binding mismatch",
    )
    predecessor = review["predecessor_sha256"]
    for name in ["preflight-predecessor.json", "runtime-slot-predecessor.json"]:
        _require(expected[EVENTS + "attempt/" + name] == predecessor, "Backup binding mismatch")
    _require(
        result["predecessor_sha256"] == terminal["predecessor_sha256"] == predecessor,
        "Predecessor mismatch",
    )
    _require(
        [row["exit_code"] for row in result["commands"]] == [1, 1, 0]
        and all(row["outcome"] == "RETURNED_BOUNDED" for row in result["commands"]),
        "Incomplete observations",
    )
    return VerifiedBaseline(
        scope=SCOPE,
        attempt_id=review["attempt_id"],
        targets=tuple(review["targets"]),
        history=(
            result["original_create_outcome"],
            result["original_removal_outcome"],
            result["cause_of_current_absence"],
        ),
        execution_window_utc=tuple(review["execution_window_utc"]),
        result_sha256=review["result_sha256"],
        terminal_sha256=review["terminal_sha256"],
        review_sha256=ANCHOR,
        verified_file_count=len(expected),
    )
