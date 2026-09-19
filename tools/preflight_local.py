"""Run benign OS/Unix probes in a dedicated short-lived Docker container.

No image pull, daemon configuration change or existing-container operation.
Only the five explicitly listed public source files are mounted, read-only.
This is a measured container experiment, not C1-T02 or a dedicated VM claim.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / 'src'))
from laboratorio.evaluation import loads_strict

IMAGE = 'python@sha256:2f17fc044b579bab302c2e8054d3a686e2cb9a83de48e70534b94cd8ebbe06a9'
FILES = ('src/laboratorio/__init__.py', 'src/laboratorio/authority.py',
         'src/laboratorio/evaluation.py', 'src/laboratorio/unix_transport.py',
         'tools/probe_unix_isolation.py')


EXPECTED_PROBES = frozenset({
    'admin_socket_owner', 'approved_effect_applied', 'candidate_admin_fs_denied',
    'candidate_dispatch_fs_denied', 'child_capabilities_zero', 'child_uid_unprivileged',
    'dispatcher_cannot_approve', 'dispatcher_socket_owner', 'docker_socket_absent',
    'external_route_absent', 'host_home_absent', 'only_one_effect', 'own_scratch_writable',
    'protected_db_denied', 'protected_oracle_denied', 'replay_same_receipt',
    'revocation_applied', 'revoked_intent_denied', 'rootfs_write_denied', 'separate_uids',
    'socket_modes_0600', 'source_write_denied', 'synthetic_admin_approval', 'wrong_peer_uid_denied',
})

OWNER_LABEL = 'limite.preflight-nonce'


def owned_container_id(identity, name, nonce):
    """Accept only a full ID attested by this run's exact name and nonce."""
    if (type(identity) is not dict or identity.get('Name') != '/' + name
            or identity.get('nonce') != nonce
            or type(identity.get('Id')) is not str
            or not re.fullmatch('[0-9a-f]{64}', identity['Id'])):
        raise ValueError('Container ownership could not be verified')
    return identity['Id']


def reconcile_container(name, nonce):
    """Read only the assigned name and project just ownership metadata."""
    projection = ('{"Id":{{json .Id}},"Name":{{json .Name}},"nonce":'
                  '{{json (index .Config.Labels "' + OWNER_LABEL + '")}}}')
    result = subprocess.run(['docker', 'container', 'inspect', '--format', projection, name],
                            capture_output=True, text=True, timeout=10)
    if result.returncode:
        absent = {'Error response from daemon: No such container: ' + name,
                  'Error: No such container: ' + name}
        if not result.stdout.strip() and result.stderr.strip() in absent:
            return None, 'absent'
        raise RuntimeError('Container lookup inconclusive')
    identity = loads_strict(result.stdout)
    try:
        return owned_container_id(identity, name, nonce), 'verified'
    except ValueError:
        return None, 'unverified'


def validate_report(report):
    fields = {'status', 'probes', 'synthetic_data', 'human_approval_performed', 'kernel',
              'separate_guest_uids', 'C1_T02_verified', 'dedicated_vm_verified',
              'adversarial_containment_verified', 'trusted_receiver_runs_as_guest_root'}
    if type(report) is not dict or set(report) != fields or report['status'] != 'PASS':
        raise ValueError('Unexpected or unsuccessful probe report')
    checks = report['probes']
    if type(checks) is not dict or set(checks) != EXPECTED_PROBES or any(v is not True for v in checks.values()):
        raise ValueError('Probe set incomplete, changed or failing')
    for field in ('C1_T02_verified', 'dedicated_vm_verified', 'adversarial_containment_verified', 'human_approval_performed'):
        if report[field] is not False:
            raise ValueError('Unsupported evidence claim: ' + field)
    if report['synthetic_data'] is not True or report['trusted_receiver_runs_as_guest_root'] is not True:
        raise ValueError('Incorrect experiment provenance')
    uids = report['separate_guest_uids']
    if type(uids) is not list or any(type(uid) is not int for uid in uids) or uids != [25001, 25002, 25003]:
        raise ValueError('Incorrect guest identities')
    if type(report['kernel']) is not str or not 1 <= len(report['kernel']) <= 128:
        raise ValueError('Missing kernel provenance')
    return True


