"""Real Direct coordination + temporary SQLite; synthetic provider, no device I/O."""
import asyncio
import json
import sqlite3
import threading
import time

import pytest

from gobot.debug_journal import clean
from gobot.device_contract import DeviceProfile
from gobot.direct_timers import expire_timers
from test_direct_conversation_mode import question
from test_realtime_ws import cleanup
from test_sophia_home_refresh import DEVICE, configured, home_updates, settle, start


def change(manager, *, guidance=None, **skills):
    db_path = manager.brain.configuration.devices.db
    with sqlite3.connect(db_path) as db:
        raw, = db.execute('SELECT profile FROM profiles WHERE owner=?', (DEVICE+'@hardware',)).fetchone()
        data = json.loads(raw)
        if guidance is not None:data['conversation']['guidance'] = guidance
        data['conversation'].setdefault('skills', {}).update(skills)
        profile = DeviceProfile.model_validate(data)
        db.execute('UPDATE profiles SET profile=? WHERE owner=?', (profile.model_dump_json(), DEVICE+'@hardware'))
    return profile


def outputs(provider, call_id=None):
    return [json.loads(event['item']['output']) for socket in provider.sockets for event in socket.sent
        if event.get('item', {}).get('type') == 'function_call_output'
        and (call_id is None or event['item'].get('call_id') == call_id)]


async def timer_call(session, response, args, call_id='timer-call'):
    before = set(session.tasks)
    await session.handle({'type':'response.function_call_arguments.done','response_id':response,
        'call_id':call_id,'name':'timer_action','arguments':json.dumps(args, ensure_ascii=False)})
    tasks = [task for task in session.tasks-before if task.get_coro().__name__ == 'tool']
    if tasks:await asyncio.wait_for(asyncio.gather(*tasks), 3)


def timer_count(session):
    with session.manager.brain.memory.connect() as db:
        return db.execute('SELECT COUNT(*) FROM timers').fetchone()[0]


def test_saved_guidance_and_disabled_skill_reach_one_idle_ack_without_voice_usage(tmp_path, settings):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings, acknowledge=False)
        try:
            s = await start(manager)
            original_home = s.home_context_status()['applied_revision']
            original_config = json.loads(json.dumps(s.config))
            guidance = 'Сначала короткий ответ. Секретный пример <script>никакого действия</script>.'
            change(manager, guidance=guidance, timer=False)
            assert await s.refresh_home_context(now=s._home_context_next_check)
            update, = home_updates(provider.sockets[0])
            assert set(update['session']) == {'type','instructions'}
            assert update['session']['instructions'].count(guidance) == 1
            assert s.capabilities.status()['state'] == 'pending'
            assert s.config == original_config
            assert guidance not in json.dumps(s.lifecycle_status(), ensure_ascii=False)
            assert guidance not in json.dumps(s.capabilities.public(), ensure_ascii=False)
            assert 'guidance' not in clean({'nested': {'guidance': guidance}})['nested']
            await s.handle({'type':'session.updated','session':provider.sockets[0].config})
            assert s.capabilities.status()['state'] == 'applied'
            assert s.home_context_status()['applied_revision'] == original_home
            assert not s.capabilities.public()['capabilities']['timer']['enabled']
            assert not s.input_open and board.budget.status()['sessions_reserved'] == 0
            assert not any(event['type'] == 'response.create' for event in provider.sockets[0].sent)
        finally:await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('skill,query',[('clock','Который час?'),('timer','Поставь таймер на пять минут'),
    ('weather','Какая погода сегодня?'),('utilities','Сколько будет 2+3?'),('memory','Найди в памяти разговор о бензине')])
