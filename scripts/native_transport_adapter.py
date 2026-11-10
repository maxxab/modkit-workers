"""Fixed native-transport adapter. Import and CLI are inert, never authorization.

Only an explicitly reviewed runner may construct/use this adapter. Offline fake
tests are cooperative instrumentation, not proof of native readiness. No retry
or implicit cleanup is performed after an uncertain operation.
"""

import base64
import csv
import hashlib
import importlib
import importlib.machinery
import importlib.util
import io
import json
import os
import platform
import stat
import sys
import sysconfig
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 64 * 1024 * 1024
MAX_FILES = 2048


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _host():
    facts = dict(
        implementation=sys.implementation.name,
        version=tuple(sys.version_info),
        platform=sys.platform,
        machine=platform.machine(),
        gil=bool(sys._is_gil_enabled()) if hasattr(sys, "_is_gil_enabled") else True,
        debug=bool(sysconfig.get_config_var("Py_DEBUG")),
        isolated=bool(sys.flags.isolated),
        optimized=bool(sys.flags.optimize),
    )
    _require(
        not sysconfig.get_config_var("Py_GIL_DISABLED")
        and facts
        == dict(
            implementation="cpython",
            version=(3, 13, 5, "final", 0),
            platform="linux",
            machine="x86_64",
            gil=True,
            debug=False,
            isolated=True,
            optimized=False,
        ),
        "host profile refused",
    )
    return facts


def _regular(path, limit=MAX_FILE):
    """Reject symlinks in every component; bounded reads, not an RSS guarantee."""
    path = Path(os.path.abspath(path))
    for part in (path, *path.parents):
        _require(not part.is_symlink(), "symlink path refused")
    _require(path.is_file() and path.stat().st_size <= limit, "file size or type refused")
    with path.open("rb") as stream:
        # Never request a sentinel byte beyond the reserved read allowance.
        value = stream.read(limit)
        _require(os.fstat(stream.fileno()).st_size <= limit, "file read bound exceeded")
    return value


class _ReadBudget:
    """One bounded verification pass, not cumulative lifetime I/O or RSS."""

    def __init__(self):
        self.remaining = MAX_TOTAL

    def read(self, path):
        # Refuse before opening the next file. Also cap the actual read to the
        # remaining allowance, so growth since stat cannot overrun the budget.
        _require(path.stat().st_size <= self.remaining, "aggregate total bound exceeded")
        value = _regular(path, limit=min(MAX_FILE, self.remaining))
        _require(len(value) <= self.remaining, "aggregate total bound exceeded")
        self.remaining -= len(value)
        return value


def _member(name):
    path = PurePosixPath(name)
    _require(
        type(name) is str
        and name == path.as_posix()
        and not path.is_absolute()
        and bool(path.parts)
        and not any(p in ("..", ".") for p in path.parts)
        and "\\" not in name,
        "unsafe member path",
    )
    return path


def _record(raw, payload, record):
    rows = list(csv.reader(io.StringIO(raw.decode("utf-8"))))
    _require(
        len(rows) == len(payload)
        and all(len(row) == 3 for row in rows)
        and {row[0] for row in rows} == set(payload),
        "RECORD inventory refused",
    )
    for name, digest, size in rows:
        if name == record:
            _require((digest, size) == ("", ""), "RECORD self hash refused")
        else:
            data = payload[name]
            wanted = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip("=")
            _require((digest, size) == ("sha256=" + wanted, str(len(data))), "RECORD bytes refused")


def _tree(root):
    _require(root.is_dir() and not root.is_symlink(), "distribution directory refused")
    files = set()
    entries = 0
    for base, directories, names in os.walk(root, followlinks=False):
        entries += len(directories) + len(names)
        _require(entries <= MAX_FILES, "distribution entry bound exceeded")
        for name in directories + names:
            _require(not (Path(base) / name).is_symlink(), "distribution symlink refused")
        files.update(Path(base) / name for name in names)
        _require(len(files) <= MAX_FILES, "distribution file bound exceeded")
    return files


