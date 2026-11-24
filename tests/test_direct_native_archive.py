"""Native Direct handlers, enrolled synthetic board and local SQLite only."""
import asyncio
from contextlib import asynccontextmanager
import json
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from gobot.device_contract import DeviceProfile
from gobot.expert_jobs import ExpertJob
from gobot.expert_profiles import PROFILES
from gobot.expert_stream import EXPERT_CUE_ID, EXPERT_CUE_TEXT, expert_service_cache
from gobot.native_archive import ArchiveBinding
from gobot.owner_terminal import (OwnerTerminalBoardRealtime,
    prepare_owner_terminal_proposal, authorize_owner_terminal_proposal)
from gobot.realtime_ws import DirectOffer, DirectRealtimeManager
from gobot.unified_voice_budget import UnifiedVoiceBudget
from test_direct_working_memory import ask, complete, context_items, requests
from test_realtime_native import configured
from test_realtime_ws import Socket, cleanup
from test_unified_voice_budget import SpeechFixture


BOARD='spotpear-001122aabbcc'


class ContextProvider:
    def __init__(self):self.sockets=[]

    @asynccontextmanager
    async def open(self,model):
        assert model=='gpt-realtime-2.1-mini'
        socket=Socket();self.sockets.append(socket)
        send=socket.send
        async def acknowledged(raw):
            await send(raw)
            event=json.loads(raw)
            if event['type']=='conversation.item.create' and event.get('item',{}).get('id','').startswith('memory_'):
                await socket.queue.put({'type':'conversation.item.added','item':event['item']})
        socket.send=acknowledged
        try:yield socket
        finally:await socket.close()


async def setup_archive(tmp_path,settings,*,read=True,write=True):
    original,_,_=configured(tmp_path,settings)
    devices=original.brain.configuration.devices
    profile=DeviceProfile(client_id=BOARD,client_kind='spotpear')
    binding=ArchiveBinding(BOARD,BOARD,BOARD+'@guest')
    with sqlite3.connect(devices.db) as db:
        db.execute('INSERT INTO profiles VALUES(?,?)',(binding.owner_id,profile.model_dump_json()))
    async def enrolled(_):return devices.profile(binding.owner_id)
    original.profile_loader=enrolled
    root=tmp_path/'permanent-archive-board'
    proposal=prepare_owner_terminal_proposal(root,BOARD,expert_profile='ARGON_DEEP')
    cache=tmp_path/'fixture-public-cue'
    expert_service_cache(cache).put('marin',EXPERT_CUE_ID,bytes(4800),24000,EXPERT_CUE_TEXT)
    authorize_owner_terminal_proposal(root,proposal['proposal_sha256'],cache_root=cache,
        owner_direct='Synthetic owner authorizes permanent uncapped board testing')
    board=OwnerTerminalBoardRealtime(original,root)
    authority=UnifiedVoiceBudget(max_expert_audio_seconds=180,expert_operation_timeout_seconds=240)
    provider=ContextProvider()
    manager=DirectRealtimeManager(board,provider=provider,speech=SpeechFixture(),
        transcription_authorizer=authority.transcription,narrator_authorizer=authority.narrator)
    service=manager.brain.memory.native_archive
    state=service.configure(binding,dict(write_enabled=write,read_enabled=read,
        retention_days=0,timezone='America/Sao_Paulo'),0,operation_id='enable',actor_id='verified-owner')
    session=await manager.accept(DirectOffer(session_id='archive-session-1',conversation_id='conversation-1',
        device_id=BOARD,client_id=BOARD,consent=True,requested_model='gpt-realtime-2.1-mini',
        client_kind='device',expert_quota_consent=True))
    manager.memory_policy_store.set(BOARD,BOARD,session.policy.authorization,
        dict(enabled=True,ttl_seconds=43200,persist=False,summarize=False,background=True,supplement=True))
    await session.memory_flow.configure()
    # Tests explicitly call refresh when needed; avoid wall-time races with it.
    session._archive_refresh_after=float('inf')
    return original,board,manager,session,provider,service,binding,state


