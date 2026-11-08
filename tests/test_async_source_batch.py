"""Actual async source hooks and deterministic caller-task cancellation boundaries."""

import asyncio
from contextvars import ContextVar
from functools import partial

import pytest
from modkit_events.persistence.models import Capability

from modkit_workers import AcquireRequest, InvalidWorkerConfiguration, RenewalOwner, runtime


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

    async def acquire(self, checked):
        self.events.append("acquire")
        self.request = checked
        return self.batch

    async def execute(self, work):
        self.events.append(work)

    @property
    def cancel(self):
        raise AssertionError("The runner must not read or call cancel")

    async def shutdown(self):
        self.events.append("shutdown")


async def reached(event):
    # A timeout diagnoses a hang; the Event itself proves the scheduling boundary.
    await asyncio.wait_for(event.wait(), timeout=5)


@pytest.mark.parametrize("size", [0, 2, 256])
async def test_one_acquire_exact_handles_order_count_and_shutdown(size):
    class Handle:
        def __eq__(self, other):
            raise AssertionError("Opaque handles must not be compared")

    handles = tuple(Handle() for _ in range(size))
    source = LocalSource(handles)
    original = request(max(1, size))
    assert await runtime.run_batch_async(source, original) == size
    assert source.events[0] == "acquire"
    assert source.events[-1] == "shutdown"
    assert len(source.events) == size + 2
    assert all(actual is expected for actual, expected in zip(source.events[1:-1], handles))
    assert source.request is not original
    assert source.request.capabilities == original.capabilities
    assert source.request.capabilities is not original.capabilities
    assert source.request.capabilities[0] is not original.capabilities[0]


async def test_repeated_handle_is_not_deduplicated():
    handle = object()
    source = LocalSource((handle, handle))
    assert await runtime.run_batch_async(source, request()) == 2
    assert source.events == ["acquire", handle, handle, "shutdown"]


class Unavailable:
    def __getattribute__(self, name):
        raise AssertionError("This runner must not access the source")


def test_creating_unawaited_coroutine_does_no_preflight_or_source_access():
    coroutine = runtime.run_batch_async(Unavailable(), None)
    coroutine.close()


async def test_cancellation_before_coroutine_first_runs_owns_no_lifecycle():
    task = asyncio.create_task(runtime.run_batch_async(Unavailable(), None))
    task.cancel("before start")
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.parametrize("invalid", [object(), None, {"limit": 1}])
async def test_wrong_request_fails_before_source_access(invalid):
    with pytest.raises(InvalidWorkerConfiguration):
        await runtime.run_batch_async(Unavailable(), invalid)


async def test_request_and_shared_capability_are_revalidated_before_source_access():
    invalid = request()
    object.__setattr__(invalid, "limit", 0)
    with pytest.raises(InvalidWorkerConfiguration):
        await runtime.run_batch_async(Unavailable(), invalid)

    from modkit_events.persistence.errors import PersistenceError

    invalid = request()
    object.__setattr__(invalid.capabilities[0], "schema_version", 0)
    with pytest.raises(PersistenceError):
        await runtime.run_batch_async(Unavailable(), invalid)


@pytest.mark.parametrize("owner", [None, "source", object()])
async def test_wrong_renewal_owner_owns_no_lifecycle(owner):
    source = LocalSource()
    source.renewal_owner = owner
    with pytest.raises(InvalidWorkerConfiguration):
        await runtime.run_batch_async(source, request())
    assert source.events == []


async def test_preflight_descriptor_error_keeps_identity_without_shutdown():
    error = RuntimeError("descriptor")

    class Source(LocalSource):
        @property
        def execute(self):
            raise error

    source = Source()
    with pytest.raises(RuntimeError) as caught:
        await runtime.run_batch_async(source, request())
    assert caught.value is error
    assert source.events == []


def synchronous_hook(*args):
    raise AssertionError("Sync hooks must not be invoked")


def generator_hook(*args):
    raise AssertionError("Generator hooks must not be invoked")
    yield


async def async_generator_hook(*args):
    raise AssertionError("Async-generator hooks must not be invoked")
    yield


@pytest.mark.parametrize("name", ["acquire", "execute", "shutdown"])
@pytest.mark.parametrize("hook", [None, synchronous_hook, generator_hook, async_generator_hook])
async def test_invalid_hook_shapes_rejected_before_acquisition(name, hook):
    source = LocalSource()
    setattr(source, name, hook)
    with pytest.raises(InvalidWorkerConfiguration):
        await runtime.run_batch_async(source, request())
    assert source.events == []


