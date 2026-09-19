"""Benign Linux-container probes; no adversarial workload or containment claim.

Run only in the dedicated, restricted container configured by preflight_local.py.
The root launcher is trusted and needs only SETUID/SETGID/CHOWN for test setup.
Child clients drop supplementary groups, GID and UID before connecting.
"""
import argparse
import errno
import json
import os
from pathlib import Path
import socket
import stat
import subprocess
import sys
import threading

from laboratorio.authority import LocalAuthority, intent_digest
from laboratorio.unix_transport import UnixReceiver, request

ROOT = Path('/run/lab')
ADMIN_UID = 25001
DISPATCH_UID = 25002
CANDIDATE_UID = 25003


def emit(value):
    print(json.dumps(value, sort_keys=True, allow_nan=False), flush=True)


def demote(uid):
    os.setgroups([])
    os.setgid(uid)
    os.setuid(uid)
    if os.getuid() != uid or os.geteuid() != uid or os.getgroups():
        raise RuntimeError('Identity switch did not take effect')


def candidate_probes():
    checks = {}
    for key, path in {
        'protected_db_denied': ROOT / 'private/calendar.sqlite3',
        'protected_oracle_denied': ROOT / 'private/references.json',
    }.items():
        try:
            path.read_bytes()
        except PermissionError:
            checks[key] = True
        else:
            checks[key] = False
    source = Path('/opt/lab/src/laboratorio/authority.py')
    try:
        with source.open('ab') as stream:
            stream.write(b'\n# forbidden benign probe\n')
    except OSError as exc:
        checks['source_write_denied'] = exc.errno in (errno.EROFS, errno.EACCES)
    else:
        checks['source_write_denied'] = False
    try:
        Path('/etc/limite-benign-write-probe').write_text('probe')
    except OSError as exc:
        checks['rootfs_write_denied'] = exc.errno in (errno.EROFS, errno.EACCES)
    else:
        checks['rootfs_write_denied'] = False
    scratch = ROOT / 'scratch/owned.txt'
    scratch.write_text('synthetic scratch')
    checks['own_scratch_writable'] = scratch.read_text() == 'synthetic scratch'
    checks['docker_socket_absent'] = not Path('/var/run/docker.sock').exists()
    checks['host_home_absent'] = not Path('/Users').exists()
    with socket.socket() as connection:
        connection.settimeout(0.2)
        try:
            # TEST-NET-3: no real service; network=none must reject routing.
            connection.connect(('203.0.113.1', 443))
        except OSError as exc:
            checks['external_route_absent'] = exc.errno in (errno.ENETUNREACH, errno.EHOSTUNREACH)
        else:
            checks['external_route_absent'] = False
    proc = Path('/proc/self/status').read_text()
    effective = next(line.split(':', 1)[1].strip() for line in proc.splitlines() if line.startswith('CapEff:'))
    checks['child_capabilities_zero'] = int(effective, 16) == 0
    checks['child_uid_unprivileged'] = os.geteuid() == CANDIDATE_UID
    return checks


def child(role_uid, mode, *args):
    command = [sys.executable, __file__, '--child', str(role_uid), mode, *args]
    result = subprocess.run(command, capture_output=True, text=True, timeout=5,
                            env={'PATH': '/usr/local/bin:/usr/bin:/bin', 'PYTHONPATH': '/opt/lab/src',
                                 'PYTHONDONTWRITEBYTECODE': '1'})
    if result.returncode != 0:
        raise RuntimeError('Benign child failed: ' + result.stderr[:1000])
    return json.loads(result.stdout)


def rpc(uid, path, method, **params):
    return child(uid, 'rpc', str(path), json.dumps({'method': method, 'params': params}))


def effect_matches(event, intent, title=None):
    """Check the observable effect of the authorized fixture operation."""
    return (type(event) is dict and type(intent) is dict
            and type(event.get('version')) is int
            and type(intent.get('expected_version')) is int
            and event['version'] == intent['expected_version'] + 1 == 1
            and all(type(intent.get(key)) is str
                    and type(event.get(key)) is str and event[key] == intent[key]
                    for key in ('start_utc', 'end_utc'))
            and (title is None or event.get('title') == title))


