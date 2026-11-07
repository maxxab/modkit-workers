"""Application-owned synchronous/async work boundaries; no lifecycle implementation."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, replace
from enum import Enum
from typing import TYPE_CHECKING, Protocol, TypeVar

from .handlers import InvalidWorkerConfiguration
from .settings import _validate_bounds

if TYPE_CHECKING:
    from modkit_events.persistence.models import Capability

WorkT = TypeVar("WorkT")


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class AcquireRequest:
    capabilities: Iterable[Capability]
    limit: int
    discovery_budget: int

    def __post_init__(self) -> None:
        _validate_bounds(self.limit, self.discovery_budget)
        from modkit_events.persistence.models import Capability

        items: list[Capability] = []
        keys: set[tuple[str, int]] = set()
        for index, capability in enumerate(self.capabilities):
            if index >= 256 or type(capability) is not Capability:
                raise InvalidWorkerConfiguration("Invalid or excessive acquisition capabilities")
            item = replace(capability)  # Shared scalar/error contract; do not relabel.
            key = (item.command_type, item.schema_version)
            if key in keys:
                raise InvalidWorkerConfiguration("Duplicate acquisition capability")
            keys.add(key)
            items.append(item)
        if not items:
            raise InvalidWorkerConfiguration("Acquisition capabilities must not be empty")
        items.sort(key=lambda item: (item.command_type, item.schema_version))
        object.__setattr__(self, "capabilities", tuple(items))


class RenewalOwner(Enum):
    SOURCE = "source"


class WorkSource(Protocol[WorkT]):
    """Source owns transactions, execution, and the single renewal path."""

    @property
    def renewal_owner(self) -> RenewalOwner: ...
    def acquire(self, request: AcquireRequest, /) -> tuple[WorkT, ...]: ...
    def execute(self, work: WorkT, /) -> None: ...
    def cancel(self, work: WorkT, /) -> None: ...
    def shutdown(self) -> None: ...


class AsyncWorkSource(Protocol[WorkT]):
    """Async hooks are awaited explicitly; no synchronous offload is supplied."""

    @property
    def renewal_owner(self) -> RenewalOwner: ...
    async def acquire(self, request: AcquireRequest, /) -> tuple[WorkT, ...]: ...
    async def execute(self, work: WorkT, /) -> None: ...
    async def cancel(self, work: WorkT, /) -> None: ...
    async def shutdown(self) -> None: ...
