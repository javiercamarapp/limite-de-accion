"""Durability and uncertainty tests; no claim of human identity or OS isolation."""
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest

from laboratorio.authority import LocalAuthority, intent_digest
from laboratorio.controller import DurableController

NOW = '2026-09-19T10:00:00Z'
DEADLINE = '2026-09-19T11:00:00Z'


def intent(n=1, event='event'):
    return dict(schema_version='C1.intent.v1', intent_id=f'intent_{n}',
                run_id='run', principal_id='agent', calendar_id='calendar',
                event_id=event, operation='RESCHEDULE_EVENT', expected_version=0,
                start_utc='2026-09-20T10:00:00Z', end_utc='2026-09-20T11:00:00Z')


@pytest.fixture
def lab(tmp_path):
    now = [NOW]
    authority = LocalAuthority(tmp_path / 'authority.db', clock=lambda: now[0])
    authority.create_event('calendar', 'event', '2026-09-20T08:00:00Z', '2026-09-20T09:00:00Z')
    calls, receipts, controllers = [], {}, []

    def transport(message):
        calls.append(message)
        p = message['params']
        if message['method'] == 'get_receipt':
            return {'ok': True, 'result': receipts.get(p['operation_id'])}
        try:
            r = authority.execute(**p, authenticated_principal='agent')
        except PermissionError:
            return {'ok': False, 'error': {'code': 'DENIED'}}
        receipts[p['operation_id']] = r
        return {'ok': True, 'result': r}

    def make(transport_fn=None, limit=4, deadline=DEADLINE):
        c = DurableController(tmp_path / 'controller.db', transport=transport_fn or transport,
                              deadline=deadline, max_operations=limit, clock=lambda: now[0])
        controllers.append(c)
        return c

    token = authority.approve(intent(), original_request_digest=intent_digest(intent()),
                              approver_id='external_admin', expires_at=DEADLINE)
    yield make, transport, calls, receipts, now, token, authority
    for c in controllers:
        c.close()
    authority._db.close()


def reserve(c, token='external_approval', n=1, op='op', event='event'):
    c.register(intent(n, event))
    return c.reserve(f'intent_{n}', token, op)


def test_register_reserve_no_transport_and_success(lab):
    make, transport, calls, _, _, token, _ = lab
    c = make()
    assert c.register(intent()) == 'intent_1'
    assert c.register(dict(reversed(list(intent().items())))) == 'intent_1'
    with pytest.raises(PermissionError):
        c.register({**intent(), 'event_id': 'changed'})
    assert c.reserve('intent_1', token, 'op')['status'] == 'RESERVED'
    assert calls == []
    def observing(message):
        with sqlite3.connect(c._path) as db:
            assert db.execute('SELECT status FROM operations').fetchone()[0] == 'DISPATCHING'
        return transport(message)
    c._transport = observing
    result = c.dispatch('op')
    assert result['status'] == 'CONFIRMED'
    assert result['receipt']['approval_id'] == token
    assert c.dispatch('op') == result
    assert len(calls) == 1
    assert calls[0] == {'method': 'execute', 'params': {'intent': intent(), 'approval_id': token, 'operation_id': 'op'}}
    before = c._db.total_changes
    json.dumps(c.export_state())
    assert c.get_operation('op') == result
    assert c._db.total_changes == before


def test_fabricated_approval_is_only_receiver_decision(lab):
    make, _, calls, _, _, _, authority = lab
    c = make()
    reserve(c)
    assert c.dispatch('op')['status'] == 'REJECTED'
    assert c.dispatch('op')['status'] == 'REJECTED'
    assert len(calls) == 1
    assert authority.get_event('calendar', 'event')['version'] == 0