async def test_sync_coroutine_factory_rejected_without_invocation():
    source = LocalSource()

    def factory(work):
        raise AssertionError("Do not call synchronous factories to inspect their returns")

    source.execute = factory
    with pytest.raises(InvalidWorkerConfiguration):
        await runtime.run_batch_async(source, request())
    assert source.events == []


@pytest.mark.parametrize("name", ["acquire", "execute", "shutdown"])
@pytest.mark.parametrize("shape", ["partial", "instance", "partial_instance", "partial_call"])
async def test_native_async_callable_and_partial_shapes_are_supported(name, shape):
    handle = object()
    source = LocalSource((handle,))
    original = getattr(source, name)

    class AsyncCall:
        async def __call__(self, *args):
            return await original(*args)

    class PartialCall:
        __call__ = partial(original)

    hook = {
        "partial": partial(original),
        "instance": AsyncCall(),
        "partial_instance": partial(AsyncCall()),
        "partial_call": PartialCall(),
    }[shape]
    setattr(source, name, hook)
    assert await runtime.run_batch_async(source, request()) == 1
    assert source.events == ["acquire", handle, "shutdown"]


async def test_partial_backed_generator_callable_rejected_without_invocation():
    class GeneratorCall:
        __call__ = partial(generator_hook)

    source = LocalSource()
    source.execute = GeneratorCall()
    with pytest.raises(InvalidWorkerConfiguration):
        await runtime.run_batch_async(source, request())
    assert source.events == []


@pytest.mark.parametrize("output", [None, [], iter(())])
async def test_invalid_acquisition_type_still_shuts_down_without_execute(output):
    source = LocalSource(output)
    with pytest.raises(TypeError):
        await runtime.run_batch_async(source, request())
    assert source.events == ["acquire", "shutdown"]


async def test_invalid_iterable_and_tuple_subclass_are_not_enumerated():
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
            await runtime.run_batch_async(source, request())
        assert source.events == ["acquire", "shutdown"]


@pytest.mark.parametrize("mutate_limit", [False, True])
async def test_saved_limit_rejects_oversized_tuple_before_execute(mutate_limit):
    class Source(LocalSource):
        async def acquire(self, checked):
            batch = await super().acquire(checked)
            if mutate_limit:
                object.__setattr__(checked, "limit", 256)
            return batch

    source = Source((object(), object(), object()))
    with pytest.raises(ValueError):
        await runtime.run_batch_async(source, request())
    assert source.events == ["acquire", "shutdown"]


@pytest.mark.parametrize("phase", ["acquire", "execute", "shutdown"])
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError, KeyboardInterrupt])
async def test_single_failure_preserves_exact_identity(phase, error_type):
    error = error_type("application failure")
    source = LocalSource((object(), object()))

    async def fail(*args):
        source.events.append("failure")
        raise error

    setattr(source, phase, fail)
    with pytest.raises(BaseException) as caught:
        await runtime.run_batch_async(source, request())
    assert caught.value is error
    assert (
        source.events
        == {
            "acquire": ["failure", "shutdown"],
            "execute": ["acquire", "failure", "shutdown"],
            "shutdown": ["acquire", *source.batch, "failure"],
        }[phase]
    )


@pytest.mark.parametrize("primary", [RuntimeError("primary"), asyncio.CancelledError("primary")])
async def test_primary_and_cleanup_failures_preserve_ordered_exact_group_leaves(primary):
    cleanup = RuntimeError("cleanup")
    source = LocalSource()

    async def acquire(checked):
        source.events.append("acquire")
        raise primary

    async def shutdown():
        source.events.append("shutdown")
        raise cleanup

    source.acquire, source.shutdown = acquire, shutdown
    with pytest.raises(BaseExceptionGroup) as caught:
        await runtime.run_batch_async(source, request())
    assert caught.value.exceptions[0] is primary
    assert caught.value.exceptions[1] is cleanup
    assert len(caught.value.exceptions) == 2
    assert isinstance(caught.value, ExceptionGroup) == isinstance(primary, Exception)
    assert source.events == ["acquire", "shutdown"]


