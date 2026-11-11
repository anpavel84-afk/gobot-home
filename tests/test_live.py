"""Live-specific protocol fixtures, no paid provider/model/audio calls."""
import asyncio,json,time
from contextlib import asynccontextmanager
import pytest,httpx
import subprocess
from test_realtime_native import configured,SDP
from gobot.live import LiveManager,short_chunks
from gobot.live_contract import LiveOffer,LiveCommand,live_sdp,live_config,live_applied
from gobot.live_timeline import ConversationTimeline
from gobot.live_provider import LiveProvider
from gobot.owner_testing import OwnerTestPolicy
from gobot.device_contract import DeviceProfile,ScreenPreferences
from gobot.expert_store import ExpertPolicy,ExpertBudget

LIVE_SDP=SDP+'m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\na=sctp-port:5000\r\n'
class Socket:
    def __init__(self,config):
        self.q=asyncio.Queue();self.sent=[];self.q.put_nowait({'type':'session.started','event_id':'started','session':config})
    async def send(self,raw):
        event=json.loads(raw);self.sent.append(event);kind=event['type']
        assert kind not in {'session.start','response.create','input_audio_buffer.commit','conversation.item.create'}
        if kind=='session.close':await self.q.put({'type':'session.closed','event_id':'closed','usage':{'seconds':15},'reason':'close_requested'})
        elif kind.endswith('.append'):
            assert 'delegation_id' in event and len(event['content'].encode())<=320
            await self.q.put({'type':kind+'ed','event_id':'ack-'+event['event_id'],'client_event_id':event['event_id']})
        elif kind in {'session.input_audio.mute','session.input_audio.unmute'}:await self.q.put({'type':kind+'d','event_id':'ack-'+event['event_id'],'client_event_id':event['event_id']})
    def __aiter__(self):return self
    async def __anext__(self):return json.dumps(await self.q.get())
    async def close(self):pass
class Provider:
    def __init__(self):self.creations=[];self.sockets=[];self.cleanup_calls=[]
    async def create(self,sdp,config):self.creations.append(config);return 'opaque-provider-session',LIVE_SDP
    @asynccontextmanager
    async def attach(self,ident):
        s=Socket(self.creations[-1]);self.sockets.append(s);yield s
    async def cleanup(self,ident):self.cleanup_calls.append(ident);return {'type':'session.closed','usage':{'seconds':15},'reason':'close_requested'}

def offer(**kw):return LiveOffer(session_id='live-app-1',conversation_id='conv-1',sdp=LIVE_SDP,device_id='browser-1',client_id='client-1',consent=True,expert_quota_consent=True,**kw)
async def native(tmp_path,settings,**kw):
    rt,_,b=configured(tmp_path,settings)
    rt.owner_testing.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='synthetic',allowed_client_id='client-1',live_enabled=True).model_dump_json())
    p=Provider();m=LiveManager(rt,provider=p);rt.live=m
    s,_=await m.start(offer(**kw),DeviceProfile(screen=ScreenPreferences(automatic_illustrations=False)))
    return m,p,s

def test_live_sdp_is_scoped_and_realtime_is_not_relaxed():
    from gobot.realtime_contract import audio_only_sdp
    assert live_sdp(LIVE_SDP)==LIVE_SDP
    with pytest.raises(ValueError):audio_only_sdp(LIVE_SDP)
    for extra in ['m=video 9 UDP/TLS/RTP/SAVPF 96\r\n','m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n']:
        with pytest.raises(ValueError):live_sdp(LIVE_SDP+extra)

def test_timeline_replay_separate_speakers_and_intentional_repeated_speech():
    t=ConversationTimeline()
    event={'type':'session.input_transcript.delta','event_id':'one','start_ms':0,'end_ms':1000,'delta':'Поставь таймер на пять секунд'}
    assert t.add(event) and not t.add(event)
    t.add({'type':'session.output_transcript.delta','event_id':'out','start_ms':500,'end_ms':1200,'delta':'Слушаю'})
    first=t.context('real-delegation-1',1000);assert first.query==event['delta']
    assert t.add({**event,'event_id':'two','start_ms':4000,'end_ms':5000})
    second=t.context('real-delegation-2',5000)
    assert second.query==first.query and second.interaction_id!=first.interaction_id
    assert ConversationTimeline().context('pending',1000) is None

def test_live_creation_append_close_and_duration_accounting(tmp_path,settings):
    async def run():
        m,p,s=await native(tmp_path,settings)
        try:
            assert s.ready and s.config['model']=='gpt-live-1' and s.config['store'] is False
            assert s.config['client']['data_channel']['allowed_client_events']==[]
            assert 'turn_detection' not in s.config['audio'] and 'tools' not in s.config
            await s.append('commentary','Результат 42. '*80,'real-delegation-id')
            appends=[e for e in s.ws.sent if e['type']=='session.commentary.append'];assert len(appends)>1
            assert all(e['delegation_id']=='real-delegation-id' for e in appends)
            await s.handle({'type':'session.usage.updated','event_id':'usage-12','usage':{'seconds':12}})
            await s.handle({'type':'session.usage.updated','event_id':'usage-15','usage':{'seconds':15}})
            assert m.budget.status()['voice_seconds_observed']==15
            await s.command(LiveCommand(command_id='mute-1',action='mute'))
            assert not s.closed
        finally:await m.shutdown();await m.realtime.shutdown()
        assert s.final_usage_confirmed and m.budget.status()['unconfirmed_sessions']==0
        assert p.cleanup_calls==[]
    asyncio.run(run())

