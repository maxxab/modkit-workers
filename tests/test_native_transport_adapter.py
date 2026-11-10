"""Offline concrete-adapter tests; real drivers and socket entrypoints are forbidden."""

import base64
import builtins
import hashlib
import importlib.util
import socket
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest


def load():
    path = Path(__file__).resolve().parents[1] / "scripts/native_transport_adapter.py"
    assert path.is_file(), "concrete source adapter is missing"
    spec = importlib.util.spec_from_file_location("concrete_adapter", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def no_sockets(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("offline test attempted a socket")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    original_import = builtins.__import__
    original_module = importlib.import_module

    def reject_package(name):
        if name.split(".")[0] in ("psycopg", "psycopg_binary", "modkit_events", "modkit_workers"):
            raise AssertionError("offline adapter test imported a real dependency")

    def guarded_import(name, *args, **kwargs):
        reject_package(name)
        return original_import(name, *args, **kwargs)

    def guarded_module(name, *args, **kwargs):
        reject_package(name)
        return original_module(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(importlib, "import_module", guarded_module)


def test_import_and_entry_are_inert():
    adapter = load()
    with pytest.raises(ValueError, match="NOT_RUN"):
        adapter.main()


def test_factory_does_not_accept_asserted_profile_or_target():
    adapter = load()
    with pytest.raises(TypeError):
        adapter.create_adapter(profile={}, host="elsewhere")


def test_constructor_does_not_accept_asserted_facts():
    adapter = load()
    with pytest.raises(TypeError):
        adapter.Adapter(helper=None, installer=None, facts={}, site=None, files={})


def test_actual_unqualified_host_refuses_before_import(monkeypatch):
    adapter = load()
    monkeypatch.setattr(
        adapter.importlib, "import_module", lambda name: pytest.fail("dependency imported")
    )
    with pytest.raises(ValueError, match="host"):
        adapter.create_adapter(Path("absent-events.whl"), Path("absent-workers.whl"))


def wheel_fixture(tmp_path, package="modkit_events", version="0.2.0"):
    info = package + f"-{version}.dist-info/"
    payload = {
        package + "/__init__.py": b"# inert fixture\n",
        info + "METADATA": f"Name: {package.replace('_', '-')}\nVersion: {version}\n".encode(),
        info + "WHEEL": b"Root-Is-Purelib: true\nTag: py3-none-any\n",
        info + "licenses/LICENSE": b"fixture",
        info + "RECORD": b"",
    }
    payload[info + "RECORD"] = "".join(
        f"{name},sha256={base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')},{len(data)}\n"
        if not name.endswith("/RECORD")
        else f"{name},,\n"
        for name, data in payload.items()
    ).encode()
    wheel = tmp_path / f"{package}-{version}-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, data in payload.items():
            archive.writestr(name, data)
    site = tmp_path / "site"
    for name, data in payload.items():
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return wheel, site, hashlib.sha256(wheel.read_bytes()).hexdigest()


def test_verified_wheel_measures_installed_bytes(tmp_path):
    adapter = load()
    wheel, site, digest = wheel_fixture(tmp_path)
    result = adapter._verify_wheel(wheel, digest, "modkit_events", "0.2.0", site)
    assert site / "modkit_events/__init__.py" in result


@pytest.mark.parametrize(
    "damage", ["hash", "bytes", "missing", "extra", "symlink", "parent_symlink"]
)
def test_wheel_provenance_refusals(tmp_path, damage):
    adapter = load()
    wheel, site, digest = wheel_fixture(tmp_path)
    target = site / "modkit_events/__init__.py"
    if damage == "hash":
        digest = "0" * 64
    elif damage == "bytes":
        target.write_bytes(b"changed")
    elif damage == "missing":
        target.unlink()
    elif damage == "extra":
        (target.parent / "extra.py").write_bytes(b"extra")
    elif damage == "symlink":
        original = tmp_path / "original"
        target.rename(original)
        target.symlink_to(original)
    else:
        alternate = tmp_path / "linked"
        alternate.symlink_to(site, target_is_directory=True)
        site = alternate
    with pytest.raises(ValueError):
        adapter._verify_wheel(wheel, digest, "modkit_events", "0.2.0", site)


def test_shadowed_import_refused(tmp_path, monkeypatch):
    adapter = load()
    wheel, site, digest = wheel_fixture(tmp_path)
    files = adapter._verify_wheel(wheel, digest, "modkit_events", "0.2.0", site)
    monkeypatch.setattr(adapter.sys, "path", [str(tmp_path / "shadow"), str(site)])
    shadow = tmp_path / "shadow/modkit_events"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("raise AssertionError('never execute')")
    with pytest.raises(ValueError, match="origin"):
        adapter._check_origins("modkit_events", site, files)


class Cursor:
    def __init__(self, rows, statusmessage=None):
        self.rows = rows
        self.statusmessage = statusmessage

    def fetchone(self):
        return self.rows[0]

    def fetchall(self):
        return list(self.rows)

    def __iter__(self):
        return iter(self.rows)


class Connection:
    def __init__(self, driver, kind):
        self.driver, self.kind = driver, kind

    def execute(self, sql, params=None, **kwargs):
        d = self.driver
        d.record((self.kind, "execute", sql, params, kwargs))
        if sql.startswith("SELECT current_setting"):
            rows = [(171100, "modkit_workers_ci", "modkit_ci_bootstrap", "modkit_ci_bootstrap")]
        elif sql.startswith("SELECT rolname"):
            rows = [("modkit_ci_bootstrap",)]
        elif sql.startswith("SELECT nspname") or sql.startswith("SELECT 'relation'"):
            rows = []
        elif sql == "SELECT session_user, current_user":
            rows = [("modkit_ci_owner_login", "modkit_owner")]
        elif sql.startswith("SELECT rolsuper"):
            rows = [(False,) * 5]
        elif sql.startswith("SELECT clock_timestamp"):
            rows = [(1,)]
        elif sql.startswith("SELECT component,version"):
            rows = [d.helper.EXPECTED_RECEIPTS[0 if params == ("events",) else 1] + (1,)]
        elif sql.startswith("SELECT session_user,current_user,"):
            rows = [d.native.identity]
        elif sql == "SELECT * FROM modkit_events.e33(%s)":
            assert params == ("workers",)
            rows = list(d.helper.EXPECTED_RECEIPTS)
        elif sql == "SELECT pg_catalog.pg_xact_status(%s::xid8)":
            assert params[0] in (101, 102)
            rows = [(next(d.native.statuses),)]
        else:
            rows = []
        return Cursor(rows, d.commit_tag if sql == "COMMIT" else sql)

    def close(self):
        self.driver.record((self.kind, "close"))


class Driver:
    """Recorder only: no inheritance from, or import of, any driver package."""

    __version__ = "3.3.8"
    pq = SimpleNamespace(version=lambda: 180006, __impl__="binary")
    sql = SimpleNamespace(SQL=lambda text: text, Identifier=lambda value: value)

    def __init__(self, helper, native):
        self.helper, self.native = helper, native
        self.calls = []
        self.failure = None
        self.commit_tag = "COMMIT"
        driver = self

        class RawCursor:
            def __init__(self, connection):
                self.connection = connection

            def __enter__(self):
                driver.record(("owner", "raw_enter"))
                return self

            def execute(self, sql, values):
                driver.record(("owner", "raw_execute", sql, values))

            def __exit__(self, *exc):
                driver.record(("owner", "raw_exit"))

        self.RawCursor = RawCursor

    def record(self, call):
        self.calls.append(call)
        if self.failure == len(self.calls) or (
            isinstance(self.failure, set) and len(self.calls) in self.failure
        ):
            raise RuntimeError("offline unknown")

    def connect(self, **options):
        kind = {
            "modkit_ci_bootstrap": "bootstrap",
            "modkit_ci_owner_login": "owner",
            "modkit_ci_operator_login": "observer",
        }[options["user"]]
        assert options == self.helper.connection_options(kind)
        self.record((kind, "connect", options))
        return Connection(self, kind)


def concrete_fixture(monkeypatch):
    from test_native_transport import FakeAdapter
    from test_native_transport import load as load_harness

    adapter = load()
    h = load_harness()
    native = FakeAdapter(h)
    driver = Driver(h, native)
    migrations = []
    apis = {}
    for component, values in zip(("events", "workers"), h.EXPECTED_RECEIPTS):
        migration = SimpleNamespace(**dict(zip(h.FIELDS, values)))
        migration.migration_digest = values[2].hex()
        migration.resources = tuple(
            SimpleNamespace(path=name)
            for name in ("sql/0001_initial.sql", "sql/grants_runtime.sql")
        )
        migrations.append(migration)
        apis[f"modkit_{component}.persistence.migrations"] = SimpleNamespace(
            manifest=lambda m=migration: (m,),
            read_sql=lambda m, r: m.component + ":" + r.path,
            read_owner_receipt=lambda m: "immutable owner receipt",
        )
    migrations[1].depends_on = (
        SimpleNamespace(
            component="events", version=1, migration_digest=migrations[0].migration_digest
        ),
    )
    apis["psycopg"] = driver

    def expectation(**kwargs):
        value = SimpleNamespace(**kwargs)
        native.modules.expectation = value
        return value

    for name, value in (
        ("managed_lifecycle", native),
        ("native_execution", native),
        ("catalog", native.modules.catalog),
        ("ledger", SimpleNamespace(ExecutionLedger=lambda: native.ledger)),
        ("observations", SimpleNamespace(SchemaStatus=lambda **kw: SimpleNamespace(**kw))),
        ("bindings", SimpleNamespace(ReadinessExpectation=expectation)),
    ):
        apis["modkit_events.persistence." + name] = value

    def native_connect(**kwargs):
        ledger = kwargs.pop("execution_ledger")
        assert ledger is native.ledger and kwargs == h.connection_options("native")
        driver.record(("native", "connect", kwargs))
        return object()

    apis["modkit_events.persistence.native_sync"] = SimpleNamespace(
        ManagedConnection=SimpleNamespace(connect=native_connect),
        **{
            name: getattr(native, name)
            for name in ("attach_native", "start_root", "rollback", "commit", "close")
        },
    )
    # Explicit cooperative seams replace all runtime measurements/imports, never
    # production authority. The real adapter, scheduler and installer still run.
    monkeypatch.setattr(adapter, "_verified_inputs", lambda *args: (dict(h.PROFILE), None, {}))
    monkeypatch.setattr(adapter.Adapter, "_import", lambda self, name: apis[name])
    actual = adapter.create_adapter(Path("fake-events"), Path("fake-workers"))
    return adapter, actual, h, native, driver


def test_actual_adapter_composes_with_accepted_harness(monkeypatch):
    _, actual, h, native, driver = concrete_fixture(monkeypatch)
    env = dict(
        GITHUB_ACTIONS="true",
        RUNNER_ENVIRONMENT="github-hosted",
        GITHUB_REPOSITORY="maxxab/modkit-workers",
        MODKIT_POSTGRES_TEST="workers-native-transport-v1",
    )
    harness = h.Harness(actual, env)
    harness.run()
    assert harness.status == "PASS_OFFLINE_OR_ADAPTER_ONLY"
    assert harness.counts == dict(connections=4, observer=7, catalog=6)
    assert not harness.handles
    calls = driver.calls
    assert [c[0] for c in calls if c[1] == "connect"] == [
        "bootstrap",
        "owner",
        "observer",
        "native",
    ]
    bootstrap = [c for c in calls if c[:2] == ("bootstrap", "execute")]
    assert len(bootstrap) == 24  # four SELECT + BEGIN + 18 mutations + COMMIT
    assert bootstrap[4][2] == "BEGIN" and bootstrap[-1][2] == "COMMIT"
    assert bootstrap[5][2] == "REVOKE ALL ON DATABASE modkit_workers_ci FROM PUBLIC"
    assert bootstrap[-2][2] == "GRANT CREATE ON DATABASE modkit_workers_ci TO modkit_owner"
    owner = [c for c in calls if c[0] == "owner" and c[1] in ("execute", "raw_execute")]
    assert len(owner) == 20  # BEGIN + actual helper's nine calls twice + COMMIT
    assert owner[0][2] == "BEGIN" and owner[-1][2] == "COMMIT"
    for offset, component in ((1, "events"), (10, "workers")):
        assert owner[offset][2] == "SET LOCAL ROLE modkit_owner"
        assert owner[offset + 1][2] == "SELECT session_user, current_user"
        assert owner[offset + 3][2:] == (
            component + ":sql/0001_initial.sql",
            None,
            {"prepare": False},
        )
        assert owner[offset + 4][2:] == (
            component + ":sql/grants_runtime.sql",
            None,
            {"prepare": False},
        )
        assert owner[offset + 6][1] == "raw_execute"
        assert owner[offset + 6][3] == h.EXPECTED_RECEIPTS[0 if component == "events" else 1]
    assert len([c for c in calls if c[:2] == ("observer", "execute")]) == 7
    assert [c[0] for c in calls if c[1] == "close"] == ["bootstrap", "owner", "observer"]
    assert actual.modules.expectation.components[0].component == "events"
    assert actual.modules.ledger is native.ledger


def test_adapter_rejects_changed_target_before_driver(monkeypatch):
    _, actual, h, _, driver = concrete_fixture(monkeypatch)
    actual.profile()
    with pytest.raises(ValueError):
        actual.connect_bootstrap({**h.connection_options("bootstrap"), "host": "elsewhere"})
    assert driver.calls == []


def env():
    return dict(
        GITHUB_ACTIONS="true",
        RUNNER_ENVIRONMENT="github-hosted",
        GITHUB_REPOSITORY="maxxab/modkit-workers",
        MODKIT_POSTGRES_TEST="workers-native-transport-v1",
    )


def test_every_driver_failure_stops_without_transaction_cleanup_or_retry(monkeypatch):
    _, actual, h, _, driver = concrete_fixture(monkeypatch)
    h.Harness(actual, env()).run()
    baseline = driver.calls
    for index in range(1, len(baseline) + 1):
        _, actual, h, _, driver = concrete_fixture(monkeypatch)
        driver.failure = index
        harness = h.Harness(actual, env())
        with pytest.raises(RuntimeError, match="offline unknown"):
            harness.run()
        assert harness.status == "UNKNOWN"
        # The immutable existing installer owns a RawCursor context. Its exit
        # runs after an execute failure, never a transaction rollback/retry.
        expected = baseline[:index]
        if baseline[index - 1][1] == "raw_execute":
            expected += [("owner", "raw_exit")]
        assert driver.calls == expected
        assert actual.failed
        before = list(driver.calls)
        with pytest.raises(ValueError, match="UNKNOWN"):
            actual.close_observer(actual.handles.get("observer"))
        assert driver.calls == before
        if baseline[index - 1][1] == "close":
            assert baseline[index - 1][0] in actual.handles


@pytest.mark.parametrize("operation", ["rollback", "commit", "close"])
def test_native_unknown_retains_harness_ownership(monkeypatch, operation):
    _, actual, h, native, driver = concrete_fixture(monkeypatch)
    native.unknown_after = (operation, 1)
    harness = h.Harness(actual, env())
    with pytest.raises(ValueError, match="UNKNOWN"):
        harness.run()
    assert harness.status == "UNKNOWN" and harness.handles
    assert not any(c[:2] == ("observer", "close") for c in driver.calls)
    assert "pending_native" in harness.handles


@pytest.mark.parametrize("field,value", [("__version__", "3.3.7"), ("__version__", 338)])
def test_driver_profile_refuses_before_connection(monkeypatch, field, value):
    _, actual, _, _, driver = concrete_fixture(monkeypatch)
    setattr(driver, field, value)
    with pytest.raises(ValueError, match="profile"):
        actual.profile()
    assert not driver.calls


@pytest.mark.parametrize("value", [180005, True, "180006"])
def test_measured_libpq_refuses_before_connection(monkeypatch, value):
    _, actual, _, _, driver = concrete_fixture(monkeypatch)
    driver.pq = SimpleNamespace(version=lambda: value, __impl__="binary")
    with pytest.raises(ValueError, match="profile"):
        actual.profile()
    assert not driver.calls


def test_other_driver_implementation_refuses(monkeypatch):
    _, actual, _, _, driver = concrete_fixture(monkeypatch)
    driver.pq = SimpleNamespace(version=lambda: 180006, __impl__="python")
    with pytest.raises(ValueError, match="profile"):
        actual.profile()
    assert not driver.calls


def test_native_loading_requires_setup_and_receipts(monkeypatch):
    _, actual, _, _, driver = concrete_fixture(monkeypatch)
    with pytest.raises(ValueError, match="prerequisites"):
        actual.load_native()
    assert driver.calls == [] and actual.modules is None


@pytest.mark.parametrize("index", [-1, 4, True, "0"])
def test_freshness_indices_refuse_without_sql(monkeypatch, index):
    _, actual, h, _, driver = concrete_fixture(monkeypatch)
    actual.profile()
    handle = actual.connect_bootstrap(h.connection_options("bootstrap"))
    with pytest.raises(ValueError, match="index"):
        actual.freshness(handle, index)
    assert len(driver.calls) == 1


def test_origin_refuses_preloaded_wrong_path_and_changed_bytes(tmp_path, monkeypatch):
    adapter = load()
    wheel, site, digest = wheel_fixture(tmp_path)
    files = adapter._verify_wheel(wheel, digest, "modkit_events", "0.2.0", site)
    monkeypatch.setattr(adapter.sys, "path", [str(site)])
    wrong = str(tmp_path / "wrong.py")
    module = SimpleNamespace(__file__=wrong, __spec__=SimpleNamespace(origin=wrong))
    monkeypatch.setitem(adapter.sys.modules, "modkit_events", module)
    with pytest.raises(ValueError, match="origin"):
        adapter._check_origins("modkit_events", site, files)
    target = site / "modkit_events/__init__.py"
    module.__file__ = module.__spec__.origin = str(target)
    target.write_bytes(b"changed after audit")
    with pytest.raises(ValueError, match="bytes"):
        adapter._check_origins("modkit_events", site, files)


def test_import_checks_selected_nested_spec_before_execution(tmp_path, monkeypatch):
    adapter = load()
    wrong = tmp_path / "unverified.py"
    monkeypatch.setattr(adapter, "_check_origins", lambda *args: None)
    monkeypatch.setattr(
        adapter.importlib.util, "find_spec", lambda name: SimpleNamespace(origin=str(wrong))
    )
    monkeypatch.setattr(
        adapter.importlib, "import_module", lambda name: pytest.fail("unverified import executed")
    )
    actual = object.__new__(adapter.Adapter)
    actual.site, actual.files = tmp_path, {}
    with pytest.raises(ValueError, match="origin"):
        actual._import("modkit_events.persistence.native_sync")


def test_host_rejects_free_threaded_build_even_with_gil_enabled(monkeypatch):
    adapter = load()
    monkeypatch.setattr(adapter.sys, "version_info", (3, 13, 5, "final", 0))
    monkeypatch.setattr(adapter.sys, "flags", SimpleNamespace(isolated=1, optimize=0))
    monkeypatch.setattr(adapter.sysconfig, "get_config_var", lambda key: key == "Py_GIL_DISABLED")
    with pytest.raises(ValueError, match="host"):
        adapter._host()


def write_record(site, info):
    paths = sorted(p for p in site.rglob("*") if p.is_file())
    record = site / info / "RECORD"
    record.write_text(
        "".join(
            f"{p.relative_to(site).as_posix()},sha256={base64.urlsafe_b64encode(hashlib.sha256(p.read_bytes()).digest()).decode().rstrip('=')},{p.stat().st_size}\n"
            if p != record
            else f"{p.relative_to(site).as_posix()},,\n"
            for p in paths
        )
    )


@pytest.mark.parametrize("style", ["hash", "hashes", "both"])
def test_known_pip_install_metadata_is_explicitly_supported(tmp_path, style):
    import json

    adapter = load()
    wheel, site, digest = wheel_fixture(tmp_path)
    info = "modkit_events-0.2.0.dist-info"
    (site / info / "INSTALLER").write_bytes(b"pip\n")
    (site / info / "REQUESTED").write_bytes(b"")
    archive_info = {}
    if style in ("hash", "both"):
        archive_info["hash"] = "sha256=" + digest
    if style in ("hashes", "both"):
        archive_info["hashes"] = {"sha256": digest}
    (site / info / "direct_url.json").write_text(
        json.dumps({"url": wheel.absolute().as_uri(), "archive_info": archive_info})
    )
    write_record(site, info)
    adapter._verify_wheel(wheel, digest, "modkit_events", "0.2.0", site)


@pytest.mark.parametrize(
    "damage", ["installer", "requested", "url", "record", "metadata", "pycache"]
)
def test_install_metadata_or_bytecode_cannot_bypass_exact_wheel(tmp_path, damage):
    import json

    adapter = load()
    wheel, site, digest = wheel_fixture(tmp_path)
    info = "modkit_events-0.2.0.dist-info"
    if damage == "installer":
        (site / info / "INSTALLER").write_bytes(b"other\n")
    elif damage == "requested":
        (site / info / "REQUESTED").write_bytes(b"not empty")
    elif damage == "url":
        (site / info / "direct_url.json").write_text(
            json.dumps({"url": "https://unrelated.invalid"})
        )
    elif damage == "metadata":
        (site / info / "METADATA").write_bytes(b"Name: modkit-events\nVersion: 999\n")
    elif damage == "pycache":
        cache = site / "modkit_events/__pycache__"
        cache.mkdir()
        (cache / "__init__.pyc").write_bytes(b"unverified executable")
    write_record(site, info)
    if damage == "record":
        (site / info / "RECORD").write_bytes(b"")
    with pytest.raises(ValueError):
        adapter._verify_wheel(wheel, digest, "modkit_events", "0.2.0", site)


@pytest.mark.parametrize("package", ["psycopg", "psycopg_binary"])
def test_driver_distribution_bytes_and_inventory(tmp_path, package):
    adapter = load()
    site = tmp_path / "site"
    info = package + "-3.3.8.dist-info"
    for name, data in {
        package + "/__init__.py": b"# fixture only",
        info + "/METADATA": f"Name: {package.replace('_', '-')}\nVersion: 3.3.8\n".encode(),
        info + "/RECORD": b"",
        **(
            {"psycopg_binary.libs/libpq-fixture.so": b"not a library"}
            if package == "psycopg_binary"
            else {}
        ),
    }.items():
        path = site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    write_record(site, info)
    assert site / package / "__init__.py" in adapter._driver_files(site, package)
    (site / package / "__init__.py").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="RECORD"):
        adapter._driver_files(site, package)


def test_guarded_import_rejects_new_file_since_measurement(tmp_path, monkeypatch):
    adapter = load()
    wheel, site, digest = wheel_fixture(tmp_path)
    files = adapter._verify_wheel(wheel, digest, "modkit_events", "0.2.0", site)
    actual = object.__new__(adapter.Adapter)
    actual.site, actual.files = site, files
    (site / "modkit_events/extra.py").write_bytes(b"new file")
    monkeypatch.setattr(adapter, "_check_origins", lambda *args: None)
    monkeypatch.setattr(
        adapter.importlib.util,
        "find_spec",
        lambda name: SimpleNamespace(origin=str(site / "modkit_events/__init__.py")),
    )
    monkeypatch.setattr(
        adapter.importlib, "import_module", lambda name: pytest.fail("import happened")
    )
    with pytest.raises(ValueError, match="inventory"):
        actual._import("modkit_events")


def test_actual_process_pg_environment_refuses_before_connection(monkeypatch):
    _, actual, h, _, driver = concrete_fixture(monkeypatch)
    actual.profile()
    monkeypatch.setenv("PGSERVICE", "unreviewed-target")
    with pytest.raises(ValueError, match="environment"):
        actual.connect_bootstrap(h.connection_options("bootstrap"))
    assert not driver.calls


def test_profile_refuses_preloaded_dependencies_before_import(tmp_path, monkeypatch):
    adapter = load()
    helper = SimpleNamespace(PROFILE={"events_wheel": "x", "workers_wheel": "y"})
    monkeypatch.setattr(adapter, "_host", lambda: {})
    prefix = tmp_path / "venv"
    monkeypatch.setattr(adapter.sys, "prefix", str(prefix))
    monkeypatch.setattr(adapter.sysconfig, "get_path", lambda name: str(prefix / "site"))
    monkeypatch.setitem(adapter.sys.modules, "psycopg", SimpleNamespace())
    with pytest.raises(ValueError, match="preloaded"):
        adapter._verified_inputs(Path("missing"), Path("missing"), helper)


def test_exact_freshness_and_bootstrap_inventory(monkeypatch):
    import ast

    module, _, _, _, _ = concrete_fixture(monkeypatch)
    source = Path(__file__).resolve().parents[1] / "scripts/check_postgres.py"
    tree = ast.parse(source.read_text())
    bootstrap = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "bootstrap"
    )
    # Compare against the independently accepted helper, parsed but not invoked.
    selects = sorted(
        (
            (node.lineno, node.args[0].value)
            for node in ast.walk(bootstrap)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
            and node.args[0].value.startswith("SELECT")
        ),
    )
    assert module.FRESHNESS == tuple(sql for _, sql in selects)
    expected = ["REVOKE ALL ON DATABASE modkit_workers_ci FROM PUBLIC"]
    for login, role in (
        ("modkit_ci_owner_login", "modkit_owner"),
        ("modkit_ci_runtime_login", "modkit_runtime"),
        ("modkit_ci_reconciler_login", "modkit_reconciler"),
        ("modkit_ci_operator_login", "modkit_operator"),
    ):
        expected.extend(
            [
                "CREATE ROLE "
                + role
                + " NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
                "CREATE ROLE "
                + login
                + " LOGIN NOINHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD 'modkit-ci-public-fixture-only'",
                "GRANT " + role + " TO " + login + " WITH INHERIT FALSE, SET TRUE",
                "GRANT CONNECT ON DATABASE modkit_workers_ci TO " + login,
            ]
        )
    expected.append("GRANT CREATE ON DATABASE modkit_workers_ci TO modkit_owner")
    assert module.BOOTSTRAP == tuple(expected)
    assert module.PREFLIGHT == (
        "SELECT session_user,current_user,rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,"
        "has_function_privilege(current_user,'pg_catalog.pg_xact_status(xid8)','EXECUTE'),"
        "has_function_privilege(current_user,'modkit_events.e33(text)','EXECUTE') "
        "FROM pg_catalog.pg_roles WHERE rolname=session_user"
    )


def test_receipt_execute_and_cursor_exit_failures_remain_unknown(monkeypatch):
    _, actual, h, _, driver = concrete_fixture(monkeypatch)
    h.Harness(actual, env()).run()
    count = next(i + 1 for i, call in enumerate(driver.calls) if call[1] == "raw_execute")
    _, actual, h, _, driver = concrete_fixture(monkeypatch)
    driver.failure = {count, count + 1}
    harness = h.Harness(actual, env())
    with pytest.raises(RuntimeError, match="offline unknown"):
        harness.run()
    assert len(driver.calls) == count + 1 and driver.calls[-1] == ("owner", "raw_exit")
    assert harness.status == "UNKNOWN" and "owner" in harness.handles


def test_bootstrap_commit_must_acknowledge_commit_not_rollback(monkeypatch):
    _, actual, h, _, driver = concrete_fixture(monkeypatch)
    driver.commit_tag = "ROLLBACK"
    harness = h.Harness(actual, env())
    with pytest.raises(ValueError, match="acknowledgement"):
        harness.run()
    assert harness.status == "UNKNOWN"
    assert driver.calls[-1][:3] == ("bootstrap", "execute", "COMMIT")
    assert "bootstrap" in harness.handles and "bootstrap" in actual.handles


@pytest.mark.parametrize(
    "damage", ["duplicate", "traversal", "nonregular", "record", "count", "size"]
)
def test_unsafe_wheel_structure_refuses_before_install_import(tmp_path, monkeypatch, damage):
    adapter = load()
    wheel, site, _ = wheel_fixture(tmp_path)
    with zipfile.ZipFile(wheel) as archive:
        payload = {i.filename: archive.read(i) for i in archive.infolist()}
    if damage == "traversal":
        payload["../escape.py"] = b"unsafe"
    if damage == "record":
        payload["modkit_events-0.2.0.dist-info/RECORD"] = b""
    if damage == "count":
        monkeypatch.setattr(adapter, "MAX_FILES", 1)
    if damage == "size":
        monkeypatch.setattr(adapter, "MAX_TOTAL", 1)
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, raw in payload.items():
            entry = zipfile.ZipInfo(name)
            if damage == "nonregular":
                entry.external_attr = (0o120000 | 0o600) << 16
            archive.writestr(entry, raw)
        if damage == "duplicate":
            with pytest.warns(UserWarning):
                archive.writestr("modkit_events/__init__.py", b"duplicate")
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    with pytest.raises(ValueError):
        adapter._verify_wheel(wheel, digest, "modkit_events", "0.2.0", site)


@pytest.mark.parametrize(
    "field,value",
    [
        ("implementation", "pypy"),
        ("version", (3, 13, 6, "final", 0)),
        ("platform", "darwin"),
        ("machine", "aarch64"),
        ("gil", False),
        ("debug", True),
        ("isolated", False),
        ("optimized", True),
    ],
)
def test_each_measured_host_property_refuses(monkeypatch, field, value):
    adapter = load()
    values = dict(
        implementation="cpython",
        version=(3, 13, 5, "final", 0),
        platform="linux",
        machine="x86_64",
        gil=True,
        debug=False,
        isolated=True,
        optimized=False,
    )
    values[field] = value
    monkeypatch.setattr(
        adapter.sys, "implementation", SimpleNamespace(name=values["implementation"])
    )
    monkeypatch.setattr(adapter.sys, "version_info", values["version"])
    monkeypatch.setattr(adapter.sys, "platform", values["platform"])
    monkeypatch.setattr(adapter.platform, "machine", lambda: values["machine"])
    monkeypatch.setattr(adapter.sys, "_is_gil_enabled", lambda: values["gil"], raising=False)
    monkeypatch.setattr(
        adapter.sysconfig,
        "get_config_var",
        lambda key: values["debug"] if key == "Py_DEBUG" else False,
    )
    monkeypatch.setattr(
        adapter.sys,
        "flags",
        SimpleNamespace(isolated=values["isolated"], optimize=values["optimized"]),
    )
    with pytest.raises(ValueError, match="host"):
        adapter._host()


@pytest.mark.parametrize("operation", ["driver", "wheel", "import", "origins"])
def test_aggregate_budget_stops_before_next_oversized_read(tmp_path, monkeypatch, operation):
    adapter = load()
    reads = []
    original = adapter._regular
    if operation == "wheel":
        wheel, site, digest = wheel_fixture(tmp_path)
        # The wheel fits; the installed RECORD is replaced by an over-budget
        # file. It must be rejected before opening that file, not after reads.
        with zipfile.ZipFile(wheel) as archive:
            total = sum(info.file_size for info in archive.infolist())
        target = site / "modkit_events-0.2.0.dist-info/RECORD"
        target.write_bytes(b"x" * (total + 1))
        monkeypatch.setattr(adapter, "MAX_TOTAL", total)

        def run():
            adapter._verify_wheel(wheel, digest, "modkit_events", "0.2.0", site)
    else:
        site = tmp_path / "site"
        package = site / ("psycopg" if operation == "driver" else "modkit_events")
        package.mkdir(parents=True)
        first, target = package / "__init__.py", package / "extra.py"
        first.write_bytes(b"12345678")
        target.write_bytes(b"abcdefgh")
        files = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (first, target)}
        monkeypatch.setattr(adapter, "MAX_TOTAL", 10)
        if operation == "driver":
            info = site / "psycopg-3.3.8.dist-info"
            info.mkdir()

            def run():
                adapter._driver_files(site, "psycopg")
        elif operation == "import":
            actual = object.__new__(adapter.Adapter)
            actual.site, actual.files = site, files

            def run():
                actual._import("modkit_events")
        else:
            # Only this budget probe needs a closed target-module inventory.
            # Use a private sys proxy; never clear the interpreter's modules or
            # let unrelated full-suite imports short-circuit the budget guard.
            modules = {
                name: module
                for name, module in adapter.sys.modules.items()
                if name != "modkit_events" and not name.startswith("modkit_events.")
            }
            for name, path in (("modkit_events", first), ("modkit_events.extra", target)):
                modules[name] = SimpleNamespace(
                    __file__=str(path), __spec__=SimpleNamespace(origin=str(path))
                )
            monkeypatch.setattr(
                adapter,
                "sys",
                SimpleNamespace(**{**vars(adapter.sys), "path": [str(site)], "modules": modules}),
            )

            def run():
                adapter._check_origins("modkit_events", site, files)

    def measured(path, *args, **kwargs):
        reads.append(Path(path))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(adapter, "_regular", measured)
    with pytest.raises(ValueError, match="total bound"):
        run()
    assert target not in reads
    if operation != "wheel":
        assert reads == [first]


