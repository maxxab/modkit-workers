"""Entry-point shape checks must see through built-in partial argument binding."""

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