def validate_profile(inspect, source):
    host = inspect['HostConfig']
    required = {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False,
                'PidsLimit': 64, 'Memory': 256 * 1024**2, 'NanoCpus': 1_000_000_000}
    for key, value in required.items():
        if type(host.get(key)) is not type(value) or host[key] != value:
            raise ValueError('Unsafe container setting: ' + key)
    normalize = lambda values: {x.upper().removeprefix('CAP_') for x in values or []}
    if normalize(host.get('CapDrop')) != {'ALL'} or normalize(host.get('CapAdd')) != {'SETUID', 'SETGID', 'CHOWN'}:
        raise ValueError('Unexpected capabilities')
    if not any(x in ('no-new-privileges', 'no-new-privileges:true') for x in host.get('SecurityOpt', [])):
        raise ValueError('no-new-privileges is required')
    if host.get('PidMode') or host.get('IpcMode') == 'host' or host.get('UTSMode') or host.get('Binds') or host.get('VolumesFrom') or host.get('PortBindings') or host.get('Devices') or host.get('DeviceRequests'):
        raise ValueError('Unexpected host sharing or devices')
    mounts = inspect['Mounts']
    if len(mounts) != 1 or mounts[0].get('Type') != 'bind' or mounts[0].get('RW') is not False or mounts[0].get('Destination') != '/opt/lab' or mounts[0].get('Source') != str(source):
        raise ValueError('Unexpected mount')
    if host.get('Tmpfs') != {'/run/lab': 'rw,noexec,nosuid,nodev,size=16m,mode=755'}:
        raise ValueError('Unexpected writable filesystem')
    return True


