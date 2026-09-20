"""Real offline fixtures; no service or socket is started."""
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile

import pytest
from laboratorio import operator_cli, experiment_registry as registry
from laboratorio import forecast_ledger, evidence_import
from laboratorio import operations_status as status
from laboratorio.controller import DurableController

SRC = Path(__file__).resolve().parents[1] / 'src'
FLAGS = ('enterprise_complete', 'C1_T02_verified', 'human_authenticated',
         'evidence_verified', 'prospective_validation', 'dispatch_authorized')


def save(path, value):
    path.write_text(json.dumps(value))
    return path


def cli(*args):
    return subprocess.run([sys.executable, '-B', '-m', 'laboratorio.operations_status',
                           *map(str, args)], capture_output=True, text=True, timeout=10,
                          env=dict(os.environ, PYTHONPATH=str(SRC), PYTHONDONTWRITEBYTECODE='1'))


def snapshot(root):
    return {str(p.relative_to(root)): (p.stat().st_mtime_ns,
            p.read_bytes() if p.is_file() else None) for p in root.rglob('*')}


@pytest.fixture
def fixtures():
    # operator requires private, non-world-writable ancestry.
    with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix='.status-test-') as raw:
        base = Path(raw).resolve()
        op = base / 'operator'
        operator_cli.prepare_fixture(op, dict(schema='operator.v1', deadline='2099-01-01T00:00:00Z',
            max_operations=5, admin_uid=os.geteuid(), dispatcher_uid=os.geteuid(), principal='synthetic'))
        intent = json.loads((op / 'intent.json').read_text())
        with DurableController(op / 'controller.sqlite3', deadline='2099-01-01T00:00:00Z',
                max_operations=5, clock=operator_cli._now, transport=lambda _: None) as ctl:
            ctl.register(intent)
            ctl.reserve(intent['intent_id'], 'approval', 'operation')
        with sqlite3.connect(op / 'controller.sqlite3') as db:
            db.execute("UPDATE operations SET status='UNKNOWN'")
        artifact = base / 'original.txt'
        artifact.write_text('Synthetic inert content')
        exp = base / 'experiments'
        registry.initialize(exp)
        spec = dict(experiment_id='sample', source='synthetic', configuration={'note': 'PRIVATE_MARKER'},
            inputs=[dict(name='input', path=str(artifact))], results=[dict(name='result', path=str(artifact))],
            code=[dict(name='code', path=str(artifact))])
        registry.append(exp, spec)
        forecasts = base / 'forecasts'
        ledger = forecast_ledger.Ledger(forecasts, clock=lambda: '2026-03-01T00:00:00Z')
        ledger.init()
        ledger.add(save(base / 'f.json', dict(id='f1', question='PRIVATE_MARKER', probability=0.8,
            issued_at='2026-01-01T00:00:00Z', resolve_at='2026-02-01T00:00:00Z', resolution_rule='declared')))
        bundle = base / 'bundle'
        evidence_import.import_bundle(save(base / 'spec.json', {'sources': [dict(id='source',
            title='PRIVATE_MARKER', url='https://example.org/PRIVATE_MARKER',
            captured_at='2026-01-01T00:00:00Z', source_kind='synthetic', path=str(artifact))]}), bundle)
        yield base, dict(operator_root=op, experiments=exp, forecasts=forecasts, evidence=bundle), spec


