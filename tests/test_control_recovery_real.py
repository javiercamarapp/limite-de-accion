"""CLI boundaries and an owned child killed after a real Unix/SQLite effect.

No skip on denied bind: a restricted runner must report that missing evidence.
"""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import selectors
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading

import pytest

from laboratorio import control_demo
from laboratorio.authority import LocalAuthority, intent_digest
from laboratorio.controller import DurableController
from laboratorio.unix_transport import UnixReceiver, request
from test_cli import ROOT, cli


@contextmanager
def private_run():
    # Short enough for macOS sockaddr_un, under trusted ancestors.
    with tempfile.TemporaryDirectory(prefix='.cr-', dir=ROOT) as directory:
        yield Path(directory)


@pytest.mark.parametrize('kind', ['symlink', 'parent_symlink', 'fifo', 'directory'])
def test_cli_rejects_special_json_paths_without_blocking(tmp_path, kind):
    target = tmp_path / 'empty.json'
    target.write_text('[]')
    source = tmp_path / 'input'
    if kind == 'symlink':
        source.symlink_to(target)
    elif kind == 'parent_symlink':
        source.symlink_to(tmp_path, target_is_directory=True)
        source = source / target.name
    elif kind == 'fifo':
        os.mkfifo(source)
    else:
        source.mkdir()
    result = cli('forecast-score', source, target, '--now', control_demo.NOW)
    assert result.returncode == 2, result.stdout
    assert json.loads(result.stderr)['actions_authorized'] is False
    assert result.stdout == ''
    assert target.read_text() == '[]'


def test_cli_limits_bytes_not_unicode_characters(tmp_path):
    source = tmp_path / 'large.json'
    source.write_text('["' + 'é' * 1_000_000 + '"]')
    from laboratorio.__main__ import read_json
    with pytest.raises(ValueError):
        read_json(source)


@pytest.mark.parametrize('kind', ['symlink', 'dangling', 'traversal', 'shared', 'existing'])
def test_demo_rejects_unsafe_output_without_touching_target(kind):
    with private_run() as root:
        target = root / 'target'
        target.mkdir()
        sentinel = target / 'keep'
        sentinel.write_text('unchanged')
        link = root / 'link'
        if kind == 'symlink':
            link.symlink_to(target, target_is_directory=True)
            output = link / 'run'
        elif kind == 'dangling':
            link.symlink_to(root / 'absent', target_is_directory=True)
            output = link / 'run'
        elif kind == 'traversal':
            output = target / '..' / 'run'
        elif kind == 'shared':
            target.chmod(0o777)
            output = target / 'run'
        else:
            output = target
        before = sorted(str(p.relative_to(root)) for p in root.rglob('*'))
        with pytest.raises((OSError, ValueError)):
            control_demo._fresh_private_directory(output)
        assert sorted(str(p.relative_to(root)) for p in root.rglob('*')) == before
        assert sentinel.read_text() == 'unchanged'


def test_demo_closes_authority_when_fixture_initialization_fails(monkeypatch):
    opened = []
    class BrokenFixture(LocalAuthority):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            opened.append(self)
        def create_event(self, *args, **kwargs):
            raise RuntimeError('fixture failure')
    monkeypatch.setattr(control_demo, 'LocalAuthority', BrokenFixture)
    with private_run() as root:
        with pytest.raises(RuntimeError, match='fixture failure'):
            control_demo.run_demo(root / 'run')
        assert len(opened) == 1
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            opened[0]._db.execute('SELECT 1')
        assert not list(root.rglob('*.sock'))


def test_cli_reports_storage_failure_as_json(monkeypatch, capsys):
    from laboratorio.__main__ import main
    def fail(output):
        raise sqlite3.OperationalError('storage unavailable')
    monkeypatch.setattr(control_demo, 'run_demo', fail)
    assert main(['demo-durable-control', '--out', 'unused']) == 2
    captured = capsys.readouterr()
    assert captured.out == ''
    assert json.loads(captured.err) == {'error': 'storage unavailable', 'actions_authorized': False}


def test_demo_thread_start_failure_closes_socket_and_authority(monkeypatch):
    instances = []
    class RecordingReceiver(UnixReceiver):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)
    def fail_start(thread):
        raise RuntimeError('thread start failed')
    monkeypatch.setattr(control_demo, 'UnixReceiver', RecordingReceiver)
    monkeypatch.setattr(control_demo.threading.Thread, 'start', fail_start)
    with private_run() as root:
        with pytest.raises(RuntimeError, match='thread start failed'):
            control_demo.run_demo(root / 'run')
        assert not list(root.rglob('*.sock'))
        assert instances[0]._socket.fileno() == -1
        with pytest.raises(sqlite3.ProgrammingError, match='closed'):
            instances[0]._authority._db.execute('SELECT 1')


def test_demo_cleanup_preserves_foreign_replacement_and_joins_on_failure(monkeypatch):
    instances, threads = [], []
    original_start = threading.Thread.start
    class RecordingReceiver(UnixReceiver):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            instances.append(self)
    def start(thread):
        original_start(thread)
        threads.append(thread)
    def fail_controller(*args, **kwargs):
        path = instances[0]._path
        path.unlink()
        path.write_text('foreign replacement')
        raise RuntimeError('controller failure')
    monkeypatch.setattr(control_demo, 'UnixReceiver', RecordingReceiver)
    monkeypatch.setattr(control_demo.threading.Thread, 'start', start)
    monkeypatch.setattr(control_demo, 'DurableController', fail_controller)
    with private_run() as root:
        with pytest.raises(RuntimeError, match='controller failure'):
            control_demo.run_demo(root / 'run')
        assert all(not t.is_alive() for t in threads)
        assert (root / 'run' / 'a.sock').read_text() == 'foreign replacement'
        assert not (root / 'run' / 'd.sock').exists()


