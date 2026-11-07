"""Verified inert SQL resources. Applications own all migration execution.

No production manifest is supplied until the reviewed SQL closure exists.
Importing this module performs no resource reads or database operations.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import NoReturn, cast

from . import _resource_io as _io
from . import sql as _sql_anchor  # noqa: F401 - Initializes standard origin metadata.

__all__ = ["MigrationDependency", "SQLResource", "Migration", "manifest", "read_sql"]
_COMPONENT = "workers"
_PACKAGE = "modkit-workers"
_ANCHOR = "modkit_workers.persistence.sql"
_PATHS = {
    "events": ("events/0001_initial.sql", "events/grants_runtime.sql"),
    "workers": ("workers/0001_initial.sql", "workers/grants_runtime.sql"),
}
_IDS = ("modkit-pg-ab-2", "MKSC-1", "MKPF-1")
_MANIFEST_LIMIT = 65536


def _invalid() -> NoReturn:
    raise ValueError("invalid migration descriptor")


def _string(value: object) -> None:
    if type(value) is not str:
        _invalid()


def _digest(value: object) -> None:
    _string(value)
    value = cast(str, value)
    if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _invalid()


def _component_version(component: object, version: object) -> None:
    _string(component)
    if component not in _PATHS or type(version) is not int or version != 1:
        _invalid()


def _resource(value: object) -> None:
    if type(value) is not SQLResource:
        _invalid()
    try:
        _string(value.path)
        if value.path not in _PATHS["events"] + _PATHS["workers"]:
            _invalid()
        _digest(value.sha256)
    except AttributeError:
        _invalid()


def _dependency(value: object) -> None:
    if type(value) is not MigrationDependency:
        _invalid()
    try:
        _component_version(value.component, value.version)
        _digest(value.migration_digest)
    except AttributeError:
        _invalid()


def _aggregate(items: tuple[SQLResource, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(b"MKMF\x01")
    digest.update(len(items).to_bytes(4, "big"))
    for item in sorted(items, key=lambda item: item.path.encode("utf-8")):
        path = item.path.encode("utf-8")
        digest.update(len(path).to_bytes(4, "big"))
        digest.update(path)
        digest.update(bytes.fromhex(item.sha256))
    return digest.hexdigest()


def _migration(value: object) -> None:
    if type(value) is not Migration:
        _invalid()
    try:
        _component_version(value.component, value.version)
        _digest(value.migration_digest)
        if type(value.resources) is not tuple or len(value.resources) != 2:
            _invalid()
        for item in value.resources:
            _resource(item)
        if tuple(item.path for item in value.resources) != _PATHS[value.component]:
            _invalid()
        if type(value.depends_on) is not tuple:
            _invalid()
        for dependency in value.depends_on:
            _dependency(dependency)
        if value.component == "events":
            if value.depends_on:
                _invalid()
        elif len(value.depends_on) != 1 or value.depends_on[0].component != "events":
            _invalid()
        ids = (value.catalog_contract_id, value.scope_format_id, value.intent_format_id)
        for identifier in ids:
            _string(identifier)
        if ids != _IDS or _aggregate(value.resources) != value.migration_digest:
            _invalid()
    except AttributeError:
        _invalid()


@dataclass(frozen=True, slots=True, kw_only=True)
class SQLResource:
    path: str
    sha256: str

    def __post_init__(self) -> None:
        _resource(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class MigrationDependency:
    component: str
    version: int
    migration_digest: str

    def __post_init__(self) -> None:
        _dependency(self)


@dataclass(frozen=True, slots=True, kw_only=True)
class Migration:
    component: str
    version: int
    resources: tuple[SQLResource, ...]
    migration_digest: str
    depends_on: tuple[MigrationDependency, ...]
    catalog_contract_id: str
    scope_format_id: str
    intent_format_id: str

    def __post_init__(self) -> None:
        _migration(self)


def _pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("invalid migration manifest")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ValueError("invalid migration manifest")


def _keys(value: object, expected: set[str]) -> None:
    if type(value) is not dict or set(value) != expected:
        raise ValueError("invalid migration manifest")


def _parse(raw: bytes) -> tuple[Migration, ...]:
    try:
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant
        )
    except (ValueError, RecursionError):
        raise ValueError("invalid migration manifest") from None
    _keys(document, {"format_version", "package", "migrations"})
    if type(document["format_version"]) is not int or document["format_version"] != 1:
        raise ValueError("invalid migration manifest")
    if type(document["package"]) is not str or document["package"] != _PACKAGE:
        raise ValueError("invalid migration manifest")
    entries = document["migrations"]
    if type(entries) is not list or len(entries) != 1:
        raise ValueError("invalid migration manifest")
    entry = entries[0]
    _keys(
        entry,
        {
            "component",
            "version",
            "resources",
            "migration_digest",
            "depends_on",
            "catalog_contract_id",
            "scope_format_id",
            "intent_format_id",
        },
    )
    if type(entry["resources"]) is not list or len(entry["resources"]) != 2:
        raise ValueError("invalid migration manifest")
    if type(entry["depends_on"]) is not list or len(entry["depends_on"]) > 1:
        raise ValueError("invalid migration manifest")
    items = []
    for item in entry["resources"]:
        _keys(item, {"path", "sha256"})
        items.append(SQLResource(**item))
    dependencies = []
    for dependency in entry["depends_on"]:
        _keys(dependency, {"component", "version", "migration_digest"})
        dependencies.append(MigrationDependency(**dependency))
    fields = {key: value for key, value in entry.items() if key not in {"resources", "depends_on"}}
    migration = Migration(resources=tuple(items), depends_on=tuple(dependencies), **fields)
    if migration.component != _COMPONENT:
        raise ValueError("invalid migration manifest")
    return (migration,)


def _read_resource(resource: SQLResource, lease) -> bytes:
    raw = lease.read(resource.path.split("/")[1])
    if hashlib.sha256(raw).hexdigest() != resource.sha256:
        raise ValueError("migration resource digest mismatch")
    return raw


def _manifest(lease) -> tuple[Migration, ...]:
    raw = lease.read("manifest.json")
    migrations = _parse(raw)
    for migration in migrations:
        for resource in migration.resources:
            _read_resource(resource, lease)
    return migrations


def manifest() -> tuple[Migration, ...]:
    """Verify descriptors/resources in one anchored lease; never execute SQL."""
    with _io.open_lease(_ANCHOR) as lease:
        return _manifest(lease)


def read_sql(migration: Migration, resource: SQLResource, /) -> str:
    """Return verified UTF-8 SQL in one lease; caller owns all execution."""
    _migration(migration)
    _resource(resource)
    with _io.open_lease(_ANCHOR) as lease:
        available = _manifest(lease)
        if migration not in available or resource not in migration.resources:
            _invalid()
        raw = _read_resource(resource, lease)
        try:
            return raw.decode("utf-8")
        except UnicodeError:
            raise ValueError("invalid migration SQL encoding") from None
