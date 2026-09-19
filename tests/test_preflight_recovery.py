"""Deterministic effect assertions and Docker CLI recovery; no daemon required."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_tool(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'tools' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


preflight = load_tool('preflight_local')
probe = load_tool('probe_unix_isolation')
CID = 'a7' * 32
INTENT = {'expected_version': 0, 'start_utc': '2026-09-20T10:00:00Z',
          'end_utc': '2026-09-20T10:30:00Z'}
EVENT = {'version': 1, 'start_utc': '2026-09-20T10:00:00Z',
         'end_utc': '2026-09-20T10:30:00Z', 'title': 'SYNTHETIC FIXTURE'}


@pytest.mark.parametrize('title', [None, 'SYNTHETIC FIXTURE'])
def test_exact_authorized_effect(title):
    assert probe.effect_matches(copy.deepcopy(EVENT), copy.deepcopy(INTENT), title)


@pytest.mark.parametrize('title', [None, 'SYNTHETIC FIXTURE'])
@pytest.mark.parametrize('change', [
    {'start_utc': '2026-09-20T08:00:00Z', 'end_utc': '2026-09-20T08:30:00Z'},
    {'start_utc': '2026-09-20T09:00:00Z'}, {'end_utc': '2026-09-20T11:00:00Z'},
    {'version': True}, {'version': 1.0}, {'version': 0}, {'version': 2},
])
def test_receipt_and_persisted_event_reject_wrong_effect(change, title):
    assert not probe.effect_matches({**EVENT, **change}, INTENT, title)


def test_persisted_title_must_survive():
    assert not probe.effect_matches({**EVENT, 'title': 'CHANGED'}, INTENT, 'SYNTHETIC FIXTURE')


@pytest.mark.parametrize('event,intent', [
    (None, INTENT), ({'version': 1}, INTENT), (EVENT, {**INTENT, 'expected_version': False}),
    (EVENT, {**INTENT, 'expected_version': 0.0}), (EVENT, {**INTENT, 'expected_version': 1}),
])
def test_incomplete_or_noninteger_effect_evidence_is_rejected(event, intent):
    assert probe.effect_matches(event, intent) is False


class DockerCLI:
    """A scripted CLI boundary, never a fake database or authority implementation."""
    def __init__(self, create='ok', lookup='owned', removal='ok', inspection='owned', start='ok'):
        self.create = create
        self.lookup = lookup
        self.removal = removal
        self.inspection = inspection
        self.start = start
        self.calls = []
        self.name = None
        self.labels = {}

    def result(self, command, stdout='', code=0, stderr=''):
        return subprocess.CompletedProcess(command, code, stdout, stderr)

    def run(self, command, **kwargs):
        assert command[0] == 'docker'
        assert kwargs['timeout'] > 0
        self.calls.append(command)
        if command[1:3] == ['image', 'inspect']:
            if self.create == 'missing_image':
                raise subprocess.CalledProcessError(1, command)
            return self.result(command, '[]')
        if command[1] == 'create':
            self.name = command[command.index('--name') + 1]
            self.labels = dict(command[i + 1].split('=', 1) for i, v in enumerate(command) if v == '--label')
            state = json.loads((preflight.BASE / 'runs/case/state.json').read_text())
            assert state['creation_attempted'] is True
            assert state['container_name'] == self.name
            assert state['ownership_nonce'] == self.labels['limite.preflight-nonce']
            if self.create == 'timeout':
                raise subprocess.TimeoutExpired(command, kwargs['timeout'])
            if self.create == 'interrupt':
                raise KeyboardInterrupt()
            if self.create == 'error':
                raise subprocess.CalledProcessError(1, command, stderr='PRIVATE_DAEMON_DETAIL')
            return self.result(command, CID + '\n' if self.create == 'ok' else 'not-an-id\n')
        if command[1:3] == ['container', 'inspect']:
            assert command[-1] == self.name
            assert '--format' in command
            if self.lookup == 'unreachable':
                return self.result(command, code=1, stderr='PRIVATE_DAEMON_DETAIL')
            if self.lookup == 'timeout':
                raise subprocess.TimeoutExpired(command, kwargs['timeout'])
            if self.lookup == 'interrupt':
                raise KeyboardInterrupt()
            if self.lookup == 'absent':
                return self.result(command, code=1, stderr='Error response from daemon: No such container: ' + self.name + '\n')
            if self.lookup == 'malformed':
                return self.result(command, '{PRIVATE_DAEMON_DETAIL')
            if self.lookup == 'wrong_absence':
                return self.result(command, code=1, stderr='Error: No such container: other-container')
            owned = {'Id': CID, 'Name': '/' + self.name,
                     'nonce': self.labels.get('limite.preflight-nonce')}
            if self.lookup == 'label_mismatch': owned['nonce'] = 'someone-else'
            if self.lookup == 'name_mismatch': owned['Name'] += '-other'
            if self.lookup == 'id_malformed': owned['Id'] = 'abc'
            if self.lookup == 'empty': return self.result(command, '')
            if self.lookup == 'multiple': return self.result(command, json.dumps([owned, owned]))
            return self.result(command, json.dumps(owned))
        if command[1:3] == ['start', '-a']:
            if self.start == 'timeout': raise subprocess.TimeoutExpired(command, kwargs['timeout'])
            if self.start == 'interrupt': raise KeyboardInterrupt()
            import test_preflight_profile
            return self.result(command, json.dumps(test_preflight_profile.report()))
        if command[1:3] == ['rm', '-f']:
            assert command == ['docker', 'rm', '-f', CID]
            if self.removal == 'interrupt': raise KeyboardInterrupt()
            return self.result(command, CID, code=1 if self.removal == 'error' else 0)
        raise AssertionError('Unexpected CLI operation: ' + repr(command))

    def check_output(self, command, **kwargs):
        self.calls.append(command)
        assert command == ['docker', 'inspect', CID]
        import test_preflight_profile
        value = test_preflight_profile.profile()
        create = next(c for c in self.calls if c[1] == 'create')
        mount = create[create.index('--mount') + 1]
        value['Mounts'][0]['Source'] = mount.split('src=', 1)[1].split(',dst=', 1)[0]
        value.update(Id=CID, Name='/' + self.name, Config={'Labels': self.labels})
        if self.inspection == 'label_mismatch': value['Config'] = {'Labels': {'limite.preflight-nonce': 'other'}}
        if self.inspection == 'name_mismatch': value['Name'] += '-other'
        if self.inspection == 'id_malformed': value['Id'] = 'bad'
        if self.inspection == 'id_mismatch': value['Id'] = 'b8' * 32
        if self.inspection == 'unsafe_profile': value['HostConfig']['NetworkMode'] = 'host'
        value['Config']['Env'] = ['PRIVATE_DAEMON_DETAIL']
        return json.dumps([value])


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    for rel in preflight.FILES:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / rel, target)
    monkeypatch.setattr(preflight, 'BASE', tmp_path)

    def execute(cli, succeeds=False):
        monkeypatch.setattr(preflight.subprocess, 'run', cli.run)
        monkeypatch.setattr(preflight.subprocess, 'check_output', cli.check_output)
        out = tmp_path / 'runs' / 'case'
        if succeeds:
            preflight.run(out, timeout=17)
        else:
            with pytest.raises(RuntimeError, match='Preflight incomplete'):
                preflight.run(out, timeout=17)
        return json.loads((out / 'state.json').read_text()), out
    return execute


def assert_single_create(cli):
    assert sum(c[1] == 'create' for c in cli.calls) == 1


def removals(cli):
    return [c for c in cli.calls if c[1] == 'rm']


def test_normal_create_removes_once_and_preserves_security(sandbox):
    cli = DockerCLI()
    state, out = sandbox(cli, succeeds=True)
    assert state['status'] == 'PASS' and state['container_removed'] is True
    assert removals(cli) == [['docker', 'rm', '-f', CID]]
    assert_single_create(cli)
    create = next(c for c in cli.calls if c[1] == 'create')
    for option, value in [('--pull', 'never'), ('--network', 'none'), ('--cap-drop', 'ALL'),
                          ('--security-opt', 'no-new-privileges:true')]:
        assert create[create.index(option) + 1] == value
    assert '--read-only' in create
    assert [create[i + 1] for i, v in enumerate(create) if v == '--cap-add'] == ['SETUID', 'SETGID', 'CHOWN']
    assert create[-6:] == ['timeout', '--signal=TERM', '--kill-after=2s', '17s',
                           'python', '/opt/lab/tools/probe_unix_isolation.py']
    assert len(cli.name.removeprefix('limite-preflight-')) == 32
    assert len(cli.labels['limite.preflight-nonce']) == 32
    assert state['creation_attempted'] is True
    assert state['C1_T02_verified'] is False and state['dedicated_vm_verified'] is False
    assert (out / 'profile.json').exists()
    assert all('PRIVATE_DAEMON_DETAIL' not in p.read_text() for p in out.iterdir())


@pytest.mark.parametrize('creation', ['timeout', 'invalid', 'interrupt', 'error'])
def test_ambiguous_create_reconciles_exact_name_and_owned_id(sandbox, creation):
    cli = DockerCLI(create=creation)
    state, _ = sandbox(cli)
    assert state['status'] == ('INTERRUPTED' if creation == 'interrupt' else 'FAILED')
    assert state['container_removed'] is True
    assert state['cleanup_status'] == 'removed'
    assert removals(cli) == [['docker', 'rm', '-f', CID]]
    assert any(c[1:3] == ['container', 'inspect'] and c[-1] == cli.name for c in cli.calls)
    assert_single_create(cli)
    assert not any(c[1] == 'start' for c in cli.calls)


@pytest.mark.parametrize('lookup', ['label_mismatch', 'name_mismatch', 'id_malformed',
                                  'unreachable', 'timeout', 'malformed', 'empty', 'multiple', 'wrong_absence'])
def test_uncertain_or_unowned_lookup_never_removes(sandbox, lookup):
    cli = DockerCLI(create='timeout', lookup=lookup)
    state, out = sandbox(cli)
    assert state['container_removed'] is False
    assert state['status'] == 'FAILED'
    assert state['cleanup_status'] in ('unverified', 'inconclusive')
    assert removals(cli) == []
    assert_single_create(cli)
    assert 'PRIVATE_DAEMON_DETAIL' not in (out / 'state.json').read_text()


def test_confirmed_absence_has_distinct_evidence(sandbox):
    cli = DockerCLI(create='timeout', lookup='absent')
    state, _ = sandbox(cli)
    assert state['cleanup_status'] == 'absent'
    assert state['status'] == 'FAILED'
    assert state['container_removed'] is False
    assert removals(cli) == []


@pytest.mark.parametrize('removal', ['error', 'interrupt'])
def test_cleanup_failure_is_recorded_even_on_interrupt(sandbox, removal):
    cli = DockerCLI(removal=removal)
    state, _ = sandbox(cli)
    assert state['container_removed'] is False
    assert state['status'] in ('FAILED', 'INTERRUPTED')
    assert state['cleanup_status'] in ('failed', 'interrupted')
    assert len(removals(cli)) == 1


def test_missing_image_does_not_create_lookup_or_pull(sandbox):
    cli = DockerCLI(create='missing_image')
    state, _ = sandbox(cli)
    assert state['creation_attempted'] is False
    assert state['cleanup_status'] == 'not_attempted'
    assert state['container_removed'] is False
    assert cli.calls == [['docker', 'image', 'inspect', preflight.IMAGE]]


@pytest.mark.parametrize('inspection', ['label_mismatch', 'name_mismatch', 'id_malformed', 'id_mismatch'])
def test_valid_create_output_alone_does_not_authorize_removal(sandbox, inspection):
    cli = DockerCLI(inspection=inspection, lookup='label_mismatch')
    state, out = sandbox(cli)
    assert state['container_removed'] is False
    assert state['cleanup_status'] == 'unverified'
    assert removals(cli) == []
    assert not any(c[1] == 'start' for c in cli.calls)
    assert not (out / 'profile.json').exists()
    assert all('PRIVATE_DAEMON_DETAIL' not in p.read_text() for p in out.iterdir())


@pytest.mark.parametrize('failure', ['unsafe_profile', 'start_timeout', 'start_interrupt', 'lookup_interrupt'])
def test_failure_and_interrupt_evidence_survives_cleanup(sandbox, failure):
    cli = DockerCLI(inspection='unsafe_profile' if failure == 'unsafe_profile' else 'owned',
                    start=failure.removeprefix('start_'),
                    create='timeout' if failure == 'lookup_interrupt' else 'ok',
                    lookup='interrupt' if failure == 'lookup_interrupt' else 'owned')
    state, _ = sandbox(cli)
    assert state['status'] == ('INTERRUPTED' if 'interrupt' in failure else 'FAILED')
    assert state['container_removed'] is (failure != 'lookup_interrupt')
    assert_single_create(cli)
