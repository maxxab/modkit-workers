"""Connection-free scalar contracts. No native adapter or fixture imports."""

import importlib
from dataclasses import FrozenInstanceError

import pytest


def module(name="native_recovery_contracts"):
    qualified = "modkit_workers." + name
    assert importlib.util.find_spec(qualified) is not None, "S1 recovery feature is absent"
    return importlib.import_module(qualified)


def readiness():
    from modkit_events.persistence.bindings import ReadinessExpectation
    from modkit_events.persistence.observations import SchemaStatus

    return ReadinessExpectation(
        components=tuple(
            SchemaStatus(
                component=component,
                version=1,
                migration_digest=b"x" * 32,
                catalog_contract_id="modkit-pg-ab-2",
                scope_format_id="MKSC-1",
                intent_format_id="MKPF-1",
            )
            for component in ("events", "workers")
        )
    )


def config(**changes):
    c = module()
    values = dict(
        namespace=b"jobs",
        readiness=readiness(),
        source_material_bytes=c.required_recovery_source_material_bytes(),
    )
    values.update(changes)
    return c.NativeRecoveryConfig(**values)


@pytest.mark.parametrize(
    "namespace",
    [b"", b"Jobs", b"app", b"jobs ", "jobs", None, bytearray(b"jobs"), memoryview(b"jobs")],
)
def test_namespace_rejects_before_readiness(namespace):
    c = module()
    with pytest.raises(ValueError, match="namespace"):
        c.NativeRecoveryConfig(namespace=namespace, readiness=object(), source_material_bytes=1)


def test_no_namespace_coercion_hooks():
    c = module()

    class Hostile(bytes):
        def __eq__(self, other):
            raise AssertionError("hook executed")

    with pytest.raises(ValueError, match="namespace"):
        c.NativeRecoveryConfig(namespace=Hostile(b"jobs"), readiness=None, source_material_bytes=1)


@pytest.mark.parametrize(
    "field,value",
    [
        ("discovery_budget", True),
        ("discovery_budget", 4097),
        ("turn_interval_seconds", 0),
        ("fallback_interval_seconds", 6),
        ("drain_timeout_seconds", float("inf")),
        ("progress_timeout_seconds", float("nan")),
        ("source_material_bytes", True),
        ("source_material_bytes", 1),
    ],
)
@pytest.mark.requires_scalar_profile
def test_config_bounds(field, value):
    with pytest.raises(ValueError):
        config(**{field: value})


@pytest.mark.requires_scalar_profile
def test_numeric_profile_and_exact_shapes():
    c = module()
    value = config()
    assert len(c.RecoverySnapshot.__slots__) == 31
    assert len(c.PendingRecoverySummary.__slots__) == 7
    report = c._summary_profile()
    assert value.source_material_bytes == report["required"] > 0
    assert report["required"] == report["L"] + report["Q"] + max(
        report["S"] + report["C31"],
        report["S"] + report["P"] + report["C7"],
        2 * report["S"] + report["P"] + report["C31"],
        3 * report["S"] + report["P"] + report["C31"],
    )
    with pytest.raises(FrozenInstanceError):
        value.namespace = b"app"


def test_saturation_and_age_boundaries():
    c = module()
    assert c._add(c.UINT64_MAX, 1) == c.UINT64_MAX
    assert c._add(c.UINT64_MAX - 1, 1) == c.UINT64_MAX
    assert c._age_ms(1.0, 1.25) == 250
    assert c._age_ms(0.0, 1e100) == c.UINT64_MAX
    with pytest.raises(ValueError):
        c._age_ms(2.0, 1.0)


@pytest.mark.requires_scalar_profile
def test_material_requires_known_disposal():
    c = module()
    lifecycle = module("_native_recovery_lifecycle")
    lease = lifecycle._RecoveryMaterialLease(c.required_recovery_source_material_bytes())
    lease.admit()
    lease.require()
    lease.hold()
    with pytest.raises(RuntimeError):
        lease.require(projection=True)
    with pytest.raises(RuntimeError):
        lease.release(known=False, quiescent=True)
    lease.release(known=True, quiescent=True)
    with pytest.raises(RuntimeError):
        lease.require()


@pytest.mark.requires_scalar_profile
def test_supported_scalar_sizes_cover_actual_leafs():
    import sys

    c = module()
    from dataclasses import fields

    s = object.__new__(c.RecoverySnapshot)
    p = object.__new__(c.PendingRecoverySummary)
    profile = c._summary_profile()
    assert len(fields(c.RecoverySnapshot)) == 31 and sys.getsizeof(s) == 280
    assert len(fields(c.PendingRecoverySummary)) == 7 and sys.getsizeof(p) == 88
    assert sys.getsizeof(2**64 - 1) == 36 and sys.getsizeof(2**128 - 1) == 44
    assert profile["required"] == 6212