async def finish_fixture(fixture):
    original,board,manager,*_=fixture
    await cleanup(original,board,manager)
    await manager.brain.memory.native_archive.close()


def seed(service,binding,state,*,days=30):
    stamp=time.time()-days*86400
    service.record_question(binding,'old-question','old-session','Обсудим бензин: только сравнение, без покупок.',
        generation=state['generation'],accepted_at=stamp)
    service.record_answer(binding,'old-question','Бензин обсуждали для сравнения с дизелем.',
        generation=state['generation'],heard=True,provider='openai:synthetic',played_at=stamp+1)


def set_memory_skill(manager,binding,enabled):
    devices=manager.brain.configuration.devices
    profile=devices.profile(binding.owner_id)
    profile.conversation.skills.memory=enabled
    with sqlite3.connect(devices.db) as db:
        db.execute('UPDATE profiles SET profile=? WHERE owner=?',(profile.model_dump_json(),binding.owner_id))


@pytest.mark.parametrize('transition',['stop','next_question','close'])
def test_delayed_accepted_write_survives_stop_new_input_and_real_manager_teardown(tmp_path,settings,monkeypatch,transition):
    async def run():
        fixture=await setup_archive(tmp_path,settings,read=False)
        original,board,manager,s,provider,service,binding,state=fixture
        entered,release=threading.Event(),threading.Event()
        record=service.record_question
        def delayed(*args,**kwargs):
            entered.set();assert release.wait(3);return record(*args,**kwargs)
        monkeypatch.setattr(service,'record_question',delayed)
        try:
            turn,response=await asyncio.wait_for(ask(s),1.)
            assert requests(provider) and await asyncio.to_thread(entered.wait,1)
            accepted_id=turn.id
            if transition=='stop':await s.stop()
            elif transition=='next_question':
                await s.stop();await ask(s,'Как приготовить омлет?')
            else:
                await manager.close(s.id,BOARD,BOARD,None,'server_shutdown')
                assert turn.query=='' and turn.req is None
            release.set();await service.wait_idle()
            with manager.brain.memory.connect() as db:
                row=db.execute('SELECT m.content FROM messages m JOIN native_archive_sources n ON n.message_id=m.id WHERE n.source_turn_id=? AND n.component=?',
                    (accepted_id,'question')).fetchone()
            assert row and row[0]=='Какие особенности бензина?'
        finally:
            release.set();await finish_fixture(fixture)
    asyncio.run(run())


def test_delayed_source_revision_change_is_rejected(tmp_path,settings,monkeypatch):
    async def run():
        fixture=await setup_archive(tmp_path,settings,read=False)
        _,_,manager,s,_,service,binding,state=fixture
        entered,release=threading.Event(),threading.Event();record=service.record_question
        def delayed(*args,**kwargs):
            entered.set();assert release.wait(3);return record(*args,**kwargs)
        monkeypatch.setattr(service,'record_question',delayed)
        try:
            turn,_=await ask(s);assert await asyncio.to_thread(entered.wait,1)
            turn.input_revision+=1
            release.set();await service.wait_idle()
            assert service.status(binding)['counts']['messages']==0
        finally:
            release.set();await finish_fixture(fixture)
    asyncio.run(run())


def test_memory_skill_off_still_records_question_and_only_heard_answer(tmp_path,settings):
    async def run():
        fixture=await setup_archive(tmp_path,settings)
        _,_,manager,s,provider,service,binding,state=fixture
        set_memory_skill(manager,binding,False)
        try:
            turn,response=await ask(s)
            assert s.memory_flow.turn is None
            await complete(s,response,'Услышанный ответ про бензин.')
            await s.stop()
            unheard,other=await ask(s,'Почему бензин испаряется?')
            await s.handle({'type':'response.output_audio_transcript.delta','response_id':other,'delta':'НЕУСЛЫШАННЫЙ ХВОСТ'})
            await s.stop();await service.wait_idle()
            assert service.status(binding)['counts']['messages']==3
            assert not context_items(provider)
            with manager.brain.memory.connect() as db:
                text=' '.join(row[0] for row in db.execute('SELECT content FROM messages'))
            assert 'Услышанный ответ' in text and 'НЕУСЛЫШАННЫЙ' not in text
        finally:await finish_fixture(fixture)
    asyncio.run(run())