def run(out, timeout=30):
    if type(timeout) is not int or not 10 <= timeout <= 120:
        raise ValueError('Timeout must be 10..120 seconds')
    out = Path(os.path.abspath(out))
    runs = BASE / 'runs'
    if not out.is_relative_to(runs) or out == runs:
        raise ValueError('Output must be a fresh directory below runs/')
    current = runs
    for part in (None, *out.relative_to(runs).parts[:-1]):
        if part is not None:
            current /= part
        if current.is_symlink():
            raise ValueError('Output symlinks are not allowed')
        current.mkdir(exist_ok=True)
    out.mkdir(exist_ok=False)
    run_id = uuid.uuid4().hex
    name = 'limite-preflight-' + run_id
    nonce = uuid.uuid4().hex
    state = {'status': 'RUNNING', 'image': IMAGE, 'C1_T02_verified': False,
             'dedicated_vm_verified': False, 'container_removed': False,
             'run_id': run_id, 'container_name': name, 'ownership_nonce': nonce,
             'creation_attempted': False, 'cleanup_status': 'not_attempted'}
    cid = None
    final_error = None
    with tempfile.TemporaryDirectory(prefix='limite-source-') as directory:
        source = Path(directory).resolve()
        source.chmod(0o755)
        for rel in FILES:
            target = source / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(BASE / rel, target)
            target.chmod(0o644)
        for path in source.rglob('*'):
            if path.is_dir():
                path.chmod(0o755)
        before = {rel: hashlib.sha256((source / rel).read_bytes()).hexdigest() for rel in FILES}
        (out / 'source-sha256.json').write_text(json.dumps(before, indent=2))
        try:
            # Missing image is a preflight dependency, never an implicit pull.
            subprocess.run(['docker', 'image', 'inspect', IMAGE], check=True,
                           capture_output=True, text=True, timeout=10)
            command = ['docker', 'create', '--name', name,
                       '--label', 'limite.benign-preflight=true',
                       '--label', OWNER_LABEL + '=' + nonce, '--pull', 'never',
                       '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                       '--cap-add', 'SETUID', '--cap-add', 'SETGID', '--cap-add', 'CHOWN',
                       '--security-opt', 'no-new-privileges:true', '--pids-limit', '64',
                       '--memory', '256m', '--cpus', '1', '--tmpfs',
                       '/run/lab:rw,noexec,nosuid,nodev,size=16m,mode=755', '--mount',
                       f'type=bind,src={source},dst=/opt/lab,readonly', '--env',
                       'PYTHONPATH=/opt/lab/src', '--env', 'PYTHONDONTWRITEBYTECODE=1',
                       IMAGE, 'timeout', '--signal=TERM', '--kill-after=2s', str(timeout) + 's',
                       'python', '/opt/lab/tools/probe_unix_isolation.py']
            state['creation_attempted'] = True
            (out / 'state.json').write_text(json.dumps(state, indent=2))
            created = subprocess.run(command, check=True, capture_output=True, text=True, timeout=15)
            created_id = created.stdout.strip()
            if not re.fullmatch('[0-9a-f]{64}', created_id):
                raise ValueError('Unrecognized container ID; no cleanup of arbitrary identifiers')
            inspect = loads_strict(subprocess.check_output(['docker', 'inspect', created_id], text=True, timeout=10))[0]
            verified_id = owned_container_id({'Id': inspect.get('Id'), 'Name': inspect.get('Name'),
                'nonce': inspect.get('Config', {}).get('Labels', {}).get(OWNER_LABEL)}, name, nonce)
            if verified_id != created_id:
                raise ValueError('Created container ID does not match inspection')
            cid = verified_id
            state['container_id'] = cid
            validate_profile(inspect, source)
            profile = {key: inspect['HostConfig'].get(key) for key in
                       ('NetworkMode', 'ReadonlyRootfs', 'Privileged', 'CapDrop', 'CapAdd',
                        'PidsLimit', 'Memory', 'NanoCpus', 'SecurityOpt', 'Tmpfs')}
            (out / 'profile.json').write_text(json.dumps(profile, indent=2))
            executed = subprocess.run(['docker', 'start', '-a', cid], capture_output=True,
                                      text=True, timeout=timeout + 3)
            (out / 'stderr.log').write_text(executed.stderr)
            if executed.returncode:
                raise RuntimeError('Container execution failed; see local stderr.log')
            report = loads_strict(executed.stdout)
            (out / 'probes.json').write_text(json.dumps(report, indent=2))
            after = {rel: hashlib.sha256((source / rel).read_bytes()).hexdigest() for rel in FILES}
            if before != after:
                raise RuntimeError('Protected source changed')
            validate_report(report)
            state['status'] = 'PASS'
            state['source_unchanged'] = True
        except (Exception, KeyboardInterrupt) as exc:
            state['status'] = 'INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'FAILED'
            # Do not persist daemon output or inspected configuration on failures.
            state['error'] = type(exc).__name__
            final_error = exc
        finally:
            if state['creation_attempted']:
                try:
                    state['cleanup_status'] = 'inconclusive'
                    if cid is None:
                        cid, state['cleanup_status'] = reconcile_container(name, nonce)
                    if cid:
                        state['container_id'] = cid
                        state['cleanup_status'] = 'failed'
                        removed = subprocess.run(['docker', 'rm', '-f', cid], capture_output=True,
                                                 text=True, timeout=10)
                        if removed.returncode:
                            raise RuntimeError('Owned container cleanup failed')
                        state['container_removed'] = True
                        state['cleanup_status'] = 'removed'
                except (Exception, KeyboardInterrupt) as exc:
                    if isinstance(exc, KeyboardInterrupt):
                        state['cleanup_status'] = 'interrupted'
                    if state['status'] != 'INTERRUPTED':
                        state['status'] = 'INTERRUPTED' if isinstance(exc, KeyboardInterrupt) else 'FAILED'
                    state['cleanup_error'] = type(exc).__name__
                    final_error = final_error or exc
            (out / 'state.json').write_text(json.dumps(state, indent=2))
    if final_error:
        raise RuntimeError('Preflight incomplete; inspect ' + str(out / 'state.json')) from final_error
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True)
    parser.add_argument('--timeout', type=int, default=30)
    args = parser.parse_args()
    previous = {}
    def stop(signum, frame):
        raise KeyboardInterrupt('Preflight interrupted')
    try:
        for sig in (signal.SIGTERM, signal.SIGINT):
            previous[sig] = signal.signal(sig, stop)
        result = run(args.out, args.timeout)
    except (OSError, ValueError, RuntimeError, KeyboardInterrupt) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
