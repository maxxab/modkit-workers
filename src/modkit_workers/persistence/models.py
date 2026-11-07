"""Immutable worker requests; backend encoding is an explicit pure projection."""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import datetime
from types import MappingProxyType
from uuid import UUID

from modkit_events.persistence import bindings as common
from modkit_events.persistence import models as shared
from modkit_events.persistence.errors import _boundary
from modkit_events.persistence.scope import Scope, canonical_scope, encode_scope_fields


def _work_id(value: object) -> UUID:
    """Worker string convenience only; shared carriers continue to use UUID."""
    if type(value) is not str or len(value) != 36:
        raise ValueError
    parsed = UUID(value)
    if str(parsed) != value:
        raise ValueError
    return parsed


def _logical_json(value: object, depth: int = 0, active: set[int] | None = None) -> object:
    """Snapshot logical JSON without rendering/limiting arbitrary integers.

    This is not a canonical serializer or database scalar codec. Managed encoding
    and its tighter byte/depth/numeric budget belongs exclusively to foundation.
    """
    if depth > 64:
        raise ValueError
    if value is None or type(value) in (bool, int, str):
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError
        return value
    if active is None:
        active = set()
    if id(value) in active:
        raise ValueError
    active.add(id(value))
    try:
        if isinstance(value, Mapping):
            result = {}
            for key, item in value.items():
                if type(key) is not str or key in result:
                    raise ValueError
                result[key] = _logical_json(item, depth + 1, active)
            return MappingProxyType(result)
        if type(value) in (list, tuple):
            return tuple(_logical_json(item, depth + 1, active) for item in value)
        raise ValueError
    finally:
        active.remove(id(value))


@dataclass(frozen=True, slots=True, repr=False)
class JobInput:
    work_id: str
    command_type: str
    schema_version: int
    scope: Scope
    payload: Mapping[str, object]
    original_available_at: datetime = field(kw_only=True)
    protected: shared.ProtectedBindingInput = field(kw_only=True)
    deadline: datetime | None = field(default=None, kw_only=True)
    idempotency_key: str | None = field(default=None, kw_only=True)
    replay_policy: shared.ReplayPolicy = field(default=shared.ReplayPolicy.DISABLED, kw_only=True)
    max_attempts: int = field(default=1, kw_only=True)

    @_boundary
    def __post_init__(self) -> None:
        _work_id(self.work_id)
        common._identifier(self.command_type)
        if type(self.schema_version) is not int or self.schema_version < 1:
            raise ValueError
        canonical_scope(self.scope)  # Exact Scope type and all fields revalidated.
        if not isinstance(self.payload, Mapping):
            raise ValueError
        object.__setattr__(self, "payload", _logical_json(self.payload))
        object.__setattr__(
            self, "original_available_at", common._instant(self.original_available_at)
        )
        if self.deadline is not None:
            object.__setattr__(self, "deadline", common._instant(self.deadline))
        if self.idempotency_key is not None:
            common._identifier(self.idempotency_key)
        if type(self.replay_policy) is not shared.ReplayPolicy:
            raise ValueError
        common._integer(self.max_attempts, 1, 1000)
        if type(self.protected) is not shared.ProtectedBindingInput:
            raise ValueError
        object.__setattr__(self, "protected", replace(self.protected))

    @property
    @_boundary
    def scope_bytes(self) -> bytes:
        return canonical_scope(self.scope)

    @property
    @_boundary
    def semantic_input(self) -> bytes:
        return common.canonical_json(self.payload)

    @property
    @_boundary
    def replay_input(self) -> bytes:
        return common.encode_mapping_replay(self.payload)

    @property
    @_boundary
    def protected_binding(self) -> bytes:
        return common.canonical_protected_binding(self.protected).content

    @property
    @_boundary
    def evidence(self) -> shared.CanonicalEvidence:
        return common.canonical_intent(_admission(self))


def _admission(job: JobInput) -> shared.AdmissionInput:
    if type(job) is not JobInput:
        raise ValueError
    # Revalidate/copy all user fields at the prepared-request boundary.
    snapshot = replace(job)
    application, tenant, owner = encode_scope_fields(snapshot.scope)
    scope = shared.ScopeEvidence(
        canonical_version=1,
        canonical=canonical_scope(snapshot.scope),
        application=application,
        tenant=tenant,
        owner=owner,
    )
    identity = shared.WorkIdentity(
        work_id=_work_id(snapshot.work_id),
        kind=shared.WorkKind.JOB,
        subscription_id=None,
        namespace="jobs",
        command_type=snapshot.command_type,
        scope=scope,
        idempotency_key=snapshot.idempotency_key,
    )
    return shared.AdmissionInput(
        identity=identity,
        schema_version=snapshot.schema_version,
        semantic_input=common.canonical_json(snapshot.payload),
        replay_input=common.encode_mapping_replay(snapshot.payload),
        protected_binding=common.canonical_protected_binding(snapshot.protected).content,
        replay_policy=snapshot.replay_policy,
        max_attempts=snapshot.max_attempts,
        deadline=snapshot.deadline,
        original_available_at=snapshot.original_available_at,
    )


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobSubmitRequest:
    job: JobInput

    @_boundary
    def __post_init__(self) -> None:
        if type(self.job) is not JobInput:
            raise ValueError
        object.__setattr__(self, "job", replace(self.job))


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobReadRequest:
    work_id: str

    @_boundary
    def __post_init__(self) -> None:
        _work_id(self.work_id)


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobFindRequest:
    job: JobInput

    @_boundary
    def __post_init__(self) -> None:
        if type(self.job) is not JobInput:
            raise ValueError
        object.__setattr__(self, "job", replace(self.job))


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobAcquireRequest:
    capabilities: Iterable[shared.Capability]
    limit: int
    lease_seconds: int | float
    scan_after: UUID | None
    discovery_budget: int

    @_boundary
    def __post_init__(self) -> None:
        items = []
        keys = set()
        for position, capability in enumerate(self.capabilities):
            if position >= 256 or type(capability) is not shared.Capability:
                raise ValueError
            value = replace(capability)
            key = (
                common._identifier(value.command_type),
                common._integer(value.schema_version, 1, 2147483647),
            )
            if key in keys:
                raise ValueError
            keys.add(key)
            items.append(value)
        if not items:
            raise ValueError
        items.sort(key=lambda value: (common._identifier(value.command_type), value.schema_version))
        object.__setattr__(self, "capabilities", tuple(items))
        common._integer(self.limit, 1, 256)
        common._integer(self.discovery_budget, self.limit, 4096)
        if type(self.lease_seconds) not in (int, float) or not 0 < self.lease_seconds <= 3600:
            raise ValueError
        lease = float(self.lease_seconds)
        if not math.isfinite(lease):
            raise ValueError
        object.__setattr__(self, "lease_seconds", lease)
        if self.scan_after is not None and type(self.scan_after) is not UUID:
            raise ValueError


@dataclass(frozen=True, slots=True, kw_only=True, repr=False)
class JobListRequest:
    after: shared.WorkCursor | None
    limit: int

    @_boundary
    def __post_init__(self) -> None:
        common._integer(self.limit, 1, 256)
        if self.after is not None:
            if type(self.after) is not shared.WorkCursor:
                raise ValueError
            object.__setattr__(self, "after", replace(self.after))
