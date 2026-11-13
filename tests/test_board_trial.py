"""Approved finite trial only. Provider and CLI are mocks; no paid requests."""
import asyncio,json,time
import pytest
from gobot.board_trial import prepare_trial,TrialBudget,TrialRealtime,PublicExpertBudget
from test_board_realtime import prepared,enable,offer
from test_realtime_native import tick

def enable_expert(path):
    from gobot.expert_store import ExpertPolicy
    p=ExpertPolicy.model_validate_json(path.read_text());path.write_text(p.model_copy(update={'enabled':True}).model_dump_json())

def trial(tmp_path,settings):
    original,old,_,oldpath=prepared(tmp_path,settings)
    path=prepare_trial(tmp_path/'extended','board');enable(path);enable_expert(path.parent/'experts/policy.json')
    from test_realtime_native import Provider
    provider=Provider();manager=TrialRealtime(original,path.parent,provider=provider)
    return original,old,manager,provider,path,oldpath

def test_separate_once_only_grant_preserves_old_allowance_and_never_renews(tmp_path):
    from gobot.board_realtime import prepare_policy,BoardBudget
    old=prepare_policy(tmp_path/'original','board');enable(old);b=BoardBudget(old.parent)
    b.reserve_session('old',True,'board');before=old.read_bytes()
    path=prepare_trial(tmp_path/'extended','board');initial=path.read_bytes()
    assert not TrialBudget(path.parent).board_status()['enabled']
    prepare_trial(path.parent,'different');assert path.read_bytes()==initial
    enable(path);budget=TrialBudget(path.parent)
    p=budget.reserve_session('one-manual',True,'board')
    assert (p.max_session_seconds,p.max_responses_per_session,p.max_output_tokens)==(180,12,2048)
    for i in range(12):budget.reserve_response('one-manual',p)
    with pytest.raises(PermissionError):budget.reserve_response('one-manual',p)
    with pytest.raises(PermissionError):budget.reserve_session('retry',True,'board')
    assert b.board_status()['sessions_remaining']==7 and old.read_bytes()==before
    assert budget.board_status()['reserved_estimate_usd']==1

def test_trial_rejects_unapproved_caps_and_other_device(tmp_path):
    path=prepare_trial(tmp_path,'board');enable(path);b=TrialBudget(tmp_path)
    with pytest.raises(PermissionError):b.reserve_session('foreign',True,'phone')
    p=b.policy();path.write_text(p.model_copy(update={'max_session_seconds':300}).model_dump_json())
    with pytest.raises(PermissionError,match='outside_owner_allowance'):b.reserve_session('too-long',True,'board')
    path.write_text(p.model_copy(update={'expires_at':time.time()-1}).model_dump_json())
    with pytest.raises(PermissionError):b.reserve_session('expired',True,'board')
    epath=tmp_path/'experts/policy.json';enable_expert(epath);e=PublicExpertBudget(epath.parent);p=e.policy()
    epath.write_text(p.model_copy(update={'allowed_profiles':['ASTRA_HIGH']}).model_dump_json())
    with pytest.raises(PermissionError):e.policy()

def test_public_guest_not_private_identity_and_confirmation_only_once(tmp_path,settings):
    original,old,b,provider,path,_=trial(tmp_path,settings)
    async def run():
        try:
            with pytest.raises(PermissionError):await b.start(offer())
            await b.start(offer(expert_quota_consent=True));s=b.sessions['board-b-1']
            assert s.experts.status()['enabled'] and not s.expert_authorized and not s.owner_test_authorized
            assert not s.offer.remember and s.access.confirmed_profile_id is None
            turn=await s.new_turn(query='Сравни два публичных подхода к посадке растений')
            proposed=s.experts.propose(turn.query,'SOL_HIGH',turn);calls=[]
            async def execute(job):calls.append(job.profile);return 'Результат fixture. Актуальность внешних данных не проверена.'
            s.experts.executor=execute;s.experts.admission=lambda profile:{'available':True}
            with pytest.raises(PermissionError):await s.experts.start(proposed['proposal_id'],'no-consent')
            assert not calls
            await s.new_turn(query='Да');s.experts.observe('Да')
            job=await s.experts.start(proposed['proposal_id'],'confirmed-once');await job.worker
            assert job.state=='completed' and len(calls)==1
            assert calls[0]['model']=='gpt-6.1-sol' and calls[0]['effort']=='high'
            assert (job.timeout_seconds,job.context_token_limit,job.max_result_characters)==(90,3000,6000)
            assert not s.experts.status()['enabled']
            assert await s.experts.start(proposed['proposal_id'],'confirmed-once') is job
            assert len(calls)==1 and not old.budget.board_status()['reserved_estimate_usd']
        finally:await b.shutdown();await old.shutdown();await original.shutdown()
    asyncio.run(run())

def test_missing_verified_source_offers_analysis_but_never_launches_cli(tmp_path,settings):
    original,old,b,provider,path,_=trial(tmp_path,settings)
    async def run():
        try:
            await b.start(offer(expert_quota_consent=True));s=b.sessions['board-b-1']
            query='Какие последние крупные сделки NVIDIA?';turn=await s.new_turn(query=query)
            await s.tool('fact-source','gobot_tool',json.dumps({'query':query}),turn)
            pending=s.experts.pending
            assert pending and not pending.confirmed and pending.state=='awaiting_confirmation'
            outputs=[json.loads(v['item']['output']) for v in s.ws.sent if v.get('item',{}).get('type')=='function_call_output']
            assert outputs[-1]['expert_proposal']['expert']['profile']=='SOL_HIGH'
            assert 'неподтверждёнными' in outputs[-1]['text']
            assert s.experts.budget.status()['sessions_reserved']==0
        finally:await b.shutdown();await old.shutdown();await original.shutdown()
    asyncio.run(run())

def test_scene_displays_only_real_job_state_no_fake_progress():
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/voice'))
    from spotpear_expert_scene import expert_scene
    assert expert_scene({'job':{'state':'unknown'}}) is None
    for state in ('awaiting_confirmation','queued','running','completed','cancelled','failed','timed_out'):
        scene=expert_scene({'job':{'state':state,'job_id':'fixture'}})
        assert scene['payload']['namespace']=='gobot.ui' and scene['payload']['type']=='status_card'
        assert '%' not in scene['payload']['text'] and len(scene['payload']['text'])<80
