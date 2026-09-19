import json
import pytest
from laboratorio.evaluation import loads_strict, make_cases, public_cases, evaluate


def test_strict_rejects_duplicate_keys():
    with pytest.raises(ValueError):
        loads_strict('{"id":"x","id":"y"}')

@pytest.mark.parametrize('text', ['NaN','Infinity','-Infinity','{"x":NaN}','1e999'])
def test_strict_rejects_nonfinite(text):
    with pytest.raises(ValueError): loads_strict(text)

def test_strict_preserves_normal_values():
    assert loads_strict('{"a":[1,null,false]}') == {'a':[1,None,False]}

def test_reproducible_benign_case_families():
    a=make_cases(17,3)
    assert a==make_cases(17,3)
    assert len(a)==15 and len({c['id'] for c in a})==15
    assert len({c['domain'] for c in a})==5
    assert a!=make_cases(18,3)

def test_public_export_has_no_answer_key():
    cases=make_cases(7,1);public=public_cases(cases)
    assert len(public)==5
    assert all(set(c)=={'id','domain','prompt'} for c in public)

def test_complete_exact_answers():
    cases=make_cases(1,2)
    out=evaluate(cases,[{'id':c['id'],'answer':c['expected']} for c in cases])
    assert out['coverage']==1 and out['accuracy']==1
    assert out['status']=='COMPLETE' and out['total']==10
    assert out['authorizes_actions'] is False
    assert out['claim_scope']=='ONLY_THESE_CASES_NOT_GENERAL_INTELLIGENCE'

def test_missing_answers_never_disappear_from_denominator():
    cases=make_cases(4,1)
    out=evaluate(cases,[{'id':cases[0]['id'],'answer':cases[0]['expected']}])
    assert out['total']==5 and out['correct']==1 and out['missing']==4
    assert out['accuracy']==0.2 and out['status']=='INCOMPLETE'

def test_duplicate_and_unknown_response_ids_rejected():
    c=make_cases(2,1)
    with pytest.raises(ValueError):evaluate(c,[{'id':c[0]['id'],'answer':0}]*2)
    with pytest.raises(ValueError):evaluate(c,[{'id':'not-a-case','answer':0}])

def test_bool_is_not_a_numeric_answer():
    c=[{'id':'n','domain':'math','prompt':'1','expected':1,'method':'numeric','tolerance':0}]
    assert evaluate(c,[{'id':'n','answer':True}])['correct']==0
    assert evaluate(c,[{'id':'n','answer':1.0}])['correct']==1

def test_exact_json_does_not_coerce_boolean_or_number():
    c=[{'id':'j','domain':'data','prompt':'x','expected':{'v':1},'method':'exact_json'}]
    assert evaluate(c,[{'id':'j','answer':{'v':True}}])['correct']==0

def test_model_status_fields_are_not_authority():
    c=make_cases(3,1)
    with pytest.raises(ValueError):evaluate(c,[{'id':c[0]['id'],'answer':0,'approved':True}])

def test_no_eval_of_model_code(tmp_path):
    p=tmp_path/'must-not-exist'
    c=[{'id':'x','domain':'data','prompt':'x','expected':0,'method':'exact_json'}]
    out=evaluate(c,[{'id':'x','answer':f"__import__('pathlib').Path({str(p)!r}).write_text('x')"}])
    assert out['correct']==0 and not p.exists()

def test_malformed_case_catalog_rejected():
    c=make_cases(1,1)
    with pytest.raises(ValueError):evaluate(c+[c[0]],[])
    with pytest.raises(ValueError):evaluate([],[])

def test_numeric_nonfinite_answer_rejected():
    c=make_cases(1,1)
    with pytest.raises(ValueError):evaluate(c,[{'id':c[0]['id'],'answer':float('nan')}])