def test_budget_origin_probe_coexists_with_unrelated_loaded_module(tmp_path, monkeypatch):
    adapter = load()
    outside = str(tmp_path / "unrelated.py")
    sentinel = SimpleNamespace(__file__=outside, __spec__=SimpleNamespace(origin=outside))
    modules = dict(adapter.sys.modules)
    modules["modkit_events.persistence.unrelated_test_sentinel"] = sentinel
    real_modules = adapter.sys.modules
    proxy = SimpleNamespace(**{**vars(adapter.sys), "modules": modules})
    monkeypatch.setattr(adapter, "sys", proxy)
    monkeypatch.setattr(real_modules[__name__], "load", lambda: adapter)
    test_aggregate_budget_stops_before_next_oversized_read(tmp_path, monkeypatch, "origins")
    assert real_modules is __import__("sys").modules
    assert "modkit_events.persistence.unrelated_test_sentinel" not in real_modules
    # The probe's private filtering must not weaken production validation when
    # an unrelated loaded origin is actually presented to that validator.
    assert modules["modkit_events.persistence.unrelated_test_sentinel"] is sentinel
    first = tmp_path / "site/modkit_events/__init__.py"
    original_mapping = {
        "modkit_events": SimpleNamespace(
            __file__=str(first), __spec__=SimpleNamespace(origin=str(first))
        ),
        "modkit_events.persistence.unrelated_test_sentinel": sentinel,
    }
    monkeypatch.setattr(
        adapter,
        "sys",
        SimpleNamespace(
            **{**vars(proxy), "path": [str(tmp_path / "site")], "modules": original_mapping}
        ),
    )
    with pytest.raises(ValueError, match="preloaded import origin or bytes refused"):
        adapter._check_origins(
            "modkit_events",
            tmp_path / "site",
            {first: hashlib.sha256(first.read_bytes()).hexdigest()},
        )
