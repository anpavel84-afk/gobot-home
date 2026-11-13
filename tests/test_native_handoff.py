"""Native provider is fake; A coordinator/transport are real. No paid calls."""
import asyncio,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_board_realtime import prepared,enable,offer
from gobot.conversation_modes import ConversationModes
from gobot.native_handoff import NativeHandoff
from gobot.models import VoiceRequest

@pytest.mark.parametrize('engine',['A','B','C'])
@pytest.mark.parametrize('phase',['connecting','listening','thinking','speaking'])
def test_voice_status_is_bounded_and_explicit(engine,phase):
    from gobot.voice_status import voice_status
    message=voice_status(engine,phase)
    assert message['payload']['voice_engine']==engine and message['payload']['voice_phase']==phase
    assert message['payload']['namespace']=='gobot.ui' and len(json.dumps(message).encode())<8192
    with pytest.raises(ValueError):voice_status('unknown',phase)

@pytest.mark.parametrize('text',[
    'Ты можешь включить экспертный режим?', 'Можешь включить экспертный режим?',
    'Переведи меня в экспертный режим', 'Экспертный режим',
])
def test_natural_direct_mode_requests(text):
    from gobot.conversation_modes import expert_mode_request
    assert expert_mode_request(text)==''

@pytest.mark.parametrize('text',[
    'Он сказал: экспертный режим', 'Повтори фразу «Ты можешь включить экспертный режим?»',
    'Я хочу экспертный режим', 'Давай экспертный режим пожалуйста',
])
def test_owner_keyword_mentions_trigger_mode(text):
    from gobot.conversation_modes import expert_mode_request
    assert expert_mode_request(text)==''

def test_question_with_embedded_mode_keyword_keeps_the_full_question():
    from gobot.conversation_modes import expert_mode_request
    text='Сравни два подхода в экспертном режиме'
    assert expert_mode_request(text)==text

@pytest.mark.parametrize('separator',[': ','. ', ', ', ' — ', '? '])
def test_single_utterance_goes_straight_to_a_with_original_question(tmp_path,settings,separator):
    original,b,provider,modes=setup(tmp_path,settings)
    async def run():
        try:
            await b.start(offer());s=b.sessions['board-b-1']
            await s.new_turn(query='Экспертный режим'+separator+'сравни два способа выращивания растений')
            result=await b.legacy_handoff.result(s)
            assert result['state']=='ready' and result['question']=='сравни два способа выращивания растений'
            assert s.closed and s.hangup_confirmed
            assert not any(e['type']=='expert_job' for e in s.events)
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())

def test_wake_name_punctuation_does_not_hide_mode_question():
    from gobot.conversation_modes import expert_mode_request
    assert expert_mode_request('ГоБот, экспертный режим. Сравни два варианта.')=='Сравни два варианта.'
    assert expert_mode_request('Не включай экспертный режим. Сравни два варианта.') is None

def setup(tmp_path,settings,authorized=True):
    original,b,provider,path=prepared(tmp_path,settings);enable(path)
    owner=SimpleNamespace(authorized=lambda binding:authorized and binding=='board',
        voice_authorized=lambda binding:authorized and binding=='board')
    modes=ConversationModes(original.brain,owner);b.legacy_handoff=NativeHandoff(b,modes)
    return original,b,provider,modes

def test_actual_close_before_a_scope_and_exact_first_question(tmp_path,settings):
    original,b,provider,modes=setup(tmp_path,settings)
    async def run():
        try:
            await b.start(offer());s=b.sessions['board-b-1']
            previous=await s.new_turn(query='Сравни способы посадки растений');previous.answer='Ранее обсуждённая оговорка.';previous.stored=True
            await s.new_turn(query='Экспертный режим')
            result=await b.legacy_handoff.result(s)
            assert s.closed and s.hangup_confirmed and not b.budget.pending_calls()
            assert b.budget.latest_report()['close_reason']=='mode_switch'
            assert result['state']=='ready' and result['flow']['provider_closed']
            assert result['question']=='Сравни способы посадки растений'
            flow=modes.items[result['flow']['mode_conversation_id']]
            req=VoiceRequest(text=result['question'],device_id='board',client_id='board',
                turn_id=result['operation_id'],mode_conversation_id=flow.id,remember=False)
            with pytest.raises(PermissionError):modes.legacy_request(req.model_copy(update={'client_id':'phone'}))
            with pytest.raises(PermissionError):modes.legacy_request(req.model_copy(update={'text':'Другой вопрос'}))
            actual,mapped=modes.legacy_request(req)
            assert mapped.device_id==flow.scope and mapped.conversation_id==flow.conversation
            assert mapped.provider=='auto' and mapped.mode=='auto' and not mapped.remember
            assert any(m['content']=='Ранее обсуждённая оговорка.' for m in actual.transition_messages)
            assert await b.legacy_handoff.result(s)==result and len(modes.items)==1
            assert s.experts.budget.status()['sessions_reserved']==0
            modes.end(flow);assert not flow.transition_messages and not flow.pending_question
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())