async def test_source_retains_partial_acquisition_and_failed_unprocessed_handles():
    first, second, third = object(), object(), object()
    error = RuntimeError("work failed")

    class Source(LocalSource):
        def __init__(self, acquisition_failure):
            super().__init__((first, second, third))
            self.acquisition_failure = acquisition_failure
            self.pending = []
            self.released = []

        async def acquire(self, checked):
            self.events.append("acquire")
            self.pending.extend(self.batch)
            if self.acquisition_failure:
                raise error
            return self.batch

        async def execute(self, work):
            self.events.append(work)
            if work is second:
                raise error
            assert self.pending.pop(0) is work

        async def shutdown(self):
            self.events.append("shutdown")
            self.released.extend(self.pending)
            self.pending.clear()

    for acquisition_failure in (True, False):
        source = Source(acquisition_failure)
        with pytest.raises(RuntimeError) as caught:
            await runtime.run_batch_async(source, request(3))
        assert caught.value is error
        assert source.events == (
            ["acquire", "shutdown"]
            if acquisition_failure
            else ["acquire", first, second, "shutdown"]
        )
        assert source.released == (
            [first, second, third] if acquisition_failure else [second, third]
        )
        assert source.pending == []


class CallerOwnedAwaitable:
    def __await__(self):
        raise AssertionError("Nested returned awaitable must not be awaited")
        yield

    def close(self):
        raise AssertionError("Nested returned awaitable must not be closed")


@pytest.mark.parametrize("phase", ["acquire", "execute", "shutdown"])
@pytest.mark.parametrize("result", [1, CallerOwnedAwaitable()])
async def test_invalid_eventual_result_is_not_awaited_again_or_closed(phase, result):
    source = LocalSource((object(), object()))

    async def invalid(*args):
        source.events.append("invalid")
        return result

    setattr(source, phase, invalid)
    with pytest.raises(TypeError):
        await runtime.run_batch_async(source, request())
    assert (
        source.events
        == {
            "acquire": ["invalid", "shutdown"],
            "execute": ["acquire", "invalid", "shutdown"],
            "shutdown": ["acquire", *source.batch, "invalid"],
        }[phase]
    )


async def test_captured_hooks_survive_acquire_mutating_source():
    class Source(LocalSource):
        async def acquire(self, checked):
            batch = await super().acquire(checked)
            self.execute = None
            self.shutdown = None
            return batch

    source = Source((object(),))
    assert await runtime.run_batch_async(source, request()) == 1
    assert source.events == ["acquire", *source.batch, "shutdown"]


async def test_hooks_keep_caller_task_and_mutable_context():
    context = ContextVar("source_context")
    marker = object()
    caller = asyncio.current_task()
    context.set(marker)
    source = LocalSource((object(),))

    async def acquire(checked):
        assert asyncio.current_task() is caller
        assert context.get() is marker
        context.set("acquired")
        return await LocalSource.acquire(source, checked)

    async def execute(work):
        assert asyncio.current_task() is caller
        assert context.get() == "acquired"
        context.set("executed")
        await LocalSource.execute(source, work)

    async def shutdown():
        assert asyncio.current_task() is caller
        assert context.get() == "executed"
        context.set("closed")
        await LocalSource.shutdown(source)

    source.acquire, source.execute, source.shutdown = acquire, execute, shutdown
    assert await runtime.run_batch_async(source, request()) == 1
    assert context.get() == "closed"


async def test_execution_is_sequential_and_result_waits_for_shutdown():
    first, second = object(), object()
    entered, release = asyncio.Event(), asyncio.Event()
    closing, closed = asyncio.Event(), asyncio.Event()
    source = LocalSource((first, second))

    async def execute(work):
        source.events.append(work)
        if work is first:
            entered.set()
            await release.wait()

    async def shutdown():
        source.events.append("shutdown")
        closing.set()
        await closed.wait()

    source.execute, source.shutdown = execute, shutdown
    task = asyncio.create_task(runtime.run_batch_async(source, request()))
    await reached(entered)
    assert source.events == ["acquire", first]
    release.set()
    await reached(closing)
    assert source.events == ["acquire", first, second, "shutdown"]
    assert not task.done()
    closed.set()
    assert await task == 2


