"""Reconciliation queries cannot replay an effect or read another principal."""
import pytest

from test_authority import setup, approve, execute
from test_unix_transport import lab, running, message
from laboratorio.unix_transport import request
from laboratorio.authority import intent_digest


def test_receipt_query_is_readonly_and_scoped(tmp_path):
    authority, intent, _, _ = setup(tmp_path)
    assert authority.get_receipt('missing', authenticated_principal='agent_demo') is None
    token = approve(authority, intent)
    expected = execute(authority, intent, token)
    changes = authority._db.total_changes
    assert authority.get_receipt('operation_1', authenticated_principal='agent_demo') == expected
    assert authority.get_receipt('operation_1', authenticated_principal='other_agent') is None
    assert authority._db.total_changes == changes
    assert authority.get_event(intent['calendar_id'], intent['event_id'])['version'] == 4


@pytest.mark.parametrize('operation,actor', [(True, 'agent_demo'), ('op', True), ('../bad', 'agent_demo')])
def test_receipt_query_validates_identifiers(tmp_path, operation, actor):
    authority, _, _, _ = setup(tmp_path)
    with pytest.raises(ValueError):
        authority.get_receipt(operation, authenticated_principal=actor)


def test_unix_receipt_query_cannot_mutate_or_impersonate(lab):
    _, authority, intent = lab
    with running(lab) as (_, admin), running(lab, 'dispatcher') as (_, dispatcher):
        assert request(dispatcher, message('get_receipt', operation_id='missing')) == {'ok': True, 'result': None}
        token = request(admin, message('approve', intent=intent, original_request_digest=intent_digest(intent),
                                      expires_at='2026-09-19T11:00:00Z'))['result']
        original = request(dispatcher, message('execute', intent=intent, approval_id=token, operation_id='query_op'))
        changes = authority._db.total_changes
        assert request(dispatcher, message('get_receipt', operation_id='query_op')) == original
        assert request(admin, message('get_receipt', operation_id='query_op'))['ok'] is False
        assert request(dispatcher, message('get_receipt', operation_id='query_op', principal_id='other'))['ok'] is False
        assert authority._db.total_changes == changes
