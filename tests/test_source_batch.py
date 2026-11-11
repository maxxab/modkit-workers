"""Real local source hooks; no transaction, durable outcome or driver qualification."""

import asyncio
from functools import partial

import pytest
from modkit_events.persistence.models import Capability

from modkit_workers import AcquireRequest, InvalidWorkerConfiguration, RenewalOwner
from modkit_workers.runtime import run_batch


def request(limit=2):
    return AcquireRequest(
        capabilities=[Capability(command_type="local", schema_version=1)],
        limit=limit,
        discovery_budget=max(16, limit),
    )


class LocalSource:
    renewal_owner = RenewalOwner.SOURCE

    def __init__(self, batch=()):
        self.batch = batch
        self.events = []
        self.request = None

    def acquire(self, checked):
        self.events.append("acquire")
        self.request = checked
        return self.batch

    def execute(self, work):
        self.events.append(work)

    @property
    def cancel(self):
        raise AssertionError("The runner must not read or call cancel")

    def shutdown(self):
        self.events.append("shutdown")


@pytest.mark.parametrize("size", [0, 2, 256])
def test_one_acquire_ordered_exact_handles_count_and_shutdown(size):
    class Handle:
        def __eq__(self, other):
            raise AssertionError("Opaque handles must not be compared")

    handles = tuple(Handle() for _ in range(size))
    source = LocalSource(handles)
    original = request(max(1, size))
    assert run_batch(source, original) == size
    assert source.events[0] == "acquire"
    assert source.events[-1] == "shutdown"
    assert len(source.events) == size + 2
    assert all(actual is expected for actual, expected in zip(source.events[1:-1], handles))
    assert source.request is not original
    assert source.request.capabilities == original.capabilities
    assert source.request.capabilities is not original.capabilities


def test_repeated_handle_is_not_deduplicated():
    handle = object()
    source = LocalSource((handle, handle))
    assert run_batch(source, request()) == 2
    assert source.events == ["acquire", handle, handle, "shutdown"]


@pytest.mark.parametrize("invalid", [object(), None, {"limit": 1}])
def test_wrong_request_never_reads_source(invalid):
    class Unavailable:
        def __getattribute__(self, name):
            raise AssertionError("Invalid request must fail before source access")

    with pytest.raises(InvalidWorkerConfiguration):
        run_batch(Unavailable(), invalid)


def test_request_is_reconstructed_before_any_source_access():
    class Unavailable:
        def __getattribute__(self, name):
            raise AssertionError("Invalid request must fail before source access")

    invalid = request()
    object.__setattr__(invalid, "limit", 0)
    with pytest.raises(InvalidWorkerConfiguration):
        run_batch(Unavailable(), invalid)


def test_shared_capability_is_revalidated_before_source_access():
    source = LocalSource()
    invalid = request()
    object.__setattr__(invalid.capabilities[0], "schema_version", 0)
    from modkit_events.persistence.errors import PersistenceError

    with pytest.raises(PersistenceError):
        run_batch(source, invalid)
    assert source.events == []


@pytest.mark.parametrize("owner", [None, "source", object()])
def test_wrong_renewal_owner_does_not_enter_lifecycle(owner):
    source = LocalSource()
    source.renewal_owner = owner
    with pytest.raises(InvalidWorkerConfiguration):
        run_batch(source, request())
    assert source.events == []


def test_descriptor_error_preserves_identity_without_shutdown():
    error = RuntimeError("application descriptor error")

    class Source(LocalSource):
        @property
        def execute(self):
            raise error

    source = Source()
    with pytest.raises(RuntimeError) as caught:
        run_batch(source, request())
    assert caught.value is error
    assert source.events == []


async def coroutine_hook(*args):
    raise AssertionError("Async hooks must not be called")


def generator_hook(*args):
    raise AssertionError("Generator hooks must not be called")
    yield


async def async_generator_hook(*args):
    raise AssertionError("Async-generator hooks must not be called")
    yield


@pytest.mark.parametrize("name", ["acquire", "execute", "shutdown"])
@pytest.mark.parametrize("hook", [None, coroutine_hook, generator_hook, async_generator_hook])
def test_invalid_hook_shapes_fail_before_acquisition(name, hook):
    source = LocalSource()
    setattr(source, name, hook)
    with pytest.raises(InvalidWorkerConfiguration):
        run_batch(source, request())
    assert source.events == []


def test_partial_async_callable_instance_is_rejected_without_invocation():
    class Async:
        async def __call__(self, work):
            raise AssertionError("Async hook must not run")

    source = LocalSource()
    source.execute = partial(Async())
    with pytest.raises(InvalidWorkerConfiguration):
        run_batch(source, request())
    assert source.events == []


def test_sync_partial_callable_instance_executes_normally():
    class Record:
        def __init__(self, events):
            self.events = events

        def __call__(self, work):
            self.events.append(work)

    handle = object()
    source = LocalSource((handle,))
    source.execute = partial(Record(source.events))
    assert run_batch(source, request()) == 1
    assert source.events == ["acquire", handle, "shutdown"]