def test_delayed_confirmed_playback_write_survives_actual_manager_close(tmp_path,settings,monkeypatch):
    async def run():
        fixture=await setup_archive(tmp_path,settings,read=False)
        _,_,manager,s,_,service,binding,state=fixture
        entered,release=threading.Event(),threading.Event();record=service.record_answer
        def delayed(*args,**kwargs):
            entered.set();assert release.wait(3);return record(*args,**kwargs)
        monkeypatch.setattr(service,'record_answer',delayed)
        try:
            turn,response=await ask(s)
            await complete(s,response,'Подтверждённый физическим playback ответ.')
            assert await asyncio.to_thread(entered.wait,1)
            await manager.close(s.id,BOARD,BOARD,None,'server_shutdown')
            assert turn.answer==''
            release.set();await service.close(grace_seconds=2)
            with manager.brain.memory.connect() as db:
                text=[row[0] for row in db.execute("SELECT content FROM messages WHERE role='assistant'")]
            assert text==['Подтверждённый физическим playback ответ.']
        finally:
            release.set();await finish_fixture(fixture)
    asyncio.run(run())


def test_old_archive_lookup_does_not_delay_primary_and_supplements_once_after_playback(tmp_path,settings,monkeypatch):
    async def run():
        fixture=await setup_archive(tmp_path,settings)
        _,board,manager,s,provider,service,binding,state=fixture
        seed(service,binding,state)
        entered,release=threading.Event(),threading.Event();recall=service.recall
        def delayed(*args,**kwargs):
            entered.set();assert release.wait(3);return recall(*args,**kwargs)
        monkeypatch.setattr(service,'recall',delayed)
        try:
            turn,response=await asyncio.wait_for(ask(s),1.)
            assert len(requests(provider))==1 and await asyncio.to_thread(entered.wait,1)
            release.set();await s.memory_flow.turn['task']
            assert s.memory_flow.turn['late'] and len(requests(provider))==1
            payload=s.memory_flow.turn['result']
            assert all(item['source_kind']=='device_archive' for item in payload['messages'])
            assert len(payload['messages'])==2
            await complete(s,response)
            for _ in range(100):
                if s.live_response and s.live_response!=response:break
                await asyncio.sleep(.001)
            assert len(requests(provider))==2 and s.current is turn
            assert requests(provider)[-1]['response']['tool_choice']=='none'
            await complete(s,s.live_response,'Кстати, сравнивали без рекомендаций покупки.')
            await service.wait_idle()
            assert len(requests(provider))==2 and s.memory_flow.last['supplements']==1
            assert board.budget.board_status()['response_attempts']==2
        finally:
            release.set();await finish_fixture(fixture)
    asyncio.run(run())


@pytest.mark.parametrize('action',['clear','read_off'])
def test_clear_or_read_revoke_while_lookup_waits_prevents_provider_delivery(tmp_path,settings,monkeypatch,action):
    async def run():
        fixture=await setup_archive(tmp_path,settings)
        _,_,manager,s,provider,service,binding,state=fixture
        seed(service,binding,state)
        entered,release=threading.Event(),threading.Event();recall=service.recall
        def delayed(*args,**kwargs):
            result=recall(*args,**kwargs);entered.set();assert release.wait(3);return result
        monkeypatch.setattr(service,'recall',delayed)
        try:
            turn,response=await ask(s);search=s.memory_flow.turn
            assert await asyncio.to_thread(entered.wait,1)
            if action=='clear':service.clear(binding,state['revision'],operation_id='clear',actor_id='owner')
            else:service.configure(binding,{**state['policy'],'read_enabled':False},state['revision'],operation_id='disable',actor_id='owner')
            release.set();await search['task'];await complete(s,response)
            assert not context_items(provider) and len(requests(provider))==1
        finally:
            release.set();await finish_fixture(fixture)
    asyncio.run(run())


