import json,time
import pytest
from gobot.board_wake_test import WakeTestBudget,prepare_policy

def admitted(tmp_path):
    path=prepare_policy(tmp_path,'board')
    p=json.loads(path.read_text());p.update(enabled=True,expires_at=time.time()+3600);path.write_text(json.dumps(p))
    return WakeTestBudget(tmp_path)

def test_preparation_is_disabled_and_does_not_renew_existing_decision(tmp_path):
    path=prepare_policy(tmp_path,'board');before=path.read_bytes()
    assert not json.loads(before)['enabled']
    assert prepare_policy(tmp_path,'other')==path and path.read_bytes()==before
    assert not (tmp_path/'mount.json').exists()

def test_exact_three_starts_persist_and_fourth_is_denied(tmp_path):
    budget=admitted(tmp_path)
    for i in range(3):budget.reserve_session('manual-'+str(i),True,'board')
    assert WakeTestBudget(tmp_path).board_status()['sessions_remaining']==0
    with pytest.raises(PermissionError):budget.reserve_session('fourth',True,'board')

def test_other_client_and_unbounded_expiry_do_not_reserve(tmp_path):
    budget=admitted(tmp_path)
    with pytest.raises(PermissionError):budget.reserve_session('phone',True,'other')
    assert budget.board_status()['sessions_remaining']==3
    p=json.loads(budget.policy_path.read_text());p['expires_at']=None;budget.policy_path.write_text(json.dumps(p))
    with pytest.raises(PermissionError):budget.reserve_session('unbounded',True,'board')