def test_complete_readonly_and_cli(fixtures, monkeypatch):
    base, paths, _ = fixtures
    def forbidden(*args, **kwargs):
        raise AssertionError('socket calls forbidden')
    monkeypatch.setattr(socket, 'socket', forbidden)
    before = snapshot(base)
    report = status.collect_status(**paths)
    assert report['status'] == 'AVAILABLE'
    assert all(report[key] is False for key in FLAGS)
    op = report['components']['operator']
    assert op['budget_total'] == 5 and op['budget_used'] == 1
    assert op['counts']['UNKNOWN'] == 1 and op['counts']['DISPATCHING'] == 0
    assert op['service_alive'] is None
    assert report['components']['forecasts']['brier'] is None
    assert report['components']['forecasts']['pending'] == 1
    assert report['components']['forecasts']['overdue'] == 1
    assert report['components']['evidence']['declared_origins'] == {'public': 0, 'synthetic': 1, 'authorized': 0}
    args = [arg for key, value in paths.items() for arg in ('--' + key.replace('_', '-'), value)]
    for fmt in ('json', 'text'):
        run = cli(*args, '--format', fmt)
        assert run.returncode == 0, run.stderr
        assert str(base) not in run.stdout and 'PRIVATE_MARKER' not in run.stdout
        assert '\x1b' not in run.stdout
        if fmt == 'json':
            actual = json.loads(run.stdout)
            # Each collection uses its own local clock; crossing a second is valid.
            actual['components']['forecasts'].pop('as_of')
            expected = json.loads(json.dumps(report))
            expected['components']['forecasts'].pop('as_of')
            assert actual == expected
        else:
            assert report['components']['experiments']['head_sha256'] in run.stdout
    assert snapshot(base) == before


def test_absent_and_isolated_damage(fixtures):
    base, paths, _ = fixtures
    assert status.collect_status()['status'] == 'NOT_CONFIGURED'
    (paths['evidence'] / 'source-01.txt').write_text('tampered')
    paths['experiments'] = base / 'missing'
    report = status.collect_status(**paths)
    assert report['status'] == 'INVALID'
    assert report['components']['experiments']['status'] == 'MISSING'
    assert report['components']['evidence']['status'] == 'INVALID'
    assert report['components']['operator']['status'] == 'AVAILABLE'
    assert cli('--evidence', paths['evidence']).returncode == 2


def test_incomplete_and_originals_not_read(fixtures):
    base, paths, spec = fixtures
    spec['results'] = []
    registry.append(paths['experiments'], spec)
    (base / 'original.txt').unlink()
    os.mkfifo(base / 'original.txt')
    report = status.collect_status(**paths)
    assert report['status'] == 'INCOMPLETE'
    assert report['components']['experiments']['latest_state'] == 'MISSING'
    assert report['components']['experiments']['files_checked'] is False
    assert report['components']['evidence']['status'] == 'AVAILABLE'
    assert cli('--experiments', paths['experiments']).returncode == 2


@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'oversize', 'duplicate', 'bool'])
def test_strict_forecasts(fixtures, kind):
    base, paths, _ = fixtures
    p = paths['forecasts'] / '00000000.json'
    if kind in ('symlink', 'fifo'):
        p.unlink()
        if kind == 'symlink': p.symlink_to(base / 'original.txt')
        else: os.mkfifo(p)
    elif kind == 'oversize':
        with p.open('wb') as f: f.truncate(32 * 1024 + 1)
    elif kind == 'duplicate': p.write_text('{"kind":"init","kind":"init"}')
    else: save(p, dict(kind='init', registered_at='2026-01-01T00:00:00Z', payload={'version': True}))
    assert status.collect_status(**paths)['components']['forecasts']['status'] == 'INVALID'


def test_resolved_and_source_origin(fixtures):
    base, paths, _ = fixtures
    forecast_ledger.Ledger(paths['forecasts']).resolve(save(base / 'r.json', dict(id='f1', outcome=True,
        resolved_at='2026-03-01T00:00:00Z', evidence_url='https://example.org/private')))
    f = status.collect_status(**paths)['components']['forecasts']
    assert f['resolved'] == 1 and f['pending'] == 0
    assert f['brier'] == pytest.approx(0.04) and f['baseline_brier'] == 0.25
    assert Path(status.__file__).resolve() == SRC / 'laboratorio/operations_status.py'
    run = subprocess.run([sys.executable, '-B', '-c', 'import laboratorio.operations_status as m; print(m.__file__)'],
        env=dict(os.environ, PYTHONPATH=str(SRC)), capture_output=True, text=True, check=True)
    assert Path(run.stdout.strip()).resolve() == SRC / 'laboratorio/operations_status.py'


