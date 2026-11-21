"""Offline integration risks: phased answers, early speech and logical jobs.

All transports/executors below are synthetic; no external connection or provider
request is made, and no acoustic/latency acceptance is claimed.
"""
import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from gobot.agents import CodexEventAdapter
from gobot.expert_jobs import ExpertJobs, explicit_expert_request
from gobot.expert_stream import AnswerDelta
from gobot.pipeline import expert_voiced_events
from gobot.stt import OpenAIRecognition
from test_realtime_experts import session, budget


def test_codex_phase_lifecycle_blocks_commentary_and_unclassified_live_text():
    parser=CodexEventAdapter(strict_phases=True,job_id='job')
    assert parser.parse({'method':'item/started','params':{'item':{
        'id':'c','type':'agentMessage','phase':'commentary'}}})==[]
    assert parser.parse({'method':'item/agentMessage/delta','params':{
        'itemId':'c','delta':'PRIVATE COMMENTARY'}})==[]
    assert parser.parse({'method':'item/completed','params':{'item':{
        'id':'c','type':'agentMessage','phase':'commentary','text':'PRIVATE COMMENTARY'}}})==[]
    assert parser.parse({'method':'item/agentMessage/delta','params':{
        'itemId':'unknown','delta':'Unclassified'}})==[]
    assert parser.parse({'method':'item/reasoning/textDelta','params':{'delta':'PRIVATE REASONING'}})==[]
    parser.parse({'method':'item/started','params':{'item':{
        'id':'answer','type':'agentMessage','phase':'partial_answer'}}})
    first=parser.parse({'method':'item/agentMessage/delta','params':{
        'itemId':'answer','delta':'Первый ответ. '}})
    assert first==['Первый ответ. '] and first[0].speakable
    assert first[0].item_id=='answer' and first[0].job_id=='job'
    completed={'method':'item/completed','params':{'item':{
        'id':'answer','type':'agentMessage','phase':'partial_answer','text':'Первый ответ. '}}}
    assert parser.parse(completed)==[] and parser.parse(completed)==[]
    assert parser.parse({'method':'turn/completed','params':{'turn':{'status':'completed'}}})==[]
    assert parser.text=='Первый ответ. '


def test_old_cli_requires_completed_structured_assistant_item_for_speech():
    parser=CodexEventAdapter(strict_phases=True)
    assert parser.parse({'method':'item/agentMessage/delta','params':{
        'itemId':'old','delta':'Законченный ответ.'}})==[]
    result=parser.parse({'method':'item/completed','params':{'item':{
        'id':'old','type':'agentMessage','text':'Законченный ответ.'}}})
    assert result==['Законченный ответ.']
    assert result[0].phase=='final_answer' and result[0].completed and result[0].verified
    assert parser.parse({'type':'item.completed','item':{'id':'tool','type':'command_execution',
        'text':'PRIVATE TOOL OUTPUT'}})==[]


class SyntheticSpeech:
    def __init__(self):self.turn_count=0;self.closed=0;self.texts=[];self.prepared=False
    @asynccontextmanager
    async def turn(self):
        self.turn_count+=1
        try:yield self
        finally:self.closed+=1
    async def prepare(self,*args,**kwargs):self.prepared=True
    async def synthesize(self,text,provider,voice,*,paid_consent):
        assert provider=='openai' and voice=='marin' and paid_consent
        self.texts.append(text)
        yield b'\0\0'*8,24000


def test_first_expert_audio_precedes_final_text_and_reuses_one_turn():
    async def run():
        gate=asyncio.Event();speech=SyntheticSpeech()
        async def source():
            yield AnswerDelta('НЕ ЧИТАТЬ',phase='commentary',verified=True,job_id='j')
            yield AnswerDelta('Первый вариант хорош. ',phase='partial_answer',verified=True,job_id='j')
            await gate.wait()
            yield AnswerDelta('Второй вариант быстрее.',phase='final_answer',verified=True,job_id='j')
        iterator=expert_voiced_events(speech,source(),job_id='j',conversation_id='c',turn_id='t',
            response_id='r',paid_tts_consent=True)
        events=[]
        async with asyncio.timeout(2):
            while True:
                event=await anext(iterator);events.append(event)
                if event['type']=='audio_chunk':break
        assert not gate.is_set() and speech.texts==['Первый вариант хорош.']
        assert speech.prepared and speech.turn_count==1
        gate.set()
        events.extend([event async for event in iterator])
        chunks=[e['data'] for e in events if e['type']=='audio_chunk']
        assert [e['seq'] for e in chunks]==[0,1]
        assert all(e['response_id']=='r' and e['audio_role']=='expert_answer' for e in chunks)
        assert len([e for e in events if e['type']=='audio_stop'])==1
        assert next(e for e in events if e['type']=='audio_stop')['data']['reason']=='finished'
        assert speech.texts==['Первый вариант хорош.','Второй вариант быстрее.'] and speech.closed==1
    asyncio.run(run())


