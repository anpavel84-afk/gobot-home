"""Free A/C lifecycle, real Brain RAM/tool integration, fake provider only."""
import asyncio,time,subprocess
from pathlib import Path
import pytest,httpx
from gobot.conversation_modes import mode_intent,IDLE_SECONDS
from gobot.models import VoiceRequest,ChatRequest
from gobot.live_contract import LiveCommand
from gobot.device_contract import DeviceProfile,ScreenPreferences
from test_live import native,offer

@pytest.mark.parametrize('text,target',[
 ('Экспертный режим!','legacy'),('ГоБот, переключи меня в экспертный режим','legacy'),
 ('Давай перейдём в экспертный режим','legacy'),('Давай перейдем в экспертный режим A','legacy'),
 ('Давай перейдём в экспертный режим А. Давай.','legacy'),('Экспертный режим А','legacy'),
 ('Переключись в режим A','legacy'),('Давай включим экспертный режим','legacy'),
 ('Включи вдумчивый режим','legacy'),('Давай разберём подробно','legacy'),
 ('Вернись к обычному разговору','live'),('Живой разговор','live'),('Стоп','end'),('stop','end'),
 ('Что означает экспертный режим?',None),('Он сказал «экспертный режим»',None),
 ('Стоп, а теперь расскажи про Луну',None)])
def test_only_explicit_control(text,target):assert mode_intent(text)==target

def test_c_to_a_confirmed_close_shared_ram_and_back_to_c(tmp_path,settings):
 async def run():
  m,p,s=await native(tmp_path,settings,conversation_mode='unified')
  try:
   flow=s.mode_flow
   assert flow.mode=='live' and not flow.provider_closed
   # Actual existing Memory, no duplicate family store or persistent conversation.
   turn=await s.interaction('Расскажи о Луне','ui-test-1');turn.answer='Луна — спутник Земли.'
   await s.finish_turn(True)
   private=ChatRequest(text='Личный секрет',device_id='personal:other',conversation_id=flow.conversation,remember=False)
   m.brain.memory.start(private);m.brain.memory.finish(private,'completed','Чужие данные','fixture',[])
   assert await s.mode_control('Экспертный режим')
   await m.close(s.id,s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,'mode_switch')
   assert s.final_usage_confirmed and flow.active and flow.provider_closed and flow.mode=='legacy'
   req=VoiceRequest(text='А сколько ей лет?',mode_conversation_id=flow.id,device_id=flow.owner,client_id=flow.client,profile_epoch=flow.epoch,remember=True)
   _,mapped=m.modes.legacy_request(req)
   assert not mapped.remember and mapped.device_id==flow.scope
   context=m.brain.memory.context(mapped)
   assert context['messages'][0]['content']=='Расскажи о Луне'
   assert 'Чужие данные' not in str(context)
   with pytest.raises(PermissionError,match='busy'):m.modes.legacy_request(req)
   flow.legacy_turn=None
   m.modes.select(flow,'live')
   again=offer(conversation_mode='unified',mode_conversation_id=flow.id).model_copy(update={'session_id':'live-second'})
   s2,_=await m.start(again,DeviceProfile(screen=ScreenPreferences(automatic_illustrations=False)))
   assert s2.access.effective_scope==s.access.effective_scope
   assert any('Луна — спутник Земли' in str(row) for row in s2.config['input'])
   assert all(row['content'][0]['type']=='output_text' for row in s2.config['input'] if row['role']=='assistant')
   await m.close(s2.id,flow.owner,flow.client,flow.epoch,'conversation_ended')
   assert not flow.active and flow.mode=='live'
   with pytest.raises(PermissionError):m.modes.bind(again.model_copy(update={'session_id':'no-replay'}))
   assert len(p.creations)==2
  finally:await m.shutdown();await m.realtime.shutdown()
 asyncio.run(run())