@pytest.mark.parametrize('args', [('--format', '/private/secret'), ('--dispatch=/private/secret',),
    ('--operator-root', 'file:/private/secret'), ('--experiments', '../private/secret')])
def test_safe_cli_errors(args):
    run = cli(*args)
    assert run.returncode == 2 and '/private/' not in run.stdout + run.stderr
    assert 'Traceback' not in run.stdout + run.stderr


@pytest.mark.parametrize('damage', ['config_bool', 'config_duplicate', 'database', 'fifo', 'symlink', 'wal', 'sidecar', 'view'])
def test_operator_untrusted_storage(fixtures, damage):
    base, paths, _ = fixtures
    root = paths['operator_root']
    db = root / 'controller.sqlite3'
    config = root / 'config.json'
    if damage == 'config_bool':
        value = json.loads(config.read_text())
        value['max_operations'] = True
        save(config, value)
    elif damage == 'config_duplicate':
        config.write_text(config.read_text().replace('"max_operations": 5', '"max_operations": 5, "max_operations": 5'))
    elif damage == 'database': db.write_bytes(b'not sqlite')
    elif damage in ('fifo', 'symlink'):
        db.unlink()
        if damage == 'fifo': os.mkfifo(db)
        else: db.symlink_to(base / 'original.txt')
    elif damage == 'wal':
        raw = bytearray(db.read_bytes())
        raw[18:20] = b'\x02\x02'
        db.write_bytes(raw)
    elif damage == 'sidecar': Path(str(db) + '-journal').write_bytes(b'journal')
    else:
        with sqlite3.connect(db) as conn:
            conn.execute('ALTER TABLE operations RENAME TO other')
            conn.execute('CREATE VIEW operations AS SELECT * FROM other')
    report = status.collect_status(**paths)
    assert report['components']['operator']['status'] == 'INVALID'
    assert report['components']['experiments']['status'] == 'AVAILABLE'
    run = cli('--operator-root', root)
    assert run.returncode == 2 and 'Traceback' not in run.stderr
    assert str(base) not in run.stdout + run.stderr


def test_dispatching_clock_and_budget_are_not_repaired(fixtures):
    base, paths, _ = fixtures
    with sqlite3.connect(paths['operator_root'] / 'controller.sqlite3') as db:
        db.execute("UPDATE operations SET status='DISPATCHING'")
        db.execute('UPDATE controller_state SET clock_blocked=1')
    before = snapshot(base)
    report = status.collect_status(**paths)
    op = report['components']['operator']
    assert op['clock_blocked'] is True and op['counts']['DISPATCHING'] == 1
    assert op['counts']['CONFIRMED'] == 0 and op['budget_used'] == 1
    assert all(report[k] is False for k in FLAGS)
    assert snapshot(base) == before


def test_bounded_directory_before_legacy_listdir(fixtures, monkeypatch):
    _, paths, _ = fixtures
    for i in range(257): (paths['experiments'] / f'extra-{i}').touch()
    def forbidden(*args): raise AssertionError('legacy unbounded listing reached')
    monkeypatch.setattr(os, 'listdir', forbidden)
    assert status.collect_status(experiments=paths['experiments'])['status'] == 'INVALID'


def test_preflight_size_before_legacy_api(fixtures, monkeypatch):
    _, paths, _ = fixtures
    with (paths['experiments'] / '000001.json').open('wb') as stream:
        stream.truncate(64001)
    def forbidden(*args): raise AssertionError('legacy export reached')
    monkeypatch.setattr(registry, 'export_registry', forbidden)
    assert status.collect_status(experiments=paths['experiments'])['status'] == 'INVALID'


