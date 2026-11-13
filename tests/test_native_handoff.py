"""Native provider is fake; A coordinator/transport are real. No paid calls."""
import asyncio,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from test_board_realtime import prepared,enable,offer
from gobot.conversation_modes import ConversationModes
from gobot.native_handoff import NativeHandoff
from gobot.models import VoiceRequest

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

def test_streaming_a_transport_reuses_question_without_second_stt(tmp_path):
    import httpx,base64
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'services/voice'))
    from gobot_device_gateway import Gateway
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
            data=json.loads(req.content);assert data['text']=='Исходный вопрос' and data['mode_conversation_id']=='flow'
            return httpx.Response(200,stream=Events())
        def factory(**kw):return httpx.AsyncClient(transport=httpx.MockTransport(handle),**kw)
        config={'brain_url':'http://127.0.0.1:18781','device_id':'board','conversation_id':'conversation',
            'paid_speech_consent':True,'stt_provider':'openai','tts_provider':'openai','tts_voice':'marin','cli_usage_consent':True}
        gateway=Gateway(config,'fixture-token',client_factory=factory);gateway.quota_path=tmp_path/'quota.json'
        async def send(data):sent.append(data)
        async def audio(ws,packet):packets.append(packet);first_audio.set()
        gateway.send_audio=audio
        await gateway.brain_response(None,send,None,'handoff-turn',flow_id='flow',recognized_text='Исходный вопрос')
        assert calls==['/api/v1/chat/voice/stream'] and packets
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
