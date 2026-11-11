"""Manual, source-only transport harness. Import and CLI never connect.

The injected adapter is trusted cooperative test-host code, not an authorization
token. There is deliberately no CLI activation switch or workflow. A separately
reviewed runner must verify actual artifacts/profile and obtain permission before
supplying a live adapter. Offline fakes prove control flow, never native readiness.
Synthetic host destruction after UNKNOWN is not managed cleanup or rollback.
"""

from sys import getsizeof

PROFILE = {
    "implementation": "cpython",
    "version": (3, 13, 5, "final", 0),
    "platform": "linux",
    "machine": "x86_64",
    "gil": True,
    "debug": False,
    "isolated": True,
    "optimized": False,
    "outside_checkout_venv": True,
    "driver": "3.3.8",
    "libpq": 180006,
    "pq_impl": "binary",
    "events_source": "9362f0d318c762283f70b18c4f2907f1fda39f8b",
    "events_wheel": "4df4d6744a5fd88320bdb143685e8f844f58642f5bfc773c7912aea08d8cb25e",
    "workers_wheel": "8b021822a21c1f4daa757e77a83d46f01e7cdc999132ede8cdfceb9231000f87",
    "installed_provenance": True,
}
FIELDS = (
    "component",
    "version",
    "migration_digest",
    "catalog_contract_id",
    "scope_format_id",
    "intent_format_id",
)
EXPECTED_RECEIPTS = tuple(
    (component, 1, bytes.fromhex(digest), "modkit-pg-ab-2", "MKSC-1", "MKPF-1")
    for component, digest in (
        ("events", "0a17c42c4abaade875770ddc587a3c80347259e2e29d4ad13a308cc244b9fe67"),
        ("workers", "ac59c791bcd5841929b4048818df492b2cf0af70855a617698c4f953a98815f4"),
    )
)


def validate_profile(facts):
    # Facts must be independently measured by a reviewed adapter, never env flags.
    if (
        type(facts) is not dict
        or facts.keys() != PROFILE.keys()
        or any(type(facts[k]) is not type(v) or facts[k] != v for k, v in PROFILE.items())
    ):
        raise Refusal("artifact or host profile refused")


def validate_target(row, roles, schemas, objects):
    if (
        type(row) is not tuple
        or len(row) != 4
        or type(row[0]) is not int
        or row != (171100, "modkit_workers_ci", "modkit_ci_bootstrap", "modkit_ci_bootstrap")
        or roles != ["modkit_ci_bootstrap"]
        or schemas != []
        or objects != []
    ):
        raise Refusal("fresh target or identity refused")


def connection_options(kind):
    logins = {
        "bootstrap": "modkit_ci_bootstrap",
        "owner": "modkit_ci_owner_login",
        "observer": "modkit_ci_operator_login",
        "native": "modkit_ci_runtime_login",
    }
    if kind not in logins:
        raise Refusal("unknown connection kind")
    options = (
        "-c statement_timeout=10000 -c lock_timeout=2000 "
        "-c idle_in_transaction_session_timeout=15000 -c timezone=UTC "
        "-c default_transaction_isolation=read\\ committed"
    )
    if kind in ("native", "observer"):
        options += " -c role=" + ("modkit_runtime" if kind == "native" else "modkit_operator")
    return {
        "host": "127.0.0.1",
        "hostaddr": "127.0.0.1",
        "port": 5432,
        "dbname": "modkit_workers_ci",
        "user": logins[kind],
        "password": "modkit-ci-public-fixture-only",
        "connect_timeout": 5,
        "passfile": "/dev/null",
        "sslmode": "disable",
        "options": options,
        "autocommit": kind != "native",
    }


def check_native_receipts(rows):
    if type(rows) is not tuple or len(rows) != 2:
        raise Refusal("receipt tuple shape")
    # No borrowed tuple, row or field is returned or stored in a host collection.
    for index in range(2):
        for column in range(6):
            value = getattr(rows[index], FIELDS[column])
            expected = EXPECTED_RECEIPTS[index][column]
            if type(value) is not type(expected) or value != expected:
                raise Refusal("receipt field or order mismatch")
            value = None


class Refusal(ValueError):
    """Bounded, nonsecret refusal; never a driver exception container."""


def require_environment(env):
    expected = {
        "GITHUB_ACTIONS": "true",
        "RUNNER_ENVIRONMENT": "github-hosted",
        "GITHUB_REPOSITORY": "maxxab/modkit-workers",
        "MODKIT_POSTGRES_TEST": "workers-native-transport-v1",
    }
    if any(env.get(k) != v for k, v in expected.items()) or any(k.startswith("PG") for k in env):
        raise Refusal("environment refused")


