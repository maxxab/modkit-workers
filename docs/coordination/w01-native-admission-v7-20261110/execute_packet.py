"""One-attempt fresh native fixture controller. --check performs no native IO."""
import argparse
import hashlib
import json
import os
import resource
import stat
import subprocess
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent
IMAGE = 'sha256:1ce96cce5978a21ae11f09b3ad3cb619e1d0c7297c8f3becae51c6a9bb2979b0'
NAME = 'modkit-install-20261109-r4'
LABEL = 'install-20261109-r4'
STAGE = '/tmp/modkit-install-r4'
SOURCE_INPUTS_SHA = '57e0c0be08bc3a53fee5cfcb96050ed3c469ddc38a97ece75c9324a33574b0f4'
DOCKER = ['docker', '--host', 'unix:///var/run/docker.sock']
MODULES = ('fixture_runner.py', 'controller-provision.sql', 'source-inputs.json',
    'bootstrap/bootstrap.py', 'bootstrap/libpq_adapter.py', 'bootstrap/runtime_bootstrap.py',
    'validation/validator.py', 'validation/native_adapter.py', 'validation/native_probes.py',
    'validation/source_smoke.py', 'validation/native_actor.py', 'validation/expected-grant-contract.json')
PREP_CHECKS = ('packet_pure_tests.py', 'controller_tests.py', 'bootstrap/test_bootstrap.py', 'bootstrap/test_libpq.py', 'bootstrap/test_runtime.py', 'validation/test_validator.py', 'validation/test_native_transport.py', 'validation/test_native_probes.py', 'test_execution_controls.py', 'test_current_bindings.py', 'test_shared_slot.py', 'current-bindings-green.log', 'preparation-after-durability.log', 'shared-slot-green.log', 'test_capture_durability.py', 'capture-durability-green.log', 'capture-durability-baseline-red.log', 'test_failed_client.py', 'failed-client-red.log', 'failed-client-green.log', 'preparation-v4-final.log', 'test_native_admission.py', 'native-admission-green.log')


def need(ok, code):
    if not ok:
        raise ValueError(code)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def payload():
    source_bytes = (ROOT / 'source-inputs.json').read_bytes()
    need(digest(source_bytes) == SOURCE_INPUTS_SHA, 'SOURCE_MANIFEST_DRIFT')
    source = json.loads(source_bytes)
    need(source['commits'] == {'events': '7eb2ed814ab1a700b03c77c3a92dbb882b06a224',
                              'workers': 'a2a6da6a669275779cf4476d07ec00e64986e320'}
         and len(source['files']) == 78, 'SOURCE_COMMITS')
    names = list(MODULES) + [row['path'] for row in source['files']]
    names += ['corrected-inputs/' + component + '/' + name
              for component in ('events', 'workers')
              for name in ('0001_initial.sql', 'grants_runtime.sql', 'manifest.json')]
    names += ['corrected-inputs/events/owner_receipt.sql']
    need(len(names) == len(set(names)) and len(names) <= 256, 'PAYLOAD_INVENTORY')
    result = {}
    total = 0
    for name in names:
        relative = Path(name)
        need(not relative.is_absolute() and '..' not in relative.parts
             and all(part not in ('', '.') for part in relative.parts)
             and '\\' not in name and not name.endswith('.pyc') and '__pycache__' not in name,
             'PAYLOAD_PATH')
        path = ROOT / relative
        need(path.is_file() and not path.is_symlink(), 'PAYLOAD_FILE')
        need(not any(parent.is_symlink() for parent in path.parents if parent != ROOT.parent),
             'PAYLOAD_PARENT')
        raw = path.read_bytes()
        need(len(raw) <= 2 * 1024 * 1024, 'PAYLOAD_FILE_BOUND')
        total += len(raw)
        need(total <= 12 * 1024 * 1024, 'PAYLOAD_TOTAL_BOUND')
        result[name] = {'bytes': len(raw), 'sha256': digest(raw), 'hex': raw.hex()}
    for row in source['files']:
        need(result[row['path']]['sha256'] == row['sha256']
             and result[row['path']]['bytes'] == row['bytes'], 'SOURCE_DRIFT')
    return result


