"""Native Realtime protocol/component fixtures. No provider calls or paid audio."""
import asyncio,json,time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import httpx,pytest
from gobot.realtime_contract import RealtimeOffer,RealtimeCommand,RealtimePolicy,MODEL,audio_only_sdp,session_config,settings_applied
from gobot.realtime_budget import RealtimeBudget,estimate_usd
from gobot.realtime_provider import RealtimeProvider
from gobot.realtime import RealtimeManager
from gobot.device_contract import DeviceProfile
from gobot.brain import Service
from gobot.family import Family
from gobot.family_access import IdentityAccessManager

SDP='v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=-\r\nt=0 0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\na=rtpmap:111 opus/48000/2\r\n'

class Socket:
    def __init__(self):self.queue=asyncio.Queue();self.sent=[];self.config={};self.closed=False;self.n=0
    async def send(self,raw):
        obj=json.loads(raw);self.sent.append(obj)
        if obj['type']=='session.update':
            update=obj['session']
            if 'model' in update:self.config=update
            else:self.config['audio']['input'].update(update.get('audio',{}).get('input',{}))
            await self.queue.put({'type':'session.updated','session':json.loads(json.dumps(self.config))})
        if obj['type']=='response.create':
            self.n+=1;await self.queue.put({'type':'response.created','response':{'id':'resp_'+str(self.n)}})
        if obj['type']=='conversation.item.create' and obj.get('item',{}).get('id'):
            await self.queue.put({'type':'conversation.item.added','item':obj['item']})
    async def close(self):self.closed=True;await self.queue.put(None)
    def __aiter__(self):return self
    async def __anext__(self):
        v=await self.queue.get()
        if v is None:raise StopAsyncIteration
        return json.dumps(v)

class Provider:
    def __init__(self):self.creations=[];self.hangups=[];self.sockets=[];self.answer=SDP;self.pause=None;self.attach_error=False
    async def create(self,sdp,config,owner):
        self.creations.append((sdp,config,owner))
        if self.pause:await self.pause.wait()
        return 'rtc_fixture',self.answer
    @asynccontextmanager
    async def attach(self,ident):
        if self.attach_error:raise RuntimeError('fixture failure')
        sock=Socket();self.sockets.append(sock);yield sock
    async def hangup(self,ident):self.hangups.append(ident)

def offer(**kw):
    return RealtimeOffer(session_id='app-1',conversation_id='conv-1',sdp=SDP,device_id='browser-1',client_id='client-1',consent=True,**kw)

def configured(tmp_path,settings):
    budget=RealtimeBudget(tmp_path/'native-budget')
    p=RealtimePolicy(enabled=True,authorization='fixture-only',expires_at=time.time()+600,max_sessions=5)
    budget.policy_path.write_text(p.model_dump_json())
    brain=Service(settings);provider=Provider()
    async def profile(_):return DeviceProfile()
    manager=RealtimeManager(brain,provider=provider,budget=budget,profile_loader=profile,identity=IdentityAccessManager(Family(brain.memory)))
    return manager,provider,budget

async def tick():await asyncio.sleep(.01)
async def start(manager,req=None):
    await manager.start(req or offer());return manager.sessions[(req or offer()).session_id]
async def command(s,action,**kw):return await s.command(RealtimeCommand(command_id='cmd-'+str(len(s.commands)),action=action,**kw))

@pytest.mark.parametrize('tail',['m=application 9 UDP/DTLS/SCTP webrtc-datachannel\r\n','m=video 9 UDP/TLS/RTP/SAVPF 96\r\n','m=audio 0 UDP/TLS/RTP/SAVPF 111\r\n'])
def test_sdp_rejects_extra_media_including_rejected_sections(tail):
    with pytest.raises(ValueError):audio_only_sdp(SDP+tail)

@pytest.mark.parametrize('bad',['','v=1\r\n'+SDP,SDP.replace('audio 9','audio 0'),SDP+'a=sctp-port:5000\r\n',SDP+'\0'])
def test_sdp_malformed_or_data_channel_denied(bad):
    with pytest.raises(ValueError):audio_only_sdp(bad)

def test_model_voice_text_and_configuration_ack_are_exact():
    config=session_config(RealtimePolicy(),'private instructions',[],speak=False)
    assert config['model']==MODEL and config['audio']['output']['voice']=='marin'
    assert config['output_modalities']==['text'] and config['audio']['input']['turn_detection'] is None
    assert settings_applied(config,config)
    assert not settings_applied({'tracing':None},config)
    altered=json.loads(json.dumps(config));altered['audio']['output']['voice']='cedar'
    assert not settings_applied(altered,config)

