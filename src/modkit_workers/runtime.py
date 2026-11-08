"""Explicit synchronous one-shot execution for an application-owned source."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import replace
from typing import TypeVar, cast

from .handlers import InvalidWorkerConfiguration, _handler_entrypoints
from .work_source import AcquireRequest, RenewalOwner, WorkSource

WorkT = TypeVar("WorkT")

__all__ = ["run_batch"]


def run_batch(source: WorkSource[WorkT], request: AcquireRequest, /) -> int:
    """Acquire once, execute sequentially, then shut down this exclusive source.

    The count records normal execute returns, not durable outcomes. Preflight
    failure leaves lifecycle ownership with the caller. Once acquisition starts,
    shutdown is attempted exactly once, including after invalid/partial output.
    Source owns all pending-work cleanup, transactions and renewal; cancel is
    never called. Simultaneous execution/acquisition and shutdown failures form
    a BaseExceptionGroup retaining both original exceptions.
    """
    if type(request) is not AcquireRequest:
        raise InvalidWorkerConfiguration("Expected AcquireRequest")
    checked = replace(request)
    limit = checked.limit
    if source.renewal_owner is not RenewalOwner.SOURCE:
        raise InvalidWorkerConfiguration("WorkSource must own renewal")
    acquire = source.acquire
    # Return checks also protect callers using untyped source implementations.
    execute = cast(Callable[[WorkT], object], source.execute)
    shutdown = cast(Callable[[], object], source.shutdown)
    for hook in (acquire, execute, shutdown):
        if not callable(hook):
            raise InvalidWorkerConfiguration("WorkSource hooks must be callable")
        if any(
            inspect.iscoroutinefunction(entry)
            or inspect.isgeneratorfunction(entry)
            or inspect.isasyncgenfunction(entry)
            for entry in _handler_entrypoints(hook)
        ):
            raise InvalidWorkerConfiguration("WorkSource hooks must be synchronous")

    failure: BaseException | None = None
    try:
        batch = acquire(checked)
        if type(batch) is not tuple:
            raise TypeError("WorkSource.acquire must return an exact tuple")
        if len(batch) > limit:
            raise ValueError("WorkSource.acquire exceeded the requested limit")
        count = 0
        for work in batch:
            if execute(work) is not None:
                raise TypeError("WorkSource.execute must return None")
            count += 1
        return count
    except BaseException as primary:
        failure = primary
        raise
    finally:
        try:
            if shutdown() is not None:
                raise TypeError("WorkSource.shutdown must return None")
        except BaseException as cleanup:
            if failure is None:
                raise
            raise BaseExceptionGroup(
                "WorkSource batch and shutdown failed", [failure, cleanup]
            ) from None