def test_board_a_grant_is_separate_exact_and_finite(tmp_path,settings):
    import time
    from gobot.expert_store import ExpertBudget,ExpertPolicy
    from gobot.hardware_legacy import HardwareLegacy,bounded_stream
    root=tmp_path/'a';budget=ExpertBudget(root)
    policy=ExpertPolicy(enabled=True,authorization='fixture',audience='owner_interactive',allowed_client_id='board',
        expires_at=time.time()+100,max_sessions=2,allowed_profiles=['SOL_HIGH'],job_timeout_seconds=90,
        max_context_tokens=3000,max_result_characters=6000)
    budget.policy_path.write_text(policy.model_dump_json())
    admission=HardwareLegacy(root)
    assert admission.allowed('board') and not admission.allowed('phone')
    owner=SimpleNamespace(authorized=lambda _:False,voice_authorized=lambda _:False)
    modes=ConversationModes(SimpleNamespace(running={}),owner);modes.hardware_legacy=admission
    req_offer=offer()
    flow=modes.from_native(req_offer,[],'Исходный вопрос','operation-1')
    req=VoiceRequest(text='Исходный вопрос',device_id='board',client_id='board',remember=False,
        turn_id='operation-1',mode_conversation_id=flow.id)
    _,mapped=modes.legacy_request(req)
    assert mapped.provider=='codex' and mapped.model_id=='gpt-6.1-sol' and flow.legacy_profile=='SOL_HIGH'
    assert budget.status()['sessions_remaining']==1
    flow.legacy_turn=None;flow.pending_question=''
    modes.legacy_request(req.model_copy(update={'turn_id':'operation-2','text':'Уточнение'}))
    assert not admission.allowed('board') and budget.status()['sessions_remaining']==0
    with pytest.raises(PermissionError):admission.reserve('board','operation-3')
    async def check():
        closed=[]
        async def source():
            try:yield 'x'*6001
            finally:closed.append(True)
        from gobot.processes import AgentError
        with pytest.raises(AgentError):[part async for part in bounded_stream(source(),policy)]
        assert closed
    asyncio.run(check())

def test_offered_a_needs_current_real_confirmation(tmp_path,settings):
    original,b,provider,modes=setup(tmp_path,settings)
    async def run():
        try:
            await b.start(offer());s=b.sessions['board-b-1']
            t=await s.new_turn(query='Вопрос, требующий подробного разбора')
            proposal=b.legacy_handoff.propose(s,t)
            assert proposal['available'] and not proposal['background_job']
            assert not b.legacy_handoff.operations
            await s.new_turn(query='Да')
            result=await b.legacy_handoff.result(s)
            assert result['state']=='ready' and result['question']=='Вопрос, требующий подробного разбора'
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())

def test_server_abstention_offers_a_then_real_yes_switches_without_expert_job(tmp_path,settings):
    original,b,provider,modes=setup(tmp_path,settings)
    async def run():
        try:
            await b.start(offer());s=b.sessions['board-b-1']
            query='Какие актуальные новости тестовой компании?';turn=await s.new_turn(query=query)
            await s.tool('source-check','gobot_tool',json.dumps({'query':query}),turn)
            outputs=[json.loads(v['item']['output']) for v in s.ws.sent if v.get('item',{}).get('type')=='function_call_output']
            output=outputs[-1]
            assert output['mode_proposal']['available'] and output['requires_user_confirmation']
            assert 'Переключить?' in output['text'] and not b.legacy_handoff.operations
            assert not s.experts.jobs
            await s.new_turn(query='Да')
            result=await b.legacy_handoff.result(s)
            assert result['state']=='ready' and result['question']==query
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())

def test_unconfirmed_hangup_never_enters_a_or_retries_paid_work(tmp_path,settings):
    original,b,provider,modes=setup(tmp_path,settings)
    async def fail(call):raise OSError('mock 503')
    provider.hangup=fail
    async def run():
        try:
            await b.start(offer());s=b.sessions['board-b-1']
            await s.new_turn(query='Экспертный режим')
            result=await b.legacy_handoff.result(s)
            assert result['state']=='blocked' and result['error']=='native_close_unconfirmed'
            assert not modes.items and b.budget.pending_calls()
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())

