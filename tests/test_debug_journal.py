"""Private diagnostic journal acceptance. Synthetic texts, fake provider IO, no paid calls."""
import asyncio,json,sqlite3,sys,time
from types import SimpleNamespace
from pathlib import Path
import httpx,pytest
from fastapi import FastAPI
from gobot.debug_journal import DebugJournal,clean
from gobot.debug_journal_api import attach_brain_journal
from gobot.owner_testing import OwnerTesting,OwnerTestPolicy
from gobot.weather import WeatherClient,WeatherError
from gobot.device_contract import WeatherPreferences
from gobot.settings_tools import SettingsTools
from test_weather_timer_expansion import forecast_source


def setup(tmp_path,enabled=True,clock=time.time):
    owner=OwnerTesting(tmp_path/'owner')
    owner.policy_path.write_text(OwnerTestPolicy(authorization='synthetic',allowed_client_id='bound',debug_journal_enabled=enabled).model_dump_json())
    # A reversible fixture codec, NOT evidence of encryption; real DPAPI below.
    j=DebugJournal(tmp_path/'journal',owner,protect=lambda x:x[::-1],unprotect=lambda x:x[::-1],clock=clock)
    return owner,j


def put(j,*,client='client',epoch='epoch',session='session',**kw):
    return j.append(binding='bound',owner='owner',client=client,epoch=epoch,session=session,engine='C',kind='user_input',data={'text':'SYNTHETIC question'},**kw)


def test_explicit_consent_bound_device_scope_epoch_delete_and_off(tmp_path):
    async def run():
        owner,j=setup(tmp_path,False)
        assert not put(j) and not j.path.exists()
        owner.update('bound',{'debug_journal_enabled':True})
        assert not j.append(binding='other',owner='owner',client='client',session='s',engine='C',kind='error')
        assert put(j) and put(j,client='other') and put(j,epoch='other')
        assert await j.flush()
        key=j.scope('owner','client','epoch')
        assert len(j.read(key,'session')['events'])==1
        assert not j.read(key,'wrong-session')['events']
        assert j.clear(key)==1
        assert j.sessions(j.scope('owner','other','epoch'))
        owner.update('bound',{'debug_journal_enabled':False})
        assert not put(j)
        await j.close()
    asyncio.run(run())


def test_redaction_limits_no_audio_context_or_credentials():
    value=clean({'text':'Bearer synthetic-token https://example.org/a?secret=private sk-'+('x'*24),
        'headers':{'Authorization':'secret'},'audio':'PCM','embeddings':[1,2],
        'instructions':'PRIVATE PROMPT','context':'PRIVATE ARCHIVE','latitude':0,
        'nested':{'password':'secret','ok':'visible'},'huge':'x'*20000,'nan':float('nan')})
    assert set(value)=={'text','nested','huge','nan'}
    assert 'synthetic-token' not in value['text'] and '?secret=' not in value['text']
    assert 'sk-' not in value['text'] and value['nested']=={'ok':'visible'}
    assert len(value['huge'])<16100 and value['nan']=='[nonfinite]'


def test_record_order_pagination_retention_caps_and_failsoft(tmp_path):
    async def run():
        now=[time.time()];owner,j=setup(tmp_path,clock=lambda:now[0])
        for n in range(205):assert put(j,turn=str(n))
        assert await j.flush()
        key=j.scope('owner','client','epoch');latest=j.read(key,'session')
        assert len(latest['events'])==200 and latest['events'][0]['turn_id']=='5'
        older=j.read(key,'session',before=latest['next_before'])
        assert len(older['events'])==5 and older['events'][0]['turn_id']=='0'
        assert not j.append(binding='bound',owner='owner',client='client',session='s',engine='C',kind='audio_chunk',data={'data':'raw'})
        now[0]+=8*86400
        assert not j.sessions(key)
        with j.connect() as c:assert c.execute('SELECT count(*) FROM events').fetchone()[0]==0
        j.protect=lambda _:(_ for _ in ()).throw(OSError('SYNTHETIC private disk error'))
        assert put(j);assert await j.flush()
        assert j.status('bound')['error']=='journal_write_failed' and j.dropped==1
        # Bad policy or unavailable disk cannot propagate into the voice loop.
        owner.policy_path.write_text('invalid')
        assert not put(j) and j.last_error=='journal_enqueue_failed'
        await j.close()
    asyncio.run(run())