def test_unsupported_scalar_profile_rejects(monkeypatch):
    c = module()
    monkeypatch.setattr(c.struct, "calcsize", lambda value: 4)
    with pytest.raises(ValueError, match="profile"):
        c.required_recovery_source_material_bytes()


def test_receipts_are_not_constructible_or_subclassable():
    setup = module("native_recovery_setup")
    with pytest.raises(TypeError):
        setup.NativeRecoveryConfigurationReceipt()
    with pytest.raises(TypeError):
        type("Forged", (setup.NativeRecoveryConfigurationReceipt,), {})


# S2 test-private future-interface models. Never installed as production fallback.
def profile_double(monkeypatch):
    from dataclasses import make_dataclass
    from types import SimpleNamespace

    setup = module("native_recovery_setup")
    names = (
        "retained_cells admitted_live checkouts roots roots_per_checkout executions "
        "preparations preparations_per_execution prepare_bytes prepare_bytes_per_execution "
        "results results_per_ticket result_bytes result_bytes_per_ticket cleanup_bundles "
        "cleanup_bytes construction_slots"
    ).split()
    Limits = make_dataclass("LifecycleLimits", [(n, int) for n in names], frozen=True)
    limits = Limits(*[4096 if n == "cleanup_bytes" else 2 for n in names])
    Requirements = make_dataclass(
        "RecoveryRequirements", [("lifecycle_minimum", object), ("readiness", object)], frozen=True
    )
    Verified = make_dataclass("VerifiedRecoveryProfile", [("requirements", object)], frozen=True)
    events = []
    api = SimpleNamespace(
        RecoveryRequirements=Requirements,
        VerifiedRecoveryProfile=Verified,
        recovery_requirements=lambda *, readiness: Requirements(limits, readiness),
        verify_recovery_driver=lambda req: events.append("verify") or Verified(req),
    )
    monkeypatch.setattr(setup, "_profile_api", lambda: api, raising=False)
    monkeypatch.setattr(setup, "_limits_type", lambda: Limits, raising=False)
    return setup, limits, events


@pytest.mark.requires_scalar_profile
def test_s2_preflight_full_vector_then_verify(monkeypatch):
    setup, limits, events = profile_double(monkeypatch)
    assert setup.preflight_native_recovery(config(), limits=limits) is None
    assert events == ["verify"] and not setup._attempted


@pytest.mark.parametrize("index", range(17))
@pytest.mark.requires_scalar_profile
def test_s2_every_minimum_precedes_driver(monkeypatch, index):
    from dataclasses import fields, replace

    setup, limits, events = profile_double(monkeypatch)
    name = fields(limits)[index].name
    small = replace(limits, **{name: getattr(limits, name) - 1})
    with pytest.raises(ValueError):
        setup.preflight_native_recovery(config(), limits=small)
    assert events == [] and not setup._attempted


@pytest.mark.requires_scalar_profile
def test_s2_factory_profile_recheck_before_material(monkeypatch):
    m = module("native_recovery")
    setup = module("native_recovery_setup")
    c = module()
    called = []

    def reject(*args):
        called.append("recheck")
        raise ValueError("insufficient receipt limits")

    monkeypatch.setattr(setup, "_recheck_profile", reject, raising=False)
    resources = c.NativeRecoveryResources(
        configuration=object(), connection=object(), ledger=object()
    )
    from types import SimpleNamespace

    app = SimpleNamespace(validate_profile=lambda ns: None, authorize_root=lambda *a: None)
    with pytest.raises(ValueError, match="receipt"):
        m.create_job_recovery(config=config(), resources=resources, application=app)
    assert called == ["recheck"]


@pytest.mark.requires_scalar_profile
def test_s2_driver_failure_precedes_configuration(monkeypatch):
    setup, limits, events = profile_double(monkeypatch)
    api = setup._profile_api()

    def reject(req):
        raise setup.RecoveryUnavailable("unsupported driver")

    api.verify_recovery_driver = reject
    with pytest.raises(setup.RecoveryUnavailable):
        setup.preflight_native_recovery(config(), limits=limits)
    assert not setup._attempted


