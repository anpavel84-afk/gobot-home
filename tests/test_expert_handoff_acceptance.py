"""Native/CLI handoff acceptance with real Brain components and synthetic transports."""
import asyncio,json,time,subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_realtime_native import configured,start,offer,command,tick
from gobot.expert_jobs import ExpertJobs,profile_in_text
from gobot.expert_store import ExpertBudget,ExpertPolicy,ExpertStore

@pytest.fixture(autouse=True)
def synthetic_codex_catalog(monkeypatch):
    import gobot.expert_jobs as jobs
    from gobot.expert_profiles import resolve_profile
    rows=[{'slug':'gpt-6.1-sol','supported_reasoning_levels':[{'effort':'high'},{'effort':'xhigh'}]},
          {'slug':'gpt-6-astra','supported_reasoning_levels':[{'effort':'medium'},{'effort':'high'}]}]
    monkeypatch.setattr(jobs,'resolve_profile',lambda name:resolve_profile(name,codex_metadata=rows))

async def native(tmp_path,settings,*,remember=True,executor=None):
    m,p,b=configured(tmp_path,settings)
    b.policy_path.write_text(b.policy().model_copy(update={'expert_jobs_allowed':True}).model_dump_json(),encoding='utf-8')
    family=m.identity.family;ident=family.create('Synthetic adult','adult','synthetic-test-pin')['id']
    actor=family.verify_pin(ident,'synthetic-test-pin')
    req=offer().model_copy(update={'device_id':'personal:'+ident,'confirmed_profile_epoch':actor['epoch'],
        'personalization_mode':'confirmed_profile','expert_quota_consent':True,'remember':remember})
    s=await start(m,req);budget=ExpertBudget(tmp_path/'expert-budget')
    policy=ExpertPolicy(enabled=True,authorization='synthetic-expert-grant',expires_at=time.time()+120,max_sessions=1,
        allowed_client_id='client-1',allowed_profiles=['SOL_HIGH','ASTRA_MEDIUM'],max_result_characters=1000)
    budget.policy_path.write_text(policy.model_dump_json(),encoding='utf-8')
    calls=[]
    async def fake(job):calls.append(job.profile);return await executor(job) if executor else 'Вывод: 42. Это оценка, а не измеренный факт.'
    s.experts=ExpertJobs(s,executor=fake,budget=budget,admission=lambda profile:{'available':True})
    return m,p,b,s,budget,actor,calls

async def propose(s):
    turn=await s.new_turn(query='Сравни две синтетические архитектуры')
    return s.experts.propose(turn.query,'SOL_HIGH',turn)

async def consent(s):
    turn=await s.new_turn(query='Да, Sol High');return turn

async def wait_for(predicate):
    for _ in range(100):
        if predicate():return
        await asyncio.sleep(.01)
    assert predicate()

def test_late_voice_consent_one_cli_one_original_call_output_same_voice(tmp_path,settings):
    async def run():
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings)
        try:
            proposal=await propose(s);turn=await s.new_turn('late-audio-confirmation')
            task=asyncio.create_task(s.tool('call_delayed','expert_start',json.dumps({'proposal_id':proposal['proposal_id']}),turn))
            await tick();assert calls==[] and budget.status()['sessions_reserved']==0
            await s.input_text(turn,'Да, Sol High');await task
            job=s.experts.pending;await job.worker
            assert len(calls)==1 and calls[0]['model']=='gpt-6.1-sol' and calls[0]['effort']=='high'
            outputs=[e['item'] for e in s.ws.sent if e['type']=='conversation.item.create' and e['item'].get('call_id')=='call_delayed']
            assert len(outputs)==1 and json.loads(outputs[0]['output'])['accepted'] is True
            notices=[json.loads(e['item']['content'][0]['text']) for e in s.ws.sent if e.get('item',{}).get('role')=='user' and 'expert_job_completed' in str(e['item'].get('content'))]
            assert len(notices)==1 and notices[0]['data']['result']['numbers']==['42']
            assert len(p.creations)==1 and s.config['audio']['output']['voice']=='marin'
            assert await s.experts.start(proposal['proposal_id'],'call_delayed') is job
            with pytest.raises(ValueError):await s.experts.start(proposal['proposal_id'],'another-call')
        finally:await m.shutdown()
    asyncio.run(run())