def test_safe_formatter_and_unconfigured_cli():
    hostile = '\x1b]0;PRIVATE_MARKER\x07'
    report = status.collect_status()
    report['components']['operator'] = dict(status='AVAILABLE', deadline=hostile,
        budget_total=hostile, budget_used=True, counts={'UNKNOWN': hostile})
    report['status'] = hostile
    output = status.format_text(report)
    assert '\x1b' not in output and 'PRIVATE_MARKER' not in output
    run = cli()
    assert run.returncode == 0
    assert json.loads(run.stdout)['status'] == 'NOT_CONFIGURED'


def test_parent_symlink_and_missing_required_file(fixtures):
    base, paths, _ = fixtures
    alias = base / 'alias'
    alias.symlink_to(paths['forecasts'], target_is_directory=True)
    assert status.collect_status(forecasts=alias)['status'] == 'INVALID'
    (paths['operator_root'] / 'config.json').unlink()
    assert status.collect_status(**paths)['components']['operator']['status'] == 'MISSING'


def test_integrity_never_authenticates_declared_origin(fixtures):
    _, paths, _ = fixtures
    import hashlib
    manifest = paths['evidence'] / 'manifest.json'
    value = json.loads(manifest.read_text())
    value['manifest']['sources'][0]['source_kind'] = 'authorized'
    value['sha256'] = hashlib.sha256(registry.canonical(value['manifest'])).hexdigest()
    save(manifest, value)
    report = status.collect_status(**paths)
    assert report['components']['evidence']['declared_origins']['authorized'] == 1
    assert report['components']['evidence']['integrity'] == 'MATCH'
    assert report['human_authenticated'] is report['evidence_verified'] is False


@pytest.mark.parametrize('payload', ['[]', 'true', '{"unexpected":1}',
    '{"x":1,"x":2}', '{"x":NaN}'])
def test_invalid_intent_contract(fixtures, payload):
    _, paths, _ = fixtures
    with sqlite3.connect(paths['operator_root'] / 'controller.sqlite3') as db:
        db.execute('UPDATE intents SET intent_json=?', (payload,))
    assert status.collect_status(**paths)['components']['operator'] == {'status': 'INVALID'}


@pytest.mark.parametrize('state,payload', [('CONFIRMED', 'true'), ('CONFIRMED', '[]'),
    ('CONFIRMED', 'null'), ('CONFIRMED', '{}'), ('CONFIRMED', None),
    ('UNKNOWN', 'true'), ('RESERVED', '{}'), ('REJECTED', '[]'), ('DISPATCHING', '{}')])
def test_invalid_persisted_receipt(fixtures, state, payload):
    base, paths, _ = fixtures
    with sqlite3.connect(paths['operator_root'] / 'controller.sqlite3') as db:
        db.execute('UPDATE operations SET status=?, receipt_json=?', (state, payload))
    before = snapshot(base)
    assert status.collect_status(**paths)['components']['operator'] == {'status': 'INVALID'}
    assert snapshot(base) == before


@pytest.mark.parametrize('damage', ['missing_columns', 'missing_constraints', 'duplicate_ids',
    'generated_status', 'missing_index', 'wrong_type'])
def test_exact_operator_schema(fixtures, damage):
    _, paths, _ = fixtures
    with sqlite3.connect(paths['operator_root'] / 'controller.sqlite3') as db:
        if damage == 'missing_index':
            db.execute('DROP INDEX active_event')
        else:
            rows = db.execute('SELECT * FROM operations').fetchall()
            ddl = db.execute("SELECT sql FROM sqlite_schema WHERE name='operations'").fetchone()[0]
            db.execute('DROP TABLE operations')
            if damage == 'missing_columns':
                db.execute('CREATE TABLE operations(operation_id TEXT, status TEXT, receipt_json TEXT)')
                db.execute("INSERT INTO operations VALUES ('operation','UNKNOWN',NULL)")
            elif damage == 'generated_status':
                db.execute("CREATE TABLE operations(operation_id TEXT, receipt_json TEXT, status TEXT AS ('CONFIRMED'))")
                db.execute("INSERT INTO operations(operation_id) VALUES ('operation')")
            else:
                if damage == 'wrong_type': ddl = ddl.replace('operation_id TEXT', 'operation_id BLOB')
                else: ddl = ddl.replace(' PRIMARY KEY', '').replace(' UNIQUE', '')
                db.execute(ddl)
                db.executemany('INSERT INTO operations VALUES (?,?,?,?,?,?,?)', rows)
                if damage == 'duplicate_ids':
                    db.executemany('INSERT INTO operations VALUES (?,?,?,?,?,?,?)', rows)
    assert status.collect_status(**paths)['components']['operator'] == {'status': 'INVALID'}


