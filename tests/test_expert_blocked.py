"""Blocked handoffs must be visible without fabricating a queued CLI job."""
import asyncio,json
from test_realtime_native import configured,start
from gobot.expert_jobs import explicit_expert_request

def test_disabled_handoff_is_instructions_and_not_fake_confirmation(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);s=await start(m)
        try:
            assert 'native_experts_disabled' in s.config['instructions']
            assert 'expert_start' not in {t['name'] for t in s.config['tools']}
            turn=await s.new_turn(query='Передай этот вопрос на CLI')
            await s.input_text(turn,turn.query) # Duplicate final transcript is not a second request.
            await s.tool('blocked-proposal','expert_propose',json.dumps({'task':turn.query,'profile':'SOL_HIGH'}),turn)
            output=next(json.loads(e['item']['output']) for e in s.ws.sent if e.get('item',{}).get('call_id')=='blocked-proposal')
            assert output['state']=='blocked' and output['executed'] is False and output['accepted'] is False
            assert set(output['availability']['blocked_reasons'])>={'native_experts_disabled','confirmed_adult_profile_required','expert_budget_missing_or_expired'}
            assert not s.experts.jobs and s.experts.pending is None and not s.closed
            assert s.expert_activity['explicit_request']==1
            assert any(e['type']=='expert_blocked' for e in s.events)
            # Unsupported provider/model contents are never diagnostic keys.
            s.expert_activity['PRIVATE_TASK']=1;s.expert_blocked_reasons['PRIVATE_QUERY']=1
        finally:await m.shutdown()
        report=b.latest_report()
        assert report['expert_activity']=={'explicit_request':1,'blocked':2,'proposal_requested':1}
        assert report['expert_blocked_reasons']['native_experts_disabled']==2
        assert 'PRIVATE' not in json.dumps(report) and 'Передай' not in json.dumps(report,ensure_ascii=False)
    asyncio.run(run())

def test_enabled_global_flag_does_not_expose_start_to_guest_without_grant(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        b.policy_path.write_text(b.policy().model_copy(update={'expert_jobs_allowed':True}).model_dump_json())
        s=await start(m)
        try:
            assert 'expert_start' not in {t['name'] for t in s.config['tools']}
            turn=await s.new_turn(query='Обычный вопрос')
            assert not s.expert_activity
            await s.tool('start-without-proposal','expert_start','{"proposal_id":"missing"}',turn)
            assert 'accepted' not in s.expert_activity and not s.closed
        finally:await m.shutdown()
    asyncio.run(run())

def test_explicit_intent_is_diagnostic_only():
    for text in ['Передай вопрос на CLI','Адресуй это эксперту','Отправь на проверку Sol High','Спроси Argon','Попроси эксперта проверить это','Можешь подключить эксперта?']:
        assert explicit_expert_request(text)
    for text in ['Что такое CLI?','Sol — это модель?','Нет, спасибо','Объясни солнечную систему','Не подключай эксперта','Он сказал: попроси эксперта проверить это','«Передай вопрос на CLI»','Объясни фразу подключи эксперта']:
        assert not explicit_expert_request(text)
