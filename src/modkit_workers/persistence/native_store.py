"""Optional fixed native job preparations on the caller-owned Events root.

No connection, transaction, execution, result release or cleanup is implicit.
The common issuer must execute the admitted preparation and retain its result
until the caller has finished borrowing it.
"""

from modkit_events.persistence.native_profile import WorkersNativeOperation, result_capacity

from . import bindings, rows
from .catalog import get_statement
from .models import JobReadRequest, JobSubmitRequest
from .observations import JobAdmissionObservation, JobDetails, JobPayload, JobRecord

_SUBMIT = WorkersNativeOperation(
    statement=get_statement("W01"),
    request_type=JobSubmitRequest,
    build_request=bindings._submit_raw,
    decode_rows=rows._decode_submit_raw,
    validate_result=rows._validate_submit_result_raw,
    result_types=(JobAdmissionObservation,),
)
_READ_JOB = WorkersNativeOperation(
    statement=get_statement("W02"),
    request_type=JobReadRequest,
    build_request=bindings._read_job_raw,
    decode_rows=rows._decode_read_raw,
    validate_result=rows._validate_read_result_raw,
    result_types=(JobRecord, JobDetails, JobPayload),
)

SUBMIT_RESULT_CAPACITY = result_capacity(_SUBMIT)
READ_JOB_RESULT_CAPACITY = result_capacity(_READ_JOB)


def prepare_submit(execution, request: JobSubmitRequest, /, *, execution_ledger):
    """Reserve and freeze a W01 submission; this does not execute or commit."""
    from modkit_events.persistence.native_execution import prepare_component
    return prepare_component(execution, _SUBMIT, request, execution_ledger=execution_ledger)


def prepare_read_job(execution, request: JobReadRequest, /, *, execution_ledger):
    """Reserve and freeze a W02 complete protected-record read."""
    from modkit_events.persistence.native_execution import prepare_component
    return prepare_component(execution, _READ_JOB, request, execution_ledger=execution_ledger)


__all__ = (
    "prepare_submit", "prepare_read_job",
    "SUBMIT_RESULT_CAPACITY", "READ_JOB_RESULT_CAPACITY",
)