@pytest.mark.requires_scalar_profile
def test_s2_preflight_cannot_reset_attempted_setup(monkeypatch):
    setup, limits, events = profile_double(monkeypatch)
    monkeypatch.setattr(setup, "_attempted", True)
    with pytest.raises(RuntimeError, match="already attempted"):
        setup.preflight_native_recovery(config(), limits=limits)
    assert events == []


@pytest.mark.requires_scalar_profile
def test_s2_configuration_receipt_fresh_once_only_adoption(monkeypatch):
    import sys
    from types import ModuleType, SimpleNamespace

    setup, limits, events = profile_double(monkeypatch)
    monkeypatch.setattr(setup, "_attempted", False)
    monkeypatch.setattr(setup, "_configuration", None)
    monkeypatch.setattr(setup, "_load_native_capability", lambda: None)

    class Ledger:
        def __init__(self):
            self.uncertainty = SimpleNamespace(present=False)

    class Connection:
        closed = autocommit = False
        pgconn = SimpleNamespace(transaction_status=0, pipeline_status=0)

    domain = SimpleNamespace(stopped=False)

    def install(name, **attrs):
        mod = ModuleType(name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, "modkit_events.persistence." + name, mod)

    install("ledger", ExecutionLedger=Ledger)
    install(
        "managed_lifecycle",
        LifecycleLimits=type(limits),
        configure_managed_registry=lambda **kw: events.append("configure"),
    )
    install("resource_registry", resource_domain=lambda: domain)
    install("native_sync", ManagedConnection=Connection)
    setup.preflight_native_recovery(config(), limits=limits)
    receipt = setup.configure_native_recovery_profile(limits=limits)
    assert events == ["verify", "configure"]
    resources = module().NativeRecoveryResources(
        configuration=receipt, connection=Connection(), ledger=Ledger()
    )
    assert setup._recheck_profile(config(), resources).lifecycle_minimum == limits
    owner_token = object()
    setup._validate_resources(resources, owner_token)
    setup._adopt_resources(resources, owner_token)
    with pytest.raises(ValueError, match="adopted"):
        setup._adopt_resources(resources, object())
    with pytest.raises(RuntimeError, match="once-only"):
        setup.configure_native_recovery_profile(limits=limits)
    domain.stopped = True
    with pytest.raises(ValueError, match="provenance"):
        setup._recheck_profile(config(), resources)


@pytest.mark.requires_scalar_profile
def test_s2_cursor_transient_fits_existing_summary_phase():
    import sys
    from uuid import UUID

    report = module()._summary_profile()
    cursor = UUID(int=2**128 - 1)
    transient = sys.getsizeof(cursor) + 2 * sys.getsizeof(cursor.int)
    assert transient == 152
    assert report["cursor_transient"] == transient
    assert report["L"] + report["Q"] + 3 * report["S"] + report["C31"] + transient <= 6212


@pytest.mark.parametrize("child", ["admitted_live", "checkouts"])
@pytest.mark.requires_scalar_profile
def test_s2_parent_cell_minima_reject_before_driver(monkeypatch, child):
    from dataclasses import replace

    setup, limits, events = profile_double(monkeypatch)
    minimum = replace(limits, retained_cells=1, admitted_live=1, checkouts=1)
    api = setup._profile_api()
    api.recovery_requirements = lambda *, readiness: api.RecoveryRequirements(minimum, readiness)
    invalid = replace(minimum, **{child: 2})
    with pytest.raises(ValueError, match="relationship"):
        setup.preflight_native_recovery(config(), limits=invalid)
    assert events == [] and not setup._attempted


def configure_doubles(monkeypatch, setup, limits, events, configure):
    import sys
    from types import ModuleType, SimpleNamespace

    monkeypatch.setattr(setup, "_attempted", False)
    monkeypatch.setattr(setup, "_configuration", None)
    monkeypatch.setattr(setup, "_load_native_capability", lambda: events.append("capability"))
    for name, attrs in (
        ("ledger", {"ExecutionLedger": object}),
        (
            "managed_lifecycle",
            {"LifecycleLimits": type(limits), "configure_managed_registry": configure},
        ),
        ("resource_registry", {"resource_domain": lambda: SimpleNamespace(stopped=False)}),
    ):
        mod = ModuleType(name)
        mod.__dict__.update(attrs)
        monkeypatch.setitem(sys.modules, "modkit_events.persistence." + name, mod)


