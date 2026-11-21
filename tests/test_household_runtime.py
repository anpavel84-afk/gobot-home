"""Scoped native control regressions; real Brain/SQLite, synthetic provider only."""
import asyncio
import json

import httpx

from gobot.quick_intents import resolve_quick
from gobot.skill_catalogue import compact_instructions
from test_live_backend import configured, wire
from test_live_native_tools import start, say, count_timers


def test_decline_timer_duration_clears_pending_without_ending_conversation(tmp_path, settings):
    async def run():
        manager, session = await start(tmp_path, settings)
        try:
            await say(session, 'Поставь таймер', 0)
            assert (await session.tool_context(session.current))['pending_action']['kind'] == 'timer_duration'
            await say(session, 'Нет, спасибо', 5000)
            assert not session.closed and not session.closing
            assert not (await session.tool_context(session.current)).get('pending_action')
            await say(session, 'На пять минут', 10000)
            assert count_timers(manager) == 0
            assert any(e['type'] == 'session.commentary.append' and 'Действие отменено' in e['content'] for e in session.ws.sent)
        finally:
            await manager.shutdown()
            await manager.realtime.shutdown()
    asyncio.run(run())


def test_ordinal_uses_announced_snapshot_and_loses_binding_on_topic_change(tmp_path, settings):
    async def run():
        manager, session = await start(tmp_path, settings)
        try:
            req = session.timer_request()
            first = manager.brain.tools.execute('timer', req, {'seconds': 300, 'operation': 'start'})
            second = manager.brain.tools.execute('timer', req, {'seconds': 600, 'operation': 'start'})
            first_id, second_id = first.evidence['timer_id'], second.evidence['timer_id']
            await say(session, 'Покажи таймеры', 0)
            await say(session, 'Отмени второй', 5000)
            with manager.brain.memory.connect() as connection:
                states = dict(connection.execute('SELECT id,status FROM timers').fetchall())
            assert states == {first_id: 'running', second_id: 'cancelled'}
            await say(session, 'Покажи таймеры', 10000)
            assert manager.brain.tools.timer_context(req)
            await say(session, 'Который час?', 15000)
            assert not manager.brain.tools.timer_context(req)
            await say(session, 'Отмени первый', 20000)
            with manager.brain.memory.connect() as connection:
                assert connection.execute('SELECT status FROM timers WHERE id=?', (first_id,)).fetchone()[0] == 'running'
        finally:
            await manager.shutdown()
            await manager.realtime.shutdown()
    asyncio.run(run())


def test_timer_snapshot_cannot_cross_client_and_result_matches_widget(tmp_path, settings):
    async def run():
        manager, session = await start(tmp_path, settings)
        try:
            await say(session, 'Поставь таймер на пять минут', 0)
            widget = next(e['data']['presentation'] for e in session.events if e['type'] == 'visual_response' and e['data']['presentation']['type'] == 'timer_widget')
            status = [e['data'] for e in session.events if e['type'] == 'local_tool_status' and e['data']['state'] == 'completed'][-1]
            assert status['result_id'] == widget['id'] and status['has_source']
            await say(session, 'Покажи таймеры', 5000)
            req = session.timer_request(session.current)
            assert manager.brain.tools.timer_context(req)
            other = req.model_copy(update={'client_id': 'another-client'})
            assert not manager.brain.tools.timer_context(other)
            result = manager.brain.tools.cancel_timer(other, 'первый')
            assert result.evidence['needs_parameters']
            with manager.brain.memory.connect() as connection:
                assert connection.execute("SELECT count(*) FROM timers WHERE status='running'").fetchone()[0] == 1
        finally:
            await manager.shutdown()
            await manager.realtime.shutdown()
    asyncio.run(run())


def test_orphan_date_is_a_domain_clarification_and_bare_number_needs_unit():
    question = resolve_quick('А завтра?', {'weather_followup': False})
    assert question.executor == 'quick_clarify' and question.slots['missing_slots'] == ['domain']
    timer = resolve_quick('Таймер на пять')
    assert timer.executor == 'quick_clarify' and timer.slots['missing_slots'] == ['duration_unit']
    month = resolve_quick('Какая температура будет здесь в январе?')
    assert month.executor == 'settings' and month.slots == {'operation': 'weather_unsupported', 'reason': 'horizon'}
    assert resolve_quick('Погода в Рио не нужна') is None


def test_duration_unit_reply_uses_one_scoped_quantity_and_creates_one_timer(tmp_path, settings):
    async def run():
        manager, session = await start(tmp_path, settings)
        try:
            await say(session, 'Таймер на пять', 0)
            assert count_timers(manager) == 0
            await say(session, 'Минут', 5000)
            assert count_timers(manager) == 1
            status = [e['data'] for e in session.events if e['type'] == 'visual_response' and e['data']['presentation']['type'] == 'timer_widget'][-1]
            assert status['presentation']['metadata']['duration_ms'] == 300000
            assert not (await session.tool_context(session.current)).get('pending_action')
        finally:
            await manager.shutdown()
            await manager.realtime.shutdown()
    asyncio.run(run())


def test_selected_rules_are_counted_with_actual_backend_request(tmp_path):
    async def run():
        bodies = []
        def handler(request):
            body = json.loads(request.content)
            bodies.append(body)
            if request.url.path.endswith('input_tokens'):
                return httpx.Response(200, json={'input_tokens': 2048})
            return httpx.Response(200, text=wire(), headers={'content-type': 'text/event-stream'})
        backend, owner = configured(tmp_path, handler)
        question = 'Объясни, почему меняются времена года'
        await backend.answer(question, {'behavior_rules': 'UNTRUSTED-RULE-DO-NOT-LOAD'}, binding='owner', operation='selected-rules', developer=True)
        expected = compact_instructions(question, max_chars=1000, max_rules=4)
        assert expected and expected in bodies[0]['instructions']
        assert bodies[0]['instructions'] == bodies[1]['instructions']
        assert bodies[0]['input'] == bodies[1]['input']
        assert 'UNTRUSTED-RULE-DO-NOT-LOAD' not in json.dumps(bodies)
        assert bodies[1]['max_output_tokens'] == 512 and bodies[1]['tools'] == []
        assert len(bodies) == 2 and owner.status('owner')['attempts_today']['live_backend'] == 1
    asyncio.run(run())