def test_live_timer_delegation_is_real_action_and_replay_does_not_duplicate(tmp_path,settings):
    async def run():
        m,p,s=await native(tmp_path,settings)
        try:
            for event in [
                {'type':'session.input_transcript.delta','event_id':'speech','start_ms':0,'end_ms':1000,'delta':'Поставь таймер на пять секунд'},
                {'type':'session.delegation.created','event_id':'delegated','offset_ms':1000,'delegation':{'id':'real-delegation','target':'client'}}]:await s.handle(event)
            await s.delegation_tasks['real-delegation']
            await s.handle({'type':'session.delegation.created','event_id':'replayed-other-event','offset_ms':1000,'delegation':{'id':'real-delegation','target':'client'}})
            with m.brain.memory.connect() as c:assert c.execute('SELECT count(*) FROM timers').fetchone()[0]==1
            assert any(e['type']=='visual_response' for e in s.events)
            assert any(e['type']=='session.commentary.append' and e['delegation_id']=='real-delegation' for e in s.ws.sent)
        finally:await m.shutdown();await m.realtime.shutdown()
    asyncio.run(run())

def test_client_delegation_expert_uses_real_delegation_not_function_call_output(tmp_path,settings):
    async def run():
        m,p,s=await native(tmp_path,settings)
        budget=s.experts.budget
        budget.policy_path.write_text(ExpertPolicy(enabled=True,authorization='expert-fixture',allowed_client_id='client-1',allowed_profiles=['ARGON_DEEP'],expires_at=time.time()+120,max_sessions=1).model_dump_json())
        calls=[]
        async def execute(job):calls.append(job);return 'Проверяемый вывод 42. Это оценка.'
        s.experts.executor=execute;s.experts.admission=lambda _:{'available':True}
        try:
            turn=await s.interaction('Спроси Argon: сравни два варианта','interaction-1')
            await s.route(turn,'application-operation','real-provider-delegation')
            job=s.experts.pending;assert job and job.worker;await job.worker
            assert len(calls)==1 and job.call_id is None and job.delegation_id=='real-provider-delegation'
            assert job.operation_id and job.state=='completed'
            assert not any(e['type']=='conversation.item.create' for e in s.ws.sent)
            assert any(e['type']=='expert_result' for e in s.events)
            assert any(e['type']=='session.commentary.append' and e['delegation_id']=='real-provider-delegation' for e in s.ws.sent)
        finally:await m.shutdown();await m.realtime.shutdown()
    asyncio.run(run())

def test_live_provider_fixed_api_and_no_realtime_wire_contract():
    async def run():
        requests=[]
        async def handler(request):
            requests.append(request);return httpx.Response(201,json={'session':{'id':'opaque_id'},'transport':{'sdp':LIVE_SDP}})
        p=LiveProvider(key_loader=lambda:'synthetic-key',client_factory=lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        ident,sdp=await p.create(LIVE_SDP,live_config('marin','instructions',[]))
        assert ident=='opaque_id' and sdp==LIVE_SDP
        assert str(requests[0].url)=='https://api.openai.com/v1/live/sessions'
        body=json.loads(requests[0].content);assert body['session']['delegation']=={'type':'client'}
        assert body['transport']['type']=='webrtc'
    asyncio.run(run())

def test_live_production_browser_full_duplex_cleanup():
    subprocess.run(['node','tests/live_browser.cjs'],check=True,capture_output=True,text=True)

def test_live_cancel_setup_closes_known_provider_once(tmp_path,settings):
    async def run():
        rt,_,_=configured(tmp_path,settings)
        rt.owner_testing.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='synthetic',allowed_client_id='client-1',live_enabled=True).model_dump_json())
        entered=asyncio.Event();release=asyncio.Event()
        class SlowProvider(Provider):
            async def create(self,sdp,config):
                entered.set();await release.wait();return await super().create(sdp,config)
        p=SlowProvider();m=LiveManager(rt,provider=p);rt.live=m
        starting=asyncio.create_task(m.start(offer(),DeviceProfile()))
        await entered.wait()
        closing=asyncio.create_task(m.close('live-app-1','browser-1','client-1',None,'user_stop'))
        await asyncio.sleep(.01);release.set();await closing
        with pytest.raises(RuntimeError,match='live_setup_cancelled'):await starting
        assert p.cleanup_calls==['opaque-provider-session'] and len(p.creations)==1
        assert m.sessions['live-app-1'].closed and m.budget.status()['unconfirmed_sessions']==0
        await m.close('live-app-1','browser-1','client-1',None)
        assert len(p.cleanup_calls)==1
        await rt.shutdown()
    asyncio.run(run())

def test_live_new_profile_closes_and_clears_ram_without_history_transfer(tmp_path,settings):
    async def run():
        m,p,s=await native(tmp_path,settings)
        await s.interaction('Синтетический личный текст','speech-100')
        await s.handle({'type':'session.output_transcript.delta','event_id':'answer','start_ms':200,'end_ms':1000,'delta':'Синтетический ответ'})
        await m.invalidate_principal('browser-1')
        assert s.closed and not s.timeline.segments and s.current.req is None and not s.current.answer
        with m.brain.memory.connect() as c:assert c.execute('SELECT count(*) FROM turns').fetchone()[0]==0
        await m.realtime.shutdown()
    asyncio.run(run())