def test_saved_disable_is_enforced_before_provider_prompt_refresh(tmp_path, settings, skill, query):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        try:
            s = await start(manager)
            turn = await s.new_turn(query=query)
            async def no_response():pass
            s.response = no_response
            old_revision = s.capabilities.applied_settings_revision
            change(manager, **{skill:False})
            await s.tool('disabled-action','gobot_tool',json.dumps({'query':query}),turn)
            result, = outputs(provider,'disabled-action')
            assert result['executed'] is False and result['error'] == 'capability_disabled_by_owner'
            assert timer_count(s) == 0
            assert s.capabilities.applied_settings_revision == old_revision
        finally:await cleanup(original, board, manager)
    asyncio.run(run())


def test_timer_native_semantic_and_generic_calls_share_one_durable_user_action(tmp_path, settings):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        try:
            s = await start(manager)
            turn, response = await question(s, 'Поставь таймер на пять минут')
            await timer_call(s,response,{'operation':'start','duration_text':'пять минут'},'first')
            await timer_call(s,response,{'operation':'start','duration_text':'пять минут'},'second')
            await s.tool('generic','gobot_tool',json.dumps({'query':turn.query}),turn)
            results = outputs(provider)
            assert len(results) == 3 and timer_count(s) == 1
            assert len({item['evidence']['timer_id'] for item in results}) == 1
            assert results[0]['evidence']['replayed'] is False
            assert results[1]['evidence']['replayed'] and results[2]['evidence']['replayed']
            assert not s.experts.jobs
        finally:await cleanup(original, board, manager)
    asyncio.run(run())


def test_timer_works_inside_conversation_with_literal_duration_and_no_expert(tmp_path, settings):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        try:
            s = await start(manager)
            _, response = await question(s, 'София, кстати, поставь таймер на пять минут и продолжай объяснять.')
            await timer_call(s,response,{'operation':'start','duration_text':'пять минут'})
            result, = outputs(provider)
            assert result['executed'] and result['evidence']['duration_seconds'] == 300
            assert timer_count(s) == 1 and not s.experts.jobs
            assert result['delivery']['display'] == 'unconfirmed'
        finally:await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('argument',[None,'60 секунд'])
def test_semantic_duration_normalization_creates_one_real_timer_and_replays(tmp_path,settings,argument):
    async def run():
        original,board,manager,provider=configured(tmp_path,settings)
        try:
            s=await start(manager)
            _,response=await question(s,'Включи кухонный отсчёт на минутку.')
            args={'operation':'start'}
            if argument is not None:args['duration_text']=argument
            await timer_call(s,response,args,'semantic-first')
            await timer_call(s,response,args,'semantic-repeat')
            results=outputs(provider)
            assert len(results)==2 and timer_count(s)==1
            assert all(r['executed'] and r['evidence']['duration_seconds']==60 for r in results)
            assert results[0]['evidence']['replayed'] is False
            assert results[1]['evidence']['replayed'] is True
            assert not s.experts.jobs
        finally:await cleanup(original,board,manager)
    asyncio.run(run())


def test_wrong_model_duration_has_honest_retry_text_and_no_timer(tmp_path,settings):
    async def run():
        original,board,manager,provider=configured(tmp_path,settings)
        try:
            s=await start(manager)
            _,response=await question(s,'Включи кухонный отсчёт на минутку.')
            await timer_call(s,response,{'operation':'start','duration_text':'120 секунд'})
            result,=outputs(provider)
            assert result['executed'] is False
            assert result['error']=='timer_duration_source_mismatch'
            assert result['text']=='Таймер не установлен: я неточно расслышал просьбу. Повторите её, пожалуйста.'
            assert timer_count(s)==0
        finally:await cleanup(original,board,manager)
    asyncio.run(run())