def test_budget_is_off_by_default_and_failed_attempts_not_refunded(tmp_path):
    budget=RealtimeBudget(tmp_path)
    with pytest.raises(PermissionError):budget.reserve_session('a',True)
    p=RealtimePolicy(enabled=True,authorization='only-fixture',expires_at=time.time()+60,max_sessions=1,max_responses_per_session=1)
    budget.policy_path.write_text(p.model_dump_json())
    budget.reserve_session('a',True)
    with pytest.raises(ValueError):RealtimeBudget(tmp_path).reserve_session('a',True)
    with pytest.raises(PermissionError):budget.reserve_session('b',True)
    budget.reserve_response('a',p)
    with pytest.raises(PermissionError):budget.reserve_response('a',p)
    usage={'total_tokens':21,'input_token_details':{'audio_tokens':10},'text':'private must disappear'}
    assert budget.record('a','r',usage)
    assert not budget.record('a','r',usage)
    assert budget.total_tokens('a')==21
    with budget.connect() as c:assert 'private' not in c.execute('SELECT usage FROM usage').fetchone()[0]

def test_trial_budget_is_bound_to_one_client_and_excludes_other_spending(tmp_path):
    budget=RealtimeBudget(tmp_path)
    policy=RealtimePolicy(enabled=True,authorization='phone-trial-fixture',expires_at=time.time()+60,max_sessions=1,
                          allowed_client_id='phone-only',max_session_seconds=90,max_responses_per_session=4,max_output_tokens=384)
    budget.policy_path.write_text(policy.model_dump_json())
    with pytest.raises(PermissionError):budget.reserve_session('desktop-attempt',True,'desktop')
    assert budget.status()['sessions_reserved']==0
    p=budget.reserve_session('phone-attempt',True,'phone-only')
    assert p.input_transcription is False and not p.expert_jobs_allowed and not p.image_generation_allowed
    assert p.max_session_seconds==90 and p.max_responses_per_session==4

def test_token_cost_estimate_uses_reported_categories_not_seconds():
    assert estimate_usd({'input_token_details':{'text_tokens':1000000,'audio_tokens':1000000,'cached_tokens_details':{'text_tokens':100000,'audio_tokens':200000}},'output_token_details':{'text_tokens':1000000,'audio_tokens':1000000}})==pytest.approx(31.006)

