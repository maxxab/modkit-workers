"""Worker-only composition of real neutral catalog metadata."""
from modkit_events.persistence import catalog as e

from modkit_workers.persistence import catalog as w


def test_workers_use_neutral_metadata_and_complete_rows():
    for i in range(1, 6):
        s = w.get_statement(f"W{i:02}")
        assert type(s) is e.StatementSpec
        assert s is w.get_statement(s.key)
    assert len(w.get_statement("W02").result.columns) == 71
    assert len(w.get_statement("W04").result.columns) == 72
    assert len(w.get_statement("W05").result.columns) == 75
    assert w.get_statement("W04").result.cardinality is e.CardinalityKind.FIND_TWO
    assert w.get_statement("W05").result.cardinality is e.CardinalityKind.SCAN
    assert tuple(p.name for p in w.get_statement("W05").parameters) == (
        "namespace", "command_types", "schema_versions", "limit", "lease_seconds", "scan_after", "discovery_budget")
    assert w.get_statement("W02").result.columns[:56] == e.get_statement("E15").result.columns
    assert w.get_statement("W01").parameters[:20] == e.get_statement("E03").parameters[:20]
    assert w.get_statement("W01").parameters[20].name == "material_state"
    assert w.get_statement("W01").parameters[-1].name == "projection_metadata"


def test_all_39_have_unique_columns_and_allowlisted_keys():
    specs = tuple(e.get_statement(f"E{i:02}") for i in range(1, 35)) + tuple(w.get_statement(f"W{i:02}") for i in range(1, 6))
    assert len({s.key for s in specs}) == 39
    for s in specs:
        assert len({p.name for p in s.parameters}) == len(s.parameters)
        assert len({col.name for col in s.result.columns}) == len(s.result.columns)
        assert s.contract_id == "modkit-pg-ab-2"
    for key in ("E01", "W00", "W06", "submit", None):
        try:
            w.get_statement(key)
        except (TypeError, ValueError):
            pass
        else:
            raise AssertionError("foreign key accepted")


def test_worker_transitions_compose_without_copying_neutral_rules():
    from modkit_events.persistence import transitions as e_t

    from modkit_workers.persistence import transitions as w_t
    assert w_t._WORK_RULES is e_t._WORK_RULES
    assert tuple(rule.rule_id for rule in w_t._ADMISSION_RULES) == ("submit_runnable", "submit_blocked")
    assert all(rule.operation == "W01" for rule in w_t._ADMISSION_RULES)