def _verify_wheel(wheel, digest, package, version, site):
    wheel, site = Path(wheel), Path(site)
    raw = _regular(wheel)
    _require(hashlib.sha256(raw).hexdigest() == digest, "wheel digest refused")
    _require(wheel.name == f"{package}-{version}-py3-none-any.whl", "wheel name refused")
    info = f"{package}-{version}.dist-info/"
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        entries = archive.infolist()
        _require(len(entries) <= MAX_FILES, "wheel file bound exceeded")
        _require(len({i.filename for i in entries}) == len(entries), "duplicate wheel member")
        _require(sum(i.file_size for i in entries) <= MAX_TOTAL, "wheel total bound exceeded")
        for entry in entries:
            _member(entry.filename)
            _require(
                not entry.is_dir()
                and entry.file_size <= MAX_FILE
                and stat.S_IFMT(entry.external_attr >> 16) in (0, stat.S_IFREG)
                and entry.filename.startswith((package + "/", info)),
                "wheel member refused",
            )
        payload = {entry.filename: archive.read(entry) for entry in entries}
    record = info + "RECORD"
    _require(record in payload and info + "METADATA" in payload, "wheel metadata missing")
    _record(payload[record], payload, record)
    metadata = BytesParser().parsebytes(payload[info + "METADATA"])
    _require(
        metadata.get_all("Name") == [package.replace("_", "-")]
        and metadata.get_all("Version") == [version],
        "distribution identity refused",
    )
    actual = _tree(site / package) | _tree(site / info)
    # pip may write only these installation metadata additions. No bytecode or
    # executable additions are permitted; the reviewed runner must use --no-compile.
    extras = actual - {site / name for name in payload}
    permitted = {site / (info + name) for name in ("INSTALLER", "REQUESTED", "direct_url.json")}
    _require(extras <= permitted, "extra installed distribution file")
    _require({site / name for name in payload} <= actual, "missing installed distribution file")
    installed = {}
    budget = _ReadBudget()
    for path in sorted(actual):
        name = path.relative_to(site).as_posix()
        installed[name] = budget.read(path)
        if name in payload and name != record:
            _require(installed[name] == payload[name], "installed byte mismatch")
    if site / (info + "INSTALLER") in extras:
        _require(installed[info + "INSTALLER"] == b"pip\n", "installer metadata refused")
    if site / (info + "REQUESTED") in extras:
        _require(installed[info + "REQUESTED"] == b"", "requested metadata refused")
    if site / (info + "direct_url.json") in extras:
        direct = json.loads(installed[info + "direct_url.json"])
        accepted = (
            {"hash": "sha256=" + digest},
            {"hashes": {"sha256": digest}},
            {"hash": "sha256=" + digest, "hashes": {"sha256": digest}},
        )
        _require(
            any(
                direct == {"url": wheel.absolute().as_uri(), "archive_info": info}
                for info in accepted
            ),
            "direct URL metadata refused",
        )
    _record(installed[record], installed, record)
    return {site / name: hashlib.sha256(data).hexdigest() for name, data in installed.items()}


def _check_origins(package, site, files):
    spec = importlib.machinery.PathFinder.find_spec(package, sys.path)
    _require(spec is not None and spec.origin is not None, "missing import origin")
    _require(Path(spec.origin) == site / package / "__init__.py", "shadowed import origin")
    budget = _ReadBudget()
    for name, module in tuple(sys.modules.items()):
        if name == package or name.startswith(package + "."):
            origin = getattr(module, "__file__", None)
            spec = getattr(module, "__spec__", None)
            _require(
                origin is not None and spec is not None and spec.origin == origin,
                "preloaded import origin refused",
            )
            path = Path(origin)
            _require(
                path in files and hashlib.sha256(budget.read(path)).hexdigest() == files[path],
                "preloaded import origin or bytes refused",
            )
            locations = getattr(module, "__path__", None)
            if locations is not None:
                _require(list(locations) == [str(path.parent)], "package search path refused")


def create_adapter(events_wheel, workers_wheel):
    """Explicit offline construction, with local artifacts only; never connects."""
    return Adapter(events_wheel, workers_wheel)


def _support(name, digest):
    path = Path(__file__).absolute().parent / (name + ".py")
    raw = _regular(path)
    _require(hashlib.sha256(raw).hexdigest() == digest, "support source digest refused")
    module = SimpleNamespace(__name__=name, __file__=str(path))
    # Execute the bytes just checked, not a second read or an unverified pyc.
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def _driver_files(site, package):
    info = f"{package}-3.3.8.dist-info"
    roots = [site / package, site / info]
    if package == "psycopg_binary":
        roots.append(site / "psycopg_binary.libs")
    paths = set().union(*(_tree(root) for root in roots))
    _require(len(paths) <= MAX_FILES, "driver file bound exceeded")
    budget = _ReadBudget()
    payload = {path.relative_to(site).as_posix(): budget.read(path) for path in sorted(paths)}
    metadata = BytesParser().parsebytes(payload[info + "/METADATA"])
    _require(
        metadata.get_all("Name") == [package.replace("_", "-")]
        and metadata.get_all("Version") == ["3.3.8"],
        "driver identity refused",
    )
    _record(payload[info + "/RECORD"], payload, info + "/RECORD")
    # Driver identity is the reviewed version plus installed RECORD and measured
    # binary/libpq facts, not an unprovided upstream wheel digest attestation.
    return {site / name: hashlib.sha256(data).hexdigest() for name, data in payload.items()}