def test_provider_fixed_endpoints_and_no_retry_or_key_in_result():
    async def run():
        requests=[]
        async def handler(req):
            requests.append(req)
            if req.url.path.endswith('/hangup'):return httpx.Response(204)
            return httpx.Response(201,text=SDP,headers={'Location':'/v1/realtime/calls/rtc_fixture'})
        p=RealtimeProvider(key_loader=lambda:'synthetic-fixture',client_factory=lambda:httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        call,answer=await p.create(SDP,session_config(RealtimePolicy(),'instructions',[]),'owner')
        assert call=='rtc_fixture' and answer==SDP
        assert len(requests)==1 and requests[0].headers['Authorization']=='Bearer synthetic-fixture'
        with pytest.raises(ValueError):await p.create(SDP+'m=application 9 UDP/DTLS/SCTP test\r\n',{},'owner')
        assert len(requests)==1
        await p.hangup(call);assert requests[-1].url.path=='/v1/realtime/calls/rtc_fixture/hangup'
    asyncio.run(run())

def test_session_setup_is_owned_and_same_session_serves_two_text_turns(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        try:
            s=await start(m);assert s.ready and s.ws
            with pytest.raises(KeyError):m.owned(s.id,'someone-else','client-1',None)
            with pytest.raises(ValueError):await m.start(offer())
            await command(s,'text',text='Привет, ГоБот!');await tick()
            await s.handle({'type':'response.done','response':{'id':'resp_1','status':'completed','usage':{'total_tokens':15}}})
            await command(s,'text',text='А что ещё?');await tick()
            assert len(p.creations)==1 and len(s.turns)==2
            assert [x['type'] for x in s.ws.sent].count('response.create')==2
            assert all(t.req and not t.req.remember for t in s.turns)
            assert all(t.req.device_id.startswith('realtime-guest:') for t in s.turns)
            assert not any(x in json.dumps(p.creations) for x in ('pin_hash','pin_salt','embedding'))
        finally:await m.shutdown()
    asyncio.run(run())

def test_no_legacy_voice_or_cli_for_native_turn(tmp_path,settings,monkeypatch):
    async def forbidden(*a,**kw):raise AssertionError('legacy path invoked')
    monkeypatch.setattr('gobot.audio.Speech.synth',forbidden,raising=False)
    monkeypatch.setattr('gobot.providers.bridge_stream',forbidden)
    async def run():
        m,p,b=configured(tmp_path,settings)
        try:
            s=await start(m);await command(s,'text',text='Привет!');await tick()
            assert any(x['type']=='response.create' for x in s.ws.sent)
        finally:await m.shutdown()
    asyncio.run(run())

def test_close_before_setup_is_tombstone_and_spends_nothing(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        await m.close('app-1','browser-1','client-1',None)
        with pytest.raises(ValueError):await m.start(offer())
        assert not p.creations and b.status()['sessions_reserved']==0
    asyncio.run(run())

def test_cancel_during_creation_hangs_up_late_call(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);p.pause=asyncio.Event()
        setup=asyncio.create_task(m.start(offer()));await tick()
        await m.close('app-1','browser-1','client-1',None);p.pause.set()
        with pytest.raises(RuntimeError):await setup
        assert p.hangups==['rtc_fixture']
        await m.shutdown();assert p.hangups==['rtc_fixture']
    asyncio.run(run())

@pytest.mark.parametrize('error',['sdp','sideband'])
def test_setup_failures_hangup_and_do_not_fallback(tmp_path,settings,error):
    async def run():
        m,p,b=configured(tmp_path,settings)
        if error=='sdp':p.answer=SDP+'m=application 9 UDP/DTLS/SCTP test\r\n'
        else:p.attach_error=True
        with pytest.raises((ValueError,RuntimeError)):await m.start(offer())
        assert p.hangups==['rtc_fixture'] and len(p.creations)==1
    asyncio.run(run())

def test_generation_done_is_not_playback_and_unheard_tail_not_history(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        try:
            s=await start(m);await command(s,'text',text='Обычный вопрос');await tick()
            await s.handle({'type':'response.output_audio_transcript.delta','response_id':'resp_1','delta':'Полный ответ.'})
            await s.handle({'type':'output_audio_buffer.started','response_id':'resp_1'})
            await s.handle({'type':'response.done','response':{'id':'resp_1','status':'completed'}})
            assert not s.current.stored
            await command(s,'interrupt');assert s.current.cancelled
            row=m.brain.memory.transient[s.current.id]
            assert row['status']=='cancelled' and row['result']==''
            assert not any(x['type']=='turn_complete' for x in s.events)
        finally:await m.shutdown()
    asyncio.run(run())

def test_client_and_server_playback_ack_both_required_and_followup_no_response(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        try:
            s=await start(m);await command(s,'text',text='Обычный вопрос');await tick()
            await s.handle({'type':'response.output_audio_transcript.delta','response_id':'resp_1','delta':'Короткий ответ.'})
            await s.handle({'type':'output_audio_buffer.started','response_id':'resp_1'})
            await s.handle({'type':'response.done','response':{'id':'resp_1','status':'completed'}})
            await command(s,'playback_started',response_id='resp_1')
            await s.handle({'type':'output_audio_buffer.stopped','response_id':'resp_1'})
            assert not s.current.stored
            await command(s,'playback_stopped',response_id='resp_1')
            assert s.current.stored and not s.current.cancelled
            before=sum(x['type']=='response.create' for x in s.ws.sent)
            await command(s,'followup')
            assert s.ws.config['audio']['input']['turn_detection']['create_response'] is False
            assert sum(x['type']=='response.create' for x in s.ws.sent)==before
            s.followup_deadline=time.monotonic()-.1
            for _ in range(100):
                if s.closed:break
                await asyncio.sleep(.02)
            assert s.closed
            assert sum(x['type']=='response.create' for x in s.ws.sent)==before
        finally:await m.shutdown()
    asyncio.run(run())

def test_no_thanks_closes_without_response_or_legacy_tts(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        s=await start(m);await command(s,'text',text='Нет, спасибо');await tick()
        assert s.closed and not any(x['type']=='response.create' for x in s.ws.sent)
        await m.shutdown()
    asyncio.run(run())

def test_tool_is_idempotent_and_model_cannot_mutate_unconfirmed_request(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        try:
            s=await start(m);await command(s,'text',text='Привет!');await tick()
            event={'type':'response.function_call_arguments.done','call_id':'call_tool','name':'gobot_tool','arguments':json.dumps({'query':'Поставь таймер на 5 минут'})}
            await s.handle(event);await s.handle(event);await tick()
            outputs=[x for x in s.ws.sent if x.get('item',{}).get('type')=='function_call_output']
            assert len(outputs)==1 and outputs[0]['item']['call_id']=='call_tool'
            with m.brain.memory.connect() as c:assert c.execute('SELECT count(*) FROM timers').fetchone()[0]==0
        finally:await m.shutdown()
    asyncio.run(run())

def test_family_false_match_pin_and_other_profiles_never_preload_private_data(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        family=m.identity.family
        user=family.create('Synthetic Adult','adult','fixture-pin')
        m.brain.memory.add_fact('personal:'+user['id'],'PRIVATE_CANARY_NOT_FOR_NATIVE',True)
        request=offer().model_copy(update={'device_id':'personal:'+user['id'],'profile_epoch':'confirmed-fixture'})
        access=m.identity.native(request,{'state':'recognized','profile_id':user['id'],'personal_authorized':True})
        assert not access.private_access and not access.native_identity_verified and access.child_restrictions
        try:
            s=await start(m,request)
            assert 'PRIVATE_CANARY' not in json.dumps(p.creations)
            assert s.access.effective_scope!='personal:'+user['id']
            await command(s,'text',text='Что ты обо мне знаешь?');await tick()
            with m.brain.memory.connect() as c:assert c.execute('SELECT count(*) FROM messages').fetchone()[0]==0
            other=m.identity.native(request.model_copy(update={'session_id':'different'}))
            assert other.effective_scope!=access.effective_scope and IdentityAccessManager.invalidates(access,other)
        finally:await m.shutdown()
    asyncio.run(run())

def test_native_timer_paraphrase_uses_same_validated_action_and_device_state(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        try:
            s=await start(m);await command(s,'text',text='Поставь таймер на 5 минут');await tick()
            await s.tool('timer-call','gobot_tool',json.dumps({'query':'Поставь таймер на пять минут'}),s.current)
            with m.brain.memory.connect() as c:
                row=c.execute('SELECT device_id,status FROM timers').fetchone()
                assert row['device_id']=='realtime-device:client-1' and row['status']=='running'
            assert any(x['type']=='visual_response' and x['data']['presentation']['type']=='timer_widget' for x in s.events)
        finally:await m.shutdown()
    asyncio.run(run())

def test_native_report_retains_only_numeric_stage_times_and_usage(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        s=await start(m)
        await command(s,'text',text='SYNTHETIC_PRIVATE_QUERY');await tick()
        turn=s.current
        await s.handle({'type':'response.output_audio_transcript.delta','response_id':'resp_1','delta':'SYNTHETIC_PRIVATE_ANSWER'})
        await s.handle({'type':'output_audio_buffer.started','response_id':'resp_1'})
        await command(s,'playback_started',response_id='resp_1')
        b.record(s.id,'resp_1',{'total_tokens':12,'input_tokens':8,'output_tokens':4,'private':'SECRET'})
        turn.timings.update({'private':'SECRET','unknown_number':123})
        await m.shutdown()
        report=b.status()['latest_report']
        assert report['reported_tokens']==12 and report['usage_responses_received']==1
        assert report['response_attempts']==1
        times=report['turns_ms'][0]
        assert 0<=times['input_ended']<=times['response_created']<=times['client_playback']
        assert 'PRIVATE' not in json.dumps(report) and 'SECRET' not in json.dumps(report)
        assert 'unknown_number' not in times and report['contains_conversation_content'] is False
    asyncio.run(run())

def test_phone_trial_denies_other_clients_before_provider_and_clamps_generators(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        policy=b.policy().model_copy(update={'allowed_client_id':'client-1'})
        b.policy_path.write_text(policy.model_dump_json())
        profile=DeviceProfile()
        profile.screen=profile.screen.model_copy(update={'generation_allowed':True,'generation_consent':True,'generation_mode':'helpful','generation_daily_limit':3})
        async def load(_):return profile
        m.profile_loader=load
        try:
            with pytest.raises(PermissionError):await m.start(offer().model_copy(update={'client_id':'other-client'}))
            assert not p.creations and b.status()['sessions_reserved']==0
            s=await start(m)
            assert [t['name'] for t in s.config['tools']]==['gobot_tool']
            assert not s.profile.screen.generation_allowed and s.profile.screen.generation_mode=='off'
            assert profile.screen.generation_allowed and profile.screen.generation_daily_limit==3
        finally:await m.shutdown()
    asyncio.run(run())

def test_native_close_reason_and_provider_error_codes_survive_cleanup_without_raw_data(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        s=await start(m);await command(s,'text',text='Synthetic question');await tick()
        await s.interrupt()
        cancel=next(e for e in reversed(s.ws.sent) if e['type']=='response.cancel')
        errors=lambda:[e for e in s.events if e['type']=='error']
        await s.handle({'type':'error','error':{'code':'response_cancel_not_active','event_id':cancel['event_id'],'message':'SECRET_RAW_PROVIDER_MESSAGE'}})
        assert not errors() and any(e['type']=='warning' for e in s.events)
        # A matching code alone is insufficient: it must refer to our own cancel event.
        await s.handle({'type':'error','error':{'code':'response_cancel_not_active','event_id':'unrelated-event','message':'SECRET_RAW_PROVIDER_MESSAGE'}})
        assert errors()
        await m.close(s.id,s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,'provider_error')
        await m.close(s.id,s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,'client_closed')
        report=b.latest_report()
        assert report['close_reason']=='provider_error' and s.close_reason=='provider_error'
        assert report['provider_errors']=={'response_cancel_not_active':2}
        assert report['lifecycle_ms']['lifetime']>=0 and 'SECRET' not in json.dumps(report)
        assert s.hangup_confirmed and len(p.hangups)==1
    asyncio.run(run())

def test_native_response_limit_closes_with_explicit_reason_and_no_extra_provider_call(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        b.policy_path.write_text(b.policy().model_copy(update={'max_responses_per_session':1}).model_dump_json())
        s=await start(m);await command(s,'text',text='One response');await tick()
        s.generating=False;s.response_requested=False;s.speaking=False
        await s.response()
        assert s.closed and s.close_reason=='response_budget_exhausted'
        assert sum(e['type']=='response.create' for e in s.ws.sent)==1
        assert b.latest_report()['close_reason']=='response_budget_exhausted'
        assert b.status()['sessions_remaining']==4
        await m.shutdown()
    asyncio.run(run())

def test_truncated_native_audio_allows_followup_only_after_playback_without_claiming_complete_history(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        s=await start(m);await command(s,'text',text='Synthetic question');await tick()
        await s.handle({'type':'response.output_audio_transcript.delta','response_id':'resp_1','delta':'Partial answer, cut by token budget'})
        await s.handle({'type':'output_audio_buffer.started','response_id':'resp_1'})
        await s.handle({'type':'response.done','response':{'id':'resp_1','status':'incomplete','status_details':{'reason':'max_output_tokens'}}})
        assert not s.current.stored and not s.closed
        await command(s,'playback_started',response_id='resp_1')
        await s.handle({'type':'output_audio_buffer.stopped','response_id':'resp_1'})
        await command(s,'playback_stopped',response_id='resp_1')
        assert s.current.stored and s.current.truncated and not s.current.cancelled
        assert m.brain.memory.transient[s.current.id]['status']=='incomplete'
        assert any(e['type']=='turn_complete' and e['data']['incomplete'] for e in s.events)
        creates=sum(e['type']=='response.create' for e in s.ws.sent)
        await command(s,'followup')
        assert sum(e['type']=='response.create' for e in s.ws.sent)==creates
        await m.shutdown()
        assert b.latest_report()['completion_counts']=={'max_output_tokens':1}
    asyncio.run(run())

def test_reasoning_only_limit_does_not_start_followup_or_retry(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        s=await start(m);await command(s,'text',text='Synthetic question');await tick()
        await s.handle({'type':'response.done','response':{'id':'resp_1','status':'incomplete','status_details':{'reason':'max_output_tokens'}}})
        assert not s.closed and s.current.cancelled
        assert any(e['type']=='turn_incomplete' for e in s.events)
        assert not any(e['type']=='turn_complete' for e in s.events)
        assert sum(e['type']=='response.create' for e in s.ws.sent)==1
        with pytest.raises(ValueError):await command(s,'followup')
        await m.shutdown()
    asyncio.run(run())

def test_no_thanks_declines_expert_proposal_without_closing_or_starting_cli(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings)
        try:
            s=await start(m);await command(s,'text',text='Сравни архитектуры');await tick()
            proposal=s.experts.propose('Сравни архитектуры','ARGON_DEEP',s.current)
            before=sum(x['type']=='response.create' for x in s.ws.sent)
            await command(s,'text',text='Нет, спасибо');await tick()
            assert not s.closed and s.experts.pending.state=='cancelled'
            assert sum(x['type']=='response.create' for x in s.ws.sent)==before
            assert any(x['type']=='tool_status' and x['data'].get('status')=='pending_declined' for x in s.events)
        finally:await m.shutdown()
    asyncio.run(run())
