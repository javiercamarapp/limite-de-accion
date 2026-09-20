"""Pruebas del ledger; subprocess importa exclusivamente las fuentes del clon."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from laboratorio import forecast_ledger as ledger

SRC = Path(__file__).resolve().parents[1] / 'src'
T0 = '2026-01-01T00:00:00Z'
T1 = '2026-02-01T00:00:00Z'
T2 = '2026-03-01T00:00:00Z'


def forecast(**changes):
    return dict(id='f1', question='Evento sintético', probability=0.8,
                issued_at=T0, resolve_at=T1, resolution_rule='Registro sintético', **{}) | changes


def resolution(**changes):
    return dict(id='f1', outcome=True, resolved_at=T1,
                evidence_url='https://example.org/synthetic') | changes


def source(tmp_path, data):
    p = tmp_path / 'input.json'
    p.write_text(json.dumps(data), encoding='utf-8')
    return p


def snapshot(path):
    return {p.name: p.read_bytes() for p in path.iterdir()}


def cli(*args):
    env = dict(os.environ, PYTHONPATH=str(SRC), PYTHONDONTWRITEBYTECODE='1')
    return subprocess.run([sys.executable, '-m', 'laboratorio.forecast_ledger',
                           *map(str, args)], env=env, text=True, capture_output=True,
                          timeout=10)


def test_clone_sources():
    assert Path(ledger.__file__).resolve() == SRC / 'laboratorio/forecast_ledger.py'
    out = subprocess.run([sys.executable, '-c',
        'import laboratorio.forecast_ledger as m; print(m.__file__)'],
        env=dict(os.environ, PYTHONPATH=str(SRC)), capture_output=True, text=True, check=True)
    assert Path(out.stdout.strip()).resolve() == SRC / 'laboratorio/forecast_ledger.py'


def test_cli_real_reopen_score_false_outcome(tmp_path):
    path = tmp_path / 'ledger'
    for args in [('init', path), ('add', path, source(tmp_path, forecast()))]:
        result = cli(*args)
        assert result.returncode == 0, result.stderr
    pending = json.loads(cli('score', path).stdout)
    assert pending['brier'] is None and pending['baseline_brier'] is None
    assert pending['pending'] == 1
    assert cli('resolve', path, source(tmp_path, resolution(outcome=False))).returncode == 0
    out = json.loads(cli('score', path).stdout)
    assert out['brier'] == pytest.approx(0.64)
    assert out['baseline_brier'] == 0.25
    assert out['evidence_verified'] is False and out['prospective_validation'] is False
    shown = json.loads(cli('show', path).stdout)
    assert shown['forecasts'][0]['registered_at'] > T2
    assert shown['forecasts'][0]['status'] == 'resolved'
    before = snapshot(path)
    bad = cli('resolve', path, source(tmp_path, resolution()))
    assert bad.returncode != 0 and not bad.stdout and str(tmp_path) not in bad.stderr
    assert snapshot(path) == before


def test_clock_reopen_pending_and_readonly(tmp_path):
    path = tmp_path / 'ledger'
    l = ledger.Ledger(path, clock=lambda: T0)
    l.init()
    l.add(source(tmp_path, forecast()))
    before = snapshot(path)
    reopened = ledger.Ledger(path, clock=lambda: T2)
    assert reopened.show()['forecasts'][0]['status'] == 'overdue'
    assert reopened.score()['brier'] is None
    assert snapshot(path) == before
    reopened.resolve(source(tmp_path, resolution()))
    assert reopened.score()['brier'] == pytest.approx(0.04)
    before = snapshot(path)
    backwards = ledger.Ledger(path, clock=lambda: T1)
    with pytest.raises(ValueError):
        backwards.add(source(tmp_path, forecast(id='f2')))
    assert snapshot(path) == before
    assert backwards.show()['clock_regressed'] is True


@pytest.mark.parametrize('action,data', [
    ('add', forecast()), ('add', forecast(probability=True)),
    ('add', forecast(issued_at=T2)), ('add', forecast(extra=1)),
    ('resolve', resolution(id='unknown')), ('resolve', resolution(outcome=1)),
    ('resolve', resolution(resolved_at=T0)), ('resolve', resolution()),
])
def test_invalid_no_mutation(tmp_path, action, data):
    l = ledger.Ledger(tmp_path / 'ledger', clock=lambda: T0)
    l.init(); l.add(source(tmp_path, forecast()))
    before = snapshot(l.path)
    with pytest.raises(ValueError):
        getattr(l, action)(source(tmp_path, data))
    assert snapshot(l.path) == before


@pytest.mark.parametrize('raw', ['{}', 'null', '[]', '{',
    '{"id":"f1","id":"f2"}', '{"probability":NaN}', '\ud800'])
def test_bad_json(tmp_path, raw):
    l = ledger.Ledger(tmp_path / 'ledger', clock=lambda: T0); l.init()
    p = tmp_path / 'bad.json'; p.write_bytes(raw.encode('utf-8', errors='surrogatepass'))
    before = snapshot(l.path)
    with pytest.raises(ValueError): l.add(p)
    assert snapshot(l.path) == before


def test_special_files_size_and_missing_queries(tmp_path):
    l = ledger.Ledger(tmp_path / 'missing')
    for method in (l.show, l.score):
        with pytest.raises(ValueError): method()
    assert not l.path.exists()
    l.init(); before = snapshot(l.path)
    p = source(tmp_path, forecast()); link = tmp_path / 'link'; link.symlink_to(p)
    fifo = tmp_path / 'fifo'; os.mkfifo(fifo)
    big = tmp_path / 'big'; big.write_bytes(b' ' * (ledger.MAX_INPUT_BYTES + 1))
    for invalid in (link, fifo, big, tmp_path):
        with pytest.raises(ValueError): l.add(invalid)
    assert snapshot(l.path) == before
    alias = tmp_path / 'alias'; alias.symlink_to(l.path, target_is_directory=True)
    with pytest.raises(ValueError): ledger.Ledger(alias).show()
    with pytest.raises(ValueError): ledger.Ledger(alias / 'nested').init()
    with pytest.raises(ValueError): l.init()
    assert snapshot(l.path) == before


def test_corrupt_and_volume_limits(tmp_path, monkeypatch):
    l = ledger.Ledger(tmp_path / 'ledger', clock=lambda: T0); l.init()
    monkeypatch.setattr(ledger, 'MAX_FORECASTS', 1)
    l.add(source(tmp_path, forecast()))
    before = snapshot(l.path)
    with pytest.raises(ValueError): l.add(source(tmp_path, forecast(id='f2')))
    assert snapshot(l.path) == before
    monkeypatch.setattr(ledger, 'MAX_TOTAL_BYTES', 1)
    with pytest.raises(ValueError): l.show()
    monkeypatch.setattr(ledger, 'MAX_TOTAL_BYTES', 16 * 1024 * 1024)
    next(iter(l.path.iterdir())).write_text('corrupt')
    with pytest.raises(ValueError): l.score()
    out = cli('score', l.path)
    assert out.returncode != 0 and not out.stdout


def test_special_destinations_and_cli_no_clock(tmp_path):
    for name in (':memory:', 'file:memory?mode=memory', 'https://example.org/x'):
        with pytest.raises(ValueError): ledger.Ledger(name).init()
    out = cli('init', tmp_path / 'ledger', '--clock', T0)
    assert out.returncode != 0 and not (tmp_path / 'ledger').exists()


def test_read_budget_and_entry_budget(tmp_path, monkeypatch):
    l = ledger.Ledger(tmp_path / 'ledger', clock=lambda: T0); l.init()
    l.add(source(tmp_path, forecast()))
    reads = []
    original = ledger.os.read
    def counted(fd, size):
        data = original(fd, size)
        reads.append(len(data))
        return data
    monkeypatch.setattr(ledger.os, 'read', counted)
    l.show()
    assert len(reads) <= 4
    assert sum(reads) == sum(len(v) for v in snapshot(l.path).values())
    monkeypatch.setattr(ledger, 'MAX_TOTAL_BYTES', 10)
    reads.clear()
    with pytest.raises(ValueError): l.show()
    assert not reads  # fstat rejects before reading a file over the remaining budget
    monkeypatch.setattr(ledger, 'MAX_FORECASTS', 1)
    for i in range(2, 5): (l.path / f'{i:08d}.json').write_text('{}')
    with pytest.raises(ValueError): l.show()
    assert not reads


def test_failed_publication_is_atomic_and_preserves_destination(tmp_path, monkeypatch):
    l = ledger.Ledger(tmp_path / 'ledger', clock=lambda: T0); l.init()
    before = snapshot(l.path)
    original = ledger.os.link
    def fail(*args, **kwargs):
        raise OSError('synthetic publication failure')
    monkeypatch.setattr(ledger.os, 'link', fail)
    with pytest.raises(ValueError): l.add(source(tmp_path, forecast()))
    assert snapshot(l.path) == before
    monkeypatch.setattr(ledger.os, 'link', original)
    l.add(source(tmp_path, forecast()))
    assert l.score()['pending'] == 1
    target = l.path / '00000001.json'
    preserved = target.read_bytes()
    with l._open(exclusive=True) as fd:
        with pytest.raises(FileExistsError):
            l._commit(fd, 1, {'kind': 'init', 'registered_at': T0, 'payload': {'version': 1}})
    assert target.read_bytes() == preserved
    assert len(list(l.path.iterdir())) == 2


@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'hardlink', 'oversize'])
def test_special_or_oversized_manifest_rejected(tmp_path, kind):
    l = ledger.Ledger(tmp_path / 'ledger', clock=lambda: T0); l.init()
    p = l.path / '00000000.json'
    raw = p.read_bytes(); p.unlink()
    other = tmp_path / 'other'; other.write_bytes(raw)
    if kind == 'symlink': p.symlink_to(other)
    elif kind == 'fifo': os.mkfifo(p)
    elif kind == 'hardlink': os.link(other, p)
    else: p.write_bytes(b'x' * (ledger.MAX_INPUT_BYTES + 1))
    with pytest.raises(ValueError): l.show()
    out = cli('show', l.path)
    assert out.returncode != 0 and out.stdout == ''


def test_bad_calendar_unverified_and_no_backdated_registration(tmp_path):
    l = ledger.Ledger(tmp_path / 'ledger', clock=lambda: T2); l.init()
    for changes in ({'issued_at': '2026-02-30T00:00:00Z'},
                    {'issued_at': T1, 'resolve_at': T0},
                    {'issued_at': '2026-01-01T00:00:00+00:00'}):
        before = snapshot(l.path)
        with pytest.raises(ValueError): l.add(source(tmp_path, forecast(**changes)))
        assert snapshot(l.path) == before
    l.add(source(tmp_path, forecast()))
    assert l.show()['forecasts'][0]['registered_at'] == T2
    assert l.show()['prospective_validation'] is False
    for bad in (resolution(resolved_at='2027-01-01T00:00:00Z'),
                resolution(evidence_url='https://user:secret@example.org/')):
        before = snapshot(l.path)
        with pytest.raises(ValueError): l.resolve(source(tmp_path, bad))
        assert snapshot(l.path) == before


def test_lock_contention_fails_promptly(tmp_path):
    l = ledger.Ledger(tmp_path / 'ledger', clock=lambda: T0); l.init()
    with l._open(exclusive=True):
        result = cli('show', l.path)
    assert result.returncode != 0 and not result.stdout


def test_unpaired_unicode_surrogate_rejected(tmp_path):
    l = ledger.Ledger(tmp_path / 'ledger', clock=lambda: T0); l.init()
    before = snapshot(l.path)
    with pytest.raises(ValueError):
        l.add(source(tmp_path, forecast(question='\ud800')))
    assert snapshot(l.path) == before
