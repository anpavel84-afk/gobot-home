"""Confirmation/job fixtures; no actual expert, model or TTS calls."""
import asyncio,json,time
from types import SimpleNamespace
from gobot.expert_jobs import ExpertJobs
from gobot.expert_profiles import resolve_profile
from gobot.realtime_budget import RealtimeBudget
import pytest

def session():
    s=SimpleNamespace(policy=SimpleNamespace(expert_jobs_allowed=True),expert_authorized=True,turns=[1],current=SimpleNamespace(query='Сравни архитектуры',answer='',cancelled=False),
        offer=SimpleNamespace(conversation_id='conv',expert_quota_consent=True),access=SimpleNamespace(effective_scope='guest-fixture'),closed=False,sent=[],events=[],tasks=[],responses=0)
    async def send(item):s.sent.append(item)
    async def respond():s.responses+=1
    def emit(kind,**kw):s.events.append((kind,kw))
    def spawn(coro):
        t=asyncio.create_task(coro);s.tasks.append(t);return t
    s.send=send;s.response=respond;s.emit=emit;s.spawn=spawn
    return s

def budget(tmp_path):
    from gobot.realtime_contract import RealtimePolicy
    b=RealtimeBudget(tmp_path)
    b.policy_path.write_text(RealtimePolicy(enabled=True,authorization='expert-fixture',expires_at=time.time()+100,max_sessions=1).model_dump_json())
    return b

def test_exact_profiles_use_separate_effort_metadata_without_substitution():
    rows=[{'slug':'gpt-6-astra','supported_reasoning_levels':[{'effort':'high'}]},{'slug':'gpt-6.1-sol','supported_reasoning_levels':[{'effort':'xhigh'}]}]
    astra=resolve_profile('ASTRA_HIGH',codex_metadata=rows);sol=resolve_profile('SOL_XHIGH',codex_metadata=rows)
    assert astra['metadata_verified'] and astra['model']=='gpt-6-astra' and astra['effort']=='high'
    assert sol['metadata_verified'] and sol['effort']=='xhigh'
    assert not resolve_profile('SOL_XHIGH',codex_metadata=rows[:1])['metadata_verified']

def test_model_proposal_is_not_confirmation_and_no_decline_launch(tmp_path):
    async def run():
        s=session();calls=[]
        async def execute(j):calls.append(j.id);return 'Вывод 42.'
        jobs=ExpertJobs(s,executor=execute,budget=budget(tmp_path))
        p=jobs.propose(s.current.query,'ARGON_DEEP',s.current)
        with pytest.raises(PermissionError):await jobs.start(p['proposal_id'],'real-call-id')
        jobs.observe('Нет, спасибо')
        with pytest.raises(PermissionError):await jobs.start(p['proposal_id'],'real-call-id')
        assert not calls
    asyncio.run(run())

def test_confirmation_runs_once_returns_one_real_call_output_and_same_session(tmp_path):
    async def run():
        s=session();calls=[]
        async def execute(j):calls.append(j.profile);return 'Главный вывод: 42. Это предположение, а не измерение.'
        jobs=ExpertJobs(s,executor=execute,budget=budget(tmp_path))
        p=jobs.propose(s.current.query,'ARGON_DEEP',s.current)
        s.turns.append(2);jobs.observe('Да, Argon')
        job=await jobs.start(p['proposal_id'],'call_actual_1');await job.worker
        assert job.state=='completed' and len(calls)==1
        assert await jobs.start(p['proposal_id'],'call_actual_1') is job
        with pytest.raises(ValueError):await jobs.start(p['proposal_id'],'call_actual_2')
        assert len(s.sent)==2 and s.sent[0]['item']['call_id']=='call_actual_1'
        assert json.loads(s.sent[0]['item']['output'])['accepted'] is True
        assert 'result' not in json.loads(s.sent[0]['item']['output'])
        result=json.loads(s.sent[1]['item']['content'][0]['text'])['data']['result']
        assert result['numbers']==['42'] and 'предположение' in result['display_text'] and s.responses==1
    asyncio.run(run())

def test_scope_amendment_is_not_blanket_yes_and_budget_not_reused(tmp_path):
    async def run():
        s=session();jobs=ExpertJobs(s,budget=budget(tmp_path))
        p=jobs.propose(s.current.query,'ARGON_DEEP',s.current)
        s.turns.append(2);jobs.observe('Да, но сравни только два варианта')
        with pytest.raises(PermissionError):await jobs.start(p['proposal_id'],'call_1')
        assert jobs.budget.status()['sessions_reserved']==0
    asyncio.run(run())

def test_stale_result_does_not_interrupt_new_topic_and_profile_is_not_transferred(tmp_path):
    async def run():
        s=session();gate=asyncio.Event()
        async def execute(j):await gate.wait();return 'Synthetic result 17.'
        jobs=ExpertJobs(s,executor=execute,budget=budget(tmp_path))
        p=jobs.propose(s.current.query,'ARGON_DEEP',s.current);jobs.observe('Да')
        job=await jobs.start(p['proposal_id'],'call_running');await asyncio.sleep(0)
        s.turns.append(2);gate.set();await job.worker
        out=json.loads(s.sent[0]['item']['output'])
        assert 'result' not in out and s.responses==0
        assert job.result and job.result['numbers']==['17']
        s.access.effective_scope='different-profile'
        with pytest.raises(ValueError):await jobs.start(p['proposal_id'],'call_other')
    asyncio.run(run())

def test_explicit_selected_expert_is_consent_only_for_exact_request(tmp_path):
    s=session();s.current.query='Спроси Argon: сравни два варианта'
    jobs=ExpertJobs(s,budget=budget(tmp_path))
    p=jobs.propose(s.current.query,'ARGON_DEEP',s.current);assert p['confirmed']
    p=jobs.propose('Измени файлы на компьютере','ARGON_DEEP',s.current);assert not p['confirmed']

def test_cancelled_job_does_not_deliver_completed_result(tmp_path):
    async def run():
        s=session();started=asyncio.Event()
        async def execute(j):started.set();await asyncio.sleep(100)
        jobs=ExpertJobs(s,executor=execute,budget=budget(tmp_path))
        p=jobs.propose(s.current.query,'ARGON_DEEP',s.current);jobs.observe('Да')
        job=await jobs.start(p['proposal_id'],'call_cancel');await started.wait();await jobs.cancel(job.id)
        assert job.state=='cancelled' and not job.result
        assert len(s.sent)==2 and json.loads(s.sent[1]['item']['content'][0]['text'])['data']['state']=='cancelled'
        assert jobs.budget.status()['sessions_reserved']==1
    asyncio.run(run())
