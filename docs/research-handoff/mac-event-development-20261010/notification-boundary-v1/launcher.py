"""Explicit no-Seatbelt development protocol. Manual execution only.

No isolation qualification, network/fork/file-escape probes or old supervisor.
One child runs pure tests/algorithms; a parent records bounded streams/exit.
OS file/network isolation is absent. Resource control is not qualified yet.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import selectors
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE
WORKSPACE = HERE.parents[1]
PYTHON = Path('<LOCAL_RUNTIME_PATH>')
LABEL = 'DEVELOPMENT_ONLY_NO_OS_FILE_NETWORK_ISOLATION'
UNIT = '5 regression test bundles + 100 method-prefix bundles + 85 reference bundles'


def sha(path):
    if path.is_symlink():
        raise ValueError('symlink input forbidden: ' + str(path))
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, data):
    with path.open('x') as handle:
        json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write('\n')


def verify():
    manifest = json.loads((HERE / 'binding.json').read_text())
    for item in manifest['files']:
        if sha(WORKSPACE / item['path']) != item['sha256']:
            raise ValueError('binding mismatch: ' + item['path'])
    if sha(PYTHON.resolve()) != manifest['python_sha256']:
        raise ValueError('runtime executable mismatch')
    frozen = WORKSPACE / 'next-round-package-005-r2'
    doc = json.loads((frozen / 'MANIFEST.json').read_text())
    if len(doc['files']) != 362:
        raise ValueError('frozen count mismatch')
    for item in doc['files']:
        if sha(frozen / item['path']) != item['sha256']:
            raise ValueError('old frozen mismatch: ' + item['path'])
    return manifest


def emit(phase, count, result):
    print(json.dumps({'protocol': LABEL, 'phase': phase,
                      'counted_bundles': count, 'result': result}), flush=True)


def calculate():
    # Child limits bound this one process; algorithm/test modules create none.
    resource.setrlimit(resource.RLIMIT_CPU, (50, 50))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    verify()
    sys.path.insert(0, str(ROOT))
    import unittest
    import regression_tests
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(regression_tests.BoundaryTests)
    if suite.countTestCases() != 5:
        raise ValueError('five regression bundles required')
    result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
    emit('regression_tests', 5, {'tests_run': result.testsRun, 'passed': result.wasSuccessful()})
    if not result.wasSuccessful():
        raise RuntimeError('regression failure; main phase not started')
    public = json.loads((ROOT / 'public-input.json').read_text())
    from worker import run
    output = run(public)
    if output['method_invocations'] != 100:
        raise ValueError('main budget mismatch')
    emit('main', 100, output)
    # No OS barrier: this is code-order separation of oracle and worker only.
    oracle = json.loads((ROOT / 'oracle.physical.json').read_text())
    from offline_evaluator import evaluate_saved
    report = evaluate_saved(public, oracle, output, 105)
    emit('evaluation', 85, report)
    if report['total_evaluations'] != 190 or any(
            v is False for row in report['checks'] for k, v in row.items() if k.endswith('match')):
        raise RuntimeError('independent verification failed; report preserved')
    verify()


def interrupted(sig, frame):
    raise RuntimeError('received signal ' + str(sig))


def launch():
    parser = argparse.ArgumentParser()
    parser.add_argument('--confirm-no-os-isolation', action='store_true', required=True)
    parser.add_argument('--output-name', required=True)
    args = parser.parse_args()
    if not args.output_name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in args.output_name):
        raise ValueError('output name must use lowercase letters/digits/hyphen')
    started = time.monotonic()
    out = HERE / args.output_name
    out.mkdir()  # never overwrite/reuse a result directory
    child = None
    reaped = False
    status = None
    usage = None
    error = None
    streams = {}
    selector = selectors.DefaultSelector()
    receipt = {'protocol': LABEL, 'os_file_network_isolation': False,
               'requested_limits': {'wall_seconds': 120, 'aggregate_cpu_seconds': 60, 'bundles': 240},
               'enforcement': 'single child CPU hard50 + parent CPU hard8; wall cooperative110; output9MiB',
               'attempts': 1, 'retries': 0, 'evaluation_unit': UNIT}
    try:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGXCPU):
            signal.signal(sig, interrupted)
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        # Keep hard60 until spawning: a child cannot raise an inherited hard8.
        # Soft7 stops prelaunch parent work; lower parent hard8 after Popen.
        resource.setrlimit(resource.RLIMIT_CPU, (7, 60))
        with (HERE / 'execution-used.json').open('x') as mark:
            json.dump({'status': 'CONSUMED_ONCE_BEFORE_LAUNCH', 'output': str(out), 'controller_pid': os.getpid()}, mark)
        binding = verify()
        write(out / 'intent.json', receipt | {'binding_sha256': sha(HERE / 'binding.json'), 'status': 'CONSUMED'})
        # Fixed executable/script; no shell; no sandbox/old actor/probe dispatch.
        command = [str(PYTHON), '-I', '-B', str(HERE / 'launcher.py'), '--internal-pure-calculation']
        receipt['command'] = command
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, start_new_session=True, close_fds=True,
                                 env={'PATH': '/usr/bin:/bin', 'LANG': 'C.UTF-8', 'PCG_PARENT_PID': str(os.getpid())})
        for name in ('stdout', 'stderr'):
            pipe = getattr(child, name)
            streams[name] = bytearray()
            os.set_blocking(pipe.fileno(), False)
            selector.register(pipe, selectors.EVENT_READ, name)
        resource.setrlimit(resource.RLIMIT_CPU, (7, 8))
        while selector.get_map() or not reaped:
            if time.monotonic() - started >= 110:
                raise TimeoutError('wall stop110 before nominal120')
            for key, _ in selector.select(0.05):
                chunk = os.read(key.fileobj.fileno(), 65536)
                if chunk:
                    streams[key.data].extend(chunk)
                else:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
            if sum(map(len, streams.values())) > 9 * 1024 * 1024:
                raise RuntimeError('output stop9MiB')
            if not reaped:
                pid, child_status, child_usage = os.wait4(child.pid, os.WNOHANG)
                if pid:
                    reaped, status, usage = True, child_status, child_usage
                    child.returncode = os.waitstatus_to_exitcode(status)
        receipt['child_exit_code'] = os.waitstatus_to_exitcode(status)
        if receipt['child_exit_code'] != 0:
            raise RuntimeError('child failed')
        rows = [json.loads(line) for line in streams['stdout'].decode().splitlines()]
        if [r['phase'] for r in rows] != ['regression_tests', 'main', 'evaluation']:
            raise ValueError('phase receipts missing/extra')
        if [r['counted_bundles'] for r in rows] != [5, 100, 85]:
            raise ValueError('budget receipts mismatch')
        verify()
        receipt.update(status='DEVELOPMENT_COMPLETED_NOT_ISOLATION_QUALIFIED', tests_run=5, counted_bundles=190)
        receipt['physical_notification_acceptance'] = rows[-1]['result']['physical_notification_acceptance']
        receipt['physical_misses'] = rows[-1]['result']['physical_misses']
        if not receipt['physical_notification_acceptance']:
            receipt['status'] = 'DIAGNOSTIC_COMPLETED_WITH_PHYSICAL_ALERT_GAPS_NOT_SAFETY_ACCEPTANCE'
    except BaseException as exc:
        error = type(exc).__name__ + ': ' + str(exc)
        receipt['status'] = 'FAILED_STOPPED_NO_RETRY'
    finally:
        # Signals during cleanup must not skip kill/drain/receipt steps.
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGXCPU):
            signal.signal(sig, signal.SIG_IGN)
        if child is not None:
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            if not reaped:
                _, status, usage = os.wait4(child.pid, 0)
                child.returncode = os.waitstatus_to_exitcode(status)
            receipt['child_exit_code'] = os.waitstatus_to_exitcode(status)
            for name in ('stdout', 'stderr'):
                pipe = getattr(child, name)
                if pipe.closed:
                    continue
                streams.setdefault(name, bytearray())
                os.set_blocking(pipe.fileno(), False)
                while sum(map(len, streams.values())) < 10 * 1024 * 1024:
                    try:
                        data = os.read(pipe.fileno(), 65536)
                    except BlockingIOError:
                        break
                    if not data:
                        break
                    streams[name].extend(data)
                pipe.close()
        selector.close()
        for name, data in streams.items():
            (out / (name + '.log')).write_bytes(data)
        receipt['output_sha256'] = {name + '.log': sha(out / (name + '.log')) for name in streams}
        try:
            verify()
            receipt['input_and_362_frozen_hashes_after'] = 'MATCH'
        except BaseException as exc:
            receipt['input_and_362_frozen_hashes_after'] = str(exc)
            error = error or 'post hash failed'
            receipt['status'] = 'FAILED_STOPPED_NO_RETRY'
        receipt['error'] = error
        own = resource.getrusage(resource.RUSAGE_SELF)
        receipt['charged_cpu_seconds'] = own.ru_utime + own.ru_stime + (0 if usage is None else usage.ru_utime + usage.ru_stime)
        receipt['wall_seconds_before_receipt_write'] = time.monotonic() - started
        if receipt['charged_cpu_seconds'] > 60 or receipt['wall_seconds_before_receipt_write'] > 120:
            error = error or 'final measured resource budget exceeded'
            receipt.update(status='FAILED_STOPPED_NO_RETRY', error=error)
        write(out / 'receipt.json', receipt)
    print(str(out / 'receipt.json'))
    return 1 if error else 0


if __name__ == '__main__':
    if sys.argv[1:] == ['--internal-pure-calculation']:
        mark = json.loads((HERE / 'execution-used.json').read_text())
        if str(os.getppid()) != os.environ.get('PCG_PARENT_PID') or mark['controller_pid'] != os.getppid():
            raise SystemExit('BLOCKED: internal child requires parent gate')
        calculate()
        raise SystemExit(0)
    raise SystemExit(launch())