@pytest.mark.parametrize('reply',['Нет, спасибо','Нет','Да, но сравни только один вариант'])
def test_late_refusal_or_scope_amendment_never_executes(tmp_path,settings,reply):
    async def run():
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings)
        try:
            proposal=await propose(s);turn=await s.new_turn('audio-refusal')
            task=asyncio.create_task(s.tool('call_refusal','expert_start',json.dumps({'proposal_id':proposal['proposal_id']}),turn))
            await tick();await s.input_text(turn,reply);await task
            assert not calls and budget.status()['sessions_reserved']==0 and not s.closed
        finally:await m.shutdown()
    asyncio.run(run())

def test_new_question_keeps_result_card_and_profile_scoped_durable_result(tmp_path,settings):
    async def run():
        gate=asyncio.Event()
        async def work(job):await gate.wait();return 'Результат 17 с оговоркой о точности.'
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings,executor=work)
        try:
            proposal=await propose(s);await consent(s);job=await s.experts.start(proposal['proposal_id'],'call_saved')
            await wait_for(lambda:job.state=='running')
            await s.new_turn(query='Расскажи про другую тему');gate.set();await job.worker
            event=next(e for e in s.events if e['type']=='expert_result')
            assert event['data']['voice_deferred'] is True and event['data']['result']['numbers']==['17']
            out=next(e['item'] for e in s.ws.sent if e.get('item',{}).get('call_id')=='call_saved')
            assert 'result' not in json.loads(out['output'])
            saved=m.expert_store.list(actor['id'],actor['epoch'],'conv-1')
            assert len(saved)==1 and saved[0]['result']['numbers']==['17']
            another=m.identity.family.create('Other synthetic adult','adult','other-test-pin')['id']
            other=m.identity.family.verify_pin(another,'other-test-pin')
            assert m.expert_store.list(other['id'],other['epoch'],'conv-1')==[]
        finally:await m.shutdown()
        # Read survives provider/session close, never re-launches the executor.
        restored=ExpertStore(m.brain.memory,m.identity.family)
        assert restored.list(actor['id'],actor['epoch'],'conv-1')[0]['state']=='completed'
        assert len(calls)==1
    asyncio.run(run())

def test_remember_false_never_persists_expert_text(tmp_path,settings):
    async def run():
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings,remember=False)
        try:
            proposal=await propose(s);await consent(s);job=await s.experts.start(proposal['proposal_id'],'call_ram');await job.worker
            assert job.result and not m.expert_store.list(actor['id'],actor['epoch'])
            with m.brain.memory.connect() as c:assert c.execute('SELECT count(*) FROM expert_results').fetchone()[0]==0
        finally:await m.shutdown()
    asyncio.run(run())

@pytest.mark.parametrize('failure',[RuntimeError,TimeoutError])
def test_expert_failure_does_not_close_native_conversation(tmp_path,settings,failure):
    async def run():
        async def work(job):raise failure('synthetic secret must not enter error status')
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings,executor=work)
        try:
            proposal=await propose(s);await consent(s);job=await s.experts.start(proposal['proposal_id'],'call_error');await job.worker
            assert job.state in {'failed','timed_out'} and not s.closed and len(calls)==1
            assert 'synthetic secret' not in json.dumps(s.events)
            assert sum(e.get('item',{}).get('call_id')=='call_error' for e in s.ws.sent)==1
        finally:await m.shutdown()
    asyncio.run(run())

def test_followup_closes_mic_but_keeps_agreed_expert_job(tmp_path,settings):
    async def run():
        gate=asyncio.Event()
        async def work(job):await gate.wait();return 'Вывод: 2.'
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings,executor=work)
        try:
            proposal=await propose(s);await consent(s);job=await s.experts.start(proposal['proposal_id'],'call_wait')
            await wait_for(lambda:job.state=='running')
            s.followup_deadline=time.monotonic()-1;s.last_activity=time.monotonic()-100
            await wait_for(lambda:any(e['type']=='followup_closed' for e in s.events))
            assert not s.closed and s.input_mode=='waiting_expert' and job.state=='running'
            gate.set();await job.worker;assert job.state=='completed'
        finally:await m.shutdown()
    asyncio.run(run())

def test_expired_or_wrong_profile_quota_and_model_selection_fail_closed(tmp_path,settings):
    async def run():
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings)
        try:
            turn=await s.new_turn(query='Спроси Sol High: сравни варианты')
            with pytest.raises(ValueError):s.experts.propose(turn.query,'ASTRA_MEDIUM',turn)
            proposal=s.experts.propose(turn.query,'SOL_HIGH',turn)
            budget.policy_path.write_text(budget.policy().model_copy(update={'allowed_profiles':['ASTRA_MEDIUM']}).model_dump_json(),encoding='utf-8')
            with pytest.raises(PermissionError):await s.experts.start(proposal['proposal_id'],'call_wrong_profile')
            assert not calls and budget.status()['sessions_reserved']==0
            budget.policy_path.write_text(budget.policy().model_copy(update={'allowed_profiles':['SOL_HIGH'],'expires_at':time.time()-1}).model_dump_json(),encoding='utf-8')
            with pytest.raises(PermissionError):await s.experts.start(proposal['proposal_id'],'call_expired')
            assert not calls
        finally:await m.shutdown()
    asyncio.run(run())

