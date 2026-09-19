"""Integration checks use only a copied runner and benign Python workers."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def mirror(tmp_path):
    (tmp_path / 'tools').mkdir()
    package = tmp_path / 'src/laboratorio'
    package.mkdir(parents=True)
    (package / '__init__.py').touch()
    shutil.copy(ROOT / 'src/laboratorio/evaluation.py', package)
    shutil.copy(ROOT / 'tools/probar_modelo_local.py', tmp_path / 'tools')
    return tmp_path


def launch(root, body, deadline=None, wrapper=None):
    (root / 'tools/inferencia_mlx.py').write_text(
        'import os,sys,time,json,signal\nfrom pathlib import Path\n'
        'out=Path(sys.argv[sys.argv.index("--output")+1])\n'
        'out.with_name("worker.pid").write_text(str(os.getpid()))\n' + body)
    env = dict(os.environ)
    env.pop('LAB_BUILD_DEADLINE', None)
    if deadline is not None:
        env['LAB_BUILD_DEADLINE'] = datetime.fromtimestamp(time.time()+deadline, timezone.utc).isoformat()
    command = [sys.executable, str(root / 'tools/probar_modelo_local.py')]
    if wrapper:
        command = [sys.executable, '-c', wrapper, str(root / 'tools/probar_modelo_local.py')]
    return subprocess.Popen(command + ['--out', str(root / 'runs/check'), '--timeout', '30', '--per-family', '1'], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def ready(root, proc):
    path = root / 'runs/check/worker.pid'
    end = time.monotonic()+3
    while time.monotonic()<end:
        if path.exists():
            return int(path.read_text())
        if proc.poll() is not None:
            raise AssertionError(proc.communicate())
        time.sleep(.02)
    raise AssertionError('worker not ready')


def alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False


def cleanup(root, proc):
    if proc.poll() is None:
        proc.kill()
    proc.communicate(timeout=4)
    path = root / 'runs/check/worker.pid'
    if path.exists():
        try:
            os.killpg(int(path.read_text()), signal.SIGKILL)
        except ProcessLookupError:
            pass


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGINT])
def test_signal_reaps_only_owned_worker(mirror, sig):
    outsider = subprocess.Popen([sys.executable, '-c', 'import time;time.sleep(60)'])
    proc = launch(mirror, 'signal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)\n')
    try:
        pid = ready(mirror, proc)
        time.sleep(.05)
        proc.send_signal(sig)
        proc.communicate(timeout=4)
        assert not alive(pid), 'runner left its worker alive'
        assert outsider.poll() is None
        assert proc.returncode != 0
        state = json.loads((mirror / 'runs/check/state.json').read_text())
        report = json.loads((mirror / 'runs/check/evaluation.json').read_text())
        assert state['status'] == report['execution_status'] == 'INTERRUPTED'
    finally:
        cleanup(mirror, proc)
        outsider.kill()
        outsider.wait()


@pytest.mark.parametrize('body', [
    'out.write_text("not json")\n',
    'out.write_text(json.dumps({"responses":[],"format_errors":[]}))\n',
    'out.write_text(json.dumps({"responses":[],"format_errors":["bad answer"]}))\n',
])
def test_invalid_or_incomplete_never_succeeds(mirror, body):
    proc = launch(mirror, body)
    try:
        proc.communicate(timeout=4)
        state = json.loads((mirror / 'runs/check/state.json').read_text())
        report = json.loads((mirror / 'runs/check/evaluation.json').read_text())
        assert proc.returncode != 0
        assert state['status'] == report['execution_status'] == 'FAILED'
        assert report['format_errors'] or report['missing']
    finally:
        cleanup(mirror, proc)


def test_deadline_cleans_worker(mirror):
    proc = launch(mirror, 'time.sleep(60)\n', deadline=.5)
    try:
        pid = ready(mirror, proc)
        proc.communicate(timeout=4)
        assert not alive(pid)
        assert proc.returncode != 0
        assert json.loads((mirror / 'runs/check/state.json').read_text())['status'] == 'TIMEOUT'
    finally:
        cleanup(mirror, proc)


def test_rejects_symlink_runs(mirror, tmp_path):
    outside = tmp_path / 'outside'
    outside.mkdir()
    (mirror / 'runs').symlink_to(outside, target_is_directory=True)
    proc = launch(mirror, 'time.sleep(60)\n')
    try:
        proc.communicate(timeout=2)
        assert proc.returncode != 0
        assert not (outside / 'check').exists()
    finally:
        cleanup(mirror, proc)


def test_existing_output_preserved(mirror):
    out = mirror / 'runs/check'
    out.mkdir(parents=True)
    (out / 'state.json').write_text('sentinel')
    proc = launch(mirror, '')
    try:
        proc.communicate(timeout=3)
        assert proc.returncode != 0
        assert (out / 'state.json').read_text() == 'sentinel'
    finally:
        cleanup(mirror, proc)


@pytest.mark.parametrize('code', [0, 7])
def test_complete_results_preserve_worker_failure(mirror, code):
    body = ('cases=json.loads(out.with_name("references.json").read_text())\n'
            'out.write_text(json.dumps({"responses":[{"id":c["id"],"answer":c["expected"]} for c in cases],"format_errors":[]}))\n'
            f'sys.exit({code})\n')
    proc = launch(mirror, body)
    try:
        proc.communicate(timeout=3)
        report = json.loads((mirror / 'runs/check/evaluation.json').read_text())
        assert report['accuracy'] == 1
        assert report['execution_status'] == ('FINISHED' if code == 0 else 'FAILED')
        assert (proc.returncode == 0) == (code == 0)
    finally:
        cleanup(mirror, proc)


def test_io_exception_after_spawn_reaps_and_preserves_error(mirror):
    wrapper = '''import os,runpy,sys,time
from pathlib import Path
original=os.replace
failed=False
def replace(src,dst):
    global failed
    if Path(dst).name == 'state.json' and not failed and '"pid"' in Path(src).read_text():
        until=time.monotonic()+1
        while not Path(dst).with_name('worker.pid').exists() and time.monotonic()<until:
            time.sleep(.01)
        failed=True
        raise OSError('injected state write failure')
    return original(src,dst)
os.replace=replace
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
'''
    proc = launch(mirror, 'time.sleep(60)\n', wrapper=wrapper)
    try:
        _, stderr = proc.communicate(timeout=4)
        pid = int((mirror / 'runs/check/worker.pid').read_text())
        assert not alive(pid)
        assert proc.returncode != 0
        assert b'injected state write failure' in stderr
        state = json.loads((mirror / 'runs/check/state.json').read_text())
        report = json.loads((mirror / 'runs/check/evaluation.json').read_text())
        assert state['status'] == report['execution_status'] == 'FAILED'
        assert 'injected state write failure' in state['error']
        assert not list((mirror / 'runs/check').glob('.state.json*'))
    finally:
        cleanup(mirror, proc)


def test_budget_uses_both_clocks_without_renewal(monkeypatch):
    spec = importlib.util.spec_from_file_location('watchdog_test', ROOT / 'tools/probar_modelo_local.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.time, 'monotonic', lambda: 100)
    monkeypatch.setattr(module.time, 'time', lambda: 200)
    assert module.remaining(110, 210) == 10
    # Civil time advances during suspension even if monotonic does not.
    monkeypatch.setattr(module.time, 'time', lambda: 211)
    assert module.remaining(110, 210) < 0
    # A backwards civil adjustment cannot extend the monotonic budget.
    monkeypatch.setattr(module.time, 'time', lambda: 190)
    monkeypatch.setattr(module.time, 'monotonic', lambda: 111)
    assert module.remaining(110, 210) < 0


def test_inference_symlink_not_read(mirror):
    secret = mirror / 'secret.json'
    secret.write_text('private sentinel')
    proc = launch(mirror, 'out.symlink_to(Path.cwd()/"secret.json")\n')
    try:
        proc.communicate(timeout=3)
        report = json.loads((mirror / 'runs/check/evaluation.json').read_text())
        assert proc.returncode != 0
        assert report['execution_status'] == 'FAILED'
        assert report['format_errors']
        assert secret.read_text() == 'private sentinel'
    finally:
        cleanup(mirror, proc)
