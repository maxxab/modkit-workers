"""Pure Workers boundaries; no driver, runtime, transaction or service qualification."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from modkit_events.persistence.errors import ErrorCode, PersistenceError
from modkit_events.persistence.models import Capability
from modkit_events.persistence.scope import Scope

from modkit_workers import (
    AcquireRequest,
    AsyncWorkSource,
    ConflictingHandlerRouteError,
    DuplicateHandlerError,
    HandlerKind,
    HandlerRegistration,
    HandlerRegistry,
    InvalidWorkerConfiguration,
    JobContext,
    RenewalOwner,
    UnknownCommandType,
    UnsupportedHandlerVersion,
    WorkerSettings,
    WorkSource,
)


def sync_handler(context):
    raise AssertionError("Registry must never execute handlers")


async def async_handler(context):
    raise AssertionError("Registry must never execute handlers")


def registration(**changes):
    values = dict(
        command_type="send", schema_version=1, handler=sync_handler, kind=HandlerKind.SYNC
    )
    return HandlerRegistration(**(values | changes))


def context(**changes):
    values = dict(
        work_id="app-id",
        command_type="send",
        schema_version=1,
        scope=Scope("app"),
        payload={"nested": [{"n": 1}]},
        attempt=1,
    )
    return JobContext(**(values | changes))


class HandlerContracts(unittest.TestCase):
    def test_lookup_snapshot_and_subscriber_isolation_without_callbacks(self):
        source = [registration(), registration(schema_version=2)]
        registry = HandlerRegistry(source)
        source.clear()
        self.assertEqual(registry.capabilities(), frozenset({("send", 1), ("send", 2)}))
        self.assertIs(registry.get("send", 1).handler, sync_handler)
        self.assertEqual(len(registry.registrations()), 2)
        independent = HandlerRegistry([registration(handler=lambda ctx: None)])
        self.assertIsNot(independent.get("send", 1).handler, registry.get("send", 1).handler)
        with self.assertRaises(FrozenInstanceError):
            registry._registrations = ()
        with self.assertRaises(FrozenInstanceError):
            registry.get("send", 1).schema_version = 3

    def test_duplicates_routes_unknown_and_version_are_distinct(self):
        with self.assertRaises(DuplicateHandlerError):
            HandlerRegistry([registration(), registration()])
        for route in (None, "other"):
            with self.subTest(route=route), self.assertRaises(ConflictingHandlerRouteError):
                HandlerRegistry(
                    [registration(route="jobs"), registration(schema_version=2, route=route)]
                )
        registry = HandlerRegistry([registration()])
        with self.assertRaises(UnknownCommandType):
            registry.get("missing", 1)
        with self.assertRaises(UnsupportedHandlerVersion):
            registry.get("send", 2)
        with self.assertRaises(InvalidWorkerConfiguration):
            registry.get("send", True)

    def test_explicit_sync_async_entrypoint_shapes(self):
        class Sync:
            def __call__(self, ctx):
                raise AssertionError

        class Async:
            async def __call__(self, ctx):
                raise AssertionError

        def generator(ctx):
            raise AssertionError
            yield

        async def async_generator(ctx):
            raise AssertionError
            yield

        class Generator:
            __call__ = generator

        class AsyncGenerator:
            __call__ = async_generator

        for handler in (sync_handler, Sync()):
            self.assertIs(registration(handler=handler).handler, handler)
        for handler in (async_handler, Async()):
            self.assertIs(registration(handler=handler, kind=HandlerKind.ASYNC).handler, handler)
            with self.assertRaises(InvalidWorkerConfiguration):
                registration(handler=handler)
        for handler in (generator, Generator(), async_generator, AsyncGenerator(), object()):
            for kind in HandlerKind:
                with (
                    self.subTest(handler=type(handler), kind=kind),
                    self.assertRaises(InvalidWorkerConfiguration),
                ):
                    registration(handler=handler, kind=kind)
        with self.assertRaises(InvalidWorkerConfiguration):
            registration(kind=HandlerKind.ASYNC)
        with self.assertRaises(InvalidWorkerConfiguration):
            registration(kind="sync")

    def test_logical_versions_and_identifier_and_count_bounds(self):
        version = 10**5000
        self.assertEqual(
            HandlerRegistry([registration(schema_version=version)]).capabilities(),
            frozenset({("send", version)}),
        )
        for value in ("", " ", "x\0y", "é" * 129, "\ud800", 1):
            with (
                self.subTest(value_type=type(value)),
                self.assertRaises(InvalidWorkerConfiguration),
            ):
                registration(command_type=value)
        for value in (0, True, 1.0):
            with self.assertRaises(InvalidWorkerConfiguration):
                registration(schema_version=value)
        self.assertEqual(HandlerRegistry([]).capabilities(), frozenset())
        with self.assertRaises(InvalidWorkerConfiguration):
            HandlerRegistry(registration(schema_version=i + 1) for i in range(4097))
        self.assertEqual(registration(command_type=" send ").command_type, " send ")

    def test_caller_iterator_and_descriptor_errors_keep_identity(self):
        error = RuntimeError("caller failure")

        def broken():
            yield registration()
            raise error

        with self.assertRaises(RuntimeError) as caught:
            HandlerRegistry(broken())
        self.assertIs(caught.exception, error)

        class Descriptor:
            def __get__(self, instance, owner):
                raise error

        class Handler:
            __call__ = Descriptor()

        with self.assertRaises(RuntimeError) as caught:
            registration(handler=Handler())
        self.assertIs(caught.exception, error)


class ContextContracts(unittest.TestCase):
    def test_snapshot_and_scope_and_no_protected_projection(self):
        payload = {"nested": [{"n": 1}], "float": 1.0}
        value = context(payload=payload, scope=Scope("a\0b"))
        payload["nested"][0]["n"] = 9
        self.assertEqual(value.payload["nested"][0]["n"], 1)
        self.assertIs(type(value.payload["float"]), float)
        with self.assertRaises(TypeError):
            value.payload["nested"][0]["n"] = 7
        with self.assertRaises(FrozenInstanceError):
            value.attempt = 2
        self.assertNotIn("nested", repr(value))
        for field in ("protected_binding", "public_projection", "to_dict", "provider", "fence"):
            self.assertFalse(hasattr(value, field))

    def test_scope_error_keeps_existing_detached_contract(self):
        try:
            raise RuntimeError("ambient")
        except RuntimeError:
            with self.assertRaises(ValueError) as caught:
                context(scope=object())
        self.assertNotIsInstance(caught.exception, InvalidWorkerConfiguration)
        self.assertEqual(str(caught.exception), "Invalid scope")
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)
        self.assertTrue(caught.exception.__suppress_context__)

    def test_managed_codec_limits_and_errors_not_logical_unbounded_json(self):
        nested = 1
        for _ in range(33):
            nested = [nested]
        for payload in (
            {"n": float("nan")},
            {"n": object()},
            {"n": 10**4096},
            {"n": "x" * 1048576},
            {"n": nested},
        ):
            with (
                self.subTest(payload_keys=tuple(payload)),
                self.assertRaises(PersistenceError) as caught,
            ):
                context(payload=payload)
            self.assertIs(caught.exception.code, ErrorCode.LOCAL_INVALID_ARGUMENT)
            self.assertFalse(caught.exception.unconfirmed)
        self.assertEqual(context(schema_version=10**5000).schema_version, 10**5000)

    def test_attempt_deadline_and_exact_scalar_validation(self):
        local = datetime(2030, 1, 1, tzinfo=timezone(timedelta(hours=3)))
        self.assertEqual(context(deadline=local).deadline, local.astimezone(UTC))
        for changes in (
            {"attempt": True},
            {"attempt": 0},
            {"attempt": 1001},
            {"deadline": datetime(2030, 1, 1)},
            {"payload": []},
            {"schema_version": False},
            {"work_id": ""},
        ):
            with (
                self.subTest(changes=tuple(changes)),
                self.assertRaises(InvalidWorkerConfiguration),
            ):
                context(**changes)


class AcquisitionContracts(unittest.TestCase):
    def test_explicit_bounds_snapshot_shared_capabilities(self):
        source = [
            Capability(command_type="z", schema_version=2),
            Capability(command_type="a", schema_version=1),
        ]
        value = AcquireRequest(capabilities=source, limit=2, discovery_budget=3)
        source.clear()
        self.assertEqual(tuple(c.command_type for c in value.capabilities), ("a", "z"))
        with self.assertRaises(FrozenInstanceError):
            value.limit = 3
        for changes in (
            {"limit": True},
            {"limit": 0},
            {"limit": 257},
            {"discovery_budget": 0},
            {"discovery_budget": 4097},
            {"discovery_budget": True},
        ):
            with self.assertRaises(InvalidWorkerConfiguration):
                replace(value, **changes)
        with self.assertRaises(InvalidWorkerConfiguration):
            replace(value, capabilities=[])
        with self.assertRaises(InvalidWorkerConfiguration):
            replace(value, capabilities=[value.capabilities[0]] * 2)
        with self.assertRaises(InvalidWorkerConfiguration):
            replace(value, capabilities=[("a", 1)])
        with self.assertRaises(InvalidWorkerConfiguration):
            replace(
                value,
                capabilities=[
                    Capability(command_type="a", schema_version=i + 1) for i in range(257)
                ],
            )

    def test_mutated_shared_scalar_is_revalidated_not_trusted(self):
        cap = Capability(command_type="send", schema_version=1)
        object.__setattr__(cap, "schema_version", 2**31)
        with self.assertRaises(PersistenceError) as caught:
            AcquireRequest(capabilities=[cap], limit=1, discovery_budget=1)
        self.assertIs(caught.exception.code, ErrorCode.LOCAL_INVALID_ARGUMENT)

    def test_settings_required_and_runtime_options_held(self):
        self.assertEqual(
            WorkerSettings(acquire_limit=256, discovery_budget=4096).acquire_limit, 256
        )
        with self.assertRaises(TypeError):
            WorkerSettings()
        with self.assertRaises(TypeError):
            WorkerSettings(acquire_limit=1, discovery_budget=1, execution_slots=1)
        for limit, budget in ((True, 1), (0, 1), (257, 257), (2, 1), (1, 4097), (1, float("inf"))):
            with self.assertRaises(InvalidWorkerConfiguration):
                WorkerSettings(acquire_limit=limit, discovery_budget=budget)

    def test_application_owned_work_handles_need_no_generic_record(self):
        class Source:
            renewal_owner = RenewalOwner.SOURCE

            def acquire(self, request):
                return ("existing-erp-row",)

            def execute(self, work):
                self.executed = work

            def cancel(self, work):
                self.cancelled = work

            def shutdown(self):
                self.closed = True

        source: WorkSource[str] = Source()
        request = AcquireRequest(
            capabilities=[Capability(command_type="send", schema_version=1)],
            limit=1,
            discovery_budget=1,
        )
        (work,) = source.acquire(request)
        self.assertEqual(work, "existing-erp-row")
        self.assertFalse(hasattr(source, "executed"))
        source.execute(work)
        source.cancel(work)
        source.shutdown()
        self.assertEqual(source.executed, work)
        self.assertEqual(source.cancelled, work)
        self.assertTrue(source.closed)
        self.assertIs(source.renewal_owner, RenewalOwner.SOURCE)


class AsyncSourceContracts(unittest.IsolatedAsyncioTestCase):
    async def test_async_hooks_are_explicitly_awaited_by_application(self):
        class Source:
            renewal_owner = RenewalOwner.SOURCE

            async def acquire(self, request):
                return (object(),)

            async def execute(self, work):
                self.executed = work

            async def cancel(self, work):
                self.cancelled = work

            async def shutdown(self):
                self.closed = True

        source: AsyncWorkSource[object] = Source()
        request = AcquireRequest(
            capabilities=[Capability(command_type="send", schema_version=1)],
            limit=1,
            discovery_budget=1,
        )
        (work,) = await source.acquire(request)
        self.assertFalse(hasattr(source, "executed"))
        await source.execute(work)
        await source.cancel(work)
        await source.shutdown()
        self.assertIs(source.executed, work)
        self.assertIs(source.cancelled, work)
        self.assertTrue(source.closed)


class ImportContracts(unittest.TestCase):
    def test_root_import_without_siblings_or_optional_dependencies(self):
        # A clean process catches accidental eager imports hidden by this suite's shared imports.
        script = """
import importlib.abc, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'modkit_events','redis','sqlalchemy','psycopg','asyncpg','pydantic'}:
            raise AssertionError('Unexpected dependency import: ' + fullname)
sys.meta_path.insert(0, Block())
import modkit_workers
assert 'HandlerRegistry' in modkit_workers.__all__
assert not hasattr(modkit_workers, 'JobWorker')
assert not hasattr(modkit_workers, 'EventWorker')
"""
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        result = subprocess.run(
            [sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=10
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
