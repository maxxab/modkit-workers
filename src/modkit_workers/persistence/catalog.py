"""Built-in jobs' closed metadata; compose the actual neutral event catalog."""
from types import MappingProxyType
from modkit_events.persistence.catalog import (
    CardinalityKind, ColumnSpec, ConstraintId, ParameterSpec, RecordKind,
    ResultSpec, StatementSpec, WireType, get_statement as _event_statement,
)


def _parameter(name: str, kind: WireType, nullable: bool = False) -> ParameterSpec:
    return ParameterSpec(name=name, wire_type=kind, nullable=nullable, constraint=ConstraintId(name))


def _column(name: str, kind: WireType, nullable: bool = False) -> ColumnSpec:
    return ColumnSpec(name=name, wire_type=kind, nullable=nullable)


def _nullable(columns: tuple[ColumnSpec, ...]) -> tuple[ColumnSpec, ...]:
    return tuple(_column(col.name, col.wire_type, True) for col in columns)


def _statement(key: str, params: tuple[ParameterSpec, ...], kind: RecordKind,
               cardinality: CardinalityKind, columns: tuple[ColumnSpec, ...], mutation: bool) -> StatementSpec:
    return StatementSpec(key=key, contract_id="modkit-pg-ab-2", parameters=params,
        result=ResultSpec(record=kind, cardinality=cardinality, columns=columns), mutation=mutation)


_B = WireType.BYTEA
_T = WireType.TEXT
_U = WireType.UUID
_Z = WireType.TIMESTAMPTZ
_O = WireType.BOOL
_MATERIAL = (
    _parameter("material_state", _T), _parameter("protected_sidecar", _B, True),
    _parameter("protected_reference", _B, True), _parameter("protected_codec", _B, True),
    _parameter("protected_key_version", _B, True), _parameter("protected_expires_at", _Z, True),
    _parameter("protected_recovery_metadata", _B), _parameter("protected_cleanup_policy", _T),
    _parameter("projection_metadata", _B),
)
_JOB_HALF = (
    _column("job_work_id", _U), _column("job_application", _B),
    _column("job_tenant", _B, True), _column("job_owner", _B, True),
    _column("job_protected_binding", _B), _column("job_semantic_input", _B),
) + tuple(_column(p.name, p.wire_type, p.nullable) for p in _MATERIAL)
_WORK = _event_statement("E15").result.columns
_JOB = _WORK + _JOB_HALF
_JOB_CANDIDATE = _WORK + (_column("job_half_present", _O),) + _nullable(_JOB_HALF)
_JOB_SCAN = _event_statement("E04").result.columns[:4] + _nullable(_JOB)
# These slices are the fixed Admission prefix and paired job claim protocol,
# verified against literal accepted field order by the contract controls.
_ADMISSION = _event_statement("E03").parameters[:20]
_CLAIM = tuple(p for p in _event_statement("E04").parameters if p.name != "kind")
_ITEMS = (
    _statement("W01", _ADMISSION + _MATERIAL, RecordKind.ADMISSION, CardinalityKind.EXACT_ONE,
               _event_statement("E03").result.columns, True),
    _statement("W02", _event_statement("E15").parameters, RecordKind.JOB, CardinalityKind.OPTIONAL_ONE, _JOB, False),
    _statement("W03", _event_statement("E30").parameters, RecordKind.JOB, CardinalityKind.LIMIT, _JOB, False),
    _statement("W04", _event_statement("E17").parameters, RecordKind.JOB_CANDIDATE, CardinalityKind.FIND_TWO, _JOB_CANDIDATE, False),
    _statement("W05", _CLAIM, RecordKind.JOB_SCAN, CardinalityKind.SCAN, _JOB_SCAN, True),
)
_STATEMENTS = MappingProxyType({s.key: s for s in _ITEMS})


def get_statement(key: str) -> StatementSpec:
    """Return only the five canonical worker descriptors."""
    if type(key) is not str or key not in _STATEMENTS:
        raise ValueError("unknown worker statement key")
    return _STATEMENTS[key]


__all__ = ("get_statement",)
