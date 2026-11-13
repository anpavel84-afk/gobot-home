"""Prepared board B shares Brain but cannot borrow C/phone allowance. No API calls."""
import asyncio,time
import pytest
from gobot.board_realtime import BoardRealtime,BoardBudget,prepare_policy
from gobot.realtime_contract import RealtimeOffer,RealtimeCommand
from test_realtime_native import configured,Provider,SDP,tick
from gobot.device_contract import DeviceProfile,ScreenPreferences

def prepared(tmp_path,settings):
    original,_,_=configured(tmp_path,settings)
    root=tmp_path/'board-b';path=prepare_policy(root,'board')
    async def profile(_):return DeviceProfile(screen=ScreenPreferences(automatic_illustrations=False))
    original.profile_loader=profile
    p=Provider();manager=BoardRealtime(original,root,provider=p)
    return original,manager,p,path

def enable(path):
    from gobot.realtime_contract import RealtimePolicy
    p=RealtimePolicy.model_validate_json(path.read_text());path.write_text(p.model_copy(update={'enabled':True}).model_dump_json())

def offer(ident='board-b-1',**kw):
    return RealtimeOffer(session_id=ident,conversation_id='conv-board',sdp=SDP,
        device_id='board',client_id='board',consent=True,remember=False,
        requested_voice='marin',requested_model='gpt-realtime-2.1-mini',client_kind='device',**kw)

def test_preparation_disabled_and_never_rewrites_existing_policy(tmp_path,settings):
    original,b,p,path=prepared(tmp_path,settings)
    async def run():
        try:
            with pytest.raises(PermissionError):await b.start(offer())
            assert not p.creations and original.brain is b.brain and b.journal is original.journal
            assert b.owner_testing is original.owner_testing and b.budget.path!=original.budget.path
            before=path.read_bytes();prepare_policy(path.parent,'another-board');assert path.read_bytes()==before
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())

def test_board_forecast_read_does_not_require_or_enable_settings_writes(tmp_path,settings):
    import json
    from gobot.settings_tools import SettingsResult
    original,b,p,path=prepared(tmp_path,settings);enable(path);calls=[]
    async def execute(req,slots,**kwargs):
        calls.append(slots['operation']);return SettingsResult('Проверенный прогноз fixture.',evidence={'verified':True})
    original.brain.configuration.execute=execute
    async def run():
        try:
            await b.start(offer());s=b.sessions['board-b-1'];assert not s.can_configure_device()
            query='Какая погода завтра?';turn=await s.new_turn(query=query)
            await s.tool('forecast-read','gobot_tool',json.dumps({'query':query}),turn)
            assert calls==['weather_forecast'] and not s.can_configure_device()
            query='Установи громкость 50 процентов';turn=await s.new_turn(query=query)
            await s.tool('setting-write','gobot_tool',json.dumps({'query':query}),turn)
            assert calls==['weather_forecast']
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())

@pytest.mark.parametrize('patch',[{'client_id':'phone'},{'owner_test_binding':'phone'},
    {'remember':True},{'speaker_consent':True},{'personalization_mode':'confirmed_profile'},
    {'requested_model':'gpt-realtime-2.1'},{'requested_voice':'cedar'},{'expert_quota_consent':True}])
def test_cannot_elevate_board_or_change_selected_model(tmp_path,settings,patch):
    original,b,p,path=prepared(tmp_path,settings);enable(path)
    async def run():
        try:
            with pytest.raises(PermissionError):await b.start(offer().model_copy(update=patch))
            assert not p.creations
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())

def test_board_budget_eight_attempts_60_seconds_and_no_paid_retry(tmp_path):
    path=prepare_policy(tmp_path/'b','board');enable(path);budget=BoardBudget(path.parent)
    for i in range(8):
        policy=budget.reserve_session(f'manual-{i}',True,'board')
        assert (policy.max_session_seconds,policy.max_responses_per_session,policy.max_output_tokens)==(60,8,512)
    with pytest.raises((PermissionError,ValueError)):budget.reserve_session('ninth',True,'board')
    with pytest.raises((PermissionError,ValueError)):budget.reserve_session('manual-0',True,'board')
    assert budget.board_status()['reserved_estimate_usd']==1
    assert budget.board_status()['sessions_remaining']==0