class HostOracle:
    """Independent 8192 logical-byte reservation, not native B credit or RSS.

    Four XID and four status occurrences only. Conservative fixed slot costs
    charge both the retained graph and one full draft before any scalar copy.
    No receipt, native page, object, or exception is retained here.
    """

    def __init__(self):
        self.reserved = False
        self.xids = ()
        self.statuses = ()
        self.used = self.peak = 0

    def reserve(self):
        if self.reserved:
            raise Refusal("duplicate reservation")
        if getsizeof((0,) * 8) + 8 * 256 > 4096:
            raise Refusal("host oracle profile")
        self.reserved = True
        self.used = 8192
        self.peak = 8192

    def xid(self, value):
        if not self.reserved:
            raise Refusal("missing host reservation")
        if type(value) is not int or not 0 <= value < 2**64 or getsizeof(value) > 256:
            raise Refusal("invalid uint64")
        if len(self.xids) == 4:
            raise Refusal("XID occurrences exhausted")
        # Charge includes the old tuple, the new tuple, and this scalar draft.
        self.xids += (int.from_bytes(value.to_bytes(8, "big"), "big"),)

    def status(self, value):
        if not self.reserved:
            raise Refusal("missing host reservation")
        if type(value) is not str or value not in ("in progress", "aborted", "committed"):
            raise Refusal("invalid transaction status")
        if getsizeof(value) > 256 or len(self.statuses) == 4:
            raise Refusal("status occurrences exhausted")
        # Canonical host-owned strings, never the observer result graph.
        self.statuses += (
            ("in progress", "aborted", "committed")[
                ("in progress", "aborted", "committed").index(value)
            ],
        )

    def release(self):
        if not self.reserved:
            raise Refusal("missing host reservation")
        self.xids = self.statuses = ()
        self.used = 0
        self.reserved = False


LIMITS = dict(
    retained_cells=4,
    admitted_live=4,
    checkouts=4,
    roots=8,
    roots_per_checkout=4,
    executions=4,
    preparations=8,
    preparations_per_execution=4,
    prepare_bytes=8192,
    prepare_bytes_per_execution=4096,
    results=8,
    results_per_ticket=1,
    result_bytes=33554432,
    result_bytes_per_ticket=4194304,
    cleanup_bundles=4,
    cleanup_bytes=4096,
    construction_slots=8,
)
COUNTERS = tuple("P V C R X A AB B BB K KB D".split())