@pytest.mark.skipif(sys.platform!='win32',reason='Real Windows DPAPI only')
def test_real_windows_dpapi_roundtrip_without_plaintext_at_rest(tmp_path):
    async def run():
        owner,j=setup(tmp_path);await j.close()
        j=DebugJournal(tmp_path/'real',owner)
        assert put(j);assert await j.flush()
        with j.connect() as c:
            sealed=c.execute('SELECT sealed FROM events').fetchone()[0]
        assert b'SYNTHETIC question' not in sealed and b'SYNTHETIC question' not in j.path.read_bytes()
        assert j.read(j.scope('owner','client','epoch'),'session')['events'][0]['data']['text']=='SYNTHETIC question'
        await j.close()
    asyncio.run(run())


def test_internal_journal_api_auth_binding_epoch_and_delete(tmp_path):
    async def run():
        owner,j=setup(tmp_path);assert put(j);await j.flush()
        app=FastAPI();attach_brain_journal(app,SimpleNamespace(journal=j,owner_testing=owner),lambda:None)
        identity={'device_id':'owner','client_id':'client','profile_epoch':'epoch','binding':'bound'}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),base_url='http://test') as c:
            assert (await c.get('/api/v1/debug-journal',params={**identity,'binding':'other'})).status_code==403
            assert len((await c.get('/api/v1/debug-journal',params=identity)).json()['sessions'])==1
            assert not (await c.get('/api/v1/debug-journal/session',params={**identity,'profile_epoch':'new'})).json()['events']
            assert (await c.get('/api/v1/debug-journal/session',params={**identity,'before':-1})).status_code==422
            assert (await c.post('/api/v1/debug-journal/clear',json={**identity,'other_profile':True})).status_code==422
            assert (await c.post('/api/v1/debug-journal/clear',json=identity)).json()['deleted']==1
        await j.close()
    asyncio.run(run())


def test_live_journal_survives_close_and_records_actual_weather_failure_and_recovery(tmp_path,settings):
    from test_live_native_tools import start,say
    async def run():
        m,s=await start(tmp_path,settings);j=m.journal
        j.protect=lambda x:x[::-1];j.unprotect=lambda x:x[::-1]
        m.realtime.owner_testing.update(s.owner_test_binding,{'debug_journal_enabled':True})
        m.brain.configuration.devices.update('browser-1@fixture',{'weather':{'enabled':True,'location_name':'Synthetic','latitude':0,'longitude':0}})
        class FailedWeather:
            async def forecast(self,*a,**k):raise WeatherError('weather_source_timeout')
        m.brain.configuration.weather=FailedWeather()
        sid=s.id;key=j.scope(s.offer.device_id,s.offer.client_id,s.offer.profile_epoch)
        try:
            await say(s,'Какая погода завтра?',0,answer='SYNTHETIC answer')
            await s.finish_turn(True)
            m.brain.configuration.weather=forecast_source()[0]
            await say(s,'А завтра там же?',5000)
        finally:await m.shutdown();await m.realtime.shutdown()
        events=j.read(key,sid)['events']
        failed=[e for e in events if e['kind']=='local_tool_status' and e['data'].get('state')=='failed']
        assert failed and failed[0]['data']['reason']=='weather_source_timeout' and not failed[0]['data']['has_source']
        assert any(e['kind']=='tool_result' and e['data']['evidence'].get('verified') is True for e in events)
        turns=[e for e in events if e['kind']=='dialogue_turn']
        assert any(e['data']['question']=='Какая погода завтра?' and e['data']['playback']=='client_playback_reported' for e in turns)
        assert any(e['kind']=='closed' for e in events)
        # Separate diagnostics never opt the request into semantic history.
        with m.brain.memory.connect() as c:
            assert c.execute('SELECT count(*) FROM turns').fetchone()[0]==0
    asyncio.run(run())


def test_invalid_weather_is_evicted_then_next_user_request_fetches_fresh():
    async def run():
        client,calls,_=forecast_source(lambda d:d['temperature_2m_max'].__setitem__(0,None))
        place=WeatherPreferences(enabled=True,location_name='Synthetic',latitude=0,longitude=0)
        with pytest.raises(WeatherError,match='weather_invalid_data'):await client.forecast(place,offset=1,days=1)
        assert len(calls)==1 and not client.cache
        valid,valid_calls,_=forecast_source();client.transport=valid.transport
        assert len((await client.forecast(place,offset=1,days=1))['days'])==1
        await client.forecast(place,offset=1,days=1)
        assert len(valid_calls)==1 # Success cached; no paid/automatic repair calls.
    asyncio.run(run())


