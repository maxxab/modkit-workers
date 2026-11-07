"""Internal built-in job scope over neutral SQL transition requirements."""
from modkit_events.persistence.transitions import _WORK_RULES, _rule

_ADMISSION_RULES = (
    _rule("submit_runnable", "W01", "new", "queued", "job_kind_full_identity_binding_material_atomic_halves_supported_int4", "null"),
    _rule("submit_blocked", "W01", "new", "blocked_schema", "job_kind_full_identity_binding_material_atomic_halves_wide_version", "null"),
)
# W05 executes the neutral claim requirements in the same SQL statement as the
# full job-half observation; it does not create a second execution state machine.
_ACQUIRE_RULE = _rule("acquire_jobs", "W05", "queued|retry_waiting", "claimed",
    "neutral_claim_and_complete_consistent_job_half_single_snapshot", "null")

__all__ = ()
