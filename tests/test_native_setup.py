"""Real canonical configuration plus test-only resource facts; no DB connections."""

import os
import subprocess
import sys
from importlib import util
from pathlib import Path

import pytest

PREFIX = """
import copy
from modkit_events.persistence import managed_lifecycle as managed
from modkit_events.persistence.ledger import ExecutionLedger
from modkit_events.persistence.resource_registry import resource_domain
from modkit_workers import native_setup as setup
from modkit_workers.native_contracts import NativeJobConfig, NativeJobResources
from modkit_events.persistence.bindings import ReadinessExpectation
from modkit_events.persistence.observations import SchemaStatus
limits = managed.LifecycleLimits(
    retained_cells=2, admitted_live=2, checkouts=2, roots=3, roots_per_checkout=2,
    executions=2, preparations=2, preparations_per_execution=1, prepare_bytes=1049857,
    prepare_bytes_per_execution=1049857, results=2, results_per_ticket=1,
    result_bytes=44129507, result_bytes_per_ticket=44129507,
    cleanup_bundles=2, cleanup_bytes=8192, construction_slots=6)
pins = ReadinessExpectation(components=tuple(
    SchemaStatus(component=c, version=1, migration_digest=b'x'*32,
        catalog_contract_id='modkit-pg-ab-2', scope_format_id='MKSC-1', intent_format_id='MKPF-1')
    for c in ('events','workers')))
config = NativeJobConfig(readiness=pins, lease_seconds=30,
    max_acquire_page_payload_bytes=2**32,max_payload_bytes=1048576,
    max_payload_depth=32,max_result_bytes=1048576,source_material_bytes=1073741824)
def rejects(call):
    try:
        call()
    except (ValueError, RuntimeError, TypeError):
        return
    raise AssertionError('expected refusal')
"""


def run_case(body):
    assert util.find_spec("modkit_workers.native_setup") is not None, "real setup is absent"
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    src = str(Path(__file__).parents[1] / "src")
    env["PYTHONPATH"] = src + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-B", "-c", PREFIX + body],
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_real_configuration_receipt_once_only_and_retained_limit_snapshot():
    run_case("""
receipt = setup.configure_native_job_profile(limits=limits)
checked = setup._checked_limits(receipt)
assert checked == limits and checked is not limits
object.__setattr__(limits, 'roots', 99)
assert setup._checked_limits(receipt).roots == 3
rejects(lambda: setup.configure_native_job_profile(limits=checked))
rejects(lambda: setup.NativeJobConfigurationReceipt())
rejects(lambda: copy.copy(receipt))
rejects(lambda: setup._checked_limits(object()))
""")


def test_receipt_slot_tampering_does_not_change_issuance_authority():
    run_case("""
receipt = setup.configure_native_job_profile(limits=limits)
object.__setattr__(receipt, '_stamp', object())
rejects(lambda: setup._checked_limits(receipt))
""")


def test_preconfigured_without_receipt_is_not_reconfigured_or_adopted():
    run_case("""
managed.configure_managed_registry(limits=limits, execution_ledger=ExecutionLedger())
try:
    setup.configure_native_job_profile(limits=limits)
except Exception:
    pass
else:
    raise AssertionError('preconfigured domain accepted')
rejects(lambda: setup.configure_native_job_profile(limits=limits))
""")


RESOURCES = """
receipt = setup.configure_native_job_profile(limits=limits)
class Backend:
    transaction_status = 0
    pipeline_status = 0
class Connection:
    closed = False
    autocommit = False
    def __init__(self):
        self.pgconn = Backend()
setup._native_connection_type = lambda: Connection
resources = NativeJobResources(configuration=receipt,
    data_connection=Connection(), renewal_connection=Connection(),
    data_ledger=ExecutionLedger(), renewal_ledger=ExecutionLedger())
source = object()
"""


def test_validation_is_not_adoption_and_adoption_has_one_observable_owner():
    run_case(
        RESOURCES
        + """
setup._validate_resources(resources, config=config, source=source)
assert not setup._resources_adopted(resources, source)
setup._adopt_resources(resources, source)
assert setup._resources_adopted(resources, source)
assert not setup._resources_adopted(resources, object())
rejects(lambda: setup._adopt_resources(resources, object()))
rejects(lambda: setup._adopt_resources(resources, source))
resource_domain().trip()
assert setup._resources_adopted(resources, source)
"""
    )


@pytest.mark.parametrize(
    "change",
    [
        "object.__setattr__(resources, 'renewal_connection', resources.data_connection)",
        "object.__setattr__(resources, 'renewal_ledger', resources.data_ledger)",
        "resources.data_connection.autocommit = True",
        "resources.data_connection.pgconn.transaction_status = 2",
        "resources.data_connection.closed = True",
        "resource_domain().trip()",
    ],
)
def test_invalid_resources_reject_before_ownership_transfer(change):
    run_case(
        RESOURCES
        + change
        + """
rejects(lambda: setup._validate_resources(resources, config=config, source=source))
assert not setup._resources_adopted(resources, source)
"""
    )


def test_two_adopters_have_exactly_one_winner():
    run_case(
        RESOURCES
        + """
from threading import Barrier, Thread
gate=Barrier(3)
wins=[]
def adopt(owner):
    gate.wait()
    try:
        setup._adopt_resources(resources, owner)
        wins.append(owner)
    except RuntimeError:
        pass
owners=[object(),object()]
threads=[Thread(target=adopt,args=(owner,)) for owner in owners]
for t in threads:t.start()
gate.wait()
for t in threads:
    t.join(3)
    assert not t.is_alive()
assert len(wins)==1
assert setup._resources_adopted(resources,wins[0])
"""
    )


def test_setup_module_import_never_imports_optional_driver():
    run_case("""
import sys
assert 'psycopg' not in sys.modules
assert 'modkit_events.persistence.native_sync' not in sys.modules
""")


def test_receipt_rejects_deletion_and_detects_bypassed_missing_stamp():
    run_case("""
receipt = setup.configure_native_job_profile(limits=limits)
try:
    del receipt._stamp
except AttributeError:
    pass
else:
    raise AssertionError('receipt allowed ordinary deletion')
object.__delattr__(receipt, '_stamp')
rejects(lambda: setup._checked_limits(receipt))
""")


def test_insufficient_configured_native_capacity_rejects_before_adoption():
    run_case(
        RESOURCES.replace(
            "receipt = setup.configure_native_job_profile(limits=limits)",
            "from dataclasses import replace\nlimits=replace(limits, construction_slots=5)\n"
            "receipt = setup.configure_native_job_profile(limits=limits)",
        )
        + """
rejects(lambda: setup._validate_resources(resources, config=config, source=source))
assert not setup._resources_adopted(resources, source)
"""
    )


def test_adopted_carrier_cannot_be_replaced_or_tampered():
    run_case(
        RESOURCES
        + """
from dataclasses import replace
setup._validate_resources(resources, config=config, source=source)
setup._adopt_resources(resources, source)
rejects(lambda: setup._resources_adopted(replace(resources), source))
object.__setattr__(resources, 'data_connection', Connection())
rejects(lambda: setup._resources_adopted(resources, source))
"""
    )