CHILD = r'''
import json, sys
from laboratorio.controller import DurableController
from laboratorio.unix_transport import request
from laboratorio.authority import LocalAuthority
def transport(message):
    if sys.argv[3] == 'unix':
        response = request(sys.argv[2], message)
    else:
        authority = LocalAuthority(sys.argv[2], clock=lambda: '2026-09-19T10:00:00Z')
        try:
            response = {'ok': True, 'result': authority.execute(
                **message['params'], authenticated_principal='agent')}
        finally:
            authority._db.close()
    if response.get('ok') is not True:
        raise RuntimeError('receiver rejected effect')
    print(json.dumps(response), flush=True)
    # Parent sees the committed receipt; block before returning it to dispatch.
    sys.stdin.buffer.read(1)
    return response
with DurableController(sys.argv[1], transport=transport,
                       deadline='2026-09-19T11:00:00Z', max_operations=1,
                       clock=lambda: '2026-09-19T10:00:00Z') as controller:
    controller.dispatch('operation')
'''


@pytest.mark.parametrize('channel', ['sqlite', 'unix'])
def test_sigkill_after_effect_before_controller_persistence(channel):
    with private_run() as root:
        authority = LocalAuthority(root / 'r.db', clock=lambda: control_demo.NOW)
        receiver = thread = child = None
        try:
            intent = dict(schema_version='C1.intent.v1', intent_id='intent', run_id='run',
                          principal_id='agent', calendar_id='calendar', event_id='event',
                          operation='RESCHEDULE_EVENT', expected_version=0,
                          start_utc='2026-09-20T10:00:00Z', end_utc='2026-09-20T10:30:00Z')
            authority.create_event('calendar', 'event', '2026-09-20T08:00:00Z',
                                   '2026-09-20T08:30:00Z', title='SYNTHETIC')
            approval = authority.approve(intent, original_request_digest=intent_digest(intent),
                                         approver_id='synthetic_fixture', expires_at=control_demo.DEADLINE)
            socket_path = root / 'd.sock'
            if channel == 'unix':
                receiver = UnixReceiver(socket_path, authority, allowed_uid=os.geteuid(),
                                        role='dispatcher', principal_id='agent')
                thread = threading.Thread(target=receiver.serve_forever)
                thread.start()
            calls = []
            def transport(message):
                calls.append(message['method'])
                if channel == 'unix':
                    return request(socket_path, message)
                assert message['method'] == 'get_receipt', 'recovery must never resend'
                return {'ok': True, 'result': authority.get_receipt(
                    **message['params'], authenticated_principal='agent')}
            options = dict(transport=transport, deadline=control_demo.DEADLINE,
                           max_operations=1, clock=lambda: control_demo.NOW)
            with DurableController(root / 'c.db', **options) as controller:
                controller.register(intent)
                controller.reserve('intent', approval, 'operation')
            endpoint = socket_path if channel == 'unix' else root / 'r.db'
            child = subprocess.Popen([sys.executable, '-c', CHILD, str(root / 'c.db'), str(endpoint), channel],
                                     env=dict(os.environ, PYTHONPATH=str(ROOT / 'src')),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            with selectors.DefaultSelector() as selector:
                selector.register(child.stdout, selectors.EVENT_READ)
                assert selector.select(timeout=5), 'child did not reach committed effect'
                response = json.loads(child.stdout.readline())
            assert response['ok'] is True
            assert response['result']['version'] == 1
            with sqlite3.connect(root / 'c.db') as db:
                assert db.execute('SELECT status, receipt_json FROM operations').fetchone() == ('DISPATCHING', None)
            child.kill()  # SIGKILL of exactly our owned benign process.
            child.communicate(timeout=5)
            assert child.returncode == -signal.SIGKILL
            with DurableController(root / 'c.db', **options) as controller:
                assert controller.get_operation('operation')['status'] == 'UNKNOWN'
                snapshot = controller.export_state()
                assert controller.dispatch('operation')['status'] == 'UNKNOWN'
                assert controller.export_state() == snapshot
                assert calls == []
                assert controller.reconcile('operation')['status'] == 'CONFIRMED'
                assert calls == ['get_receipt']
                assert controller.export_state()['metadata']['max_operations'] == 1
                controller.register({**intent, 'intent_id': 'second', 'expected_version': 1})
                with pytest.raises(PermissionError, match='Presupuesto'):
                    controller.reserve('second', 'another_approval', 'second_operation')
            with DurableController(root / 'c.db', **options) as controller:
                assert controller.dispatch('operation')['status'] == 'CONFIRMED'
                assert calls == ['get_receipt']
            event = authority.get_event('calendar', 'event')
            assert event['version'] == 1
            assert event['start_utc'] == intent['start_utc']
            assert event['end_utc'] == intent['end_utc']
        finally:
            if child is not None:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)
            try:
                if receiver is not None:
                    receiver.close()
            finally:
                if thread is not None and thread.ident is not None:
                    thread.join(timeout=3)
                authority._db.close()
                assert thread is None or not thread.is_alive()