@pytest.mark.parametrize(
    "child,parent",
    [
        ("admitted_live", "retained_cells"),
        ("checkouts", "retained_cells"),
        ("roots_per_checkout", "roots"),
        ("preparations_per_execution", "preparations"),
        ("prepare_bytes_per_execution", "prepare_bytes"),
        ("results_per_ticket", "results"),
        ("result_bytes_per_ticket", "result_bytes"),
    ],
)
def test_s2_direct_invalid_relation_preserves_setup_latch(monkeypatch, child, parent):
    from dataclasses import replace

    setup, limits, events = profile_double(monkeypatch)
    invalid = replace(limits, **{child: getattr(limits, parent) + 1})

    def reject_at_events(**kwargs):
        events.append("configure")
        raise ValueError("relationship detected too late")

    configure_doubles(monkeypatch, setup, limits, events, reject_at_events)
    with pytest.raises(ValueError, match="relationship"):
        setup.configure_native_recovery_profile(limits=invalid)
    assert not setup._attempted
    assert events == []


def test_s2_uncertain_configure_keeps_attempt_latched(monkeypatch):
    setup, limits, events = profile_double(monkeypatch)

    def uncertain(**kwargs):
        assert setup._attempted
        events.append("configure")
        raise RuntimeError("uncertain setup")

    configure_doubles(monkeypatch, setup, limits, events, uncertain)
    with pytest.raises(RuntimeError, match="uncertain"):
        setup.configure_native_recovery_profile(limits=limits)
    assert setup._attempted and setup._configuration is None
    with pytest.raises(RuntimeError, match="once-only"):
        setup.configure_native_recovery_profile(limits=limits)
    assert events.count("configure") == 1