def test_job_deletion_and_profile_epoch_revoke_private_result(tmp_path,settings):
    async def run():
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings)
        try:
            proposal=await propose(s);await consent(s);job=await s.experts.start(proposal['proposal_id'],'call_delete');await job.worker
            assert len(m.expert_store.list(actor['id'],actor['epoch']))==1
            with m.brain.memory.connect() as c:c.execute("UPDATE family_profiles SET epoch='new-epoch' WHERE id=?",(actor['id'],))
            with pytest.raises(PermissionError):m.expert_store.list(actor['id'],actor['epoch'])
            assert m.expert_store.list(actor['id'],'new-epoch')==[]
            m.identity.family.delete(actor['id'])
            with m.brain.memory.connect() as c:assert c.execute('SELECT count(*) FROM expert_results').fetchone()[0]==0
        finally:await m.shutdown()
    asyncio.run(run())

@pytest.mark.parametrize('text,expected',[('спроси Sol High','SOL_HIGH'),('Sol Extra High','SOL_XHIGH'),('Астра медиум','ASTRA_MEDIUM'),('Astra High','ASTRA_HIGH'),('Argon','ARGON_DEEP'),('Gemini 1',None)])
def test_profiles_are_exact_and_unknown_label_is_not_silently_substituted(text,expected):
    assert profile_in_text(text)==expected

def test_expert_policy_requires_real_scoped_finite_admission():
    with pytest.raises(ValueError):ExpertPolicy(enabled=True,authorization='not-enough')
    with pytest.raises(ValueError):ExpertPolicy(enabled=True,authorization='not-enough',allowed_client_id='client',allowed_profiles=['SOL_HIGH'],max_sessions=None)

def test_expert_browser_panel_production_dom():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run(['node','tests/expert_ui.cjs'],cwd=root,capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr

def test_cancellation_budget_exhaustion_and_profile_switch_never_relaunch(tmp_path,settings):
    async def run():
        started=asyncio.Event()
        async def work(job):started.set();await asyncio.sleep(60)
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings,executor=work)
        try:
            proposal=await propose(s);await consent(s);job=await s.experts.start(proposal['proposal_id'],'call_cancelled');await started.wait()
            await s.experts.cancel(job.id)
            assert job.state=='cancelled' and not job.result and len(calls)==1
            proposal=await propose(s);await consent(s)
            with pytest.raises(PermissionError):await s.experts.start(proposal['proposal_id'],'call_exhausted')
            assert len(calls)==1 and not s.closed
            from dataclasses import replace
            s.access=replace(s.access,effective_scope='different-owner',confirmed_profile_id='different-profile')
            with pytest.raises(ValueError):await s.experts.start(proposal['proposal_id'],'call_foreign')
        finally:await m.shutdown()
    asyncio.run(run())

def test_expert_status_exposes_blockers_without_private_results_to_guest(tmp_path,settings):
    async def run():
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings)
        try:
            proposal=await propose(s);await consent(s);job=await s.experts.start(proposal['proposal_id'],'call_status');await job.worker
            guest=m.expert_status('browser-1','client-1',None)
            assert 'confirmed_adult_profile_required' in guest['blocked_reasons'] and guest['saved_jobs']==[]
            assert 'Вывод' not in json.dumps(guest,ensure_ascii=False)
            own=m.expert_status(s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,actor['epoch'],'conv-1')
            assert own['saved_jobs'][0]['result']['numbers']==['42']
            wrong=m.expert_status(s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,'wrong-epoch','conv-1')
            assert wrong['saved_jobs']==[] and not wrong['confirmed_adult']
        finally:await m.shutdown()
    asyncio.run(run())

