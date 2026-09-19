"""Real local operator flows; same UID is not human authentication/isolation."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading

import pytest

from laboratorio.authority import intent_digest


def cli(*args):
    result = subprocess.run([sys.executable, '-m', 'laboratorio.operator_cli', *map(str, args)],
                            capture_output=True, text=True, timeout=8,
                            env={**os.environ, 'PYTHONPATH': str(Path.cwd() / 'src')})
    return result.returncode, json.loads(result.stdout or result.stderr)


@pytest.fixture
def root():
    with tempfile.TemporaryDirectory(prefix='.op-', dir=Path.cwd()) as directory:
        yield Path(directory) / 'state'


def prepare(root, budget=2):
    code, value = cli('prepare-fixture', '--root', root, '--deadline', '2099-01-01T00:00:00Z',
                      '--max-operations', budget, '--admin-uid', os.geteuid(),
                      '--dispatcher-uid', os.geteuid(), '--principal', 'operator_agent')
    assert code == 0, value
    assert value['human_authenticated'] is False
    assert value['separate_os_identities'] is False
    return json.loads((root / 'intent.json').read_text())


def command(root, name, *args):
    return cli(name, '--root', root, *args)


def snapshot(root):
    return {p.name: (hashlib.sha256(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
            for p in root.iterdir() if p.is_file()}


@pytest.fixture
def services(root):
    from laboratorio.operator_cli import serve
    prepare(root)
    stop, ready = threading.Event(), threading.Event()
    failures = []
    def run():
        try:
            serve(root, stop=stop, ready=ready)
        except BaseException as exc:
            failures.append(exc)
            ready.set()
    thread = threading.Thread(target=run)
    thread.start()
    try:
        assert ready.wait(3), 'receiver did not become ready'
        assert not failures, f'real Unix service unavailable: {failures}'
        yield root
    finally:
        stop.set()
        thread.join(5)
        assert not thread.is_alive()
        assert not (root / 'a.sock').exists()
        assert not (root / 'd.sock').exists()


def test_prepare_never_overwrites_and_queries_never_initialize(root):
    assert command(root, 'query')[0] == 2
    assert not root.exists()
    prepare(root)
    before = snapshot(root)
    assert cli('prepare-fixture', '--root', root, '--deadline', '2099-01-01T00:00:00Z',
               '--max-operations', 99, '--admin-uid', os.geteuid(),
               '--dispatcher-uid', os.geteuid(), '--principal', 'operator_agent')[0] == 2
    assert command(root, 'query')[1]['result']['operations'] == []
    assert snapshot(root) == before


def test_real_cli_register_approve_reserve_dispatch_query_revoke(services):
    root = services
    intent = json.loads((root / 'intent.json').read_text())
    assert command(root, 'register', '--intent', root / 'intent.json')[0] == 0
    # Register/reserve do not generate approval. Receiver must reject fake token.
    assert command(root, 'reserve', '--intent-id', intent['intent_id'], '--approval-id',
                   'not_approved', '--operation-id', 'unapproved')[0] == 0
    assert command(root, 'dispatch', '--operation-id', 'unapproved')[1]['result']['status'] == 'REJECTED'
    assert command(root, 'event', '--calendar-id', 'fixture_calendar', '--event-id', 'fixture_event')[1]['result']['version'] == 0
    intent['intent_id'] = 'second_intent'
    (root / 'intent.json').write_text(json.dumps(intent))
    assert command(root, 'register', '--intent', root / 'intent.json')[0] == 0
    code, approved = command(root, 'approve', '--intent', root / 'intent.json',
                             '--original-digest', intent_digest(intent), '--expires-at', '2098-01-01T00:00:00Z')
    assert code == 0, approved
    token = approved['result']
    assert command(root, 'reserve', '--intent-id', 'second_intent', '--approval-id', token,
                   '--operation-id', 'approved')[0] == 0
    result = command(root, 'dispatch', '--operation-id', 'approved')[1]['result']
    assert result['status'] == 'CONFIRMED'
    assert command(root, 'dispatch', '--operation-id', 'approved')[1]['result'] == result
    before = snapshot(root)
    assert command(root, 'query', '--operation-id', 'approved')[1]['result'] == result
    assert command(root, 'receipt', '--operation-id', 'approved')[1]['result'] == result['receipt']
    assert snapshot(root) == before
    assert command(root, 'revoke')[1]['result'] == 1
    # Every command opens storage again: cumulative budget must survive.
    intent['intent_id'], intent['expected_version'] = 'third_intent', 1
    (root / 'intent.json').write_text(json.dumps(intent))
    assert command(root, 'register', '--intent', root / 'intent.json')[0] == 0
    assert command(root, 'reserve', '--intent-id', 'third_intent', '--approval-id', 'another',
                   '--operation-id', 'exhausted')[0] == 2
    with sqlite3.connect(root / 'receiver.sqlite3') as db:
        assert db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0] == 1
        assert db.execute('SELECT approver_id FROM approvals').fetchone()[0] == f'human_uid_{os.geteuid()}'


def test_query_preserves_dispatching_and_offline_dispatch_never_retries(root):
    prepare(root)
    assert command(root, 'register', '--intent', root / 'intent.json')[0] == 0
    assert command(root, 'reserve', '--intent-id', 'fixture_intent', '--approval-id', 'external_token',
                   '--operation-id', 'uncertain')[0] == 0
    with sqlite3.connect(root / 'controller.sqlite3') as db:
        db.execute("UPDATE operations SET status='DISPATCHING'")
    before = snapshot(root)
    assert command(root, 'query', '--operation-id', 'uncertain')[1]['result']['status'] == 'DISPATCHING'
    assert snapshot(root) == before
    assert command(root, 'dispatch', '--operation-id', 'uncertain')[1]['result']['status'] == 'UNKNOWN'
    assert command(root, 'reconcile', '--operation-id', 'uncertain')[1]['result']['status'] == 'UNKNOWN'


@pytest.mark.parametrize('payload', ['{"x":1,"x":2}', '{', '{"x":NaN}', '{"x":1e999}', '[]', ' ' * 65537])
def test_strict_bounded_json(root, payload):
    prepare(root)
    bad = root / 'bad.json'
    bad.write_text(payload)
    before = snapshot(root)
    assert command(root, 'register', '--intent', bad)[0] == 2
    assert snapshot(root) == before


@pytest.mark.parametrize('kind', ['symlink', 'fifo', 'directory'])
def test_special_input_rejected_without_hanging(root, kind):
    prepare(root)
    path = root / 'bad'
    if kind == 'symlink':
        path.symlink_to(root / 'intent.json')
    elif kind == 'fifo':
        os.mkfifo(path)
    else:
        path.mkdir()
    assert command(root, 'register', '--intent', path)[0] == 2


def test_db_symlink_and_changed_budget_rejected(root):
    prepare(root)
    config = json.loads((root / 'config.json').read_text())
    config['max_operations'] = 99
    (root / 'config.json').write_text(json.dumps(config))
    assert command(root, 'register', '--intent', root / 'intent.json')[0] == 2
    db = root / 'controller.sqlite3'
    target = root / 'preserved.sqlite3'
    db.rename(target)
    db.symlink_to(target)
    before = target.read_bytes()
    assert command(root, 'query')[0] == 2
    assert target.read_bytes() == before


def test_module_help():
    result = subprocess.run([sys.executable, '-m', 'laboratorio.operator_cli', '--help'],
                            capture_output=True, text=True, timeout=5,
                            env={**os.environ, 'PYTHONPATH': str(Path.cwd() / 'src')})
    assert result.returncode == 0
    assert 'serve' in result.stdout and 'reconcile' in result.stdout


def test_revoke_blocks_previously_approved_operation(services):
    root = services
    intent = json.loads((root / 'intent.json').read_text())
    assert command(root, 'register', '--intent', root / 'intent.json')[0] == 0
    token = command(root, 'approve', '--intent', root / 'intent.json', '--original-digest',
                    intent_digest(intent), '--expires-at', '2098-01-01T00:00:00Z')[1]['result']
    assert command(root, 'reserve', '--intent-id', 'fixture_intent', '--approval-id', token,
                   '--operation-id', 'revoked')[0] == 0
    assert command(root, 'revoke')[0] == 0
    assert command(root, 'dispatch', '--operation-id', 'revoked')[1]['result']['status'] == 'REJECTED'
    assert command(root, 'event', '--calendar-id', 'fixture_calendar', '--event-id', 'fixture_event')[1]['result']['version'] == 0


def test_real_receipt_reconciliation_without_resending(services):
    root = services
    intent = json.loads((root / 'intent.json').read_text())
    assert command(root, 'register', '--intent', root / 'intent.json')[0] == 0
    token = command(root, 'approve', '--intent', root / 'intent.json', '--original-digest',
                    intent_digest(intent), '--expires-at', '2098-01-01T00:00:00Z')[1]['result']
    assert command(root, 'reserve', '--intent-id', 'fixture_intent', '--approval-id', token,
                   '--operation-id', 'recovery')[0] == 0
    from laboratorio.unix_transport import request
    # Seed an interrupted controller state around a REAL receiver effect.
    # This test does not claim to kill a process (that belongs to cli-hardening).
    with sqlite3.connect(root / 'controller.sqlite3') as db:
        db.execute("UPDATE operations SET status='DISPATCHING' WHERE operation_id='recovery'")
    effect = request(root / 'd.sock', {'method': 'execute', 'params': {
        'intent': intent, 'approval_id': token, 'operation_id': 'recovery'}})
    assert effect['ok'] is True
    result = command(root, 'reconcile', '--operation-id', 'recovery')[1]['result']
    assert result['status'] == 'CONFIRMED'
    assert result['receipt'] == effect['result']
    assert command(root, 'dispatch', '--operation-id', 'recovery')[1]['result'] == result
    assert command(root, 'event', '--calendar-id', 'fixture_calendar', '--event-id', 'fixture_event')[1]['result']['version'] == 1


@pytest.mark.parametrize('suffix', ['-journal', '-wal', '-shm'])
def test_special_sqlite_sidecars_rejected(root, suffix):
    prepare(root)
    os.mkfifo(str(root / 'controller.sqlite3') + suffix)
    assert command(root, 'query')[0] == 2
    assert command(root, 'register', '--intent', root / 'intent.json')[0] == 2


def test_clock_rollback_stays_blocked_after_reopen(root):
    prepare(root)
    with sqlite3.connect(root / 'controller.sqlite3') as db:
        db.execute("UPDATE controller_state SET last_observed='2098-01-01T00:00:00Z'")
    assert command(root, 'register', '--intent', root / 'intent.json')[0] == 2
    assert command(root, 'register', '--intent', root / 'intent.json')[0] == 2
    assert command(root, 'query')[1]['result']['metadata']['clock_blocked'] is True
    assert command(root, 'query')[1]['result']['intents'] == []


def test_fixture_has_no_approval_and_rejects_forged_principal(root):
    prepare(root)
    with sqlite3.connect(root / 'receiver.sqlite3') as db:
        assert db.execute('SELECT COUNT(*) FROM approvals').fetchone()[0] == 0
    intent = json.loads((root / 'intent.json').read_text())
    intent['principal_id'] = 'self_assigned'
    (root / 'intent.json').write_text(json.dumps(intent))
    assert command(root, 'register', '--intent', root / 'intent.json')[0] == 2
    assert command(root, 'query')[1]['result']['intents'] == []


def test_existing_endpoint_is_preserved(root):
    from laboratorio.operator_cli import serve
    prepare(root)
    (root / 'd.sock').write_text('foreign')
    before = snapshot(root)
    with pytest.raises(FileExistsError):
        serve(root)
    assert snapshot(root) == before
    assert not (root / 'a.sock').exists()


def test_symlink_root_and_parent_rejected(root):
    prepare(root)
    link = root.parent / 'alias'
    link.symlink_to(root, target_is_directory=True)
    before = snapshot(root)
    assert command(link, 'query')[0] == 2
    assert command(root, 'register', '--intent', link / 'intent.json')[0] == 2
    assert snapshot(root) == before


def test_service_does_not_reinitialize_damaged_authority(root):
    from laboratorio.operator_cli import serve
    prepare(root)
    # Truncation stands for storage loss. Startup must fail without inventing epoch 0.
    (root / 'receiver.sqlite3').write_bytes(b'')
    before = snapshot(root)
    with pytest.raises((ValueError, OSError, sqlite3.Error)):
        serve(root, stop=threading.Event())
    assert snapshot(root) == before


def test_query_rejects_wal_without_creating_sidecars(root):
    prepare(root)
    with sqlite3.connect(root / 'controller.sqlite3') as db:
        db.execute('PRAGMA journal_mode=WAL')
    db.close()
    before = snapshot(root)
    assert command(root, 'query')[0] == 2
    assert snapshot(root) == before
