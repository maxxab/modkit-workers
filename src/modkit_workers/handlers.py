"""Explicit immutable handler lookup; callbacks are never executed here."""

from __future__ import annotations

import inspect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from enum import Enum
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from modkit_events.contracts import ContractRegistry
    from modkit_events.subscriptions import Subscription

    from .context import JobContext
    from .work_source import AcquireRequest


class InvalidWorkerConfiguration(ValueError):
    """Invalid pure configuration; messages contain no application values."""


class DuplicateHandlerError(ValueError):
    pass


class ConflictingHandlerRouteError(ValueError):
    pass


class UnknownCommandType(LookupError):
    pass


class UnsupportedHandlerVersion(LookupError):
    pass


class HandlerKind(Enum):
    SYNC = "sync"
    ASYNC = "async"


class SyncJobHandler(Protocol):
    def __call__(self, context: JobContext, /) -> None: ...


class AsyncJobHandler(Protocol):
    async def __call__(self, context: JobContext, /) -> None: ...


def _identifier(value: object) -> bool:
    if type(value) is not str or not value.strip() or "\0" in value:
        return False
    try:
        return len(value.encode("utf-8")) <= 256
    except UnicodeError:
        return False


def _version(value: object) -> bool:
    return type(value) is int and value >= 1


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class HandlerRegistration:
    command_type: str
    schema_version: int
    handler: SyncJobHandler | AsyncJobHandler
    kind: HandlerKind
    route: str | None = None

    def __post_init__(self) -> None:
        if (
            not _identifier(self.command_type)
            or not _version(self.schema_version)
            or self.route is not None
            and not _identifier(self.route)
            or type(self.kind) is not HandlerKind
            or not callable(self.handler)
        ):
            raise InvalidWorkerConfiguration("Invalid handler registration")
        # Inspect direct and instance entrypoints without invoking application code.
        # Descriptor failures propagate; they are programmer errors, not invalid results.
        entrypoint = self.handler
        # Built-in partial only binds arguments; inspect the callable it preserves.
        # Do not unwrap arbitrary decorators or subclasses with custom behavior.
        while type(entrypoint) is partial:
            entrypoint = entrypoint.func
        entrypoints = (entrypoint, getattr(type(entrypoint), "__call__", None))
        if any(
            inspect.isgeneratorfunction(entry) or inspect.isasyncgenfunction(entry)
            for entry in entrypoints
        ):
            raise InvalidWorkerConfiguration("Unsupported handler entrypoint")
        asynchronous = any(inspect.iscoroutinefunction(entry) for entry in entrypoints)
        if asynchronous != (self.kind is HandlerKind.ASYNC):
            raise InvalidWorkerConfiguration("Handler kind does not match entrypoint")


@dataclass(frozen=True, slots=True, init=False, repr=False)
class HandlerRegistry:
    """One source/subscription's logical capabilities, without execution authority."""

    _registrations: tuple[HandlerRegistration, ...]
    _by_key: Mapping[tuple[str, int], HandlerRegistration]
    _routes: Mapping[str, str | None]

    def __init__(self, registrations: Iterable[HandlerRegistration]) -> None:
        ordered: list[HandlerRegistration] = []
        by_key: dict[tuple[str, int], HandlerRegistration] = {}
        routes: dict[str, str | None] = {}
        for index, registration in enumerate(registrations):
            if index >= 4096 or type(registration) is not HandlerRegistration:
                raise InvalidWorkerConfiguration("Invalid or excessive handler registrations")
            item = replace(registration)
            key = (item.command_type, item.schema_version)
            if key in by_key:
                raise DuplicateHandlerError("Duplicate handler registration")
            if item.command_type in routes and routes[item.command_type] != item.route:
                raise ConflictingHandlerRouteError("Command has conflicting handler routes")
            by_key[key] = item
            routes[item.command_type] = item.route
            ordered.append(item)
        object.__setattr__(self, "_registrations", tuple(ordered))
        object.__setattr__(self, "_by_key", MappingProxyType(by_key))
        object.__setattr__(self, "_routes", MappingProxyType(routes))

    def get(self, command_type: str, schema_version: int) -> HandlerRegistration:
        if not _identifier(command_type) or not _version(schema_version):
            raise InvalidWorkerConfiguration("Invalid handler lookup")
        if command_type not in self._routes:
            raise UnknownCommandType("Unknown command type")
        item = self._by_key.get((command_type, schema_version))
        if item is None:
            raise UnsupportedHandlerVersion("Unsupported handler schema version")
        return item

    def capabilities(self) -> frozenset[tuple[str, int]]:
        return frozenset(self._by_key)

    def registrations(self) -> tuple[HandlerRegistration, ...]:
        return self._registrations

    def validate_acquisition(self, request: AcquireRequest, /) -> AcquireRequest:
        """Copy an explicit durable subset and check its exact registered pairs."""
        if type(self) is not HandlerRegistry:
            raise InvalidWorkerConfiguration("Expected HandlerRegistry")
        from .work_source import AcquireRequest

        if type(request) is not AcquireRequest:
            raise InvalidWorkerConfiguration("Expected AcquireRequest")
        snapshot = replace(request)
        for capability in snapshot.capabilities:
            self.get(capability.command_type, capability.schema_version)
        return snapshot

    def validate_subscription(
        self,
        subscription: Subscription,
        contracts: ContractRegistry,
        /,
        *,
        request: AcquireRequest,
    ) -> AcquireRequest:
        """Check local routes and shared logical/active subscription manifests."""
        if type(self) is not HandlerRegistry:
            raise InvalidWorkerConfiguration("Expected HandlerRegistry")
        from modkit_events.contracts import ContractRegistry
        from modkit_events.subscriptions import Subscription

        if type(subscription) is not Subscription or type(contracts) is not ContractRegistry:
            raise InvalidWorkerConfiguration("Expected Subscription and ContractRegistry")
        manifest = replace(subscription)
        snapshot = self.validate_acquisition(request)
        if any(item.route != manifest.route for item in self._registrations):
            raise InvalidWorkerConfiguration("Handler route does not match subscription")
        manifest.validate(contracts, handler_capabilities=self.capabilities())
        manifest.validate(
            contracts,
            handler_capabilities=(
                (item.command_type, item.schema_version) for item in snapshot.capabilities
            ),
        )
        return snapshot
