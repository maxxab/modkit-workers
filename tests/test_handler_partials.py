"""Entry-point shape checks must see through built-in partial argument binding."""

import subprocess
import sys
from functools import partial

import pytest

from modkit_workers import (
    HandlerKind,
    HandlerRegistration,
    HandlerRegistry,
    InvalidWorkerConfiguration,
)


class SyncHandler:
    def __call__(self, context, *, option=None):
        raise AssertionError("Registration must not invoke callbacks")


class AsyncHandler:
    async def __call__(self, context, *, option=None):
        raise AssertionError("Registration must not invoke callbacks")


class GeneratorHandler:
    def __call__(self, context, *, option=None):
        raise AssertionError("Registration must not invoke callbacks")
        yield


class AsyncGeneratorHandler:
    async def __call__(self, context, *, option=None):
        raise AssertionError("Registration must not invoke callbacks")
        yield


def register(handler, kind):
    return HandlerRegistration(command_type="send", schema_version=1, handler=handler, kind=kind)


@pytest.mark.parametrize("handler_type", [GeneratorHandler, AsyncGeneratorHandler])
@pytest.mark.parametrize("kind", list(HandlerKind))
def test_partial_generator_instances_are_rejected(handler_type, kind):
    with pytest.raises(InvalidWorkerConfiguration):
        register(partial(handler_type(), option="bound"), kind)


def test_partial_async_instance_cannot_register_as_sync():
    with pytest.raises(InvalidWorkerConfiguration):
        register(partial(AsyncHandler(), option="bound"), HandlerKind.SYNC)


@pytest.mark.parametrize(
    ("handler_type", "kind"),
    [(SyncHandler, HandlerKind.SYNC), (AsyncHandler, HandlerKind.ASYNC)],
)
def test_partial_matching_shape_is_preserved_through_registry(handler_type, kind):
    handler = partial(partial(handler_type(), option="bound"))
    registry = HandlerRegistry([register(handler, kind)])
    assert registry.get("send", 1).handler is handler


def test_partial_sync_instance_cannot_register_as_async():
    with pytest.raises(InvalidWorkerConfiguration):
        register(partial(SyncHandler()), HandlerKind.ASYNC)


def test_partial_preserves_underlying_descriptor_error():
    error = RuntimeError("application descriptor failure")

    class Descriptor:
        def __get__(self, instance, owner):
            raise error

    class Handler:
        __call__ = Descriptor()

    with pytest.raises(RuntimeError) as caught:
        register(partial(Handler()), HandlerKind.SYNC)
    assert caught.value is error


@pytest.mark.parametrize(
    ("handler", "kind"),
    [
        (SyncHandler.__call__, HandlerKind.SYNC),
        (AsyncHandler.__call__, HandlerKind.ASYNC),
    ],
)
def test_partial_direct_function_keeps_supported_shape(handler, kind):
    callback = partial(handler, object(), option="bound")
    assert register(callback, kind).handler is callback


@pytest.mark.parametrize("handler", [GeneratorHandler.__call__, AsyncGeneratorHandler.__call__])
@pytest.mark.parametrize("kind", list(HandlerKind))
def test_partial_direct_generator_stays_rejected(handler, kind):
    with pytest.raises(InvalidWorkerConfiguration):
        register(partial(handler, object()), kind)


@pytest.mark.parametrize("handler_type", [GeneratorHandler, AsyncGeneratorHandler])
@pytest.mark.parametrize("kind", list(HandlerKind))
def test_partial_call_entrypoint_generators_are_rejected(handler_type, kind):
    class Handler:
        __call__ = partial(handler_type(), option="bound")

    with pytest.raises(InvalidWorkerConfiguration):
        register(Handler(), kind)


def test_partial_call_entrypoint_async_cannot_register_as_sync():
    class Handler:
        __call__ = partial(AsyncHandler(), option="bound")

    with pytest.raises(InvalidWorkerConfiguration):
        register(Handler(), HandlerKind.SYNC)


@pytest.mark.parametrize(
    ("handler_type", "kind"),
    [(SyncHandler, HandlerKind.SYNC), (AsyncHandler, HandlerKind.ASYNC)],
)
def test_partial_call_entrypoint_keeps_matching_shape(handler_type, kind):
    class Inner:
        __call__ = partial(handler_type(), option="bound")

    class Outer:
        __call__ = partial(Inner())

    callback = partial(Outer())
    registry = HandlerRegistry([register(callback, kind)])
    assert registry.get("send", 1).handler is callback


def test_cyclic_partial_call_entrypoint_is_rejected_without_execution():
    class Handler:
        def __call__(self, context):
            raise AssertionError("Registration must not invoke callbacks")

    handler = Handler()
    Handler.__call__ = partial(handler)
    with pytest.raises(InvalidWorkerConfiguration):
        register(handler, HandlerKind.SYNC)


def test_partial_call_descriptor_chain_is_bounded_without_execution():
    visits = []

    class Descriptor:
        def __get__(self, instance, owner):
            visits.append(None)
            if len(visits) > 64:
                raise AssertionError("Partial entrypoint inspection must be bounded")
            return partial(Handler())

    class Handler:
        __call__ = Descriptor()

    with pytest.raises(InvalidWorkerConfiguration):
        register(Handler(), HandlerKind.SYNC)
    assert 0 < len(visits) <= 64


def test_partial_call_entrypoint_preserves_descriptor_error():
    error = RuntimeError("application descriptor failure")

    class Descriptor:
        def __get__(self, instance, owner):
            raise error

    class Inner:
        __call__ = Descriptor()

    class Outer:
        __call__ = partial(Inner())

    with pytest.raises(RuntimeError) as caught:
        register(Outer(), HandlerKind.SYNC)
    assert caught.value is error


@pytest.mark.parametrize("call_entrypoint", [False, True])
def test_partial_func_cycles_are_rejected_without_hanging(call_entrypoint):
    code = """
from functools import partial
from modkit_workers import HandlerKind, HandlerRegistration, InvalidWorkerConfiguration

cycle = partial(print)
cycle.__setstate__((cycle, (), {}, None))
class Handler:
    __call__ = cycle
handler = Handler() if CALL_ENTRYPOINT else cycle
try:
    HandlerRegistration(command_type="send", schema_version=1,
                        handler=handler, kind=HandlerKind.SYNC)
except InvalidWorkerConfiguration:
    pass
else:
    raise AssertionError("Partial func cycles must not register")
""".replace("CALL_ENTRYPOINT", repr(call_entrypoint))
    # A regression must fail with a finite child timeout, not hang the whole suite.
    subprocess.run(
        [sys.executable, "-c", code], check=True, timeout=5, capture_output=True, text=True
    )
