"""Explicit integrated preparation tests, standard library only, never native IO.

Run: python3 -I -S -B packet_pure_tests.py
Audit hook is installed before loading packet modules or tests.
"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if not (sys.flags.isolated and sys.flags.no_site and sys.dont_write_bytecode):
    raise SystemExit('isolated no-site no-bytecode interpreter required')


def guard(event, args):
    if event.startswith('socket.') or event in {
        'subprocess.Popen', 'os.system', 'os.fork', 'os.forkpty', 'os.posix_spawn',
        'os.exec', 'os.kill', 'os.killpg',
    }:
        raise RuntimeError('preparation-only operation forbidden')
    if event == 'ctypes.dlopen' and args and args[0] is not None:
        raise RuntimeError('foreign native library loading forbidden')
    if event == 'import' and args and str(args[0]).startswith(('modkit_events', 'modkit_workers')):
        raise RuntimeError('product imports forbidden during packet preparation')
    if event == 'open' and args and isinstance(args[0], (str, bytes)):
        name = str(args[0])
        if name.endswith('.pyc') and str(ROOT) in name:
            raise RuntimeError('packet bytecode reads forbidden')


sys.addaudithook(guard)
suite = unittest.TestSuite()
for index, relative in enumerate(('controller_tests.py', 'bootstrap/test_bootstrap.py',
                                  'bootstrap/test_libpq.py', 'bootstrap/test_runtime.py',
                                  'validation/test_validator.py', 'validation/test_native_transport.py',
                                  'validation/test_native_probes.py', 'test_execution_controls.py',
                                  'test_capture_durability.py', 'test_failed_client.py', 'test_current_bindings.py', 'test_native_admission.py')):
    path = ROOT / relative
    if not path.is_file() or path.is_symlink():
        raise SystemExit('missing exact preparation test')
    # Compile source directly: no local bytecode loader or project startup hook.
    name = 'packet_pure_case_' + str(index)
    import types
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(path.read_bytes(), str(path), 'exec'), module.__dict__)
    suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))

result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not result.wasSuccessful())
