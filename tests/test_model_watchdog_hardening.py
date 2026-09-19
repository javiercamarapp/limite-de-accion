"""Benign workers exercise persistence boundaries and bounded local input/output."""
import json
import os
import signal

import pytest

from test_model_watchdog import mirror, launch, cleanup, alive

GOOD = ('cases=json.loads(out.with_name("references.json").read_text())\n'
        'out.write_text(json.dumps({"responses":[{"id":c["id"],"answer":c["expected"]} for c in cases],"format_errors":[]}))\n')
LOAD = '''import importlib.util,sys,signal
spec=importlib.util.spec_from_file_location('runner',sys.argv[1])
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
sys.argv=sys.argv[1:]
original=m.atomic_json
'''
RUN = '''
before={s:signal.getsignal(s) for s in (signal.SIGINT,signal.SIGTERM)}
try:
    result=m.main()
finally:
    assert all(signal.getsignal(s)==h for s,h in before.items())
sys.exit(result)
'''


@pytest.mark.parametrize('target', ['evaluation.json', 'state.json'])
def test_signal_during_terminal_persistence(mirror, target):
    wrapper = LOAD + f'''
fired=False
def save(path,value):
    global fired
    original(path,value)
    if path.name=={target!r} and ('end_utc' in value or 'execution_status' in value) and not fired:
        fired=True
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM,None)
m.atomic_json=save
''' + RUN
    proc = launch(mirror, GOOD, wrapper=wrapper)
    try:
        proc.communicate(timeout=4)
        state = json.loads((mirror/'runs/check/state.json').read_text())
        report = json.loads((mirror/'runs/check/evaluation.json').read_text())
        assert proc.returncode != 0
        assert state['status'] == report['execution_status'] == 'INTERRUPTED'
        assert state['signal'] == signal.SIGTERM
    finally:
        cleanup(mirror, proc)


@pytest.mark.parametrize('persistent', [False, True])
def test_terminal_state_write_failure(mirror, persistent):
    wrapper = LOAD + f'''
attempts=0
def save(path,value):
    global attempts
    if path.name=='state.json' and 'end_utc' in value:
        attempts+=1
        assert attempts<=2, 'unbounded persistence retry'
        if attempts==1 or {persistent!r}:
            raise OSError('terminal persistence unavailable')
    original(path,value)
m.atomic_json=save
''' + RUN
    proc = launch(mirror, GOOD, wrapper=wrapper)
    try:
        _, stderr = proc.communicate(timeout=4)
        state = json.loads((mirror/'runs/check/state.json').read_text())
        report = json.loads((mirror/'runs/check/evaluation.json').read_text())
        assert proc.returncode != 0
        assert b'terminal persistence unavailable' in stderr
        assert report['execution_status'] == 'FAILED'
        if not persistent:
            assert state['status'] == 'FAILED'
            assert 'terminal persistence unavailable' in state['error']
    finally:
        cleanup(mirror, proc)


@pytest.mark.parametrize('source', ['cases', 'inference'])
@pytest.mark.parametrize('kind', ['fifo', 'large', 'utf8', 'symlink'])
def test_rejects_unsafe_text(mirror, source, kind):
    path = mirror/'input.json'
    if kind == 'fifo':
        os.mkfifo(path)
    elif kind == 'large':
        path.write_bytes(b' ' * 2_000_001)
    elif kind == 'utf8':
        path.write_bytes(b'\xff')
    else:
        target = mirror/'target.json'
        from laboratorio.evaluation import make_cases
        target.write_text(json.dumps(make_cases(17, 1)))
        path.symlink_to(target)
    wrapper = None
    body = GOOD
    if source == 'cases':
        wrapper = LOAD + f"sys.argv += ['--cases', {str(path)!r}]\n" + RUN
    else:
        body = f'os.rename({str(path)!r},out)\n'
    proc = launch(mirror, body, wrapper=wrapper)
    try:
        proc.communicate(timeout=2)
        assert proc.returncode != 0
        report = json.loads((mirror/'runs/check/evaluation.json').read_text())
        assert report['execution_status'] == 'FAILED'
        if kind == 'large':
            assert 'grande' in str(report['format_errors']) or 'grande' in (mirror/'runs/check/state.json').read_text()
    finally:
        cleanup(mirror, proc)


def test_continuous_logs_are_bounded_and_reaped(mirror):
    proc = launch(mirror, 'for _ in range(100):\n os.write(1,b"x"*65536)\n os.write(2,b"y"*65536)\n time.sleep(.01)\ntime.sleep(60)\n')
    try:
        proc.communicate(timeout=3)
        state = json.loads((mirror/'runs/check/state.json').read_text())
        assert proc.returncode != 0
        assert state['status'] == 'FAILED'
        assert not alive(state['pid'])
        assert sum((mirror/'runs/check'/f).stat().st_size for f in ('worker.stdout','worker.stderr')) <= 2_000_000
        assert 'log' in state['error'].lower()
    finally:
        cleanup(mirror, proc)


def test_persistent_report_failure_still_saves_failed_state(mirror):
    wrapper = LOAD + '''
def save(path,value):
    if path.name=='evaluation.json':
        raise OSError('report persistence unavailable')
    original(path,value)
m.atomic_json=save
''' + RUN
    proc = launch(mirror, GOOD, wrapper=wrapper)
    try:
        _, stderr = proc.communicate(timeout=4)
        assert proc.returncode != 0
        assert b'report persistence unavailable' in stderr
        state = json.loads((mirror/'runs/check/state.json').read_text())
        assert state['status'] == 'FAILED'
        assert 'end_utc' in state
    finally:
        cleanup(mirror, proc)


def test_reader_bounds_bytes_and_checks_size_before_reading(tmp_path, monkeypatch):
    import importlib.util
    from test_model_watchdog import ROOT
    spec = importlib.util.spec_from_file_location('bounded_reader', ROOT/'tools/probar_modelo_local.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    path = tmp_path/'text'
    original = module.os.fdopen
    reads = []

    class Tracked:
        def __init__(self, stream):
            self.stream = stream
        def __enter__(self):
            return self
        def __exit__(self, *args):
            self.stream.close()
        def fileno(self):
            return self.stream.fileno()
        def read(self, size=-1):
            assert 0 <= size <= module.MAX_TEXT + 1
            reads.append(size)
            return self.stream.read(size)

    monkeypatch.setattr(module.os, 'fdopen', lambda *a, **k: Tracked(original(*a, **k)))
    path.write_bytes('á'.encode()*10)
    assert module.read_text_bounded(path) == 'á'*10
    assert reads
    reads.clear()
    with path.open('wb') as stream:
        stream.truncate(module.MAX_TEXT + 1)
    with pytest.raises(ValueError, match='grande'):
        module.read_text_bounded(path)
    assert reads == []