def test_expert_pipeline_cancel_closes_source_and_drops_late_audio():
    async def run():
        stopped=asyncio.Event();speech=SyntheticSpeech()
        async def source():
            try:
                yield AnswerDelta('Слышимое предложение. ',phase='partial_answer',verified=True)
                await asyncio.Event().wait()
            finally:stopped.set()
        iterator=expert_voiced_events(speech,source(),job_id='j',conversation_id='c',turn_id='t',
            response_id='r',paid_tts_consent=True)
        async with asyncio.timeout(2):
            while (await anext(iterator))['type']!='audio_chunk':pass
            await iterator.aclose()
        assert stopped.is_set() and speech.closed==1
    asyncio.run(run())


def test_disconnected_transport_preserves_job_and_cannot_reattach_other_owner(tmp_path):
    async def run():
        s=session();gate=asyncio.Event();calls=[]
        async def execute(job):calls.append(job.id);await gate.wait();return 'Вариант один. Вариант два.'
        jobs=ExpertJobs(s,executor=execute,budget=budget(tmp_path));s.experts=jobs
        proposal=jobs.propose(s.current.query,'ARGON_DEEP',s.current);jobs.observe('Да')
        job=await jobs.start(proposal['proposal_id'],'call');await asyncio.sleep(0)
        jobs.detach();s.closed=True
        gate.set();await job.worker
        assert job.state=='completed' and len(calls)==1 and not job.returned
        replacement=session();replacement.access.effective_scope='foreign'
        with pytest.raises(PermissionError):await jobs.attach(replacement)
        replacement.access.effective_scope='guest-fixture'
        await jobs.attach(replacement)
        assert replacement.experts is jobs and s.experts is not jobs
        assert len(calls)==1 and job.returned
        assert any('expert_context_snapshot' in str(x) for x in replacement.sent)
        assert not any(x.get('item',{}).get('type')=='function_call_output' for x in replacement.sent)
        await jobs.close('user_stop')
        assert jobs.closed and job.result is None
    asyncio.run(run())


def test_local_expert_entry_requires_real_selection_and_has_no_tool_call_output(tmp_path):
    async def run():
        s=session();calls=[]
        async def execute(job):calls.append(job.id);return 'Готовый ответ.'
        jobs=ExpertJobs(s,executor=execute,budget=budget(tmp_path))
        with pytest.raises(PermissionError):await jobs.start_local(s.current.query,'ARGON_DEEP',s.current)
        s.expert_input_authorized=lambda turn:turn is s.current
        job=await jobs.start_local(s.current.query,'ARGON_DEEP',s.current);await job.worker
        assert len(calls)==1 and job.call_id is None and job.operation_id.startswith('local:')
        assert not any(e.get('item',{}).get('type')=='function_call_output' for e in s.sent)
        assert await jobs.start(job.proposal_id,None) is job
    asyncio.run(run())


@pytest.mark.parametrize('text',['София, спроси у эксперта, как это устроено',
    'София, спроси у Кодекса, сравни два способа','спроси у Codex про архитектуру'])
def test_sophia_generic_expert_request_is_recognized_without_fixed_profile(text):
    assert explicit_expert_request(text)


def test_stt_commit_item_binding_duration_usage_and_configurable_long_limit():
    async def run():
        sent=[]
        class Socket:
            def __init__(self):self.queue=asyncio.Queue()
            async def send(self,raw):
                item=json.loads(raw);sent.append(item)
                if item['type']=='session.update':await self.queue.put({'type':'session.updated'})
                if item['type']=='input_audio_buffer.commit':
                    await self.queue.put({'type':'input_audio_buffer.committed','item_id':'ours'})
                    await self.queue.put({'type':'conversation.item.input_audio_transcription.completed',
                        'item_id':'stale','transcript':'WRONG'})
                    await self.queue.put({'type':'conversation.item.input_audio_transcription.completed',
                        'item_id':'ours','transcript':'Длинная задача.','usage':{'type':'duration','seconds':61,'secret':'DENIED'}})
            async def recv(self):return json.dumps(await self.queue.get())
        @asynccontextmanager
        async def connector(*args,**kwargs):yield Socket()
        async def chunks():
            for _ in range(61):yield b'\0\0'*24000
        events=[e async for e in OpenAIRecognition(api_key='fixture',connector=connector).live(
            chunks(),paid_consent=True,max_audio_seconds=180,operation_timeout_seconds=220)]
        final=events[-1]['data']
        assert final['item_id']=='ours' and final['text']=='Длинная задача.'
        assert final['usage']=={'type':'duration','seconds':61} and final['audio_seconds']==61
        assert sum(e['type']=='input_audio_buffer.commit' for e in sent)==1
        assert sent[0]['session']['audio']['input']['turn_detection'] is None
    asyncio.run(run())