@pytest.mark.parametrize("phase", ["acquire", "execute"])
async def test_delivered_cancellation_stops_execution_and_awaits_same_task_shutdown(phase):
    entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    blocked = asyncio.Event()
    seen = []
    source = LocalSource((object(), object()))

    async def cancelled(*args):
        source.events.append("blocked")
        entered.set()
        try:
            await blocked.wait()
        except asyncio.CancelledError as error:
            seen.append(error)
            raise

    async def shutdown():
        assert asyncio.current_task() is task
        source.events.append("shutdown")
        closing.set()
        await release.wait()
        source.events.append("closed")

    setattr(source, phase, cancelled)
    source.shutdown = shutdown
    task = asyncio.create_task(runtime.run_batch_async(source, request()))
    await reached(entered)
    task.cancel("primary")
    await reached(closing)
    assert not task.done()
    assert source.events == (
        ["blocked", "shutdown"] if phase == "acquire" else ["acquire", "blocked", "shutdown"]
    )
    release.set()
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert caught.value is seen[0]
    assert task.cancelled()
    assert task.cancelling() == 1
    assert source.events[-1] == "closed"


async def test_cancellation_during_shutdown_alone_keeps_identity_without_retry():
    closing = asyncio.Event()
    blocked = asyncio.Event()
    seen = []
    source = LocalSource()

    async def shutdown():
        source.events.append("shutdown")
        closing.set()
        try:
            await blocked.wait()
        except asyncio.CancelledError as error:
            seen.append(error)
            raise

    source.shutdown = shutdown
    task = asyncio.create_task(runtime.run_batch_async(source, request()))
    await reached(closing)
    task.cancel("cleanup")
    with pytest.raises(asyncio.CancelledError) as caught:
        await task
    assert caught.value is seen[0]
    assert source.events == ["acquire", "shutdown"]


@pytest.mark.parametrize("cleanup_failure", ["recancel", "ordinary"])
async def test_cleanup_failure_after_task_cancel_preserves_both_leaves_without_detached_work(
    cleanup_failure,
):
    entered, closing, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    blocked = asyncio.Event()
    seen = []
    tasks_before = asyncio.all_tasks()
    source = LocalSource((object(), object()))
    cleanup = RuntimeError("cleanup")

    async def execute(work):
        source.events.append(work)
        entered.set()
        try:
            await blocked.wait()
        except asyncio.CancelledError as error:
            seen.append(error)
            raise

    async def shutdown():
        assert asyncio.current_task() is task
        source.events.append("shutdown")
        closing.set()
        try:
            await release.wait()
            raise cleanup
        except BaseException as error:
            seen.append(error)
            raise

    source.execute, source.shutdown = execute, shutdown
    task = asyncio.create_task(runtime.run_batch_async(source, request()))
    await reached(entered)
    task.cancel("primary")
    await reached(closing)
    if cleanup_failure == "recancel":
        task.cancel("cleanup")
    else:
        release.set()
    with pytest.raises(BaseExceptionGroup) as caught:
        await task
    assert len(caught.value.exceptions) == 2
    assert caught.value.exceptions[0] is seen[0]
    assert caught.value.exceptions[1] is seen[1]
    assert isinstance(seen[0], asyncio.CancelledError)
    if cleanup_failure == "recancel":
        assert isinstance(seen[1], asyncio.CancelledError)
    else:
        assert seen[1] is cleanup
    assert not task.cancelled()
    assert task.cancelling() == (2 if cleanup_failure == "recancel" else 1)
    assert source.events == ["acquire", source.batch[0], "shutdown"]
    assert asyncio.all_tasks() == tasks_before


@pytest.mark.parametrize("phase", ["acquire", "execute"])
async def test_source_suppressed_cancellation_is_normal_control_flow(phase):
    entered = asyncio.Event()
    blocked = asyncio.Event()
    source = LocalSource((object(), object()))
    original = getattr(source, phase)
    suppressed = []

    async def suppress(*args):
        if not suppressed:
            entered.set()
            try:
                await blocked.wait()
            except asyncio.CancelledError as error:
                suppressed.append(error)
        return await original(*args)

    setattr(source, phase, suppress)
    task = asyncio.create_task(runtime.run_batch_async(source, request()))
    await reached(entered)
    task.cancel("source owns propagation")
    assert await task == 2
    assert task.cancelling() == 1
    assert not task.cancelled()
    assert len(suppressed) == 1
    assert source.events == ["acquire", *source.batch, "shutdown"]
