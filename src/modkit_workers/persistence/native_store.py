"""Optional fixed native job preparations on the caller-owned Events root.

No connection, transaction, execution, result release or cleanup is implicit.
The common issuer must execute the admitted preparation and retain its result
until the caller has finished borrowing it.
"""

from modkit_events.persistence.native_profile import (
    DEFAULT_ACQUIRE_PAGE_PAYLOAD_BYTES,
    DEFAULT_LIST_PAGE_PAYLOAD_BYTES,
    MAX_ACQUIRE_PAGE_PAYLOAD_BYTES,
    MAX_LIST_PAGE_PAYLOAD_BYTES,
    WorkersNativeOperation,
    result_capacity,
)

from . import bindings, rows
from .catalog import get_statement
from .models import (
    JobAcquireRequest,
    JobFindRequest,
    JobListRequest,
    JobReadRequest,
    JobSubmitRequest,
)
from .observations import (
    JobAdmissionObservation,
    JobCandidate,
    JobClaimObservation,
    JobDetails,
    JobIdentityDecision,
    JobIdentityObservation,
    JobPayload,
    JobRecord,
)

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

_LIST_JOBS = WorkersNativeOperation(
    statement=get_statement("W03"),
    request_type=JobListRequest,
    build_request=bindings._list_jobs_raw,
    decode_rows=rows._decode_list_raw,
    validate_result=rows._validate_list_result_raw,
    result_types=(JobRecord, JobDetails, JobPayload),
)

_FIND_JOBS = WorkersNativeOperation(
    statement=get_statement("W04"),
    request_type=JobFindRequest,
    build_request=bindings._find_jobs_raw,
    decode_rows=rows._decode_find_raw,
    validate_result=rows._validate_find_result_raw,
    result_types=(
        JobRecord,
        JobDetails,
        JobPayload,
        JobCandidate,
        JobIdentityObservation,
        JobIdentityDecision,
    ),
)

_ACQUIRE = WorkersNativeOperation(
    statement=get_statement("W05"),
    request_type=JobAcquireRequest,
    build_request=bindings._acquire_raw,
    decode_rows=rows._decode_acquire_raw,
    validate_result=rows._validate_acquire_result_raw,
    result_types=(JobRecord, JobDetails, JobPayload, JobClaimObservation),
)

SUBMIT_RESULT_CAPACITY = result_capacity(_SUBMIT)
READ_JOB_RESULT_CAPACITY = result_capacity(_READ_JOB)
FIND_JOBS_RESULT_CAPACITY = result_capacity(_FIND_JOBS)


def prepare_submit(execution, request: JobSubmitRequest, /, *, execution_ledger):
    """Reserve and freeze a W01 submission; this does not execute or commit."""
    from modkit_events.persistence.native_execution import prepare_component

    return prepare_component(execution, _SUBMIT, request, execution_ledger=execution_ledger)


def prepare_read_job(execution, request: JobReadRequest, /, *, execution_ledger):
    """Reserve and freeze a W02 complete protected-record read."""
    from modkit_events.persistence.native_execution import prepare_component

    return prepare_component(execution, _READ_JOB, request, execution_ledger=execution_ledger)


def prepare_list_jobs(
    execution,
    request: JobListRequest,
    /,
    *,
    execution_ledger,
    max_page_payload_bytes=DEFAULT_LIST_PAGE_PAYLOAD_BYTES,
):
    """Prepare a complete page with an explicit aggregate BYTEA allowance."""
    from modkit_events.persistence.native_execution import prepare_component

    return prepare_component(
        execution,
        _LIST_JOBS,
        request,
        execution_ledger=execution_ledger,
        max_page_payload_bytes=max_page_payload_bytes,
    )


def prepare_find_jobs(execution, request: JobFindRequest, /, *, execution_ledger):
    """Prepare a complete comparison-only lookup; never submit or claim work."""
    from modkit_events.persistence.native_execution import prepare_component

    return prepare_component(execution, _FIND_JOBS, request, execution_ledger=execution_ledger)


def prepare_acquire(
    execution,
    request: JobAcquireRequest,
    /,
    *,
    execution_ledger,
    max_page_payload_bytes=DEFAULT_ACQUIRE_PAGE_PAYLOAD_BYTES,
):
    """Prepare an atomic complete claim page with an all-variable-byte budget."""
    from modkit_events.persistence.native_execution import prepare_component

    return prepare_component(
        execution,
        _ACQUIRE,
        request,
        execution_ledger=execution_ledger,
        max_page_payload_bytes=max_page_payload_bytes,
    )


__all__ = (
    "prepare_acquire",
    "DEFAULT_ACQUIRE_PAGE_PAYLOAD_BYTES",
    "MAX_ACQUIRE_PAGE_PAYLOAD_BYTES",
    "prepare_submit",
    "prepare_read_job",
    "prepare_list_jobs",
    "prepare_find_jobs",
    "SUBMIT_RESULT_CAPACITY",
    "READ_JOB_RESULT_CAPACITY",
    "FIND_JOBS_RESULT_CAPACITY",
    "DEFAULT_LIST_PAGE_PAYLOAD_BYTES",
    "MAX_LIST_PAGE_PAYLOAD_BYTES",
)