def test_external_generation_refresh_replaces_delivered_provider_context(tmp_path,settings):
    async def run():
        fixture=await setup_archive(tmp_path,settings)
        _,_,manager,s,provider,service,binding,state=fixture
        seed(service,binding,state)
        try:
            turn,response=await ask(s)
            await s.memory_flow.turn['task']
            assert s.memory_flow.archive_provider
            await s.stop()
            old_socket=provider.sockets[-1]
            cleared=service.clear(binding,state['revision'],operation_id='clear',actor_id='owner')
            await s.memory_flow.refresh_archive()
            assert old_socket.closed and provider.sockets[-1] is not old_socket
            assert s.memory_flow.archive_configuration['generation']==cleared['generation']
            assert not s.memory_flow.archive_provider and not s.memory_flow._archive_context_invalid
            assert len(requests(provider))==1
        finally:await finish_fixture(fixture)
    asyncio.run(run())


def test_retention_expiry_refreshes_cached_generation_for_the_next_question(tmp_path,settings):
    async def run():
        fixture=await setup_archive(tmp_path,settings)
        _,_,manager,s,_,service,binding,state=fixture
        try:
            configured=service.configure(binding,{**state['policy'],'retention_days':1},state['revision'],
                operation_id='retention',actor_id='owner')
            await s.memory_flow.refresh_archive()
            seed(service,binding,configured,days=0)
            service.clock=lambda:time.time()+2*86400
            assert service.expire()==1
            fresh=service.policy(binding)
            assert fresh['generation']>configured['generation']
            await s.memory_flow.refresh_archive()
            assert s.memory_flow.archive_configuration['generation']==fresh['generation']
            assert not s.memory_flow._archive_context_invalid
            service.record_question(binding,'after-expiry','new-sid','Бензин после очистки срока.',
                generation=fresh['generation'],accepted_at=service.clock())
            lookup=s.request('Бензин','brand-new-turn')
            result=manager.brain.memory.recall(lookup)
            assert result['useful'] and all(item['turn_id']=='after-expiry' for item in result['messages'])
        finally:await finish_fixture(fixture)
    asyncio.run(run())


def test_clear_at_provider_writer_fence_blocks_already_computed_context(tmp_path,settings,monkeypatch):
    async def run():
        fixture=await setup_archive(tmp_path,settings)
        _,_,manager,s,provider,service,binding,state=fixture
        seed(service,binding,state)
        entered,release=threading.Event(),threading.Event();recall=service.recall
        def delayed(*args,**kwargs):
            result=recall(*args,**kwargs);entered.set();assert release.wait(3);return result
        monkeypatch.setattr(service,'recall',delayed)
        locked=False
        try:
            turn,response=await ask(s);search=s.memory_flow.turn
            assert await asyncio.to_thread(entered.wait,1)
            await s.send_lock.acquire();locked=True
            send=s.send;waiting=asyncio.Event()
            async def observed(event,**kwargs):
                if kwargs.get('_memory_gate'):waiting.set()
                return await send(event,**kwargs)
            monkeypatch.setattr(s,'send',observed)
            release.set();await asyncio.wait_for(waiting.wait(),1)
            service.clear(binding,state['revision'],operation_id='clear-at-writer',actor_id='owner')
            s.send_lock.release();locked=False
            await search['task']
            assert not context_items(provider) and len(requests(provider))==1
        finally:
            release.set()
            if locked:s.send_lock.release()
            await finish_fixture(fixture)
    asyncio.run(run())


