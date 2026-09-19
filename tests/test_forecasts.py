import pytest
from laboratorio.forecasts import score_binary_forecasts,rolling_naive_backtest

def fixture():
    f={'id':'f1','question':'¿Ocurre X antes del cierre?','probability':0.8,'issued_at':'2026-01-01T00:00:00Z','resolve_at':'2026-02-01T00:00:00Z','resolution_rule':'Sí si el registro público X informa el evento al cierre; si no, no.'}
    r={'id':'f1','outcome':True,'resolved_at':'2026-02-02T00:00:00Z','evidence_url':'https://example.org/registro'}
    return f,r

def test_brier_is_correct_and_pending_not_scored():
    f,r=fixture();pending={**f,'id':'f2','resolve_at':'2027-01-01T00:00:00Z'}
    out=score_binary_forecasts([f,pending],[r],'2026-03-01T00:00:00Z')
    assert out['resolved']==1 and out['pending']==1
    assert out['brier']==pytest.approx(0.04)
    assert out['baseline_brier']==0.25
    assert out['evidence_verified'] is False

def test_no_resolution_is_not_a_zero_error_forecast():
    f,_=fixture();out=score_binary_forecasts([f],[],'2026-03-01T00:00:00Z')
    assert out['brier'] is None and out['resolved']==0

@pytest.mark.parametrize('p',[True,float('nan'),float('inf'),-0.1,1.1,'0.8'])
def test_bad_probability_rejected(p):
    f,r=fixture();f['probability']=p
    with pytest.raises(ValueError):score_binary_forecasts([f],[r],'2026-03-01T00:00:00Z')

def test_backdating_logic_and_future_resolution_rejected():
    f,r=fixture()
    with pytest.raises(ValueError):score_binary_forecasts([{**f,'issued_at':f['resolve_at']}],[r],'2026-03-01T00:00:00Z')
    with pytest.raises(ValueError):score_binary_forecasts([f],[{**r,'resolved_at':'2027-01-01T00:00:00Z'}],'2026-03-01T00:00:00Z')
    with pytest.raises(ValueError):score_binary_forecasts([f],[{**r,'resolved_at':'2026-01-15T00:00:00Z'}],'2026-03-01T00:00:00Z')

def test_duplicate_and_unknown_resolution_rejected():
    f,r=fixture()
    with pytest.raises(ValueError):score_binary_forecasts([f,f],[r],'2026-03-01T00:00:00Z')
    with pytest.raises(ValueError):score_binary_forecasts([f],[r,r],'2026-03-01T00:00:00Z')
    with pytest.raises(ValueError):score_binary_forecasts([f],[{**r,'id':'unknown'}],'2026-03-01T00:00:00Z')

def test_naive_timestamps_and_nonbinary_outcomes_rejected():
    f,r=fixture()
    with pytest.raises(ValueError):score_binary_forecasts([{**f,'issued_at':'2026-01-01T00:00:00'}],[r],'2026-03-01T00:00:00Z')
    with pytest.raises(ValueError):score_binary_forecasts([f],[{**r,'outcome':1}],'2026-03-01T00:00:00Z')

def observations():return [{'date':f'2026-01-{i:02d}','value':i} for i in range(1,9)]

def test_naive_backtest_reference():
    out=rolling_naive_backtest(observations(),4,1,2)
    assert out['n']==4 and out['last_value_mae']==1 and out['seasonal_mae']==2
    assert out['prospective_validation'] is False
    assert out['horizon_units']=='observations'

def test_future_labels_do_not_change_earlier_predictions():
    obs=observations();a=rolling_naive_backtest(obs)
    obs[-1]['value']=9999;b=rolling_naive_backtest(obs)
    assert a['rows'][0]['last_value_prediction']==b['rows'][0]['last_value_prediction']
    assert a['rows'][0]['seasonal_prediction']==b['rows'][0]['seasonal_prediction']

def test_horizon_two_seasonal_reference():
    out=rolling_naive_backtest(observations(),4,2,2)
    assert out['n']==3 and out['last_value_mae']==2 and out['seasonal_mae']==2

@pytest.mark.parametrize('change',['duplicate','unordered','irregular','nan','boolean','insufficient'])
def test_bad_time_series_rejected(change):
    obs=observations()
    if change=='duplicate':obs[1]['date']=obs[0]['date']
    if change=='unordered':obs.reverse()
    if change=='irregular':obs[-1]['date']='2026-01-10'
    if change=='nan':obs[-1]['value']=float('nan')
    if change=='boolean':obs[-1]['value']=True
    if change=='insufficient':obs=obs[:3]
    with pytest.raises(ValueError):rolling_naive_backtest(obs)