@pytest.mark.parametrize("output", [None, [], iter(())])
def test_invalid_acquisition_type_is_not_executed(output):
    source = LocalSource(output)
    with pytest.raises(TypeError):
        run_batch(source, request())
    assert source.events == ["acquire", "shutdown"]


def test_arbitrary_iterable_and_tuple_subclass_are_not_enumerated():
    class Trap:
        def __iter__(self):
            raise AssertionError("Invalid output must not be enumerated")

    class TupleTrap(tuple):
        def __iter__(self):
            raise AssertionError("Tuple subclass must not be enumerated")

        def __len__(self):
            raise AssertionError("Tuple subclass must not be measured")

    for output in (Trap(), TupleTrap((object(),))):
        source = LocalSource(output)
        with pytest.raises(TypeError):
            run_batch(source, request())
        assert source.events == ["acquire", "shutdown"]


def test_oversized_tuple_executes_nothing_but_still_shuts_down():
    source = LocalSource((object(), object(), object()))
    with pytest.raises(ValueError):
        run_batch(source, request())
    assert source.events == ["acquire", "shutdown"]


@pytest.mark.parametrize("phase", ["acquire", "execute"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError, KeyboardInterrupt])
def test_primary_error_identity_survives_cleanup_without_retry_or_cancel(phase, error_type):
    error = error_type("application failure")
    first, second = object(), object()
    source = LocalSource((first, second))

    def fail(*args):
        source.events.append("failure")
        raise error

    setattr(source, phase, fail)
    with pytest.raises(BaseException) as caught:
        run_batch(source, request())
    assert caught.value is error
    assert source.events == (
        ["failure", "shutdown"] if phase == "acquire" else ["acquire", "failure", "shutdown"]
    )


@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError, KeyboardInterrupt])
def test_shutdown_error_alone_keeps_exact_identity(error_type):
    error = error_type("shutdown failed")
    source = LocalSource()

    def fail():
        source.events.append("shutdown")
        raise error

    source.shutdown = fail
    with pytest.raises(BaseException) as caught:
        run_batch(source, request())
    assert caught.value is error
    assert source.events == ["acquire", "shutdown"]


@pytest.mark.parametrize("primary", [RuntimeError("primary"), asyncio.CancelledError("cancel")])
def test_primary_and_shutdown_errors_are_exact_ordered_group_members(primary):
    cleanup = RuntimeError("cleanup")
    source = LocalSource()

    def acquire(checked):
        source.events.append("acquire")
        raise primary

    def shutdown():
        source.events.append("shutdown")
        raise cleanup

    source.acquire, source.shutdown = acquire, shutdown
    with pytest.raises(BaseExceptionGroup) as caught:
        run_batch(source, request())
    assert caught.value.exceptions == (primary, cleanup)
    assert caught.value.exceptions[0] is primary
    assert caught.value.exceptions[1] is cleanup
    assert caught.value.message == "WorkSource batch and shutdown failed"
    assert source.events == ["acquire", "shutdown"]


def test_failure_after_success_stops_later_work_and_shutdown_releases_pending():
    first, second, third = object(), object(), object()
    error = RuntimeError("second failed")

    class Source(LocalSource):
        def __init__(self):
            super().__init__((first, second, third))
            self.pending = list(self.batch)
            self.released = []

        def execute(self, work):
            self.events.append(work)
            if work is second:
                raise error
            assert self.pending.pop(0) is work

        def shutdown(self):
            self.events.append("shutdown")
            self.released.extend(self.pending)
            self.pending.clear()

    source = Source()
    with pytest.raises(RuntimeError) as caught:
        run_batch(source, request(3))
    assert caught.value is error
    assert source.events == ["acquire", first, second, "shutdown"]
    assert source.released == [second, third]
    assert source.pending == []


class CallerOwnedAwaitable:
    def __await__(self):
        raise AssertionError("Returned awaitable must not be awaited")
        yield

    def close(self):
        raise AssertionError("Returned awaitable must not be closed")


@pytest.mark.parametrize("phase", ["acquire", "execute", "shutdown"])
@pytest.mark.parametrize("result", [1, CallerOwnedAwaitable()])
def test_invalid_hook_result_is_rejected_without_operating_on_it(phase, result):
    source = LocalSource((object(), object()))

    def invalid(*args):
        source.events.append("invalid")
        return result

    setattr(source, phase, invalid)
    with pytest.raises(TypeError):
        run_batch(source, request())
    assert (
        source.events
        == {
            "acquire": ["invalid", "shutdown"],
            "execute": ["acquire", "invalid", "shutdown"],
            "shutdown": ["acquire", *source.batch, "invalid"],
        }[phase]
    )


def test_hooks_are_captured_before_acquire_mutates_source_attributes():
    handle = object()

    class Source(LocalSource):
        def acquire(self, checked):
            result = super().acquire(checked)
            self.execute = None
            self.shutdown = None
            return result

    source = Source((handle,))
    assert run_batch(source, request()) == 1
    assert source.events == ["acquire", handle, "shutdown"]