def test_explicit_request_confirmation_is_not_reusable_in_same_turn(tmp_path,settings):
    async def run():
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings)
        try:
            budget.policy_path.write_text(budget.policy().model_copy(update={'max_sessions':2}).model_dump_json(),encoding='utf-8')
            turn=await s.new_turn(query='Спроси Sol High: сравни два варианта')
            first=s.experts.propose(turn.query,'SOL_HIGH',turn);job=await s.experts.start(first['proposal_id'],'call_first');await job.worker
            again=s.experts.propose(turn.query,'SOL_HIGH',turn)
            with pytest.raises(PermissionError):await s.experts.start(again['proposal_id'],'call_again')
            assert len(calls)==1 and budget.status()['sessions_reserved']==1
        finally:await m.shutdown()
    asyncio.run(run())

def test_child_profile_cannot_get_expert_or_adult_saved_results(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);family=m.identity.family
        ident=family.create('Synthetic child','child','synthetic-child-pin')['id'];actor=family.verify_pin(ident,'synthetic-child-pin')
        b.policy_path.write_text(b.policy().model_copy(update={'expert_jobs_allowed':True}).model_dump_json(),encoding='utf-8')
        s=await start(m,offer().model_copy(update={'device_id':'personal:'+ident,'confirmed_profile_epoch':actor['epoch'],'personalization_mode':'confirmed_profile','expert_quota_consent':True}))
        try:
            proposal=await propose(s);await consent(s)
            with pytest.raises(PermissionError):await s.experts.start(proposal['proposal_id'],'call_child')
            with pytest.raises(PermissionError):m.expert_store.list(actor['id'],actor['epoch'])
            assert not s.expert_authorized
        finally:await m.shutdown()
    asyncio.run(run())

def test_expert_packet_contains_explained_text_but_not_another_profile_archive(tmp_path,settings):
    async def run():
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings)
        try:
            m.brain.memory.add_fact('personal:someone-else','PRIVATE_OTHER_FAMILY_CANARY',True)
            turn=await s.new_turn(query='Сравни архитектуры');turn.answer='Уже объяснённая моделью часть, число 17.'
            proposal=s.experts.propose(turn.query,'SOL_HIGH',turn);await consent(s)
            job=await s.experts.start(proposal['proposal_id'],'call_packet');await job.worker
            from gobot.context_manager import serialize_context,tokens
            text=serialize_context(job.task,job.packet)
            assert 'PRIVATE_OTHER_FAMILY_CANARY' not in text and 'число 17' in text
            assert tokens(text)<=job.context_token_limit
            assert job.result['sources_status']=='not_independently_verified'
        finally:await m.shutdown()
    asyncio.run(run())

@pytest.mark.parametrize('change',['closed','epoch','new_turn'])
def test_authorization_change_during_quota_reservation_never_spawns_cli(tmp_path,settings,change):
    async def run():
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings)
        reserve=budget.reserve_session
        def raced_reservation(*args):
            policy=reserve(*args)
            if change=='closed':s.closed=True
            elif change=='new_turn':s.turns.append(s.current)
            else:
                with m.brain.memory.connect() as c:c.execute("UPDATE family_profiles SET epoch='revoked' WHERE id=?",(actor['id'],))
            return policy
        budget.reserve_session=raced_reservation
        try:
            proposal=await propose(s);await consent(s)
            with pytest.raises(PermissionError,match='expert_context_changed'):await s.experts.start(proposal['proposal_id'],'call_raced')
            assert not calls and s.experts.pending.worker is None
            # Reservation is conservatively consumed; no automatic refund/retry after a race.
            assert budget.status()['sessions_reserved']==1
        finally:
            s.closed=False
            await m.shutdown()
    asyncio.run(run())

def test_expert_http_status_is_no_store_and_profile_scoped(tmp_path,settings):
    import httpx
    from fastapi import FastAPI
    from gobot.realtime_api import attach_brain_realtime
    async def run():
        m,p,b,s,budget,actor,calls=await native(tmp_path,settings)
        try:
            proposal=await propose(s);await consent(s);job=await s.experts.start(proposal['proposal_id'],'call_http');await job.worker
            app=FastAPI();attach_brain_realtime(app,m,lambda:None)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
                params={'device_id':s.offer.device_id,'client_id':s.offer.client_id,'confirmed_profile_epoch':actor['epoch'],'conversation_id':'conv-1'}
                own=await client.get('/api/v1/realtime/experts',params=params)
                assert own.status_code==200 and own.headers['cache-control']=='no-store'
                assert own.json()['saved_jobs'][0]['result']['numbers']==['42']
                params.update(device_id='browser-other',confirmed_profile_epoch='')
                other=await client.get('/api/v1/realtime/experts',params=params)
                assert not other.json()['saved_jobs'] and not other.json()['jobs']
                assert 'Вывод' not in other.text
        finally:await m.shutdown()
    asyncio.run(run())