def absent(result, target):
    if result.returncode != 1 or result.stdout.strip() not in (b'', b'[]'):
        return False
    message = result.stderr.decode('utf-8', 'strict').strip()
    return any(message[:len(prefix)].casefold() == prefix and message[len(prefix):] == target
               for prefix in ('error: no such object: ', 'error: no such container: ',
                   'error response from daemon: no such object: ',
                   'error response from daemon: no such container: '))


STAGER = '''import hashlib,json,os
from pathlib import Path
root=Path("/tmp/modkit-install-r4")
data=json.loads(__import__('sys').stdin.buffer.read(33554433))
assert type(data) is dict and 0<len(data)<=256
root.mkdir(mode=0o700,exist_ok=False)
total=0; output={}
for name,row in sorted(data.items()):
 p=Path(name); assert not p.is_absolute() and '..' not in p.parts and '\\\\' not in name
 raw=bytes.fromhex(row['hex']); total+=len(raw)
 assert len(raw)==row['bytes'] and len(raw)<=2097152 and total<=12582912
 assert hashlib.sha256(raw).hexdigest()==row['sha256']
 target=root/p; target.parent.mkdir(parents=True,exist_ok=True)
 with target.open('xb') as f:f.write(raw)
 output[name]={'bytes':len(raw),'sha256':row['sha256']}
print(json.dumps(output,sort_keys=True))
'''

EXPORTER = '''import hashlib,json
from pathlib import Path
root=Path("/tmp/modkit-install-r4/run"); out={}; total=0
paths=sorted(root.iterdir()); assert len(paths)<=32
for p in paths:
 assert p.is_file() and not p.is_symlink() and p.suffix in ('.json','.stdout','.stderr')
 assert p.stat().st_size<=262144
 b=p.read_bytes();total+=len(b);assert total<=1048576
 out[p.name]={'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),'hex':b.hex()}
print(json.dumps(out,sort_keys=True))
'''


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def reserve_attempt(root):
    # The durable tombstone survives cleanup. A lost/truncated journal never admits replay.
    with (root / 'attempt.claim').open('x') as output:
        output.write('Exact one-shot attempt reserved; reconcile before further action.\n')
        output.flush()
        os.fsync(output.fileno())
    sync_directory(root)
    evidence = root / 'runtime-r4'
    evidence.mkdir(exist_ok=False)
    sync_directory(root)
    return evidence


