"""The host must reject a partial probe report or relaxed container profile."""
import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('preflight_under_test', ROOT / 'tools/preflight_local.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)

NAMES = {'admin_socket_owner', 'approved_effect_applied', 'candidate_admin_fs_denied',
         'candidate_dispatch_fs_denied', 'child_capabilities_zero', 'child_uid_unprivileged',
         'dispatcher_cannot_approve', 'dispatcher_socket_owner', 'docker_socket_absent',
         'external_route_absent', 'host_home_absent', 'only_one_effect', 'own_scratch_writable',
         'protected_db_denied', 'protected_oracle_denied', 'replay_same_receipt',
         'revocation_applied', 'revoked_intent_denied', 'rootfs_write_denied', 'separate_uids',
         'socket_modes_0600', 'source_write_denied', 'synthetic_admin_approval', 'wrong_peer_uid_denied'}


def report():
    return {'status': 'PASS', 'probes': {name: True for name in NAMES},
            'synthetic_data': True, 'human_approval_performed': False,
            'kernel': 'test-linux', 'separate_guest_uids': [25001, 25002, 25003],
            'C1_T02_verified': False, 'dedicated_vm_verified': False,
            'adversarial_containment_verified': False, 'trusted_receiver_runs_as_guest_root': True}


def profile():
    return {'HostConfig': {'NetworkMode': 'none', 'ReadonlyRootfs': True, 'Privileged': False,
            'PidsLimit': 64, 'Memory': 256 * 1024**2, 'NanoCpus': 1_000_000_000,
            'CapDrop': ['ALL'], 'CapAdd': ['CAP_SETUID', 'CAP_SETGID', 'CAP_CHOWN'],
            'SecurityOpt': ['no-new-privileges:true'], 'PidMode': '', 'IpcMode': 'private',
            'UTSMode': '', 'Binds': None, 'VolumesFrom': None, 'PortBindings': {},
            'Devices': [], 'DeviceRequests': None,
            'Tmpfs': {'/run/lab': 'rw,noexec,nosuid,nodev,size=16m,mode=755'}},
            'Mounts': [{'Type': 'bind', 'RW': False, 'Source': '/source', 'Destination': '/opt/lab'}]}


def test_complete_report_and_profile_are_accepted():
    assert preflight.validate_report(report()) is True
    assert preflight.validate_profile(profile(), Path('/source')) is True


@pytest.mark.parametrize('change', ['missing', 'extra', 'false', 'numeric_true', 'claimed_isolation',
                                   'claimed_human', 'same_uid', 'bool_uid', 'failed_status', 'unknown_top'])
def test_report_rejects_incomplete_or_fabricated_evidence(change):
    value = report()
    if change == 'missing': value['probes'].pop('protected_db_denied')
    if change == 'extra': value['probes']['new_claim'] = True
    if change == 'false': value['probes']['protected_db_denied'] = False
    if change == 'numeric_true': value['probes']['protected_db_denied'] = 1
    if change == 'claimed_isolation': value['C1_T02_verified'] = True
    if change == 'claimed_human': value['human_approval_performed'] = True
    if change == 'same_uid': value['separate_guest_uids'] = [25001] * 3
    if change == 'bool_uid': value['separate_guest_uids'] = [True, 25002, 25003]
    if change == 'failed_status': value['status'] = 'FAIL'
    if change == 'unknown_top': value['certified'] = True
    with pytest.raises(ValueError): preflight.validate_report(value)


@pytest.mark.parametrize('key,value', [
    ('NetworkMode', 'host'), ('ReadonlyRootfs', False), ('Privileged', True),
    ('PidsLimit', -1), ('Memory', 0), ('NanoCpus', 0), ('CapDrop', []),
    ('CapAdd', ['ALL']), ('SecurityOpt', []), ('PidMode', 'host'), ('IpcMode', 'host'),
    ('UTSMode', 'host'), ('Binds', ['/var/run/docker.sock:/var/run/docker.sock']),
    ('VolumesFrom', ['other']), ('PortBindings', {'80/tcp': []}), ('Devices', [{'PathOnHost': '/dev/sda'}]),
    ('DeviceRequests', [{'Count': -1}]), ('Tmpfs', {'/run/lab': 'rw'})])
def test_profile_cannot_relax_the_test_environment(key, value):
    doc = profile()
    doc['HostConfig'][key] = value
    with pytest.raises(ValueError): preflight.validate_profile(doc, Path('/source'))


@pytest.mark.parametrize('change', ['writable', 'extra', 'wrong_source', 'wrong_destination'])
def test_mount_is_exactly_the_readonly_source(change):
    doc = profile()
    if change == 'writable': doc['Mounts'][0]['RW'] = True
    if change == 'extra': doc['Mounts'].append(copy.deepcopy(doc['Mounts'][0]))
    if change == 'wrong_source': doc['Mounts'][0]['Source'] = '/private'
    if change == 'wrong_destination': doc['Mounts'][0]['Destination'] = '/var/run/docker.sock'
    with pytest.raises(ValueError): preflight.validate_profile(doc, Path('/source'))