@pytest.mark.parametrize('status,code',[(429,'weather_provider_rate_limit'),(403,'weather_source_rejected'),(503,'weather_source_unavailable')])
def test_weather_source_errors_are_specific_without_retry(status,code):
    async def run():
        calls=[]
        def handle(req):calls.append(req);return httpx.Response(status)
        client=WeatherClient(transport=httpx.MockTransport(handle))
        with pytest.raises(WeatherError,match=code):await client.forecast(WeatherPreferences(enabled=True,location_name='Synthetic',latitude=0,longitude=0))
        assert len(calls)==1
        result=SettingsTools.weather_failure(WeatherError(code),'weather_forecast')
        assert result.evidence['reason']==code and result.evidence['abstained'] and result.evidence['verified'] is False
    asyncio.run(run())


def test_realtime_and_legacy_share_journal_without_native_duplicate_a_turn(tmp_path,settings):
    from test_realtime_native import configured,start
    from gobot.models import ChatRequest,event
    async def run():
        m,_,_=configured(tmp_path,settings);j=m.journal
        j.protect=lambda x:x[::-1];j.unprotect=lambda x:x[::-1]
        m.owner_testing.policy_path.write_text(OwnerTestPolicy(authorization='synthetic',allowed_client_id='client-1',debug_journal_enabled=True).model_dump_json())
        s=await start(m)
        try:
            s.preference_item='synthetic-preferences'
            await s.send({'type':'conversation.item.create','item':{'id':s.preference_item,'type':'message',
                'content':[{'type':'input_text','text':'SYNTHETIC_PRIVATE_PREFERENCES'}]}})
            turn=await s.new_turn(query='SYNTHETIC ordinary question')
            turn.answer='SYNTHETIC answer';await s.finish(turn,True)
            req=ChatRequest(text='SYNTHETIC legacy question',device_id='browser-1',client_id='client-1',remember=False)
            await m.brain.prepare(req);event(req,'final',text='SYNTHETIC legacy answer',provider='fixture')
            await j.flush()
            native=j.read(j.scope(s.offer.device_id,s.offer.client_id,s.offer.profile_epoch),s.id)['events']
            assert any(e['engine']=='B' and e['kind']=='dialogue_turn' for e in native)
            assert not any(e['engine']=='A' for e in native)
            assert 'SYNTHETIC_PRIVATE_PREFERENCES' not in json.dumps(native)
            legacy=j.read(j.scope(req.device_id,req.client_id,req.profile_epoch),req.conversation_id)['events']
            assert [e['kind'] for e in legacy]==['user_input','final']
        finally:await m.shutdown()
    asyncio.run(run())


def test_gateway_ignores_browser_scope_and_uses_authenticated_identity(tmp_path,monkeypatch):
    from gobot.debug_journal_api import attach_gateway_journal
    from fastapi import Request
    from gobot.device_store import DeviceStore
    async def run():
        app=FastAPI();devices=DeviceStore(tmp_path/'devices');seen=[]
        async def subject(request):return 'confirmed-person'
        def scoped(request,owner):return owner+'@'+request.client.host
        attach_gateway_journal(app,SimpleNamespace(api_token='SYNTHETIC'),devices,subject,scoped,lambda *_:'current-epoch')
        real_client=httpx.AsyncClient
        def handle(req):seen.append(req);return httpx.Response(200,json={'events':[]})
        monkeypatch.setattr('gobot.debug_journal_api.httpx.AsyncClient',lambda **kw:real_client(transport=httpx.MockTransport(handle),**kw))
        async with real_client(transport=httpx.ASGITransport(app,client=('127.0.0.1',123)),base_url='http://test') as c:
            assert (await c.get('/api/debug-journal/session?device_id=other&client_id=other&profile_epoch=other')).status_code==200
            params=seen[-1].url.params
            assert params['device_id']=='confirmed-person' and params['profile_epoch']=='current-epoch'
            assert params['client_id']==devices.profile('confirmed-person@127.0.0.1').client_id
            assert (await c.post('/api/debug-journal/clear',json={'device_id':'other'})).status_code==422
    asyncio.run(run())
