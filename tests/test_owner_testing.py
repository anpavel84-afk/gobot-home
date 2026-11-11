import asyncio,json,time,concurrent.futures,subprocess
from pathlib import Path
import pytest
from gobot.owner_testing import OwnerTesting,OwnerTestPolicy
from gobot.expert_store import ExpertBudget,ExpertPolicy
from gobot.expert_jobs import ExpertJobs
from test_realtime_native import configured,start,offer,command

def test_owner_panel_production_dom_no_automatic_provider_calls():
    result=subprocess.run(['node','tests/owner_test_ui.cjs'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stdout+result.stderr

def activate(m,b,*,limit=2):
    owner=m.owner_testing
    owner.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='synthetic-owner-full',allowed_client_id='client-1',expert_jobs_per_day=limit).model_dump_json())
    b.policy_path.write_text(b.policy().model_copy(update={'owner_full_test':True,'audience':'owner_interactive','allowed_client_id':'client-1',
        'allowed_models':['gpt-realtime-2.1-mini','gpt-realtime-2.1']}).model_dump_json())
    expert=ExpertBudget(b.root.parent/'realtime-experts')
    expert.policy_path.write_text(ExpertPolicy(enabled=True,authorization='synthetic-owner-full',audience='owner_interactive',owner_full_test=True,
        allowed_client_id='client-1',allowed_profiles=['ARGON_DEEP'],expires_at=None,max_sessions=None).model_dump_json())
    return owner,expert

def test_owner_budget_atomic_persistent_revocable_and_no_secret_status(tmp_path):
    owner=OwnerTesting(tmp_path);owner.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='SYNTHETIC_SECRET',allowed_client_id='owner',expert_jobs_per_day=3).model_dump_json())
    def reserve(n):
        try:owner.reserve('owner','expert',str(n));return True
        except PermissionError:return False
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:assert sum(pool.map(reserve,range(20)))==3
    assert OwnerTesting(tmp_path).status('owner')['attempts_today']['expert']==3
    assert not owner.status('other')['authorized']
    assert 'SYNTHETIC_SECRET' not in json.dumps(owner.status('owner'))
    owner.update('owner',{'expert_jobs_per_day':4});assert reserve(99)
    owner.update('owner',{'enabled':False});assert not owner.status('owner')['enabled']
    with pytest.raises(PermissionError):owner.reserve('owner','expert','disabled')
    owner.update('owner',{'enabled':True});assert owner.status('owner')['enabled']
    with pytest.raises(PermissionError):owner.update('other',{'api_estimate_usd_per_day':500})

def test_developer_acceptance_is_finite_separate_and_not_editable_by_ui(tmp_path):
    owner=OwnerTesting(tmp_path);owner.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='synthetic',allowed_client_id='owner',
        developer_acceptance_expires_at=time.time()+60,developer_realtime_limit=1).model_dump_json())
    key=owner.reserve('owner','realtime','first',estimate=.5,origin='developer');owner.settle(key,.01)
    with pytest.raises(PermissionError):owner.reserve('owner','realtime','second',origin='developer')
    owner.reserve('owner','realtime','manual-owner-use',origin='owner')
    assert owner.status('owner')['owner_vs_developer_attempts_today']=={'developer':1,'owner':1}
    with pytest.raises(ValueError):owner.update('owner',{'developer_realtime_limit':24})

def test_owner_model_noise_ack_and_guest_expert_without_private_authority(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);owner,expert=activate(m,b,limit=1)
        s=await start(m,offer(expert_quota_consent=True,requested_model='gpt-realtime-2.1',audio_preset='server_strength_half'))
        calls=[]
        async def execute(job):calls.append(job);return 'Результат: 42, с ограничениями.'
        s.experts=ExpertJobs(s,executor=execute,budget=expert,admission=lambda _: {'available':True})
        try:
            assert s.config['model']=='gpt-realtime-2.1' and s.config['audio']['input']['noise_reduction']['strength']==.5
            assert s.owner_test_authorized and not s.access.private_access and not s.expert_authorized
            turn=await s.new_turn(query='Спроси Argon: сравни две очереди')
            proposal=s.experts.propose(turn.query,'ARGON_DEEP',turn)
            job=await s.experts.start(proposal['proposal_id'],'call_real_fixture');await job.worker
            assert len(calls)==1 and not job.remember
            assert 'owner_expert_daily_limit' in s.experts.status()['blocked_reasons']
            assert owner.status('client-1')['attempts_today']['expert']==1
            owner.update('client-1',{'experts_enabled':False})
            assert not expert.policy().enabled
        finally:await m.shutdown()
    asyncio.run(run())

def test_full_model_not_allowed_never_silently_substitutes(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        with pytest.raises(PermissionError):await start(m,offer(requested_model='gpt-realtime-2.1'))
        assert not p.creations
        await m.shutdown()
    asyncio.run(run())

def test_owner_response_usage_reserved_once_and_model_priced(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);owner,_=activate(m,b)
        s=await start(m,offer(requested_model='gpt-realtime-2.1'))
        try:
            await command(s,'text',text='Синтетический короткий вопрос');await asyncio.sleep(.02)
            usage={'total_tokens':20,'input_token_details':{'audio_tokens':10},'output_token_details':{'audio_tokens':10}}
            event={'type':'response.done','response':{'id':'resp_1','status':'completed','usage':usage}}
            await s.handle(event);await s.handle(event)
            state=owner.status('client-1');assert state['attempts_today']['realtime']==1
            assert state['pending_usage']==0 and state['estimated_usd_including_pending_reserves']==.00096
        finally:await m.shutdown()
    asyncio.run(run())

def test_model_transition_transfers_only_heard_ram_context_same_scope(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);activate(m,b)
        s=await start(m);turn=await s.new_turn(query='Синтетическая тема Луны');turn.answer='Синтетический ответ';turn.stored=True
        await m.close(s.id,s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,'settings_changed')
        next_s=await start(m,offer().model_copy(update={'session_id':'app-2','requested_model':'gpt-realtime-2.1'}))
        try:assert 'Синтетическая тема Луны' in next_s.config['instructions']
        finally:await m.shutdown()
    asyncio.run(run())

def test_late_expert_audio_resets_playback_and_updates_only_heard_ram(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);s=await start(m)
        try:
            await command(s,'text',text='Синтетический вопрос');await asyncio.sleep(.02);turn=s.current
            async def play(ident,text):
                await s.handle({'type':'response.output_audio_transcript.delta','response_id':ident,'delta':text})
                await s.handle({'type':'output_audio_buffer.started','response_id':ident})
                await command(s,'playback_started',response_id=ident)
                await s.handle({'type':'response.done','response':{'id':ident,'status':'completed'}})
                await s.handle({'type':'output_audio_buffer.stopped','response_id':ident})
                await command(s,'playback_stopped',response_id=ident)
            await play('resp_1','Сначала краткий ответ. ');assert turn.stored
            await s.response();await asyncio.sleep(.02)
            assert turn.continuation and not turn.stored and not turn.client_stopped and not turn.drained
            await command(s,'playback_stopped',response_id='resp_1');assert not turn.client_stopped
            await play('resp_2','Теперь проверенный результат 42.');assert turn.stored
            row=m.brain.memory.transient[turn.id]
            assert 'результат 42' in row['result'] and len(s.turns)==1
            assert sum(e['type']=='turn_complete' for e in s.events)==2
        finally:await m.shutdown()
    asyncio.run(run())