def _verified_inputs(events_wheel, workers_wheel, helper):
    facts = _host()
    _require(
        not any(
            name.split(".")[0] in ("modkit_events", "modkit_workers", "psycopg", "psycopg_binary")
            for name in sys.modules
        ),
        "preloaded dependency refused",
    )
    prefix = Path(sys.prefix).absolute()
    site = Path(sysconfig.get_path("purelib")).absolute()
    checkout = Path(__file__).absolute().parents[1]
    _require(
        sys.prefix != sys.base_prefix
        and site.is_relative_to(prefix)
        and not prefix.is_relative_to(checkout)
        and not checkout.is_relative_to(prefix)
        and sys.dont_write_bytecode,
        "outside-checkout isolated venv required",
    )
    _require(
        not any((parent / ".git").exists() for parent in (prefix, *prefix.parents)),
        "venv is inside a checkout",
    )
    files = {}
    for wheel, package, version, key in (
        (events_wheel, "modkit_events", "0.2.0", "events_wheel"),
        (workers_wheel, "modkit_workers", "0.1.0", "workers_wheel"),
    ):
        files.update(_verify_wheel(wheel, helper.PROFILE[key], package, version, site))
        facts[key] = hashlib.sha256(_regular(wheel)).hexdigest()
    for package in ("psycopg", "psycopg_binary"):
        files.update(_driver_files(site, package))
    for package in ("modkit_events", "modkit_workers", "psycopg", "psycopg_binary"):
        _check_origins(package, site, files)
    _require(
        "modkit_events.persistence.native_sync" not in sys.modules, "native issuer already loaded"
    )
    facts.update(
        outside_checkout_venv=True,
        installed_provenance=True,
        events_source=helper.PROFILE["events_source"],
    )
    # The source ID is the reviewed identity associated with the exact wheel
    # digest, not an assertion about any mutable local Events checkout.
    return facts, site, files


FRESHNESS = (
    "SELECT current_setting('server_version_num')::int, current_database(), session_user, current_user",
    "SELECT rolname FROM pg_roles WHERE rolname !~ '^pg_' ORDER BY rolname",
    "SELECT nspname FROM pg_namespace WHERE nspname !~ '^pg_' AND nspname NOT IN ('public','information_schema') ORDER BY nspname",
    "SELECT 'relation',relname::text FROM pg_class WHERE relnamespace='public'::regnamespace "
    "UNION ALL SELECT 'function',proname::text FROM pg_proc WHERE pronamespace='public'::regnamespace "
    "UNION ALL SELECT 'type',typname::text FROM pg_type WHERE typnamespace='public'::regnamespace "
    "ORDER BY 1,2",
)
BOOTSTRAP = (
    ("REVOKE ALL ON DATABASE modkit_workers_ci FROM PUBLIC",)
    + tuple(
        statement
        for suffix in ("owner", "runtime", "reconciler", "operator")
        for statement in (
            f"CREATE ROLE modkit_{suffix} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
            f"CREATE ROLE modkit_ci_{suffix}_login LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD 'modkit-ci-public-fixture-only'",
            f"GRANT modkit_{suffix} TO modkit_ci_{suffix}_login WITH INHERIT FALSE, SET TRUE",
            f"GRANT CONNECT ON DATABASE modkit_workers_ci TO modkit_ci_{suffix}_login",
        )
    )
    + ("GRANT CREATE ON DATABASE modkit_workers_ci TO modkit_owner",)
)
PREFLIGHT = (
    "SELECT session_user,current_user,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,"
    "has_function_privilege(current_user,'pg_catalog.pg_xact_status(xid8)','EXECUTE'),"
    "has_function_privilege(current_user,'modkit_events.e33(text)','EXECUTE') "
    "FROM pg_catalog.pg_roles WHERE rolname=session_user"
)