def test_wrong_profile_epoch_and_client_cannot_resume_or_read_a(tmp_path,settings):
 async def run():
  m,p,s=await native(tmp_path,settings,conversation_mode='unified')
  try:
   f=s.mode_flow
   for owner,client,epoch in [('other',f.client,f.epoch),(f.owner,'other',f.epoch),(f.owner,f.client,'new-epoch')]:
    with pytest.raises(PermissionError):m.modes.owned(f.id,owner,client,epoch)
   await m.invalidate_principal(f.owner)
   assert not f.active
  finally:await m.shutdown();await m.realtime.shutdown()
 asyncio.run(run())

def test_ten_second_idle_uses_playback_input_and_not_visual_work(tmp_path,settings):
 async def run():
  m,p,s=await native(tmp_path,settings)
  try:
   now=time.monotonic();s.last_activity=now-9.99
   assert IDLE_SECONDS==10 and not s.idle_due(now)
   s.last_activity=now-10.01
   assert s.idle_due(now)
   s.activity_at=now;s.playback_active=True
   assert not s.idle_due(now)
   s.playback_active=False;s.input_active=True
   assert not s.idle_due(now)
   s.activity_at=now-3
   assert s.idle_due(now),'Stale client activity must not pin an open paid session'
   original=s.experts.active;s.experts.active=lambda:True
   assert not s.idle_due(now),'A bounded, already accepted job is not followup idle'
   s.experts.active=original
   s.input_active=False
   await s.command(LiveCommand(command_id='stop-word',action='text',text='стоп'))
   await m.close(s.id,s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,'conversation_ended')
   assert s.final_usage_confirmed and not any(e['type']=='session.commentary.append' for e in s.ws.sent)
  finally:await m.shutdown();await m.realtime.shutdown()
 asyncio.run(run())

def test_legacy_idle_resets_default_without_creating_live(tmp_path,settings):
 async def run():
  m,p,s=await native(tmp_path,settings,conversation_mode='unified')
  try:
   f=s.mode_flow;m.modes.select(f,'legacy')
   await m.close(s.id,f.owner,f.client,f.epoch,'mode_switch')
   f.last_activity=time.monotonic()-10.1
   assert m.modes.idle(f)
   m.modes.activity(f,False,False)
   assert not f.active and f.mode=='live' and len(p.creations)==1
   assert f.public()['wake_word_ready'] is False
  finally:await m.shutdown();await m.realtime.shutdown()
 asyncio.run(run())

@pytest.mark.parametrize('suffix',['',' A',' А'])
def test_real_transcript_path_switches_after_model_ack_without_delegation_or_heartbeat(tmp_path,settings,suffix):
 async def run():
  m,p,s=await native(tmp_path,settings,conversation_mode='unified')
  try:
   for i,text in enumerate(['Давай перейдём в ','экспертный режим'+suffix]):
    await s.handle({'type':'session.input_transcript.delta','event_id':'input-'+str(i),'start_ms':i*400,'end_ms':(i+1)*400,'delta':text})
   await s.handle({'type':'session.output_transcript.delta','event_id':'ack-output','start_ms':850,'end_ms':1400,'delta':'Да, давайте.'})
   assert not s.delegation_tasks and not s.backend_task
   task=s.mode_control_task;await asyncio.wait_for(task,2)
   await m.close(s.id,s.offer.device_id,s.offer.client_id,s.offer.profile_epoch,'mode_switch')
   assert s.closed and s.final_usage_confirmed and s.mode_flow.mode=='legacy'
   assert s.mode_flow.active and s.mode_flow.provider_closed
   assert sum(e['type']=='session.close' for e in s.ws.sent)==1
   assert s.event_counts['conversation_mode_switching']==1
   assert not s.experts.jobs
  finally:await m.shutdown();await m.realtime.shutdown()
 asyncio.run(run())

def test_mode_fragment_is_not_authorization_before_audio_end_and_correction_cancels(tmp_path,settings):
 async def run():
  m,p,s=await native(tmp_path,settings,conversation_mode='unified')
  try:
   await s.handle({'type':'session.input_transcript.delta','event_id':'first','start_ms':0,'end_ms':900,'delta':'Давай перейдем в экспертный режим'})
   await asyncio.sleep(.8)
   assert not s.closed and s.mode_flow.mode=='live','A network delivery gap is not end of speech'
   await s.handle({'type':'session.input_transcript.delta','event_id':'correction','start_ms':920,'end_ms':1500,'delta':', хотя нет, не переключай'})
   await s.handle({'type':'session.output_transcript.delta','event_id':'out','start_ms':1600,'end_ms':2200,'delta':'Хорошо.'})
   await asyncio.sleep(.1)
   assert not s.closed and s.mode_flow.mode=='live'
  finally:await m.shutdown();await m.realtime.shutdown()
 asyncio.run(run())