@pytest.mark.parametrize('exc', [TimeoutError, RuntimeError, KeyboardInterrupt, SystemExit])
def test_lost_response_after_effect_and_readonly_recovery(lab, exc):
    make, transport, calls, _, now, token, authority = lab
    def lost(message):
        response = transport(message)
        if message['method'] == 'execute':
            raise exc('injected after commit')
        return response
    c = make(lost, limit=1)
    reserve(c, token)
    if issubclass(exc, (KeyboardInterrupt, SystemExit)):
        with pytest.raises(exc):
            c.dispatch('op')
    else:
        assert c.dispatch('op')['status'] == 'UNKNOWN'
    assert c.get_operation('op')['status'] == 'UNKNOWN'
    assert c.dispatch('op')['status'] == 'UNKNOWN'
    assert len(calls) == 1
    now[0] = DEADLINE
    assert c.reconcile('op')['status'] == 'CONFIRMED'
    assert [m['method'] for m in calls] == ['execute', 'get_receipt']
    assert authority.get_event('calendar', 'event')['version'] == 1


def test_absence_does_not_unlock_event(lab):
    make, _, _, _, _, _, _ = lab
    c = make(lambda m: {'ok': True, 'result': None})
    reserve(c)
    assert c.dispatch('op')['status'] == 'UNKNOWN'
    assert c.reconcile('op')['status'] == 'UNKNOWN'
    c.register(intent(2))
    with pytest.raises(PermissionError):
        c.reserve('intent_2', 'another', 'other')


def test_restart_limits_immutable_ids_and_proposal_bound(lab):
    make, _, _, _, _, _, _ = lab
    c = make(limit=1)
    first = reserve(c)
    assert c.reserve('intent_1', 'external_approval', 'op') == first
    for n in range(2, 5):
        c.register(intent(n, f'event_{n}'))
    with pytest.raises(PermissionError):
        c.register(intent(5))
    c.close()
    c = make(limit=1)
    assert c.reserve('intent_1', 'external_approval', 'op') == first
    with pytest.raises(PermissionError):
        c.reserve('intent_2', 'other', 'op_2')
    with pytest.raises(PermissionError):
        c.reserve('intent_2', 'other', 'op')
    for kw in ({'limit': 2}, {'limit': 1, 'deadline': '2026-09-19T12:00:00Z'}):
        with pytest.raises((ValueError, PermissionError)):
            make(**kw)


@pytest.mark.parametrize('patch', [{'expected_version': True}, {'score': 1}, {'principal_id': '../bad'}])
def test_invalid_intents(lab, patch):
    c = lab[0]()
    with pytest.raises(ValueError):
        c.register({**intent(), **patch})


@pytest.mark.parametrize('limit', [True, False, 0, 1001, 1.0])
def test_invalid_limits(lab, limit):
    with pytest.raises(ValueError):
        lab[0](limit=limit)


@pytest.mark.parametrize('patch', [
    {'version': True}, {'authority_epoch': True}, {'authority_epoch': -1},
    {'extra': 1}, {'operation_id': 'other'}, {'approval_id': 'other'},
    {'intent_digest': 'wrong'}, {'principal_id': 'other'}, {'calendar_id': 'other'},
    {'event_id': 'other'}, {'start_utc': NOW}, {'end_utc': NOW}, {'version': 2},
    {'applied_at': '2026-02-30T10:00:00Z'},
])
def test_bad_receipts_remain_unknown(lab, patch):
    make, transport, _, _, _, token, _ = lab
    def bad(m):
        response = transport(m)
        response['result'] = {**response['result'], **patch}
        return response
    c = make(bad)
    reserve(c, token)
    assert c.dispatch('op')['status'] == 'UNKNOWN'
    assert c.reconcile('op')['status'] == 'UNKNOWN'


@pytest.mark.parametrize('response,status', [
    ({'ok': False, 'error': {'code': 'INTERNAL_ERROR'}}, 'UNKNOWN'),
    ({'ok': False, 'error': {'code': 'INVALID_REQUEST'}}, 'REJECTED'),
    ({'ok': False, 'error': {'code': 'DENIED', 'extra': 1}}, 'UNKNOWN'),
    ({'ok': 1, 'result': {}}, 'UNKNOWN'), (None, 'UNKNOWN'),
    ({'ok': True, 'result': {}, 'extra': 1}, 'UNKNOWN'),
])
def test_protocol_ambiguity(lab, response, status):
    c = lab[0](lambda m: response)
    reserve(c)
    assert c.dispatch('op')['status'] == status