@pytest.mark.parametrize('boundary',['skill_off','clear'])
def test_expert_prepared_archive_packet_is_revocable_before_any_cli_dispatch(tmp_path,settings,monkeypatch,boundary):
    async def run():
        fixture=await setup_archive(tmp_path,settings)
        _,_,manager,s,_,service,binding,state=fixture
        seed(service,binding,state)
        calls=[]
        async def forbidden(*args,**kwargs):
            calls.append(True)
            raise AssertionError('No actual CLI/model call is permitted')
            yield ''
        monkeypatch.setattr('gobot.expert_jobs.bridge_stream',forbidden)
        try:
            job=ExpertJob('archive-job','archive-proposal','Какие особенности бензина?',PROFILES['ARGON_DEEP'],
                s.experts.revision(),s.access.effective_scope,s.offer.conversation_id)
            job.packet=await s.experts.prepare_packet(job)
            assert job.archive_context and any(item.get('source_kind')=='device_archive' for item in job.packet['messages'])
            if boundary=='skill_off':set_memory_skill(manager,binding,False)
            else:service.clear(binding,state['revision'],operation_id='clear',actor_id='owner')
            with pytest.raises(PermissionError,match='expert_context_changed'):
                await s.experts.execute(job)
            assert not calls
            if boundary=='skill_off':
                fresh=ExpertJob('fresh','proposal','Бензин',PROFILES['ARGON_DEEP'],s.experts.revision(),s.access.effective_scope,s.offer.conversation_id)
                packet=await s.experts.prepare_packet(fresh)
                assert not packet['messages'] and not fresh.archive_context
        finally:await finish_fixture(fixture)
    asyncio.run(run())


def test_archive_unbind_retains_original_scope_across_access_replacement_and_scrub(tmp_path,settings):
    async def run():
        fixture=await setup_archive(tmp_path,settings)
        _,_,manager,s,_,service,binding,state=fixture
        memory=manager.brain.memory
        old_access=s.access
        old_key=(old_access.effective_scope,old_access.context_conversation,s.offer.profile_epoch)
        assert old_key in memory.native_archive_bindings
        try:
            s.access=SimpleNamespace(confirmed_profile_id=None,effective_scope='realtime-guest:replacement',
                context_conversation='replacement-conversation')
            await s.memory_flow.configure_archive(force=True)
            new_key=('realtime-guest:replacement','replacement-conversation',s.offer.profile_epoch)
            assert old_key not in memory.native_archive_bindings
            assert new_key in memory.native_archive_bindings
            # A real identity transition must remove the old map entry even
            # when current access no longer contains request-building fields.
            s.access=SimpleNamespace(confirmed_profile_id='private-profile')
            await s.memory_flow.configure_archive(force=True)
            assert new_key not in memory.native_archive_bindings
            assert s.memory_flow.archive_binding is None
            await s.memory_flow.close()
            assert not memory.native_archive_bindings
        finally:
            s.access=old_access
            await finish_fixture(fixture)
    asyncio.run(run())


def test_archive_close_unbinds_cached_request_after_access_is_scrubbed(tmp_path,settings):
    async def run():
        fixture=await setup_archive(tmp_path,settings)
        _,_,manager,s,_,_,_,_=fixture
        original=s.access
        assert manager.brain.memory.native_archive_bindings
        try:
            s.access=SimpleNamespace(confirmed_profile_id='private-profile')
            await s.memory_flow.close()
            assert not manager.brain.memory.native_archive_bindings
        finally:
            s.access=original
            await finish_fixture(fixture)
    asyncio.run(run())


def test_pending_archive_configuration_cannot_rebind_after_close(tmp_path,settings,monkeypatch):
    async def run():
        fixture=await setup_archive(tmp_path,settings)
        _,_,manager,s,_,service,_,_=fixture
        entered,release=threading.Event(),threading.Event();status=service.status
        def held(*args,**kwargs):
            entered.set();assert release.wait(3);return status(*args,**kwargs)
        monkeypatch.setattr(service,'status',held)
        configuring=None
        try:
            configuring=asyncio.create_task(s.memory_flow.configure_archive(force=True))
            assert await asyncio.to_thread(entered.wait,1)
            await s.memory_flow.close()
            release.set();await configuring
            assert not manager.brain.memory.native_archive_bindings
        finally:
            release.set()
            if configuring:await asyncio.gather(configuring,return_exceptions=True)
            await finish_fixture(fixture)
    asyncio.run(run())