class Harness:
    """One-shot dependency-injected schedule, with no default/live adapter.

    Minimal trusted adapter protocol (each method is one attempt, no retries):
    profile(): offline facts matching PROFILE; NOT evidence of actual provenance.
    connect_{bootstrap,owner,observer}(fixed_options): return ordinary handle.
    freshness(bootstrap, index): four SELECTs from check_postgres.bootstrap, in
      target/roles/schemas/public-objects order, without mutations.
    bootstrap_begin/commit(handle): one explicit BEGIN/acknowledged COMMIT.
    bootstrap_statement(handle,index): exactly the indexed one of the existing
      18 statements: REVOKE PUBLIC; four groups CREATE role, CREATE login,
      GRANT membership, GRANT CONNECT; GRANT owner CREATE. No dynamic SQL input.
    owner_begin/commit(handle): one explicit BEGIN/acknowledged COMMIT.
    install_component(owner,index): reuse check_postgres.install_component once
      with immutable Events then Workers manifests/resources/owner receipt.
      Exactly nine execute calls per helper. No check_postgres.main invocation.
    close_bootstrap/owner/observer(handle): one acknowledged ordinary close.
    observer_preflight(handle): one SELECT returning session/current identity,
      five false privilege flags, true pg_xact_status and E33 execute privilege.
    observer_receipts(handle): one E33('workers') SELECT, ordered six-field tuple.
    observer_status(handle,xid): one pg_catalog.pg_xact_status(%s::xid8) SELECT.
    load_native(): only after setup and observer checks; returns ledger, managed,
      native, execution, catalog, expectation. Modules are the pinned Events
      public APIs, ledger is fresh ExecutionLedger, expectation is exact
      ReadinessExpectation with two SchemaStatus values from EXPECTED_RECEIPTS.
    connect_native(options, execution_ledger=...): fresh ManagedConnection.connect.

    The future adapter must independently measure artifacts/profile before native
    imports and implement the exact SQL inventory above. This protocol's fake
    observations and asserted metadata do not qualify such an implementation.
    No method accepts a caller-selected target, SQL, grant or catalog operation.
    """

    def __init__(self, adapter, env):
        self.adapter, self.env = adapter, env
        self.oracle = HostOracle()
        self.status = "NOT_RUN"
        self.stage = "new"
        self.counts = dict(connections=0, observer=0, catalog=0)
        self.handles = {}
        self.ready = False
        self.modules = None

    def _call(self, owner, name, *args, **kwargs):
        if self.modules is not None:
            self._known()
        self.stage = name
        try:
            return getattr(owner, name)(*args, **kwargs)
        except BaseException:
            self.status = "UNKNOWN"
            # Keep handles, not arbitrary exception graphs or guessed refunds.
            raise

    def _budget(self, kind, maximum):
        if self.counts[kind] >= maximum:
            raise Refusal("call budget exhausted")
        self.counts[kind] += 1  # Attempt, not only successful return.

    def connect(self, kind):
        if self.modules is not None:
            self._known()
        self._budget("connections", 4)
        kwargs = {} if kind != "native" else {"execution_ledger": self.modules.ledger}
        self.handles[kind] = self._call(
            self.adapter, "connect_" + kind, connection_options(kind), **kwargs
        )
        return self.handles[kind]

    def observe(self, name, *args):
        if name not in ("observer_preflight", "observer_receipts", "observer_status"):
            raise Refusal("observer operation refused")
        self._budget("observer", 7)
        return self._call(self.adapter, name, *args)

    def _known(self):
        if self.modules.ledger.uncertainty.present:
            self.status = "UNKNOWN"
            raise Refusal("UNKNOWN ledger; no cleanup")

    def managed(self, name, *args, **kwargs):
        self._known()
        result = self._call(
            self.modules.managed, name, *args, execution_ledger=self.modules.ledger, **kwargs
        )
        self._known()
        return result

    def _native(self, name, *args):
        self._known()
        result = self._call(self.modules.native, name, *args, execution_ledger=self.modules.ledger)
        self.handles["pending_native"] = result
        self._known()
        del self.handles["pending_native"]
        return result

    def _receipts(self):
        rows = self.observe("observer_receipts", self.handles["observer"])
        if type(rows) is not tuple or len(rows) != 2:
            raise Refusal("observer receipt shape")
        for index in range(2):
            if type(rows[index]) is not tuple or len(rows[index]) != 6:
                raise Refusal("observer receipt shape")
            for column in range(6):
                expected = EXPECTED_RECEIPTS[index][column]
                if (
                    type(rows[index][column]) is not type(expected)
                    or rows[index][column] != expected
                ):
                    raise Refusal("observer receipt field or order mismatch")
        # Both baseline and final equal the same immutable pair; no baseline copy.

    def _catalog(self, readiness=False):
        self._budget("catalog", 6)
        execution = self.handles["execution"]
        api = self.modules.execution
        self._known()
        if readiness:
            preparation = self._call(
                api,
                "prepare_readiness",
                execution,
                "workers",
                self.modules.expectation,
                execution_ledger=self.modules.ledger,
                capacity=4096,
            )
        else:
            preparation = self._call(
                api,
                "prepare",
                execution,
                self.modules.catalog.get_statement("E14"),
                (),
                execution_ledger=self.modules.ledger,
                capacity=4096,
            )
        self.handles["preparation"] = preparation
        self.handles["ticket"] = self.managed("admit", self.handles["root"], preparation)
        self.handles["result"] = self.managed(
            "reserve_result", self.handles["ticket"], 16384 if readiness else 64
        )
        self._call(
            api,
            "execute",
            self.handles["ticket"],
            self.handles["result"],
            execution_ledger=self.modules.ledger,
        )
        self._known()
        borrowed = self.managed("read_result", self.handles["result"])
        if readiness:
            check_native_receipts(borrowed)
        else:
            self.oracle.xid(borrowed)
        # Drop the complete borrowed graph before any native B refund.
        borrowed = None
        self.managed("release_result", self.handles["result"])
        del self.handles["result"]
        self.managed("release_ticket", self.handles["ticket"])
        del self.handles["ticket"]
        self.managed("release_preparation", preparation)
        del self.handles["preparation"]

    def _status(self, xid, expected):
        value = self.observe("observer_status", self.handles["observer"], xid)
        self.oracle.status(value)
        if value != expected:
            raise Refusal("transaction status mismatch")

    def native_phase(self):
        if not self.ready or self.modules is not None:
            raise Refusal("native prerequisites missing or already consumed")
        self.modules = self._call(self.adapter, "load_native")
        self._known()
        self.managed(
            "configure_managed_registry", limits=self.modules.managed.LifecycleLimits(**LIMITS)
        )

    def _native_schedule(self):
        self.handles["execution"] = self._call(
            self.modules.managed, "reserve_execution", self.modules.ledger
        )
        self._known()
        actual = self.connect("native")
        self.handles["checkout"] = self._native("attach_native", actual, self.handles["execution"])
        for index in range(2):
            self.handles["root"] = self._native("start_root", self.handles["checkout"])
            self._catalog()
            self._catalog()
            if self.oracle.xids[-1] != self.oracle.xids[-2]:
                raise Refusal("E14 root identity mismatch")
            if index and self.oracle.xids[0] == self.oracle.xids[2]:
                raise Refusal("sequential roots must differ")
            self._catalog(readiness=True)
            xid = self.oracle.xids[-1]
            self._status(xid, "in progress")
            receipt = self._native("rollback" if index == 0 else "commit", self.handles["root"])
            self.handles["root_receipt"] = receipt
            if index == 0:
                self.managed("acknowledge_root_end", receipt)
            elif (
                self.managed("acknowledge_commit_result", receipt)
                is not self.modules.managed.CommitOutcome.COMMITTED
            ):
                raise Refusal("commit did not acknowledge COMMITTED")
            self.managed("release_root", self.handles["root"])
            del self.handles["root"]
            del self.handles["root_receipt"]
            self._status(xid, "aborted" if index == 0 else "committed")
        self._receipts()
        self._cleanup()

    def _capacity(self, expected):
        counts = self.managed("capacity_snapshot")
        if (
            type(counts) is not dict
            or set(counts) != set(COUNTERS)
            or any(type(counts[k]) is not int or counts[k] != expected.get(k, 0) for k in COUNTERS)
        ):
            raise Refusal("outstanding capacity mismatch; no guessed cleanup")

    def _cleanup(self):
        self._known()
        self._capacity(dict(P=1, V=1, C=1, X=1))
        checkout = self.handles["checkout"]
        self.managed("retire", checkout)
        self.handles["intent"] = self.managed("prepare_cleanup", checkout)
        self.handles["reservation"] = self.managed("reserve_cleanup", self.handles["intent"], 4096)
        self.handles["permit"] = self.managed("pin_cleanup", self.handles["reservation"])
        self.handles["close_receipt"] = self._native("close", self.handles["permit"])
        self._known()
        self.managed("acknowledge_physical_close", self.handles["close_receipt"])
        self.managed("release_cleanup", self.handles["reservation"])
        self.managed("detach_terminal", checkout)
        self.managed("dispose_execution", self.handles["execution"])
        self._capacity({})
        self._call(self.adapter, "close_observer", self.handles["observer"])
        self._known()
        self.handles.clear()
        self.oracle.release()

    def diagnostic(self):
        return {
            "status": self.status,
            "stage": self.stage,
            "connection_attempts": self.counts["connections"],
            "catalog_attempts": self.counts["catalog"],
            "observer_attempts": self.counts["observer"],
            "synthetic_teardown": "NOT_MANAGED_CLEANUP",
            "runtime": "NOT_RUN",
            "full84": "NOT_RUN",
            "E13": "NOT_RUN",
            "Flutter": "NOT_RUN",
        }

    def run(self):
        if self.stage != "new":
            raise Refusal("one-shot harness already consumed")
        require_environment(self.env)
        self.status = "ACTIVE"
        try:
            validate_profile(self._call(self.adapter, "profile"))
            self.oracle.reserve()
            bootstrap = self.connect("bootstrap")
            freshness = tuple(self._call(self.adapter, "freshness", bootstrap, i) for i in range(4))
            validate_target(*freshness)
            freshness = None
            self._call(self.adapter, "bootstrap_begin", bootstrap)
            for index in range(18):
                self._call(self.adapter, "bootstrap_statement", bootstrap, index)
            self._call(self.adapter, "bootstrap_commit", bootstrap)
            self._call(self.adapter, "close_bootstrap", bootstrap)
            del self.handles["bootstrap"]
            owner = self.connect("owner")
            self._call(self.adapter, "owner_begin", owner)
            for index in range(2):
                self._call(self.adapter, "install_component", owner, index)
            self._call(self.adapter, "owner_commit", owner)
            self._call(self.adapter, "close_owner", owner)
            del self.handles["owner"]
            observer = self.connect("observer")
            identity = self.observe("observer_preflight", observer)
            expected = ("modkit_ci_operator_login", "modkit_operator") + (False,) * 5 + (True,) * 2
            if (
                type(identity) is not tuple
                or len(identity) != 9
                or any(type(a) is not type(b) or a != b for a, b in zip(identity, expected))
            ):
                raise Refusal("observer identity or privilege refused")
            self._receipts()
            self.ready = True
            self.native_phase()
            self._native_schedule()
            self.status = "PASS_OFFLINE_OR_ADAPTER_ONLY"
        except BaseException:
            if self.status != "UNKNOWN":
                self.status = "FAILED"
            raise


def main():
    raise Refusal("NOT_RUN: explicit reviewed adapter and separate native permission required")


if __name__ == "__main__":
    main()