def test_signed_bridge_preserves_verified_answer_metadata(settings,monkeypatch):
    import httpx
    import gobot.bridge as bridge
    import gobot.providers as providers
    from gobot.models import ChatRequest
    async def source(*args,**kwargs):
        yield AnswerDelta('Проверенный ответ.',item_id='item',phase='partial_answer',
                          job_id=kwargs['job_id'],verified=True)
    monkeypatch.setattr(bridge,'live_stream',source)
    app=bridge.create_app(settings);original=httpx.AsyncClient
    def client(**kwargs):
        kwargs['transport']=httpx.ASGITransport(app=app,client=('127.0.0.1',1234))
        return original(**kwargs)
    monkeypatch.setattr(providers.httpx,'AsyncClient',client)
    async def run():
        req=ChatRequest(text='Сравни',provider='codex',turn_id='job',model_id='gpt-6.1-sol',usage_consent=True)
        values=[item async for item in providers.bridge_stream(settings,req,{},expert_profile='SOL_HIGH')]
        assert len(values)==1 and values[0].speakable
        assert values[0].item_id=='item' and values[0].job_id=='job' and values[0].phase=='partial_answer'
    asyncio.run(run())


def test_narrator_usage_is_measured_separate_and_secret_free():
    import base64
    from gobot.audio import Speech
    async def run():
        class Socket:
            def __init__(self):self.queue=asyncio.Queue();self.count=0
            async def send(self,raw):
                event=json.loads(raw)
                if event['type']=='session.update':await self.queue.put({'type':'session.updated'})
                if event['type']=='response.create':
                    self.count+=1
                    await self.queue.put({'type':'response.output_audio.delta','delta':base64.b64encode(b'\1\0'*8).decode()})
                    await self.queue.put({'type':'response.done','response':{'id':f'r{self.count}',
                        'status':'completed','usage':{'input_tokens':3,'output_tokens':4,'total_tokens':7,
                        'input_token_details':{'text_tokens':3,'audio_tokens':0,'private':'SECRET'},
                        'output_token_details':{'audio_tokens':4},'private':'SECRET'}}})
            async def recv(self):return json.dumps(await self.queue.get())
        @asynccontextmanager
        async def connect(*args,**kwargs):yield Socket()
        async def source():yield AnswerDelta('Первое. Второе.',phase='final_answer',verified=True)
        usage={}
        events=[e async for e in expert_voiced_events(Speech(api_key='fixture',connector=connect),source(),
            job_id='j',conversation_id='c',turn_id='t',response_id='r',paid_tts_consent=True,usage_sink=usage)]
        assert usage['complete'] and usage['requests_started']==2 and len(usage['responses'])==2
        assert [r['response_id'] for r in usage['responses']]==['r1','r2']
        assert 'SECRET' not in json.dumps(usage) and not any('estimated' in k for k in usage)
        assert events[-1]['type']=='narrator_usage'
    asyncio.run(run())


def test_service_cue_lookup_requires_exact_metadata_and_checksum(tmp_path):
    from gobot.expert_stream import expert_service_cache,load_expert_service_cue,EXPERT_CUE_ID,EXPERT_CUE_TEXT
    assert load_expert_service_cue(tmp_path)['status']=='missing'
    cache=expert_service_cache(tmp_path)
    cache.put('marin',EXPERT_CUE_ID,b'\0\0'*480,24000,EXPERT_CUE_TEXT)
    ready=load_expert_service_cue(tmp_path)
    assert ready['status']=='ready' and ready['text']==EXPERT_CUE_TEXT and ready['sample_rate']==24000
    assert ready['runtime_generation'] is False and len(ready['sha256'])==64
    path=cache.root/(cache.key('marin',EXPERT_CUE_ID)+'.wav')
    path.write_bytes(path.read_bytes()+b'corrupt')
    assert load_expert_service_cue(tmp_path)['status']=='missing'


def test_detached_job_is_cancelled_on_revoked_grant_not_spent_quota(tmp_path):
    async def run():
        s=session();started=asyncio.Event()
        async def execute(job):started.set();await asyncio.Event().wait()
        b=budget(tmp_path);jobs=ExpertJobs(s,executor=execute,budget=b)
        proposal=jobs.propose(s.current.query,'ARGON_DEEP',s.current);jobs.observe('Да')
        job=await jobs.start(proposal['proposal_id'],'call');await started.wait()
        jobs.detach();s.closed=True
        # The grant is fully reserved, yet that alone must not cancel this job.
        await asyncio.sleep(.3);assert job.state=='running'
        b.policy_path.write_text(b.policy().model_copy(update={'enabled':False}).model_dump_json())
        async with asyncio.timeout(2):await asyncio.gather(job.worker,return_exceptions=True)
        assert job.state=='cancelled' and job.error=='expert_context_changed'
        assert b.status()['sessions_reserved']==1
    asyncio.run(run())