@pytest.mark.parametrize('kind',['unapproved','private','active_expert'])
def test_denied_transfer_keeps_b_and_cannot_borrow_phone(tmp_path,settings,kind):
    original,b,provider,modes=setup(tmp_path,settings,authorized=kind!='unapproved')
    async def run():
        try:
            await b.start(offer());s=b.sessions['board-b-1']
            if kind=='private':s.offer=s.offer.model_copy(update={'remember':True})
            if kind=='active_expert':s.experts.active=lambda:True
            await s.new_turn(query='Экспертный режим')
            assert not s.closed and not modes.items and not b.legacy_handoff.operations
            assert any(e['type']=='conversation_mode_blocked' for e in s.events)
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())

def test_streaming_a_transport_reuses_question_without_second_stt(tmp_path,monkeypatch):
    import httpx,base64
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/voice'))
    from gobot_device_gateway import Gateway
    from spotpear_live import StreamingSpeech
    import spotpear_realtime
    async def run():
        sent=[];calls=[];packets=[];first_audio=asyncio.Event()
        pcm=base64.b64encode(bytes(9600)).decode()
        class Events(httpx.AsyncByteStream):
            async def __aiter__(self):
                def evt(kind,**data):return ('data: '+json.dumps({'type':kind,'turn_id':'handoff-turn','data':data})+'\n\n').encode()
                yield evt('audio_start')
                yield evt('sentence_ready',text='Первая часть ответа.')
                yield evt('audio_chunk',seq=0,format='pcm_s16le',pcm=pcm,sample_rate=24000)
                await asyncio.wait_for(first_audio.wait(),1)
                yield evt('sentence_ready',text='Вторая часть ответа.')
                yield evt('audio_chunk',seq=1,format='pcm_s16le',pcm=pcm,sample_rate=24000)
                yield evt('audio_stop',reason='finished')
        async def handle(req):
            calls.append(req.url.path);assert req.url.path=='/api/v1/chat/voice/stream'
            data=json.loads(req.content);assert data['text']=='Исходный вопрос'
            assert data['tts_character_limit']==3000
            assert any(v.get('payload',{}).get('voice_engine')=='A' and
                v['payload'].get('voice_phase')=='thinking' for v in sent)
            return httpx.Response(200,stream=Events())
        def factory(**kw):return httpx.AsyncClient(transport=httpx.MockTransport(handle),**kw)
        config={'brain_url':'http://127.0.0.1:18781','device_id':'board','conversation_id':'conversation',
            'paid_speech_consent':True,'stt_provider':'openai','tts_provider':'openai','tts_voice':'marin','cli_usage_consent':True,
            'hardware_a_batch':{'id':'a'*32,'turns':2},'mode':'realtime_b','continuous_live':True}
        gateway=Gateway(config,'fixture-token',client_factory=factory);gateway.quota_path=tmp_path/'quota.json'
        async def send(data):sent.append(data)
        async def audio(ws,packet):packets.append(packet);first_audio.set()
        gateway.send_audio=audio
        gateway.save_stats=lambda:None
        async def native(*args):return {'question':'Исходный вопрос','operation_id':'handoff-turn','flow':{
            'active':True,'provider_closed':True,'mode':'legacy','mode_conversation_id':'00000000-0000-4000-8000-000000000001'}}
        monkeypatch.setattr(spotpear_realtime,'realtime_turn',native)
        class Socket:
            async def close(self,*args):pass
        await gateway.respond(Socket(),send,StreamingSpeech(),'original-b-turn')
        assert calls==['/api/v1/chat/voice/stream'] and packets
        assert not any(v['type'] in {'gobot_access','gobot_input_end'} for v in sent)
        assert [v['text'] for v in sent if v.get('state')=='sentence_start']==['Первая часть ответа.','Вторая часть ответа.']
        assert sent[-1]=={'type':'tts','state':'stop'}
    asyncio.run(run())

def test_gateway_batch_is_finite_across_restarts_and_days(tmp_path):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/voice'))
    from gobot_device_gateway import Gateway
    config={'hardware_a_batch':{'id':'a'*32,'turns':2}}
    first=Gateway(config,'fixture');first.quota_path=tmp_path/'old-usage.json'
    first.reserve_manual_turn()
    second=Gateway(config,'fixture');second.quota_path=first.quota_path
    second.reserve_manual_turn()
    with pytest.raises(ValueError,match='hardware_a_attempts_exhausted'):second.reserve_manual_turn()
    assert not first.quota_path.exists() # No rewrite/reset of the historical daily ledger.