def test_initial_vad_and_shared_lease_ignore_c_financial_orphan(tmp_path,settings):
    from gobot.live import LiveManager
    from test_live import Provider as LiveProvider,offer as live_offer
    original,b,p,path=prepared(tmp_path,settings);enable(path)
    live=LiveManager(original,provider=LiveProvider());original.live=live;b.live=live
    with live.budget.connect() as db:
        db.execute('INSERT INTO calls(id,scope,final,cleanup_attempted) VALUES(?,?,0,1)',('orphan','unconfirmed'))
    async def run():
        try:
            result=await b.start(offer());s=b.sessions['board-b-1']
            assert result['model']=='gpt-realtime-2.1-mini' and result['voice']=='marin'
            await s.listen_initial()
            updates=[v['session'].get('audio',{}).get('input',{}).get('turn_detection') for v in s.ws.sent if v['type']=='session.update']
            assert updates[-1]['create_response'] is False and updates[-1]['interrupt_response'] is False
            assert s.input_mode=='followup' and not s.offer.remember
            with pytest.raises(ValueError,match='voice_session_already_active'):
                await live.start(live_offer().model_copy(update={'device_id':'board','client_id':'board'}),DeviceProfile())
            assert not live.provider.creations and live.budget.pending()==[('orphan',None,1)]
            assert not original.budget.pending_calls()
        finally:await b.shutdown();await live.shutdown();await original.shutdown()
    asyncio.run(run())

def test_response_drain_ack_required_before_followup(tmp_path,settings):
    original,b,p,path=prepared(tmp_path,settings);enable(path)
    async def run():
        try:
            await b.start(offer());s=b.sessions['board-b-1'];await s.listen_initial()
            await s.handle({'type':'input_audio_buffer.committed','item_id':'input-1'});await tick()
            rid=s.current.active_response_id
            assert rid
            await s.handle({'type':'response.done','response':{'id':rid,'status':'completed','usage':{'total_tokens':4}}})
            await s.handle({'type':'output_audio_buffer.stopped','response_id':rid})
            with pytest.raises(ValueError,match='playback_not_finished'):
                await s.command(RealtimeCommand(command_id='too-early',action='followup'))
            for action in ['playback_started','playback_stopped']:
                await s.command(RealtimeCommand(command_id=action,action=action,response_id=rid))
            assert s.current.stored
            await s.command(RealtimeCommand(command_id='after-drain',action='followup'))
            assert s.input_mode=='followup'
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())

def test_opt_in_api_requires_auth_and_reports_only_b_pending_calls(tmp_path,settings):
    from fastapi import FastAPI,HTTPException,Request
    import httpx
    from gobot.board_realtime_api import attach_board_realtime
    original,b,p,path=prepared(tmp_path,settings);enable(path)
    app=FastAPI()
    async def auth(request:Request):
        if request.headers.get('authorization')!='Bearer fixture':raise HTTPException(401)
    attach_board_realtime(app,b,auth)
    async def run():
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://fixture') as client:
                assert (await client.get('/api/v1/voice-ab/b/status')).status_code==401
                headers={'authorization':'Bearer fixture'}
                status=(await client.get('/api/v1/voice-ab/b/status',headers=headers)).json()
                assert status['enabled'] and status['pending_hangups']==0 and not p.creations
                b.budget.register_call('unknown-b-call')
                status=(await client.get('/api/v1/voice-ab/b/status',headers=headers)).json()
                assert not status['enabled'] and status['admission_reason']=='board_previous_hangup_unconfirmed'
                body={'device_id':'phone','action':'close','command_id':'c'}
                assert (await client.post('/api/v1/voice-ab/b/sessions/any/command',headers=headers,json=body)).status_code==403
        finally:await b.shutdown();await original.shutdown()
    asyncio.run(run())
