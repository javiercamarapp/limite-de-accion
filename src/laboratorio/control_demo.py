"""Complete benign Unix/SQLite workflow; same-UID demo is NOT role isolation."""
import json
import os
from pathlib import Path
import stat
import threading

from .authority import LocalAuthority, intent_digest
from .controller import DurableController
from .unix_transport import UnixReceiver, request

NOW = '2026-09-19T10:00:00Z'
DEADLINE = '2026-09-19T11:00:00Z'


def _fresh_private_directory(value):
    path = Path(os.path.abspath(value))
    for parent in reversed(path.parents):
        if not parent.exists():
            continue
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o022 or info.st_uid not in (0, os.geteuid()):
            raise PermissionError('Use a trusted, non-shared parent for the control demo')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.mkdir(mode=0o700, exist_ok=False)
    return path


def _write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')


def run_demo(output):
    out = _fresh_private_directory(output)
    authority = LocalAuthority(out / 'receiver.sqlite3', clock=lambda: NOW)
    os.chmod(out / 'receiver.sqlite3', 0o600)
    authority.create_event('demo_calendar', 'demo_event', '2026-09-20T08:00:00Z',
                           '2026-09-20T08:30:00Z', title='SYNTHETIC EVENT')
    intent = {'schema_version': 'C1.intent.v1', 'intent_id': 'demo_intent', 'run_id': 'demo_run',
              'principal_id': 'demo_agent', 'calendar_id': 'demo_calendar', 'event_id': 'demo_event',
              'operation': 'RESCHEDULE_EVENT', 'expected_version': 0,
              'start_utc': '2026-09-20T10:00:00Z', 'end_utc': '2026-09-20T10:30:00Z'}
    admin_path, dispatch_path = out / 'a.sock', out / 'd.sock'
    receivers, threads, controllers = [], [], []
    calls = []
    lose_first_response = [True]

    def transport(message):
        calls.append(message['method'])
        response = request(dispatch_path, message)
        if message['method'] == 'execute' and lose_first_response[0]:
            lose_first_response[0] = False
            # Deliberate application-level loss AFTER the receiver committed.
            raise TimeoutError('Synthetic response loss after the effect')
        return response

    def new_controller():
        controller = DurableController(out / 'controller.sqlite3', transport=transport,
                                       deadline=DEADLINE, max_operations=2, clock=lambda: NOW)
        os.chmod(out / 'controller.sqlite3', 0o600)
        controllers.append(controller)
        return controller

    def admin(method, **params):
        response = request(admin_path, {'method': method, 'params': params})
        if response.get('ok') is not True:
            raise RuntimeError('Synthetic administrative request rejected')
        return response['result']

    try:
        for path, role, principal in [(admin_path, 'admin', None),
                                       (dispatch_path, 'dispatcher', 'demo_agent')]:
            receiver = UnixReceiver(path, authority, allowed_uid=os.geteuid(), role=role,
                                    principal_id=principal)
            receivers.append(receiver)
            thread = threading.Thread(target=receiver.serve_forever)
            threads.append(thread)
            thread.start()
        controller = new_controller()
        controller.register(intent)
        approval = admin('approve', intent=intent, original_request_digest=intent_digest(intent),
                         expires_at=DEADLINE)
        controller.reserve(intent['intent_id'], approval, 'demo_operation')
        before = controller.dispatch('demo_operation')['status']
        controller.close()
        controller = new_controller()
        still_unknown = controller.dispatch('demo_operation')['status']
        recovered = controller.reconcile('demo_operation')
        recovery_calls = list(calls)
        first_effect = authority.get_event('demo_calendar', 'demo_event')
        next_intent = {**intent, 'intent_id': 'revoked_intent', 'expected_version': 1,
                       'start_utc': '2026-09-20T11:00:00Z', 'end_utc': '2026-09-20T11:30:00Z'}
        controller.register(next_intent)
        pending = admin('approve', intent=next_intent,
                        original_request_digest=intent_digest(next_intent), expires_at=DEADLINE)
        controller.reserve(next_intent['intent_id'], pending, 'revoked_operation')
        admin('revoke')
        rejected = controller.dispatch('revoked_operation')['status']
        final = authority.get_event('demo_calendar', 'demo_event')
        passed = (before == still_unknown == 'UNKNOWN' and recovered['status'] == 'CONFIRMED'
                  and recovery_calls == ['execute', 'get_receipt'] and rejected == 'REJECTED'
                  and final == first_effect and final['version'] == 1
                  and final['start_utc'] == intent['start_utc'] and final['end_utc'] == intent['end_utc']
                  and final['title'] == 'SYNTHETIC EVENT')
        report = {'status': 'PASS' if passed else 'FAIL', 'operation_before_recovery': before,
                  'operation_after_recovery': recovered['status'],
                  'recovery_transport_calls': recovery_calls, 'all_controller_transport_calls': calls,
                  'revoked_operation': rejected, 'final_event': final,
                  'synthetic_data': True, 'synthetic_clock': True, 'injected_response_loss': True,
                  'separate_os_identities': False, 'human_approval_performed': False,
                  'C1_T02_verified': False, 'external_effects': False}
        _write_private(out / 'controller-export.json', controller.export_state())
        _write_private(out / 'report.json', report)
        if not passed:
            raise RuntimeError('Durable control demo failed; inspect its private artifacts')
        return report
    finally:
        for receiver in receivers:
            receiver.close()
        for thread in threads:
            thread.join(timeout=3)
        for controller in controllers:
            controller.close()
        authority._db.close()