@pytest.mark.parametrize('damage', ['intent_id', 'digest', 'reference', 'calendar', 'event'])
def test_persisted_references(fixtures, damage):
    _, paths, _ = fixtures
    with sqlite3.connect(paths['operator_root'] / 'controller.sqlite3') as db:
        if damage == 'intent_id': db.execute("UPDATE intents SET intent_id='different'")
        elif damage == 'digest': db.execute("UPDATE intents SET intent_digest='wrong'")
        elif damage == 'reference': db.execute("UPDATE operations SET intent_id='missing'")
        elif damage == 'calendar': db.execute("UPDATE operations SET calendar_id='different'")
        else: db.execute("UPDATE operations SET event_id='different'")
    assert status.collect_status(**paths)['components']['operator'] == {'status': 'INVALID'}


def test_sqlite_limits_before_generated_data(fixtures, monkeypatch):
    from contextlib import contextmanager
    _, paths, _ = fixtures
    with sqlite3.connect(paths['operator_root'] / 'controller.sqlite3') as db:
        db.execute("ALTER TABLE controller_state ADD COLUMN padding TEXT AS (printf('%67108864s','x'))")
    original = operator_cli._readonly
    @contextmanager
    def guarded(path):
        with original(path) as db:
            class Guard:
                def __getattr__(self, name): return getattr(db, name)
                def execute(self, sql, *args):
                    assert db.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) <= 65536
                    assert db.getlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH) <= 16384
                    assert 'SELECT *' not in sql.upper()
                    assert 'COUNT(*)' not in sql.upper()
                    assert 'FROM CONTROLLER_STATE' not in sql.upper()
                    return db.execute(sql, *args)
            yield Guard()
    monkeypatch.setattr(operator_cli, '_readonly', guarded)
    assert status.collect_status(**paths)['components']['operator'] == {'status': 'INVALID'}


def declared_receipt(intent):
    from laboratorio.authority import intent_digest
    return dict(operation_id='operation', approval_id='approval',
        intent_digest=intent_digest(intent), principal_id=intent['principal_id'],
        calendar_id=intent['calendar_id'], event_id=intent['event_id'],
        start_utc=intent['start_utc'], end_utc=intent['end_utc'],
        version=intent['expected_version'] + 1, authority_epoch=0,
        applied_at='2026-09-19T00:00:00Z')


@pytest.mark.parametrize('damage', [None, 'version_bool', 'epoch_bool', 'event', 'digest',
    'timestamp', 'extra', 'pending', 'duplicate_json', 'nan'])