def test_direct_expert_cue_early_answer_rotation_and_physical_followup(tmp_path,settings,monkeypatch):
    """Real DirectSession + ExpertJobs + formatter/pipeline; synthetic providers."""
    import gobot.expert_jobs as jobs_module
    import gobot.expert_stream as stream_module
    from gobot.device_contract import DeviceProfile,ScreenPreferences
    from gobot.expert_profiles import resolve_profile
    from gobot.realtime_ws import DirectOffer,DirectRealtimeManager
    from test_realtime_native import configured
    from test_realtime_ws import Provider
    from test_owner_testing import activate
    rows=[{'slug':'gpt-6.1-sol','supported_reasoning_levels':[{'effort':'high'}]}]
    monkeypatch.setattr(jobs_module,'resolve_profile',lambda name:resolve_profile(name,codex_metadata=rows))
    monkeypatch.setattr(stream_module,'load_expert_service_cue',lambda: {
        'status':'ready','pcm':b'\0\0'*480,'sample_rate':24000,'sha256':'synthetic-fixture'})
    async def run():
        original,_,b=configured(tmp_path,settings)
        owner,expert=activate(original,b)
        owner.update('client-1',{'images_enabled':False})
        expert.policy_path.write_text(expert.policy().model_copy(update={'allowed_profiles':['SOL_HIGH']}).model_dump_json())
        async def profile(_):return DeviceProfile(screen=ScreenPreferences(automatic_illustrations=False))
        original.profile_loader=profile
        speech=SyntheticSpeech();gate=asyncio.Event();calls=[]
        async def source(settings,req,packet,*,expert_profile):
            calls.append(req.turn_id)
            yield AnswerDelta('Первый вариант надёжен. ',item_id='a',phase='partial_answer',job_id=req.turn_id,verified=True)
            await gate.wait()
            yield AnswerDelta('Второй вариант быстрее.',item_id='b',phase='final_answer',job_id=req.turn_id,verified=True)
        monkeypatch.setattr(jobs_module,'bridge_stream',source)
        manager=DirectRealtimeManager(original,provider=Provider(),speech=speech,
            narrator_authorizer=lambda s,j:{'paid_tts_consent':True,'tts_character_limit':2000})
        try:
            s=await manager.accept(DirectOffer(session_id='direct-expert',conversation_id='conv',
                device_id='browser-1',client_id='client-1',consent=True,client_kind='panel',
                requested_model='gpt-realtime-2.1-mini',expert_quota_consent=True))
            s.experts=ExpertJobs(s,budget=expert,admission=lambda p:{'available':True})
            execution_errors=[]
            execute=s.experts.execute
            async def observed(job):
                try:return await execute(job)
                except Exception as error:
                    execution_errors.append(repr(error));raise
            s.experts.executor=observed
            await s.wake('wake',source='browser')
            turn=await s.new_turn(query='София, спроси у Кодекса, сравни два варианта')
            job=await s.experts.start_local(turn.query,'SOL_HIGH',turn)
            async with asyncio.timeout(3):
                while s.output_owner!='service_cue' or not s.output_generation_done:await asyncio.sleep(.005)
            cue=s.output_response
            await s.playback_started(cue);await s.playback_finished(cue)
            assert not s.input_open and not gate.is_set()
            async with asyncio.timeout(3):
                while s.output_response!=job.response_id:await asyncio.sleep(.005)
            assert job.state=='running' and len(calls)==1 and len(speech.texts)>=1
            await s.rotate()
            assert job.state=='running' and len(calls)==1
            gate.set();await job.worker
            assert job.state=='completed' and job.narration_complete and not job.playback_complete,execution_errors
            assert not s.input_open and s.output_generation_done
            await s.playback_started(job.response_id)
            await s.playback_finished(job.response_id)
            await asyncio.sleep(.25)
            assert s.input_open and job.playback_complete and 'Второй вариант' in job.played_text
            snapshot=s.experts.context_items()[0]
            assert snapshot['playback_complete'] and 'Первый вариант' in snapshot['result']['display_text']
            query=await s.new_turn(query='А второй вариант подробнее?')
            context=original.brain.memory.context(query.req)
            assert any('Второй вариант быстрее' in row['content'] for row in context['messages'])
            assert len(calls)==1
            assert not any(e['type']=='response.create' for sock in manager.provider.sockets for e in sock.sent)
            with original.brain.memory.connect() as db:assert db.execute('SELECT count(*) FROM expert_results').fetchone()[0]==0
        finally:
            await manager.shutdown();await original.shutdown()
    asyncio.run(run())