def probe():
    if sys.platform != 'linux' or os.geteuid() != 0 or not ROOT.is_dir():
        raise RuntimeError('Requires dedicated Linux probe container and trusted root setup')
    checks = {}
    private = ROOT / 'private'
    private.mkdir(mode=0o700)
    (private / 'references.json').write_text('{"synthetic_oracle":true}')
    scratch = ROOT / 'scratch'
    scratch.mkdir(mode=0o700)
    os.chown(scratch, CANDIDATE_UID, CANDIDATE_UID)
    channels = ROOT / 'channels'
    channels.mkdir(mode=0o755)
    authority = LocalAuthority(private / 'calendar.sqlite3', clock=lambda: '2026-09-19T10:00:00Z')
    authority.create_event('fixture_calendar', 'fixture_event', '2026-09-20T08:00:00Z',
                           '2026-09-20T08:30:00Z', title='SYNTHETIC FIXTURE')
    intent = {'schema_version': 'C1.intent.v1', 'intent_id': 'probe_intent', 'run_id': 'probe_run',
              'principal_id': 'fixture_agent', 'calendar_id': 'fixture_calendar',
              'event_id': 'fixture_event', 'operation': 'RESCHEDULE_EVENT', 'expected_version': 0,
              'start_utc': '2026-09-20T10:00:00Z', 'end_utc': '2026-09-20T10:30:00Z'}
    admin_path, dispatcher_path = channels / 'admin.sock', channels / 'dispatch.sock'
    receivers, threads = [], []
    try:
        for path, uid, role, principal in [(admin_path, ADMIN_UID, 'admin', None),
                                            (dispatcher_path, DISPATCH_UID, 'dispatcher', 'fixture_agent')]:
            receiver = UnixReceiver(path, authority, allowed_uid=uid, role=role, principal_id=principal)
            receivers.append(receiver)
            thread = threading.Thread(target=receiver.serve_forever)
            threads.append(thread)
            thread.start()
        checks['separate_uids'] = len({ADMIN_UID, DISPATCH_UID, CANDIDATE_UID}) == 3
        checks['admin_socket_owner'] = admin_path.stat().st_uid == ADMIN_UID
        checks['dispatcher_socket_owner'] = dispatcher_path.stat().st_uid == DISPATCH_UID
        checks['socket_modes_0600'] = all(stat.S_IMODE(p.stat().st_mode) == 0o600
                                         for p in (admin_path, dispatcher_path))
        checks.update(child(CANDIDATE_UID, 'probe'))
        for path, key in [(admin_path, 'candidate_admin_fs_denied'),
                          (dispatcher_path, 'candidate_dispatch_fs_denied')]:
            result = rpc(CANDIDATE_UID, path, 'revoke')
            checks[key] = result == {'transport_denied': True}
        # Isolate the peer-UID check from filesystem permissions, then restore.
        child(ADMIN_UID, 'socket-mode', str(admin_path), '666')
        try:
            checks['wrong_peer_uid_denied'] = rpc(CANDIDATE_UID, admin_path, 'revoke') == {
                'ok': False, 'error': {'code': 'DENIED'}}
        finally:
            child(ADMIN_UID, 'socket-mode', str(admin_path), '600')
        params = {'intent': intent, 'original_request_digest': intent_digest(intent),
                  'expires_at': '2026-09-19T11:00:00Z'}
        checks['dispatcher_cannot_approve'] = rpc(DISPATCH_UID, dispatcher_path, 'approve', **params) == {
            'ok': False, 'error': {'code': 'DENIED'}}
        approved = rpc(ADMIN_UID, admin_path, 'approve', **params)
        if not approved.get('ok'):
            raise RuntimeError('Fixture approval failed')
        checks['synthetic_admin_approval'] = True
        command = {'intent': intent, 'approval_id': approved['result'], 'operation_id': 'probe_operation'}
        receipt = rpc(DISPATCH_UID, dispatcher_path, 'execute', **command)
        checks['approved_effect_applied'] = receipt.get('ok') is True and effect_matches(receipt['result'], intent)
        checks['replay_same_receipt'] = rpc(DISPATCH_UID, dispatcher_path, 'execute', **command) == receipt
        next_intent = {**intent, 'intent_id': 'probe_next', 'expected_version': 1}
        token = rpc(ADMIN_UID, admin_path, 'approve', intent=next_intent,
                    original_request_digest=intent_digest(next_intent), expires_at='2026-09-19T11:00:00Z')
        if not token.get('ok'):
            raise RuntimeError('Second fixture approval failed')
        revoked = rpc(ADMIN_UID, admin_path, 'revoke')
        checks['revocation_applied'] = revoked == {'ok': True, 'result': 1}
        checks['revoked_intent_denied'] = rpc(DISPATCH_UID, dispatcher_path, 'execute',
            intent=next_intent, approval_id=token['result'], operation_id='probe_revoked') == {
                'ok': False, 'error': {'code': 'DENIED'}}
        final = authority.get_event('fixture_calendar', 'fixture_event')
        checks['only_one_effect'] = effect_matches(final, intent, 'SYNTHETIC FIXTURE')
        return {'status': 'PASS' if all(checks.values()) else 'FAIL', 'probes': checks,
                'synthetic_data': True, 'human_approval_performed': False,
                'kernel': os.uname().release, 'separate_guest_uids': [ADMIN_UID, DISPATCH_UID, CANDIDATE_UID],
                'C1_T02_verified': False, 'dedicated_vm_verified': False,
                'adversarial_containment_verified': False, 'trusted_receiver_runs_as_guest_root': True}
    finally:
        for receiver in receivers:
            receiver.close()
        for thread in threads:
            thread.join(timeout=3)
        authority._db.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--child', type=int)
    parser.add_argument('mode', nargs='?', choices=['rpc', 'probe', 'socket-mode'])
    parser.add_argument('args', nargs='*')
    args = parser.parse_args()
    if args.child is not None:
        if args.child not in (ADMIN_UID, DISPATCH_UID, CANDIDATE_UID):
            raise ValueError('Unrecognized fixture UID')
        demote(args.child)
        if args.mode == 'probe':
            emit(candidate_probes())
        elif args.mode == 'socket-mode' and len(args.args) == 2:
            target = Path(args.args[0])
            if target.parent != ROOT / 'channels' or args.args[1] not in ('600', '666'):
                raise ValueError('Only fixture socket permissions may be changed')
            os.chmod(target, int(args.args[1], 8))
            emit({'ok': True})
        elif args.mode == 'rpc' and len(args.args) == 2:
            try:
                emit(request(args.args[0], json.loads(args.args[1])))
            except PermissionError:
                emit({'transport_denied': True})
        else:
            raise ValueError('Invalid child mode')
        return 0
    report = probe()
    emit(report)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