def simulated_313(monkeypatch):
    import platform
    import sysconfig

    c = module()
    monkeypatch.setattr(c.sys, "version_info", (3, 13, 5, "final", 0))
    monkeypatch.setattr(c.sys, "platform", "linux")
    monkeypatch.setattr(platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(sysconfig, "get_config_var", lambda name: 0)
    monkeypatch.setattr(c.sys, "_is_gil_enabled", lambda: True, raising=False)
    return c


def test_profile_313_exact_candidate_branch_on_host(monkeypatch):
    c = simulated_313(monkeypatch)
    profile = c._summary_profile()
    assert profile["interpreter_profile_id"] == "cpython-3.13.5-linux-x86_64-gil-scalar-64"
    assert profile["interpreter_version"] == (3, 13, 5)
    assert profile["required"] == 6212 and profile["Q"] == 444


@pytest.mark.parametrize(
    "version",
    [
        (3, 13, 4, "final", 0),
        (3, 13, 6, "final", 0),
        (3, 14, 0, "final", 0),
        (3, 13, 5, "candidate", 1),
    ],
)
def test_profile_rejects_other_new_versions(monkeypatch, version):
    c = simulated_313(monkeypatch)
    monkeypatch.setattr(c.sys, "version_info", version)
    with pytest.raises(ValueError, match="profile"):
        c._summary_profile()


@pytest.mark.parametrize(
    "unsupported",
    [
        "windows",
        "aarch64",
        "free-threaded",
        "debug",
        "gil-off",
        "gil-unknown",
        "flags-unknown",
        "flags-bool",
        "layout",
    ],
)
def test_profile_313_rejects_unknown_build_or_layout(monkeypatch, unsupported):
    import platform
    import sysconfig

    c = simulated_313(monkeypatch)
    if unsupported == "windows":
        monkeypatch.setattr(c.sys, "platform", "win32")
    elif unsupported == "aarch64":
        monkeypatch.setattr(platform, "machine", lambda: "aarch64")
    elif unsupported in ("free-threaded", "debug"):
        key = "Py_GIL_DISABLED" if unsupported == "free-threaded" else "Py_DEBUG"
        monkeypatch.setattr(sysconfig, "get_config_var", lambda name: int(name == key))
    elif unsupported in ("flags-unknown", "flags-bool"):
        monkeypatch.setattr(
            sysconfig,
            "get_config_var",
            lambda name: None if unsupported == "flags-unknown" else False,
        )
    elif unsupported == "gil-off":
        monkeypatch.setattr(c.sys, "_is_gil_enabled", lambda: False)
    elif unsupported == "gil-unknown":
        monkeypatch.delattr(c.sys, "_is_gil_enabled")
    else:
        monkeypatch.setattr(c.struct, "calcsize", lambda value: 4)
    with pytest.raises(ValueError, match="profile"):
        c._summary_profile()


def test_profile_312_existing_platform_scope_preserved(monkeypatch):
    import platform
    import sysconfig

    c = module()
    monkeypatch.setattr(c.sys, "version_info", (3, 12, 99, "final", 0))
    monkeypatch.setattr(c.sys, "platform", "win32")
    monkeypatch.setattr(platform, "machine", lambda: "other")
    monkeypatch.setattr(sysconfig, "get_config_var", lambda key: pytest.fail("new312 restriction"))
    p = c._summary_profile()
    assert p["interpreter_profile_id"] == "cpython-3.12-scalar-64"
    assert p["interpreter_version"] == (3, 12, 99) and p["required"] == 6212


@pytest.mark.requires_scalar_profile
def test_pinned_events_recovery_preflight_contract_without_driver_import(monkeypatch):
    """Real dependency records/minima, with only driver fact inspection replaced."""
    import builtins
    import sys
    from dataclasses import fields, replace

    from modkit_events.persistence import managed_lifecycle, recovery_profile
    from modkit_events.persistence.errors import ErrorCode, PersistenceError

    setup = module("native_recovery_setup")
    candidate = config()
    driver_checks = []
    original_import = builtins.__import__

    def checked_import(name, globals=None, locals=None, fromlist=(), level=0):
        assert not name.startswith("psycopg"), "optional driver import during source preflight"
        assert not any(
            item in ("native_execution", "native_sync")
            for item in (name.rsplit(".", 1)[-1], *(fromlist or ()))
        ), "native I/O module import during source preflight"
        return original_import(name, globals, locals, fromlist, level)

    def driver_facts():
        driver_checks.append("inspected")
        # Deliberately simulated, not positive driver/capability qualification.
        return "3.3.8", 180006, "binary"

    monkeypatch.setattr(builtins, "__import__", checked_import)
    monkeypatch.setattr(recovery_profile, "_verify_driver", driver_facts)
    monkeypatch.setattr(
        managed_lifecycle,
        "configure_managed_registry",
        lambda **kwargs: pytest.fail("preflight configured the shared registry"),
    )
    assert setup._profile_api() is recovery_profile
    assert setup._limits_type() is managed_lifecycle.LifecycleLimits
    assert not setup._attempted
    if sys.platform != "linux" or tuple(sys.version_info[:3]) not in ((3, 12, 3), (3, 13, 5)):
        # The scalar source profile is broader than the actual Events native
        # profile. A real dependency refusal must precede even simulated facts.
        generous = managed_lifecycle.LifecycleLimits(
            **{field.name: 2**32 for field in fields(managed_lifecycle.LifecycleLimits)}
        )
        with pytest.raises(PersistenceError) as caught:
            setup.preflight_native_recovery(candidate, limits=generous)
        assert caught.value.code is ErrorCode.PROFILE_REJECTED
        assert not caught.value.unconfirmed and driver_checks == []
        assert not setup._attempted
        return

    requirements = recovery_profile.recovery_requirements(readiness=candidate.readiness)
    assert type(requirements) is recovery_profile.RecoveryRequirements
    assert requirements.readiness is candidate.readiness
    assert requirements.namespace == b"jobs" and requirements.kind == "job"
    assert requirements.page_limit == 1 and requirements.required_profile == "workers"
    assert tuple(x.component for x in requirements.readiness.components) == ("events", "workers")
    limits = requirements.lifecycle_minimum
    assert type(limits) is managed_lifecycle.LifecycleLimits
    assert (
        limits.prepare_bytes
        == limits.prepare_bytes_per_execution
        == max(requirements.e13_preparation_min, requirements.e33_preparation_min)
    )
    assert (
        limits.result_bytes
        == limits.result_bytes_per_ticket
        == max(requirements.e13_result_min, requirements.e33_result_min)
    )
    assert setup.preflight_native_recovery(candidate, limits=limits) is None
    assert driver_checks == ["inspected"] and not setup._attempted
    # Real17-field minima must all reject before inspecting optional driver facts.
    for field in fields(limits):
        small = replace(limits, **{field.name: getattr(limits, field.name) - 1})
        with pytest.raises(ValueError):
            setup.preflight_native_recovery(candidate, limits=small)
        assert driver_checks == ["inspected"], field.name
        assert not setup._attempted
    # Use the real verifier's rejection path after its real equality/type checks.
    monkeypatch.setattr(recovery_profile, "_verify_driver", recovery_profile._reject_validation)
    with pytest.raises(PersistenceError) as caught:
        setup.preflight_native_recovery(candidate, limits=limits)
    assert caught.value.code is ErrorCode.PROFILE_REJECTED
    assert not caught.value.unconfirmed and not setup._attempted
