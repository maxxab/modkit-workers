"""Immutable execution observations, never protected/public or transaction authority."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from .handlers import InvalidWorkerConfiguration, _identifier, _version

if TYPE_CHECKING:
    from modkit_events.persistence.scope import Scope


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobContext:
    work_id: str
    command_type: str
    schema_version: int
    scope: Scope
    payload: Mapping[str, object]
    attempt: int
    deadline: datetime | None = None

    def __post_init__(self) -> None:
        if (
            not _identifier(self.work_id)
            or not _identifier(self.command_type)
            or not _version(self.schema_version)
            or type(self.attempt) is not int
            or not 1 <= self.attempt <= 1000
            or not isinstance(self.payload, Mapping)
        ):
            raise InvalidWorkerConfiguration("Invalid job context")
        if self.deadline is not None:
            if type(self.deadline) is not datetime or self.deadline.utcoffset() is None:
                raise InvalidWorkerConfiguration("Invalid job context deadline")
            object.__setattr__(self, "deadline", self.deadline.astimezone(UTC))
        # Lazy pure dependency: root import does not load persistence or drivers.
        from modkit_events.persistence.bindings import canonical_json, parse_canonical_json
        from modkit_events.persistence.scope import canonical_scope

        canonical_scope(self.scope)  # Preserve the shared detached ValueError boundary.
        object.__setattr__(self, "scope", replace(self.scope))
        frozen = parse_canonical_json(canonical_json(self.payload))
        object.__setattr__(self, "payload", cast(Mapping[str, object], frozen))