def durable_json(directory, state):
    with (directory / 'result.pending').open('x') as output:
        json.dump(state, output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    os.replace(directory / 'result.pending', directory / 'result.json')
    sync_directory(directory)


def capture_bytes(stdout, stderr, cap):
    # Saturation is ambiguous even when a child catches EFBIG and exits zero.
    need(stdout.stat().st_size < cap and stderr.stat().st_size < cap,
         'CAPTURE_SATURATED_UNKNOWN')
    return stdout.read_bytes(), stderr.read_bytes()


ADMISSION_STATIC_SHA256 = {
    "source-inputs.json": "57e0c0be08bc3a53fee5cfcb96050ed3c469ddc38a97ece75c9324a33574b0f4",
    "execution-plan.json": "c8c1e75d93ee88d0b3ded60bb3c5f7501f6d0c895ce99b50fbc05ec88b59e113",
    "profile-probe-qa-inventory.json": "8f4f9bd4e6bc5e97f4ac95ae97c6b689b2e08dbe287bd1680f7713bdad3d3f49",
    "validation/source_smoke.py": "457a6f20d13e0b387db482ca0008280e76eddaf84187d1d287cd1c3c382a60a7",
    "validation/expected-grant-contract.json": "fb480a71e9d7e8bd7fba563cf3c027417b6b7476f743b209178b270c4e354f5f",
    "fixture_runner.py": "faf4e8f27a53ed7911906333d0f734a47cabc563ef938ad07c4ff7fb912fe3ac",
    "bootstrap/runtime_bootstrap.py": "d3d5a8680f42a5f52f028e6fbef577ecc1410e596ef8a8f30ecee40624bcdd79",
    "controller-provision.sql": "380dd393be28c261c9d5bfa68157271d1c4c8a0d8e388066565a1f3176a7bb4b",
    "baseline_consumer.py": "6f115b27d9da08fcdcc79a459cfd0f0639c5f676a3864c7e809dbe054ec473a9",
    "baseline-inputs.json": "e59ede22d9b626306d33fd67197bee1dc58539b71e8f2f0c2de44662053800f9",
}


def _admission_directory(relative=""):
    """Open only real directories, without following any path component symlink."""
    need(ROOT.is_absolute() and ".." not in ROOT.parts, "ADMISSION_ROOT")
    parts = () if not relative else tuple(relative.split("/"))
    need(all(part not in ("", ".", "..") for part in parts), "ADMISSION_PATH")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open("/", flags)
    try:
        for part in ROOT.parts[1:] + parts:
            successor = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = successor
        return fd
    except BaseException:
        os.close(fd)
        raise


def _admission_read(name, expected):
    parts = name.split("/")
    need(all(part not in ("", ".", "..") for part in parts) and "\\" not in name, "ADMISSION_PATH")
    directory = _admission_directory("/".join(parts[:-1]))
    try:
        fd = os.open(
            parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=directory
        )
    finally:
        os.close(directory)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        need(stat.S_ISREG(info.st_mode) and info.st_size <= 2 * 1024 * 1024, "ADMISSION_FILE_BOUND")
        raw = stream.read(2 * 1024 * 1024 + 1)
    need(len(raw) <= 2 * 1024 * 1024 and digest(raw) == expected, "ADMISSION_INPUT_DRIFT")
    return raw


def _checked_admission(pins):
    """Select the fixed historical baseline before any native slot/attempt effect.

    This does not authenticate or create a user grant. Existing exact release and
    final independent execution review checks precede it; the CLI stays disabled.
    """
    static = {
        name: _admission_read(name, digest_) for name, digest_ in ADMISSION_STATIC_SHA256.items()
    }
    fixture = json.loads(static["baseline-inputs.json"])["files"]
    need(len(fixture) == 48, "ADMISSION_BASELINE_CLOSURE")
    inventory = {
        f"baseline-evidence/{index:03}.bin": (key, digest_)
        for index, (key, digest_) in enumerate(sorted(fixture.items()), 1)
    }
    directory = _admission_directory("baseline-evidence")
    try:
        need(
            set(os.listdir(directory)) == {name.split("/")[1] for name in inventory},
            "ADMISSION_BASELINE_INVENTORY",
        )
    finally:
        os.close(directory)
    expected = dict(ADMISSION_STATIC_SHA256)
    expected.update({name: digest_ for name, (_, digest_) in inventory.items()})
    need(pins.get("admission_inputs") == expected, "ADMISSION_PIN_DRIFT")
    need(pins.get("plan_sha256") == expected["execution-plan.json"], "ADMISSION_PLAN_DRIFT")
    identity = {
        "scope": "REDIS8_CURRENT_ABSENCE_RECONCILIATION_V1",
        "review_sha256": "8e5b622e460ba564029d0e786b22fce8666879e280835d0efb1a26949dd09d75",
        "result_sha256": "d0277050aa931b1fa116271fc2cf83be3cbfeac1dee34307d0a04320f4425e8a",
        "terminal_sha256": "33ce28d0bd25e5f17f75747fcb184a507b651a21fb363ff8d9419c4084f6ad4b",
        "contract_sha256": "a083cb920e25875ac0c08f5454b3403ebf157e9939d2d0191d3519cc2af77abf",
    }
    need(pins.get("historical_baseline") == identity, "ADMISSION_BASELINE_IDENTITY")
    bundle = {key: _admission_read(name, digest_) for name, (key, digest_) in inventory.items()}
    module_name = "_workers_reviewed_historical_baseline_v7"
    need(module_name not in sys.modules, "ADMISSION_MODULE_COLLISION")
    module = types.ModuleType(module_name)
    module.__file__ = str(ROOT / "baseline_consumer.py")
    sys.modules[module_name] = module
    try:
        exec(compile(static["baseline_consumer.py"], module.__file__, "exec"), module.__dict__)
        baseline = module.verify_baseline(bundle)
    finally:
        del sys.modules[module_name]
    need(
        baseline.scope == identity["scope"]
        and baseline.review_sha256 == identity["review_sha256"]
        and baseline.result_sha256 == identity["result_sha256"]
        and baseline.terminal_sha256 == identity["terminal_sha256"]
        and baseline.history == ("UNKNOWN_UNCHANGED", "UNKNOWN_UNCHANGED", "UNKNOWN")
        and baseline.native_authorized is False
        and baseline.live_absence_asserted is False,
        "ADMISSION_HISTORICAL_ONLY",
    )


def _checked_execution(data, release_path):
    pin_bytes = (ROOT / 'execution-pins.json').read_bytes()
    pins = json.loads(pin_bytes)
    expected = {name: {k: row[k] for k in ('bytes', 'sha256')} for name, row in data.items()}
    need(pins['payload'] == expected and pins['controller_sha256'] == digest(Path(__file__).read_bytes()),
         'EXECUTION_PIN_DRIFT')
    need(set(pins.get('preparation_checks', {})) == set(PREP_CHECKS), 'PREPARATION_CHECK_INVENTORY')
    for name, pin in pins['preparation_checks'].items():
        need(digest((ROOT / name).read_bytes()) == pin, 'PREPARATION_CHECK_DRIFT')
    release = json.loads(Path(release_path).read_bytes())
    need(set(release) == {'decision', 'pins_sha256', 'review_sha256', 'authority_reference', 'attempt', 'fixture'}
         and release['decision'] == 'APPROVE_EXACT_ONCE' and release['attempt'] == 1
         and type(release['attempt']) is int and release['fixture'] == NAME
         and release['pins_sha256'] == digest(pin_bytes)
         and type(release['authority_reference']) is str and release['authority_reference'], 'NO_EXACT_AUTHORITY')
    need(digest((ROOT / 'independent-execution-review.md').read_bytes()) == release['review_sha256'],
         'INDEPENDENT_REVIEW_DRIFT')
    _checked_admission(pins)
    return release, pins, expected


def _execute_owned(data, release, pins, expected):
    evidence = reserve_attempt(ROOT)
    state = {'status': 'UNKNOWN', 'fixture': NAME, 'cid': None, 'commands': [],
             'cleanup': 'NOT_ATTEMPTED', 'authority': release}
    start = time.monotonic()

    def save():
        durable_json(evidence, state)

    def call(args, *, timeout=10, check=True, stdin=None, cap=2097152):
        need(time.monotonic() - start < 600 and len(state['commands']) < 48, 'COMMAND_BUDGET')
        row = {'argv': DOCKER + args, 'timeout': timeout, 'per_stream_limit': cap,
               'outcome': 'ATTEMPTED_UNCONFIRMED'}
        state['commands'].append(row)
        index = len(state['commands'])
        save()
        def limit():
            resource.setrlimit(resource.RLIMIT_FSIZE, (cap, cap))
        child = primary = None
        try:
            with (evidence / f'{index:02}.stdout').open('xb') as out, (evidence / f'{index:02}.stderr').open('xb') as err:
                try:
                    child = subprocess.Popen(DOCKER + args, stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                                             stdout=out, stderr=err, preexec_fn=limit)
                    row['pid'] = child.pid
                    save()
                    child.communicate(input=stdin, timeout=timeout)
                    # Persist captures before progression or fixture disposal.
                    for stream in (out, err):
                        stream.flush()
                        os.fsync(stream.fileno())
                except BaseException as error:
                    primary = error  # Even a later stream-close failure cannot replace it.
                    raise
            sync_directory(evidence)
        except BaseException as error:
            if primary is None:
                primary = error
            row['outcome'] = 'FAILED_OR_TIMEOUT_SERVER_UNKNOWN'
            row['failure_type'] = type(primary).__name__
            observation = {'handle_obtained': child is not None, 'pid': row.get('pid'),
                           'policy': 'PRESERVE_CLIENT_PID_FOR_EXPLICIT_RECONCILIATION',
                           'returncode_observed': None, 'client_may_continue': True,
                           'automatic_kill_attempted': False, 'automatic_wait_attempted': False}
            row['local_client_observation'] = observation
            # Retained reviewed policy: no automatic kill/wait on failure.
            # Reading the handle's cached returncode is not a server outcome.
            if child is not None:
                try:
                    code = child.returncode
                    if type(code) is int:
                        observation['returncode_observed'] = code
                        observation['client_may_continue'] = False
                except BaseException as observation_error:
                    observation['observation_error_type'] = type(observation_error).__name__
            captures = {'partial_only': True,
                        'writer_unresolved': observation['client_may_continue'], 'errors': []}
            row['failure_captures'] = captures
            # Stream contexts are closed. Sync each available partial separately;
            # one failed sync must not skip the other capture or directory.
            for suffix in ('stdout', 'stderr'):
                captures[suffix + '_fsynced'] = False
                try:
                    with (evidence / f'{index:02}.{suffix}').open('rb') as partial:
                        os.fsync(partial.fileno())
                    captures[suffix + '_fsynced'] = True
                except BaseException as capture_error:
                    captures['errors'].append({'stage': suffix, 'type': type(capture_error).__name__})
            captures['directory_fsynced'] = False
            try:
                sync_directory(evidence)
                captures['directory_fsynced'] = True
            except BaseException as capture_error:
                captures['errors'].append({'stage': 'directory', 'type': type(capture_error).__name__})
            try:
                save()
            except BaseException:
                pass  # Preserve the original error and already durable claim/slot.
            if primary is error:
                raise
            raise primary
        row.update(outcome='RETURNED_CAPTURE_UNCONFIRMED', exit_code=child.returncode)
        save()
        stdout, stderr = capture_bytes(evidence / f'{index:02}.stdout', evidence / f'{index:02}.stderr', cap)
        row['outcome'] = 'RETURNED_BOUNDED'
        save()
        result = subprocess.CompletedProcess(DOCKER + args, child.returncode, stdout, stderr)
        if check:
            need(result.returncode == 0, 'COMMAND_FAILED_PRESERVE_FIXTURE')
        return result

    def inspect(cid):
        info = json.loads(call(['inspect', cid]).stdout)[0]
        host = info['HostConfig']
        need(info['Id'] == cid and info['Name'] == '/' + NAME and info['Image'] == IMAGE
             and info['Config']['User'] == '999:999'
             and info['Config']['Labels']['modkit.qa.packet'] == LABEL, 'FIXTURE_IDENTITY')
        need(host['NetworkMode'] == 'none' and not host.get('PortBindings') and not host.get('Binds')
             and host['ReadonlyRootfs'] and host['Memory'] == host['MemorySwap'] == 536870912
             and host['NanoCpus'] == 1000000000 and host['PidsLimit'] == 128
             and host['CapDrop'] == ['ALL'] and 'no-new-privileges:true' in host['SecurityOpt'], 'FIXTURE_LIMITS')
        need(host['Tmpfs'] == {'/var/lib/postgresql': 'rw,noexec,nosuid,size=268435456,uid=999,gid=999,mode=0700',
                              '/tmp': 'rw,noexec,nosuid,size=134217728,uid=999,gid=999,mode=1777'}
             and all(m['Type'] == 'tmpfs' and m['Destination'] in host['Tmpfs'] for m in info['Mounts']),
             'FIXTURE_STORAGE')
        need(host['LogConfig'] == {'Type': 'local', 'Config': {
            'max-size': '8m', 'max-file': '1', 'compress': 'false'}}, 'FIXTURE_LOG_BOUND')
        return info

    save()
    try:
        need(absent(call(['inspect', NAME], check=False), NAME), 'NEW_NAME_NOT_ABSENT')
        image = json.loads(call(['image', 'inspect', IMAGE]).stdout)[0]
        need(image['Id'] == IMAGE and set(image['Config'].get('Volumes') or {}) <= {'/var/lib/postgresql'},
             'IMAGE_IDENTITY')
        plan = json.loads((ROOT / 'execution-plan.json').read_bytes())
        need(plan['create_argv'][0:5] == ['create', '--pull', 'never', '--name', NAME]
             and digest((ROOT / 'execution-plan.json').read_bytes()) == pins['plan_sha256'], 'PLAN_DRIFT')
        cid = call(plan['create_argv']).stdout.decode().strip()
        need(len(cid) == 64 and all(c in '0123456789abcdef' for c in cid), 'INVALID_CID')
        state['cid'] = cid
        save()
        need(inspect(cid)['State']['Status'] == 'created', 'CREATED_STATE')
        call(['start', cid])
        ready = False
        for _ in range(20):
            result = call(['exec', cid, '/usr/lib/postgresql/18/bin/pg_isready', '-h', '/tmp',
                           '-U', 'postgres', '-d', 'postgres', '-t', '1'], timeout=5, check=False)
            if result.returncode == 0:
                ready = True
                break
            time.sleep(.25)
        need(ready, 'POSTGRES_STARTUP_UNKNOWN')
        python = ['/opt/w01/venv/bin/python', '-I', '-S', '-B', '-X', 'pycache_prefix=' + STAGE + '/unused-bytecode']
        raw = json.dumps(data, sort_keys=True).encode()
        need(len(raw) <= 33554432, 'STAGE_INPUT_BOUND')
        staged = call(['exec', '-i', cid, *python, '-c', STAGER], timeout=30, stdin=raw)
        need(json.loads(staged.stdout) == expected, 'STAGE_PROVENANCE')
        run = call(['exec', cid, *python, STAGE + '/fixture_runner.py', '--execute'], timeout=300, check=False)
        exported = call(['exec', cid, *python, '-c', EXPORTER], timeout=15, cap=3145728)
        artifacts = evidence / 'actor-evidence'
        artifacts.mkdir()
        for name, row in json.loads(exported.stdout).items():
            need('/' not in name and '\\' not in name and name not in ('.', '..'), 'EXPORT_PATH')
            blob = bytes.fromhex(row['hex'])
            need(len(blob) == row['bytes'] and digest(blob) == row['sha256'], 'EXPORT_IDENTITY')
            with (artifacts / name).open('xb') as output:
                output.write(blob)
                output.flush()
                os.fsync(output.fileno())
        sync_directory(artifacts)
        sync_directory(evidence)
        need(run.returncode == 0, 'RUNNER_FAILED_PRESERVE_FIXTURE')
        result = json.loads((artifacts / 'result.json').read_bytes())
        need(result['status'] == 'PASS_SOURCE_INSTALL_ACL_NATIVE_NOT_INSTALLED'
             and result['validation']['status'] == 'PASS'
             and result['validation']['native_probes_completed'] == 14
             and all(c['closed'] is True for c in result['connections'])
             and result['census'] == {'other_backends': 0, 'other_locks': 0}, 'NATIVE_RESULT')
        for mode in ('runtime', 'reconciler', 'recovery-owner'):
            native = json.loads((artifacts / ('native-' + mode + '.json')).read_bytes())
            need(native['physical_closed'] is True and native['ledger_uncertain'] is False
                 and native['capacity_final'] and all(type(n) is int and n == 0
                     for n in native['capacity_final'].values()), 'NATIVE_CAPACITY')
        inspect(cid)
        state['cleanup'] = 'GRACEFUL_STOP_ATTEMPTED_UNCONFIRMED'
        save()
        call(['kill', '--signal=TERM', cid])
        need(call(['wait', cid], timeout=30).stdout.strip() == b'0', 'STOP_UNKNOWN')
        stopped = inspect(cid)['State']
        need(stopped['Status'] == 'exited' and stopped['Running'] is False and stopped['ExitCode'] == 0
             and stopped['OOMKilled'] is False and not stopped['Error'], 'UNCLEAN_STOP')
        state['cleanup'] = 'NONFORCE_REMOVAL_ATTEMPTED_UNCONFIRMED'
        save()
        need(call(['rm', cid]).stdout.decode().strip() == cid, 'REMOVE_UNKNOWN')
        need(absent(call(['inspect', cid], check=False), cid)
             and absent(call(['inspect', NAME], check=False), NAME), 'REMOVAL_NOT_PROVED')
        state['status'] = 'PASS_SOURCE_INSTALL_ACL_NATIVE_NOT_INSTALLED'
        state['cleanup'] = 'EXACT_CONTAINER_ABSENT_NO_VOLUMES_OR_BINDS'
    except BaseException:
        try:
            save()
        except BaseException:
            pass  # Failure journaling cannot replace the original command error.
        raise
    else:
        save()
    return state


RUNTIME_SLOT_SOURCE = Path('/home/faris/modkit-local-20261106/resume-events-20261109/runtime-slot-v1/runtime_slot.py')
RUNTIME_SLOT_SHA256 = '08351e65ef87870c99696b80a28d46dc1f50c7eb2aa55675c99291d594526c2e'


def _runtime_slot_class():
    need(len(RUNTIME_SLOT_SHA256) == 64, 'RUNTIME_SLOT_UNFROZEN')
    need(RUNTIME_SLOT_SOURCE.is_file() and not RUNTIME_SLOT_SOURCE.is_symlink()
         and RUNTIME_SLOT_SOURCE.stat().st_size <= 65536, 'RUNTIME_SLOT_SOURCE')
    raw = RUNTIME_SLOT_SOURCE.read_bytes()
    need(digest(raw) == RUNTIME_SLOT_SHA256, 'RUNTIME_SLOT_DRIFT')
    namespace = {'__name__': 'workers_canonical_runtime_slot', '__file__': str(RUNTIME_SLOT_SOURCE)}
    exec(compile(raw, str(RUNTIME_SLOT_SOURCE), 'exec'), namespace)
    return namespace['RuntimeSlot']


def execute(data, release_path):
    # Authority and all source pins are checked before admission; no Docker is reachable here.
    release, pins, expected = _checked_execution(data, release_path)
    slot_type = _runtime_slot_class()
    with slot_type(owner='workers-main', operation='native-install',
                   pins_sha256=release['pins_sha256'], targets=(NAME,), evidence_dir=ROOT) as slot:
        # Every launch/actor/export/known-close/cleanup/absence command is inside this scope.
        # Exceptions leave durable unresolved ownership. No timeout/PID/stale takeover.
        result = _execute_owned(data, release, pins, expected)
        need(result['status'] == 'PASS_SOURCE_INSTALL_ACL_NATIVE_NOT_INSTALLED'
             and result['cleanup'] == 'EXACT_CONTAINER_ABSENT_NO_VOLUMES_OR_BINDS',
             'RUNTIME_SLOT_TERMINAL_UNCONFIRMED')
        evidence = ROOT / 'runtime-r4/result.json'
        slot.complete('SUCCESS_CLEANED', evidence_path=evidence,
                      evidence_sha256=digest(evidence.read_bytes()))
        return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--release')
    args = parser.parse_args()
    if args.release:
        raise SystemExit('UNRELEASED_TEMPLATE_NO_RUNTIME_AUTHORITY')
    files = payload()
    if args.release:
        execute(files, args.release)
    else:
        print(json.dumps({'status': 'PREPARATION_ONLY_NO_NATIVE_IO', 'files': len(files),
                          'bytes': sum(row['bytes'] for row in files.values())}))