def test_production_unified_client_switches_only_after_close():
 result=subprocess.run(['node','tests/unified_browser.cjs'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=15)
 assert result.returncode==0,result.stdout+result.stderr

def test_production_live_event_bridge_to_unified_client():
 result=subprocess.run(['node','tests/unified_live_browser.cjs'],cwd=Path(__file__).resolve().parents[1],capture_output=True,text=True,timeout=15)
 assert result.returncode==0,result.stdout+result.stderr

def test_unified_voice_endpoint_local_commands_and_timer_no_cli(tmp_path,settings,monkeypatch):
 from gobot.brain import create_app
 from gobot.conversation_modes import ModeConversation
 from gobot.owner_testing import OwnerTestPolicy
 import gobot.brain as brain_module
 import gobot.realtime as realtime_module
 from gobot.realtime_budget import RealtimeBudget
 monkeypatch.setattr(realtime_module,'RealtimeBudget',lambda *args,**kw:RealtimeBudget(tmp_path/'isolated-native-budget'))
 async def no_agent(*args,**kwargs):raise AssertionError('No CLI for local mode commands/timer')
 monkeypatch.setattr(brain_module,'bridge_stream',no_agent)
 app=create_app(settings);m=app.state.live
 m.owner_testing.policy_path.write_text(OwnerTestPolicy(enabled=True,authorization='fixture',allowed_client_id='client-1',live_enabled=True).model_dump_json())
 flow=ModeConversation('browser-1','client-1',None,'client-1',mode='legacy')
 m.modes.items[flow.id]=flow
 headers={'Authorization':'Bearer '+settings.api_token}
 base={'device_id':flow.owner,'client_id':flow.client,'mode_conversation_id':flow.id,'speak':False,'remember':True}
 async def run():
  try:
   async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test',headers=headers) as client:
    response=await client.post('/api/v1/chat/voice/stream',json={**base,'text':'Поставь таймер на пять секунд'})
    assert response.status_code==200 and 'timer_widget' in response.text
    with m.brain.memory.connect() as c:
     assert c.execute('SELECT device_id FROM timers').fetchone()[0]=='realtime-device:client-1'
     assert c.execute('SELECT count(*) FROM conversations').fetchone()[0]==0
    response=await client.post('/api/v1/chat/voice/stream',json={**base,'text':'Вернись к обычному разговору'})
    assert response.status_code==200 and 'conversation_mode' in response.text and flow.mode=='live'
    assert not flow.legacy_turn
    flow.mode='legacy'
    response=await client.post('/api/v1/chat/voice/stream',json={**base,'text':'Стоп'})
    assert response.status_code==200 and not flow.active and flow.mode=='live'
    response=await client.post('/api/v1/chat/voice/stream',json={**base,'text':'Сколько сейчас времени?'})
    assert response.status_code==403
  finally:await m.shutdown();await m.realtime.shutdown()
 asyncio.run(run())

def test_root_is_unified_but_comparison_pages_are_preserved(settings):
 from gobot.browser import create_browser_app,ORIGIN
 from fastapi.testclient import TestClient
 with TestClient(create_browser_app(settings),base_url=ORIGIN,client=('100.120.201.115',1)) as client:
  for path in ['/','/device']:
   response=client.get(path)
   assert response.status_code==200 and 'data-unified="true"' in response.text and '/unified.js' in response.text
  assert 'data-unified=' not in client.get('/demo2/b/device').text
  assert 'data-unified="true"' in client.get('/demo2/c/device').text
  assert '/unified.js' in client.get('/demo2/c/device').text
  assert client.get('/unified.js').status_code==200
