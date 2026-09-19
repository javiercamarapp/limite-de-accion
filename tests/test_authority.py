import json
from pathlib import Path
import pytest
from laboratorio.authority import LocalAuthority,intent_digest

VECTOR=json.loads((Path(__file__).resolve().parents[1]/'contracts/vector-canonico.json').read_text())

def setup(tmp_path):
    clock=['2026-09-19T10:00:00Z'];db=tmp_path/'demo.sqlite3'
    a=LocalAuthority(db,clock=lambda:clock[0]);i=dict(VECTOR['input'])
    a.create_event(i['calendar_id'],i['event_id'],'2026-09-20T08:00:00Z','2026-09-20T08:30:00Z',title='No cambiar',version=3)
    return a,i,clock,db

def approve(a,i):
    return a.approve(i,original_request_digest=intent_digest(i),approver_id='human_demo',expires_at='2026-09-19T11:00:00Z')

def execute(a,i,token,op='operation_1',actor='agent_demo'):
    return a.execute(i,approval_id=token,operation_id=op,authenticated_principal=actor)

def test_exact_c1_digest_vector():assert intent_digest(VECTOR['input'])==VECTOR['intent_digest']

@pytest.mark.parametrize('patch',[{'approved':True},{'expected_version':True},{'operation':'DELETE_EVENT'},{'end_utc':'2026-09-20T09:00:00Z'},{'start_utc':'2026-02-30T10:00:00Z'},{'calendar_id':'../../other'},{'start_utc':'2026-09-20T10:00:00+00:00'}])
def test_intent_semantics_fail_closed(patch):
    with pytest.raises(ValueError):intent_digest({**VECTOR['input'],**patch})

def test_effect_exactly_once_and_only_approved_fields(tmp_path):
    a,i,_,_=setup(tmp_path);token=approve(a,i)
    receipt=execute(a,i,token);again=execute(a,i,token)
    assert receipt==again
    event=a.get_event(i['calendar_id'],i['event_id'])
    assert event['version']==4 and event['title']=='No cambiar'
    assert event['start_utc']==i['start_utc'] and event['end_utc']==i['end_utc']
    with pytest.raises(PermissionError):execute(a,i,token,'operation_2')

def test_forgery_or_wrong_actor_denied(tmp_path):
    a,i,_,_=setup(tmp_path);token=approve(a,i)
    with pytest.raises(PermissionError):execute(a,i,'made_up_approval')
    with pytest.raises(PermissionError):execute(a,i,token,actor='other_agent')
    assert a.get_event(i['calendar_id'],i['event_id'])['version']==3

def test_content_change_and_operation_id_collision_denied(tmp_path):
    a,i,_,_=setup(tmp_path);token=approve(a,i)
    with pytest.raises(PermissionError):execute(a,{**i,'start_utc':'2026-09-20T10:05:00Z'},token)
    execute(a,i,token)
    with pytest.raises(PermissionError):execute(a,{**i,'intent_id':'other_intent'},token)

def test_original_request_binding(tmp_path):
    a,i,_,_=setup(tmp_path)
    with pytest.raises(PermissionError):a.approve(i,original_request_digest=intent_digest({**i,'start_utc':'2026-09-20T10:05:00Z'}),approver_id='human_demo',expires_at='2026-09-19T11:00:00Z')

def test_expiration_and_revocation(tmp_path):
    a,i,clock,_=setup(tmp_path);token=approve(a,i)
    clock[0]='2026-09-19T11:00:00Z'
    with pytest.raises(PermissionError):execute(a,i,token)
    clock[0]='2026-09-19T10:00:00Z';new=approve(a,i);a.revoke_all()
    with pytest.raises(PermissionError):execute(a,i,new)

def test_version_conflict_not_last_writer_wins(tmp_path):
    a,i,_,_=setup(tmp_path);a1=approve(a,i);a2=approve(a,{**i,'intent_id':'intent_2'})
    execute(a,i,a1)
    with pytest.raises(PermissionError):execute(a,{**i,'intent_id':'intent_2'},a2,'operation_2')
    assert a.get_event(i['calendar_id'],i['event_id'])['version']==4

def test_recovery_after_response_loss(tmp_path):
    a,i,clock,db=setup(tmp_path);token=approve(a,i);before=execute(a,i,token)
    a=LocalAuthority(db,clock=lambda:clock[0]);after=execute(a,i,token)
    assert before==after and a.get_event(i['calendar_id'],i['event_id'])['version']==4

def test_prior_receipt_after_revocation_is_not_new_effect(tmp_path):
    a,i,_,_=setup(tmp_path);token=approve(a,i);r=execute(a,i,token);a.revoke_all()
    assert execute(a,i,token)==r
    assert a.get_event(i['calendar_id'],i['event_id'])['version']==4

def test_missing_resource_denied(tmp_path):
    a,i,_,_=setup(tmp_path);i['event_id']='not_existing'
    with pytest.raises((ValueError,PermissionError)):approve(a,i)