@pytest.mark.parametrize('action',['stop','mute','new_turn','disable'])
def test_timer_sql_authority_lost_while_worker_waits_cannot_commit(tmp_path, settings, monkeypatch, action):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        release, entered = threading.Event(), threading.Event()
        task = None
        try:
            s = await start(manager)
            _, response = await question(s, 'Поставь таймер на пять минут')
            real_start = s.manager.brain.tools.timers.start
            def held(*args,**kwargs):
                entered.set()
                assert release.wait(3)
                return real_start(*args,**kwargs)
            monkeypatch.setattr(s.manager.brain.tools.timers,'start',held)
            task = asyncio.create_task(timer_call(s,response,{'operation':'start','duration_text':'пять минут'}))
            assert await asyncio.to_thread(entered.wait,2)
            if action == 'stop':await s.stop()
            elif action == 'mute':await s.mute(True)
            elif action == 'new_turn':await s.new_turn(query='Другой вопрос')
            else:change(manager,timer=False)
            release.set()
            await task
            assert timer_count(s) == 0
            assert not any(result.get('executed') is True for result in outputs(provider))
        finally:
            release.set()
            if task:await asyncio.gather(task,return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_unrequested_function_or_old_response_cannot_create_timer(tmp_path, settings):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        try:
            s = await start(manager)
            turn, response = await question(s,'Поставь таймер на пять минут')
            args = {'operation':'start','duration_text':'пять минут'}
            await s.tool('uncaptured','timer_action',json.dumps(args),turn)
            await s.stop()
            await timer_call(s,response,args,'stale')
            assert timer_count(s) == 0 and not outputs(provider)
        finally:await cleanup(original, board, manager)
    asyncio.run(run())


def test_expiry_and_claim_do_not_open_input_or_response_and_survive_reattachment(tmp_path, settings):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        try:
            s = await start(manager)
            service = manager.brain.tools.timers
            now = [time.time()]
            service.clock = lambda:now[0]
            service.start(s.timers.request('Синтетический таймер','fixture-action'),5,action_id='fixture-action')
            s.timers.capabilities({'type':'timer_capabilities','display_supported':True,'signal_supported':True})
            await s.timers.refresh(force=True)
            now[0] += 5
            await s.timers.refresh(force=True)
            alarms = [event['data'] for event in s.events if event['type']=='timer_alarm']
            assert len(alarms) == 1
            alarm = alarms[0]
            assert await s.timers.command({'type':'timer_output_activity','alarm_id':alarm['alarm_id'],
                'claim_id':alarm['claim_id'],'active':True})
            assert s.timers.status()['output_active']
            assert not await s.timers.command({'type':'timer_alarm_ack','alarm_id':alarm['alarm_id'],
                'claim_id':'wrong-claim','state':'finished'})
            assert s.timers.status()['signal'] != 'confirmed'
            assert await s.timers.command({'type':'timer_alarm_ack','alarm_id':alarm['alarm_id'],
                'claim_id':alarm['claim_id'],'state':'finished'})
            assert s.timers.status()['signal'] == 'confirmed' and not s.timers.status()['output_active']
            assert not s.input_open and board.budget.status()['sessions_reserved'] == 0
            assert not any(event['type']=='response.create' for event in provider.sockets[0].sent)
            await s.timers.refresh(force=True)
            assert len([event for event in s.events if event['type']=='timer_alarm']) == 1
            s.timers.detach()
            s.timers.capabilities({'type':'timer_capabilities','display_supported':True,'signal_supported':True})
            await s.timers.refresh(force=True)
            assert len([event for event in s.events if event['type']=='timer_alarm']) == 1
            assert not service.claim_due(s.timers.request(),'replacement-consumer')
        finally:await cleanup(original, board, manager)
    asyncio.run(run())


def test_expiry_worker_needs_no_session_and_preserves_unsent_claim(tmp_path, settings):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        worker = None
        stop = asyncio.Event()
        try:
            from gobot.models import ChatRequest
            req = ChatRequest(text='Synthetic timer',device_id='realtime-device:fixture',client_id='fixture')
            timers = manager.brain.tools.timers
            now = [time.time()]
            timers.clock = lambda:now[0]
            timers.start(req,5,action_id='local-fixture')
            now[0] += 5
            worker = asyncio.create_task(expire_timers(manager.brain,stop))
            async with asyncio.timeout(2):
                while not getattr(manager.brain,'timer_expiry_status',{}).get('checked_at'):
                    await asyncio.sleep(.001)
            stop.set()
            await worker
            assert manager.brain.timer_expiry_status['expired'] == 1
            assert not manager.brain.timer_expiry_status['running']
            assert len(timers.claim_due(req,'later-transport')) == 1
            assert not provider.sockets and not manager.sessions
        finally:
            stop.set()
            if worker:await worker
            await cleanup(original,board,manager)
    asyncio.run(run())


def test_saved_memory_disable_omits_context_on_transport_configuration(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        try:
            change(manager,memory=False)
            def unexpected(*args,**kwargs):raise AssertionError('disabled memory seed read')
            monkeypatch.setattr(manager.brain.memory,'context',unexpected)
            s = await start(manager)
            assert 'disabled_by_owner' in s.config['instructions']
            assert not s.memory_flow.permits_summary(s.request('fixture','fixture'))
        finally:await cleanup(original, board, manager)
    asyncio.run(run())


def test_mode_preference_read_cannot_overtake_stop(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        entered, release = asyncio.Event(), asyncio.Event()
        try:
            s = await start(manager)
            require = s.require_capability
            async def held(capability):
                entered.set()
                await release.wait()
                return await require(capability)
            monkeypatch.setattr(s,'require_capability',held)
            selection = asyncio.create_task(s.select_mode('expert'))
            await entered.wait()
            await s.stop()
            release.set()
            with pytest.raises(ValueError,match='mode_control_superseded'):await selection
            assert s.selected_mode == 'fast'
        finally:
            release.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('change_kind',['disable','stop'])
def test_due_claim_held_across_owner_change_is_consumed_without_output(tmp_path, settings, monkeypatch, change_kind):
    async def run():
        original,board,manager,provider = configured(tmp_path,settings)
        entered,release = threading.Event(),threading.Event()
        task = None
        try:
            s = await start(manager)
            timers = manager.brain.tools.timers
            now = [time.time()]
            timers.clock = lambda:now[0]
            timers.start(s.timers.request('fixture','claim-fixture'),1,action_id='fixture')
            now[0] += 1
            original_claim = timers.claim_due
            def held(*args,**kwargs):
                result = original_claim(*args,**kwargs)
                entered.set()
                assert release.wait(3)
                return result
            monkeypatch.setattr(timers,'claim_due',held)
            s.timers.capabilities({'type':'timer_capabilities','display_supported':False,'signal_supported':True})
            task = asyncio.create_task(s.timers.refresh(force=True))
            assert await asyncio.to_thread(entered.wait,2)
            if change_kind == 'disable':change(manager,timer=False)
            else:await s.stop()
            release.set()
            await task
            assert not any(event['type']=='timer_alarm' for event in s.events)
            assert not original_claim(s.timers.request(),'later-consumer')
            assert not s.input_open
        finally:
            release.set()
            if task:await asyncio.gather(task,return_exceptions=True)
            await cleanup(original,board,manager)
    asyncio.run(run())


def test_old_attachment_ack_cannot_confirm_replacement_or_replay_alarm(tmp_path, settings, monkeypatch):
    async def run():
        original,board,manager,provider = configured(tmp_path,settings)
        entered,release = threading.Event(),threading.Event()
        task = None
        try:
            s = await start(manager)
            timers = manager.brain.tools.timers
            now = [time.time()]
            timers.clock = lambda:now[0]
            timers.start(s.timers.request('fixture','ack-fixture'),1,action_id='fixture')
            now[0] += 1
            s.timers.capabilities({'type':'timer_capabilities','display_supported':False,'signal_supported':True})
            await s.timers.refresh(force=True)
            alarm, = [event['data'] for event in s.events if event['type']=='timer_alarm']
            original_ack = timers.ack
            def held(*args,**kwargs):
                entered.set()
                assert release.wait(3)
                return original_ack(*args,**kwargs)
            monkeypatch.setattr(timers,'ack',held)
            task = asyncio.create_task(s.timers.command({'type':'timer_alarm_ack',
                'alarm_id':alarm['alarm_id'],'claim_id':alarm['claim_id'],'state':'finished'}))
            assert await asyncio.to_thread(entered.wait,2)
            await s.detach()
            await s.reattach()
            s.timers.capabilities({'type':'timer_capabilities','display_supported':False,'signal_supported':True})
            release.set()
            assert await task is False
            assert s.timers.status()['signal'] == 'unconfirmed'
            assert not timers.claim_due(s.timers.request(),'replacement')
        finally:
            release.set()
            if task:await asyncio.gather(task,return_exceptions=True)
            await cleanup(original,board,manager)
    asyncio.run(run())


def test_disabling_selected_expert_returns_idle_selection_to_fast_without_response(tmp_path, settings):
    async def run():
        original,board,manager,provider = configured(tmp_path,settings)
        try:
            s = await start(manager)
            await s.select_mode('expert')
            change(manager,expert=False)
            await s.refresh_home_context(now=s._home_context_next_check)
            assert s.selected_mode == 'fast'
            assert not any(event['type']=='response.create' for event in provider.sockets[0].sent)
            assert board.budget.status()['sessions_reserved'] == 0
        finally:await cleanup(original,board,manager)
    asyncio.run(run())


def test_disabling_memory_while_recall_waits_blocks_late_context_and_supplement(tmp_path, settings, monkeypatch):
    async def run():
        from test_direct_working_memory import setup_memory,ask,complete,context_items,requests
        original,board,manager,s,provider = await setup_memory(tmp_path,settings)
        release = threading.Event()
        lookup = manager.brain.memory.recall
        def held(*args,**kwargs):
            assert release.wait(3)
            return lookup(*args,**kwargs)
        monkeypatch.setattr(manager.brain.memory,'recall',held)
        try:
            turn,response = await ask(s)
            state = s.memory_flow.turn
            count = len(context_items(provider))
            s.profile.conversation.skills.memory = False
            release.set()
            await state['task']
            await complete(s,response)
            assert len(context_items(provider)) == count
            assert len(requests(provider)) == 1
            assert not s.memory_flow.permits_summary(turn.req)
        finally:
            release.set()
            await cleanup(original,board,manager)
    asyncio.run(run())


@pytest.mark.parametrize('boundary', ['reserve', 'send'])
def test_memory_disable_while_response_waits_blocks_paid_supplement(tmp_path, settings, monkeypatch, boundary):
    async def run():
        original,board,manager,provider = configured(tmp_path,settings)
        entered,release = threading.Event(),threading.Event()
        task = None
        locked = False
        try:
            s = await start(manager)
            await s.wake('synthetic-memory-followup')
            s.input_open = False
            turn = await s.new_turn(query='Синтетический вопрос о контексте')
            turn.memory_supplement = True
            reserve = manager.budget.reserve_response
            if boundary == 'reserve':
                def held(*args,**kwargs):
                    entered.set()
                    assert release.wait(3)
                    return reserve(*args,**kwargs)
                monkeypatch.setattr(manager.budget,'reserve_response',held)
            else:
                await s.send_lock.acquire()
                locked = True
                send = s.send
                async def held(event,**kwargs):
                    if event.get('type') == 'response.create':entered.set()
                    return await send(event,**kwargs)
                monkeypatch.setattr(s,'send',held)
            task = asyncio.create_task(s.response())
            assert await asyncio.to_thread(entered.wait,2)
            change(manager,memory=False)
            release.set()
            if locked:
                s.send_lock.release();locked = False
            await task
            assert not any(event['type']=='response.create' for event in provider.sockets[0].sent)
            assert not s.response_requested and not s.pending_response
            with manager.budget.connect() as db:
                # A durable reservation is never silently refunded or retried.
                assert db.execute('SELECT sum(responses) FROM sessions').fetchone()[0] == 1
        finally:
            release.set()
            if locked:s.send_lock.release()
            if task:await asyncio.gather(task,return_exceptions=True)
            await cleanup(original,board,manager)
    asyncio.run(run())