class Adapter:
    """Concrete protocol implementation; use create_adapter for measured inputs.

    Private Python state/test seams are cooperative, not a security sandbox.
    The accepted Harness owns the finite schedule and native handle lifetimes.
    """

    def __init__(self, events_wheel, workers_wheel):
        helper = _support(
            "check_native_transport",
            "277147dbaeef067c7dddee516aef44e5b21e09745141edd428ba395648bf93b2",
        )
        installer = _support(
            "check_postgres", "fa71a090fa00f9ffd20224e3a16544542ddeeccd62aff53f78e291bfa1dddb44"
        )
        facts, site, files = _verified_inputs(events_wheel, workers_wheel, helper)
        self.helper, self.installer = helper, installer
        self.facts, self.site, self.files = facts, site, files
        self.failed = False
        self.driver = None
        self.modules = None
        self.handles = {}
        self.attempted = set()
        self.components = None
        self.observed_receipts = False

    def _guard(self):
        _require(not self.failed, "UNKNOWN adapter; no retry or cleanup")
        if self.modules is not None:
            _require(not self.modules.ledger.uncertainty.present, "UNKNOWN ledger; no cleanup")

    def _attempt(self, action, *args, **kwargs):
        self._guard()
        try:
            return action(*args, **kwargs)
        except BaseException:
            self.failed = True
            raise

    def _import(self, name):
        roots = {self.site / path.relative_to(self.site).parts[0] for path in self.files}
        current = set().union(*(_tree(root) for root in roots))
        _require(current == set(self.files), "installed inventory changed before import")
        budget = _ReadBudget()
        for path, digest in sorted(self.files.items()):
            _require(
                hashlib.sha256(budget.read(path)).hexdigest() == digest,
                "installed bytes changed before import",
            )
        for package in ("modkit_events", "modkit_workers", "psycopg", "psycopg_binary"):
            _check_origins(package, self.site, self.files)
        parent = name.rpartition(".")[0]
        if parent and parent not in sys.modules:
            self._import(parent)
        spec = importlib.util.find_spec(name)
        _require(
            spec is not None and spec.origin is not None and Path(spec.origin) in self.files,
            "selected import origin refused",
        )
        module = importlib.import_module(name)
        for package in ("modkit_events", "modkit_workers", "psycopg", "psycopg_binary"):
            _check_origins(package, self.site, self.files)
        return module

    def profile(self):
        return self._attempt(self._profile)

    def _profile(self):
        _require(self.driver is None, "profile already consumed")
        self.driver = self._import("psycopg")
        self.facts.update(
            driver=self.driver.__version__,
            libpq=self.driver.pq.version(),
            pq_impl=self.driver.pq.__impl__,
        )
        self.helper.validate_profile(self.facts)
        apis = tuple(
            self._import(f"modkit_{name}.persistence.migrations") for name in ("events", "workers")
        )
        manifests = tuple(api.manifest() for api in apis)
        _require(
            all(type(items) is tuple and len(items) == 1 for items in manifests),
            "migration inventory refused",
        )
        migrations = tuple(items[0] for items in manifests)
        self.installer.validate_pair(*migrations, self.helper.EXPECTED_RECEIPTS[0][2].hex())
        components = []
        receipt = apis[0].read_owner_receipt(migrations[0])
        for index, (api, migration) in enumerate(zip(apis, migrations)):
            _require(
                self.installer.receipt_values(migration) == self.helper.EXPECTED_RECEIPTS[index],
                "immutable migration receipt refused",
            )
            _require(
                [r.path.rsplit("/", 1)[-1] for r in migration.resources]
                == ["0001_initial.sql", "grants_runtime.sql"],
                "migration resources refused",
            )
            components.append(
                (migration, tuple(api.read_sql(migration, r) for r in migration.resources), receipt)
            )
        self.components = tuple(components)
        return dict(self.facts)

    def _connect(self, kind, options):
        self._guard()
        _require(
            not any(key.startswith("PG") for key in os.environ), "PostgreSQL environment refused"
        )
        _require(
            self.components is not None and kind not in self.attempted,
            "profile missing or connection already attempted",
        )
        expected = self.helper.connection_options(kind)
        _require(
            type(options) is dict
            and options.keys() == expected.keys()
            and all(type(options[k]) is type(v) and options[k] == v for k, v in expected.items()),
            "fixed connection options refused",
        )
        self.attempted.add(kind)
        handle = self._attempt(self.driver.connect, **expected)
        self.handles[kind] = handle
        return handle

    def connect_bootstrap(self, options):
        return self._connect("bootstrap", options)

    def connect_owner(self, options):
        return self._connect("owner", options)

    def connect_observer(self, options):
        return self._connect("observer", options)

    def _handle(self, kind, handle):
        self._guard()
        _require(kind in self.handles and self.handles[kind] is handle, "foreign handle refused")

    def freshness(self, handle, index):
        self._handle("bootstrap", handle)
        _require(type(index) is int and 0 <= index < 4, "freshness index refused")

        def read():
            cursor = handle.execute(FRESHNESS[index])
            if index == 0:
                return cursor.fetchone()
            if index in (1, 2):
                return [row[0] for row in cursor]
            return cursor.fetchall()

        return self._attempt(read)

    def _transaction(self, kind, handle, sql):
        self._handle(kind, handle)

        def execute():
            cursor = handle.execute(sql)
            if sql in ("BEGIN", "COMMIT"):
                _require(cursor.statusmessage == sql, "transaction acknowledgement refused")

        self._attempt(execute)

    def bootstrap_begin(self, handle):
        self._transaction("bootstrap", handle, "BEGIN")

    def bootstrap_commit(self, handle):
        self._transaction("bootstrap", handle, "COMMIT")

    def owner_begin(self, handle):
        self._transaction("owner", handle, "BEGIN")

    def owner_commit(self, handle):
        self._transaction("owner", handle, "COMMIT")

    def bootstrap_statement(self, handle, index):
        _require(type(index) is int and 0 <= index < 18, "bootstrap index refused")
        self._transaction("bootstrap", handle, BOOTSTRAP[index])

    def install_component(self, handle, index):
        self._handle("owner", handle)
        _require(type(index) is int and 0 <= index < 2, "component index refused")
        return self._attempt(
            self.installer.install_component, handle, self.driver, *self.components[index]
        )

    def _close(self, kind, handle):
        self._handle(kind, handle)
        self._attempt(handle.close)
        del self.handles[kind]

    def close_bootstrap(self, handle):
        self._close("bootstrap", handle)

    def close_owner(self, handle):
        self._close("owner", handle)

    def close_observer(self, handle):
        self._close("observer", handle)

    def observer_preflight(self, handle):
        self._handle("observer", handle)
        return self._attempt(lambda: handle.execute(PREFLIGHT).fetchone())

    def observer_receipts(self, handle):
        self._handle("observer", handle)
        rows = self._attempt(
            lambda: tuple(
                handle.execute("SELECT * FROM modkit_events.e33(%s)", ("workers",)).fetchall()
            )
        )
        self.observed_receipts = rows == self.helper.EXPECTED_RECEIPTS
        return rows

    def observer_status(self, handle, xid):
        self._handle("observer", handle)
        _require(type(xid) is int and 0 <= xid < 2**64, "status XID refused")
        return self._attempt(
            lambda: handle.execute("SELECT pg_catalog.pg_xact_status(%s::xid8)", (xid,)).fetchone()[
                0
            ]
        )

    def load_native(self):
        return self._attempt(self._load_native)

    def _load_native(self):
        _require(
            self.modules is None and self.observed_receipts and set(self.handles) == {"observer"},
            "native prerequisites refused",
        )

        def module(name):
            return self._import("modkit_events.persistence." + name)

        ledger = module("ledger").ExecutionLedger()
        observations, bindings = module("observations"), module("bindings")
        expectation = bindings.ReadinessExpectation(
            components=tuple(
                observations.SchemaStatus(**dict(zip(self.helper.FIELDS, row)))
                for row in self.helper.EXPECTED_RECEIPTS
            )
        )
        self.modules = SimpleNamespace(
            ledger=ledger,
            managed=module("managed_lifecycle"),
            native=module("native_sync"),
            execution=module("native_execution"),
            catalog=module("catalog"),
            expectation=expectation,
        )
        return self.modules

    def connect_native(self, options, *, execution_ledger):
        self._guard()
        _require(
            not any(key.startswith("PG") for key in os.environ), "PostgreSQL environment refused"
        )
        _require(
            self.modules is not None
            and execution_ledger is self.modules.ledger
            and "native" not in self.attempted,
            "native connection prerequisites refused",
        )
        expected = self.helper.connection_options("native")
        _require(
            type(options) is dict
            and options.keys() == expected.keys()
            and all(type(options[k]) is type(v) and options[k] == v for k, v in expected.items()),
            "fixed native options refused",
        )
        self.attempted.add("native")
        handle = self._attempt(
            self.modules.native.ManagedConnection.connect,
            execution_ledger=execution_ledger,
            **expected,
        )
        self.handles["native"] = handle
        return handle


def main():
    raise ValueError("NOT_RUN: reviewed runner and separate native permission required")


if __name__ == "__main__":
    main()
