"""Offline administrative recovery: no provider/network/firmware operations."""
import asyncio,time
from concurrent.futures import ThreadPoolExecutor
import pytest
from gobot.live_budget import LiveBudget
from gobot.owner_testing import OwnerTesting,OwnerTestPolicy,HardwareVoiceGrant

EVIDENCE=dict(gateway_idle=True,brain_idle=True,old_relay_absent=True)

def setup(tmp_path, sessions=8):
    owner=OwnerTesting(tmp_path/'owner')
    owner.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='fixture',allowed_client_id='owner',
        live_enabled=True,hardware_voice=HardwareVoiceGrant(client_id='board',grant_id='a'*32,sessions=sessions,
            session_seconds=60,backend_calls=0,estimate_usd=2.5)).model_dump_json())
    budget=LiveBudget(tmp_path/'live',owner)
    from test_live import offer
    old=offer().model_copy(update={'session_id':'old','client_id':'board','device_id':'board',
        'conversation_mode':'unified','expert_quota_consent':False})
    budget.reserve(old);budget.registered('old','provider-old');budget.observe('old',15)
    budget.cleanup_claim('old')
    return budget,old

def approve(budget,old,**kwargs):
    scope=budget.scope(old)
    budget.recovery.orphan(old.session_id,scope,local_evidence=EVIDENCE)
    return budget.recovery.approve(old.session_id,scope,owner_binding='owner',risk_ack=True,
        expires_at=time.time()+300,**kwargs)

def row(budget):
    with budget.connect() as db:return db.execute('SELECT * FROM calls WHERE id="old"').fetchone()

def test_orphan_and_approval_preserve_original_ledger_and_usage(tmp_path):
    b,old=setup(tmp_path);before=row(b);approve(b,old)
    assert row(b)==before
    assert b.status()['unconfirmed_sessions']==1
    assert b.status()['administrative_recovery']=={'orphaned_unconfirmed':1,'provider_confirmation_inferred':False}
    assert not b.recovery.orphan('old',b.scope(old),local_evidence=EVIDENCE)
    assert b.recovery.may_resume('old',b.scope(old))
    with pytest.raises(ValueError,match='already_active'):approve(b,old)
    with b.owner.connect() as db:assert db.execute('SELECT count(*),sum(cost),sum(pending) FROM attempts').fetchone()==(1,.05,1)

@pytest.mark.parametrize('missing',list(EVIDENCE))
def test_local_cleanup_is_required(tmp_path,missing):
    b,old=setup(tmp_path)
    with pytest.raises(ValueError,match='local_cleanup'):b.recovery.orphan('old',b.scope(old),local_evidence={**EVIDENCE,missing:False})
    with pytest.raises(ValueError,match='local_cleanup'):b.recovery.approve('old',b.scope(old),owner_binding='owner',risk_ack=True,expires_at=time.time()+30)

@pytest.mark.parametrize('patch',[{'owner_binding':'board'},{'risk_ack':False},{'max_new_sessions':0},
    {'max_new_sessions':True},{'expires_at':0},{'expires_at':float('nan')},{'expires_at':time.time()+90000}])
def test_invalid_owner_ack_or_bounds_denied(tmp_path,patch):
    b,old=setup(tmp_path);b.recovery.orphan('old',b.scope(old),local_evidence=EVIDENCE)
    args=dict(owner_binding='owner',risk_ack=True,expires_at=time.time()+300,max_new_sessions=1);args.update(patch)
    with pytest.raises((ValueError,PermissionError)):b.recovery.approve('old',b.scope(old),**args)

def test_atomic_consumption_and_existing_budget_are_preserved(tmp_path):
    b,old=setup(tmp_path);approve(b,old)
    new=old.model_copy(update={'session_id':'new'})
    assert b.reserve(new,resume_from=['old'])==60
    assert not b.recovery.may_resume('old',b.scope(old))
    with pytest.raises(PermissionError,match='exhausted'):b.reserve(old.model_copy(update={'session_id':'another'}),resume_from=['old'])
    assert row(b)[6]==0
    # A real terminal confirmation can still settle the original, with recovery history retained.
    b.observe('old',19,final=True,reason='close_requested')
    assert row(b)[6]==1
    with b.connect() as db:assert db.execute('SELECT count(*) FROM recovery_events WHERE session="old"').fetchone()[0]==3

