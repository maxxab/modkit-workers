"""Internal built-in job scope over neutral SQL transition requirements."""
from modkit_events.persistence.transitions import _WORK_RULES as _WORK_RULES
from modkit_events.persistence.transitions import _rule

_ADMISSION_RULES = (
    _rule("submit_runnable", "W01", "new", "queued", "job_kind_full_identity_binding_material_atomic_halves_supported_int4", "null"),
    _rule("submit_blocked", "W01", "new", "blocked_schema", "job_kind_full_identity_binding_material_atomic_halves_wide_version", "null"),
)
# W05 executes the neutral claim requirements in the same SQL statement as the
# full job-half observation. Retained E04 postimages are composed with a fresh
# material snapshot under held locks, not an E15 reread or another state machine.
_ACQUIRE_RULE = _rule("acquire_jobs", "W05", "queued|retry_waiting", "claimed",
    "neutral_claim_retained_postimage_and_locked_consistent_job_half", "null")

__all__ = ()