def test_receipt_semantics_and_observational_confirmation(fixtures, damage):
    base, paths, _ = fixtures
    intent = json.loads((paths['operator_root'] / 'intent.json').read_text())
    receipt = declared_receipt(intent)
    if damage == 'version_bool': receipt['version'] = True
    elif damage == 'epoch_bool': receipt['authority_epoch'] = False
    elif damage == 'event': receipt['event_id'] = 'different'
    elif damage == 'digest': receipt['intent_digest'] = 'wrong'
    elif damage == 'timestamp': receipt['applied_at'] = 'invalid'
    elif damage == 'extra': receipt['extra'] = 1
    raw = json.dumps(receipt)
    if damage == 'duplicate_json': raw = raw[:-1] + ',"version":1}'
    elif damage == 'nan': raw = raw.replace('"version": 1', '"version": NaN')
    with sqlite3.connect(paths['operator_root'] / 'controller.sqlite3') as db:
        db.execute('UPDATE operations SET status=?, receipt_json=?',
                   ('UNKNOWN' if damage == 'pending' else 'CONFIRMED', raw))
    before = snapshot(base)
    report = status.collect_status(**paths)
    op = report['components']['operator']
    if damage is None:
        assert op['status'] == 'AVAILABLE' and op['counts']['CONFIRMED'] == 1
        assert op['states_are_persisted'] is True
        assert all(report[k] is False for k in FLAGS)
        assert 'fixture_intent' not in json.dumps(report)
    else:
        assert op == {'status': 'INVALID'}
    assert snapshot(base) == before


@pytest.mark.parametrize('damage', ['wrong_schema', 'bool_version', 'id_mismatch'])
def test_rehashed_intent_still_requires_contract(fixtures, damage):
    import hashlib
    from laboratorio.authority import _canonical
    _, paths, _ = fixtures
    intent = json.loads((paths['operator_root'] / 'intent.json').read_text())
    if damage == 'wrong_schema': intent['schema_version'] = 'wrong'
    elif damage == 'bool_version': intent['expected_version'] = True
    else: intent['intent_id'] = 'different'
    digest = 'C1.intent.v1:sha256:' + hashlib.sha256(_canonical(intent).encode()).hexdigest()
    with sqlite3.connect(paths['operator_root'] / 'controller.sqlite3') as db:
        db.execute('UPDATE intents SET intent_json=?, intent_digest=?', (json.dumps(intent), digest))
    assert status.collect_status(**paths)['components']['operator'] == {'status': 'INVALID'}


def test_single_connection_engine_limits_and_no_recovery(fixtures, monkeypatch):
    from contextlib import contextmanager
    _, paths, _ = fixtures
    original = operator_cli._readonly
    opened = []
    @contextmanager
    def checked(path):
        opened.append(path)
        with original(path) as db:
            yield db
            assert db.getlimit(sqlite3.SQLITE_LIMIT_LENGTH) == 65536
            assert db.getlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH) == 16384
            # SQLite rejects the 64 MiB result; no Python string is created.
            with pytest.raises(sqlite3.DataError):
                db.execute('SELECT zeroblob(67108864)').fetchone()
            with pytest.raises(sqlite3.DataError):
                db.execute("SELECT printf('%67108864s','x')").fetchone()
    def forbidden(*args, **kwargs): raise AssertionError('unbounded query or recovery')
    monkeypatch.setattr(operator_cli, '_readonly', checked)
    monkeypatch.setattr(operator_cli, 'query', forbidden)
    monkeypatch.setattr(DurableController, '__init__', forbidden)
    assert status.collect_status(**paths)['components']['operator']['status'] == 'AVAILABLE'
    assert len(opened) == 1


@pytest.mark.parametrize('damage', ['budget', 'deadline', 'status', 'oversized_text', 'blob'])
def test_operator_typed_data_limits(fixtures, damage):
    _, paths, _ = fixtures
    with sqlite3.connect(paths['operator_root'] / 'controller.sqlite3') as db:
        if damage == 'budget': db.execute('UPDATE controller_state SET max_operations=4')
        elif damage == 'deadline': db.execute("UPDATE controller_state SET deadline='2098-01-01T00:00:00Z'")
        elif damage == 'status':
            db.execute('PRAGMA ignore_check_constraints=ON')
            db.execute("UPDATE operations SET status='INVENTED'")
        elif damage == 'oversized_text':
            db.execute("UPDATE intents SET intent_json=printf('%65537s','x')")
        else: db.execute('UPDATE intents SET intent_json=?', (b'{}',))
    assert status.collect_status(**paths)['components']['operator'] == {'status': 'INVALID'}