def test_scope_expiry_and_quota_failure_do_not_consume_allowance(tmp_path):
    b,old=setup(tmp_path,sessions=1);approve(b,old)
    with pytest.raises(PermissionError):b.reserve(old.model_copy(update={'session_id':'wrong','client_id':'other'}),resume_from=['old'])
    with pytest.raises(PermissionError,match='hardware_voice_limit'):b.reserve(old.model_copy(update={'session_id':'overquota'}),resume_from=['old'])
    assert b.recovery.may_resume('old',b.scope(old))
    with b.connect() as db:db.execute('UPDATE resume_approvals SET expires=0')
    assert not b.recovery.may_resume('old',b.scope(old))

def test_concurrent_starts_consume_one_administrative_admission(tmp_path):
    b,old=setup(tmp_path);approve(b,old)
    def attempt(i):
        try:b.reserve(old.model_copy(update={'session_id':f'new-{i}'}),resume_from=['old']);return True
        except PermissionError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:assert sum(pool.map(attempt,range(2)))==1

def test_owner_rebinding_invalidates_approval(tmp_path):
    b,old=setup(tmp_path);approve(b,old)
    b.owner.policy_path.write_text(b.owner.policy().model_copy(update={'allowed_client_id':'new-owner'}).model_dump_json())
    assert not b.recovery.may_resume('old',b.scope(old))

def test_unknown_financial_reserve_survives_utc_rollover_and_recovery(tmp_path):
    b,old=setup(tmp_path)
    with b.connect() as db:db.execute('UPDATE calls SET day=day-1')
    approve(b,old)
    status=b.status()
    assert status['voice_seconds_observed']==0 and status['unconfirmed_sessions']==1
    assert status['unknown_final_usage_reserve_seconds']==60
    assert status['unknown_final_usage_reserve_estimated_usd']==.05
    assert status['pending_seconds_observed_all_days']==15
    b.reserve(old.model_copy(update={'session_id':'one-manual-test'}),resume_from=['old'])
    assert b.status()['unknown_final_usage_reserve_seconds']==120
    with b.owner.connect() as db:
        assert db.execute('SELECT sum(cost),sum(pending) FROM attempts').fetchone()==(.1,2)

def test_readiness_distinguishes_approved_orphan_from_final_usage(tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    import httpx
    from gobot.live_api import attach_brain_live
    b,old=setup(tmp_path)
    manager=SimpleNamespace(budget=b,owner_testing=b.owner,sessions={})
    app=FastAPI();attach_brain_live(app,manager,lambda:None)
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            first=(await client.get('/api/v1/live/status',params={'binding':'board'})).json()
            assert not first['enabled'] and first['blocking_previous_sessions']==1
            approve(b,old)
            resumed=(await client.get('/api/v1/live/status',params={'binding':'board'})).json()
            assert resumed['enabled'] and resumed['blocking_previous_sessions']==0
            assert resumed['unresolved_previous_sessions']==1 and resumed['billing']['unconfirmed_sessions']==1
            generic=(await client.get('/api/v1/live/status')).json()
            assert not generic['enabled']
    asyncio.run(run())

def test_manager_503_no_ack_requires_admin_and_uses_new_session(tmp_path,settings):
    from test_live import Provider,offer
    from test_realtime_native import configured
    from gobot.live import LiveManager
    from gobot.device_contract import DeviceProfile
    async def run():
        rt,_,_=configured(tmp_path,settings)
        rt.owner_testing.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='fixture',allowed_client_id='client-1',live_enabled=True).model_dump_json())
        class FailedCleanup(Provider):
            async def cleanup(self,ident):self.cleanup_calls.append(ident);raise RuntimeError('HTTP 503')
        p=FailedCleanup();m=LiveManager(rt,provider=p);rt.live=m
        old=offer();m.budget.reserve(old);m.budget.registered(old.session_id,'orphan-provider')
        new=old.model_copy(update={'session_id':'fresh'})
        try:
            for _ in range(2):
                with pytest.raises(RuntimeError,match='previous_finalization_unconfirmed'):await m.start(new,DeviceProfile())
            assert p.cleanup_calls==['orphan-provider'] and not p.creations
            scope=m.budget.scope(old)
            m.budget.recovery.orphan(old.session_id,scope,local_evidence=EVIDENCE)
            m.budget.recovery.approve(old.session_id,scope,owner_binding='client-1',risk_ack=True,expires_at=time.time()+300)
            m.touch_context=('never_replay',)
            s,_=await m.start(new,DeviceProfile())
            assert s.id=='fresh' and s.provider_id!='orphan-provider'
            assert s.offer.conversation_id!=old.conversation_id and not s.operations and not s.turns
            assert m.touch_context is None and p.cleanup_calls==['orphan-provider']
            assert m.budget.status()['unconfirmed_sessions']==2
        finally:await m.shutdown();await rt.shutdown()
    asyncio.run(run())
