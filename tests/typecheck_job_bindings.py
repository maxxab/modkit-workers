"""Static consumer regression; run with the real Events dependency on MYPYPATH."""

from typing import assert_type

from modkit_events.persistence.bindings import FrozenRequest

from modkit_workers.persistence import bindings, models


def binding_results(
    submit: models.JobSubmitRequest,
    read: models.JobReadRequest,
    listing: models.JobListRequest,
    acquire: models.JobAcquireRequest,
    find: models.JobFindRequest,
) -> None:
    assert_type(bindings.submit(submit), FrozenRequest)
    assert_type(bindings.read_job(read), FrozenRequest)
    assert_type(bindings.list_jobs(listing), FrozenRequest)
    assert_type(bindings.acquire(acquire), FrozenRequest)
    prepared = bindings.find_jobs(find)
    assert_type(prepared, bindings.PreparedJobFind)
    assert_type(prepared.lookup, FrozenRequest)
    assert_type(prepared.expected_submission, FrozenRequest)

    # Strict checking must still reject the wrong request and a keyword for a
    # positional-only parameter. An erased signature makes these ignores unused.
    bindings.submit(read)  # type: ignore[arg-type]
    bindings.read_job(request=read)  # type: ignore[call-arg]