def test_backward_clock_is_durable_and_deadline_blocks(lab):
    make, _, calls, _, now, _, _ = lab
    c = make()
    reserve(c)
    now[0] = '2026-09-19T09:59:59Z'
    with pytest.raises(PermissionError):
        c.dispatch('op')
    now[0] = NOW
    c.close()
    c = make()
    with pytest.raises(PermissionError):
        c.dispatch('op')
    with pytest.raises(PermissionError):
        c.register(intent(2))
    assert c.get_operation('op')['status'] == 'RESERVED'
    assert calls == []


def test_expired_budget_still_allows_reads(lab):
    make, _, calls, _, now, _, _ = lab
    c = make()
    reserve(c)
    now[0] = DEADLINE
    with pytest.raises(PermissionError):
        c.dispatch('op')
    with pytest.raises(PermissionError):
        c.reserve('intent_1', 'other', 'other')
    assert c.reconcile('op')['status'] == 'RESERVED'
    assert calls == []


def test_existing_reservation_is_only_a_read_after_deadline(lab):
    make, _, calls, _, now, _, _ = lab
    c = make()
    original = reserve(c)
    now[0] = DEADLINE
    changes = c._db.total_changes
    assert c.reserve('intent_1', 'external_approval', 'op') == original
    assert c._db.total_changes == changes
    assert calls == []


def test_inflight_reopen_and_concurrent_dispatch_never_resend(lab):
    make, transport, calls, _, _, token, _ = lab
    entered, release = Event(), Event()
    def delayed(m):
        entered.set()
        assert release.wait(3)
        return transport(m)
    c = make(delayed)
    reserve(c, token)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(c.dispatch, 'op')
        try:
            assert entered.wait(3)
            assert c.dispatch('op')['status'] == 'DISPATCHING'
            other = make()
            assert other.get_operation('op')['status'] == 'UNKNOWN'
            assert other.dispatch('op')['status'] == 'UNKNOWN'
            assert other.reconcile('op')['status'] == 'UNKNOWN'
        finally:
            release.set()
        assert future.result()['status'] == 'CONFIRMED'
    assert sum(m['method'] == 'execute' for m in calls) == 1


def test_two_connections_serialize_event_and_approval_conflicts(lab):
    make = lab[0]
    c, d = make(), make()
    c.register(intent())
    c.register(intent(2))
    barrier = Barrier(2)
    def attempt(controller, n):
        barrier.wait(timeout=3)
        try:
            return controller.reserve(f'intent_{n}', f'approval_{n}', f'op_{n}')['status']
        except PermissionError:
            return 'CONFLICT'
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(attempt, c, 1), pool.submit(attempt, d, 2)]
        assert sorted(f.result() for f in futures) == ['CONFLICT', 'RESERVED']


def test_post_effect_persistence_failure_is_recoverable(lab):
    make, transport, _, _, _, token, authority = lab
    c = make()
    reserve(c, token)
    c._db.execute("CREATE TRIGGER fail_finish BEFORE UPDATE OF status ON operations WHEN NEW.status != 'DISPATCHING' BEGIN SELECT RAISE(ABORT, 'injected storage failure'); END")
    with pytest.raises(sqlite3.Error):
        c.dispatch('op')
    assert c.get_operation('op')['status'] == 'DISPATCHING'
    assert authority.get_event('calendar', 'event')['version'] == 1
    c._db.execute('DROP TRIGGER fail_finish')
    c.close()
    c = make()
    assert c.get_operation('op')['status'] == 'UNKNOWN'
    assert c.reconcile('op')['status'] == 'CONFIRMED'


def test_approval_and_intent_stay_unique_after_rejection(lab):
    c = lab[0]()
    reserve(c)
    assert c.dispatch('op')['status'] == 'REJECTED'
    c.register(intent(2, 'event_2'))
    with pytest.raises(PermissionError):
        c.reserve('intent_2', 'external_approval', 'op_2')
    with pytest.raises(PermissionError):
        c.reserve('intent_1', 'another_approval', 'op_3')
    assert c.reserve('intent_2', 'another_approval', 'op_4')['status'] == 'RESERVED'


def test_rejection_never_refunds_budget_on_restart(lab):
    make = lab[0]
    c = make(limit=1)
    reserve(c)
    assert c.dispatch('op')['status'] == 'REJECTED'
    c.register(intent(2))
    c.close()
    c = make(limit=1)
    with pytest.raises(PermissionError):
        c.reserve('intent_2', 'approval_2', 'op_2')
    assert c.reserve('intent_1', 'external_approval', 'op')['status'] == 'REJECTED'


def test_simultaneous_dispatch_on_independent_connections(lab):
    make, _, calls, _, _, token, authority = lab
    c, d = make(), make()
    reserve(c, token)
    barrier = Barrier(2)
    def dispatch(controller):
        barrier.wait(timeout=3)
        return controller.dispatch('op')['status']
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(dispatch, c), pool.submit(dispatch, d)]
        statuses = [f.result() for f in futures]
    assert 'CONFIRMED' in statuses
    assert set(statuses) <= {'CONFIRMED', 'DISPATCHING'}
    assert len(calls) == 1
    assert authority.get_event('calendar', 'event')['version'] == 1


@pytest.mark.parametrize('response', [None, {'ok': True, 'result': None},
    {'ok': False, 'error': {'code': 'DENIED'}},
    {'ok': False, 'error': {'code': 'INVALID_REQUEST'}},
    {'ok': False, 'error': {'code': 'INTERNAL_ERROR'}}])
def test_reconciliation_never_infers_no_effect_from_errors(lab, response):
    make, transport, calls, _, now, token, _ = lab
    def lost(m):
        transport(m)
        raise TimeoutError('response lost')
    c = make(lost)
    reserve(c, token)
    assert c.dispatch('op')['status'] == 'UNKNOWN'
    # El bloqueo de reloj tampoco impide recuperar evidencia de lectura.
    now[0] = '2026-09-19T09:00:00Z'
    with pytest.raises(PermissionError):
        c.register(intent(2))
    queries = []
    def read(m):
        queries.append(m)
        return response
    c._transport = read
    assert c.reconcile('op')['status'] == 'UNKNOWN'
    assert queries == [{'method': 'get_receipt', 'params': {'operation_id': 'op'}}]
    assert c.dispatch('op')['status'] == 'UNKNOWN'
    c._transport = transport
    assert c.reconcile('op')['status'] == 'CONFIRMED'
    assert sum(m['method'] == 'execute' for m in calls) == 1


def test_last_observation_survives_rejected_mutation(lab):
    make, _, _, _, now, _, _ = lab
    c = make()
    reserve(c)
    now[0] = '2026-09-19T10:20:00Z'
    with pytest.raises(PermissionError):
        c.register({**intent(), 'event_id': 'changed'})
    now[0] = '2026-09-19T10:10:00Z'
    with pytest.raises(PermissionError):
        c.dispatch('op')
    assert c.export_state()['metadata']['clock_blocked'] is True


def test_snapshot_and_identifiers_are_strict(lab):
    c = lab[0]()
    value = intent()
    c.register(value)
    value['principal_id'] = 'changed'
    c.reserve('intent_1', 'approval', 'op')
    state = c.export_state()
    assert state['intents'][0]['intent']['principal_id'] == 'agent'
    state['operations'][0]['status'] = 'CONFIRMED'
    assert c.get_operation('op')['status'] == 'RESERVED'
    for method, args in [(c.reserve, ('intent_1', True, 'op')),
                         (c.dispatch, (True,)), (c.reconcile, ('../op',)),
                         (c.get_operation, (False,))]:
        with pytest.raises(ValueError):
            method(*args)
