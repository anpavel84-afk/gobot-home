"""Real Direct handlers with synthetic provider/PCM only; no API requests."""
import asyncio
import base64
import json
import threading
import time

import pytest

from test_owner_terminal_direct import setup_terminal
from test_realtime_ws import cleanup


async def setup_memory(tmp_path, settings, *, ack_context=True):
    original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
    if ack_context:
        from contextlib import asynccontextmanager

        def add_context_ack(socket):
            send = socket.send

            async def acknowledged_send(raw):
                await send(raw)
                event = json.loads(raw)
                if (event['type'] == 'conversation.item.create' and
                        event.get('item', {}).get('id', '').startswith('memory_')):
                    await socket.queue.put({'type': 'conversation.item.added',
                                            'item': event['item']})

            socket.send = acknowledged_send

        for socket in provider.sockets:
            add_context_ack(socket)
        open_provider = provider.open

        @asynccontextmanager
        async def with_context_ack(model):
            async with open_provider(model) as socket:
                add_context_ack(socket)
                yield socket

        provider.open = with_context_ack
    manager.memory_policy_store.set('board', 'board', session.policy.authorization,
        {'enabled': True, 'ttl_seconds': 43200, 'persist': False, 'summarize': False,
         'background': True, 'supplement': True})
    await session.memory_flow.configure()
    for index in range(9):
        text = ('Обсудим бензин: интересует только сравнение без рекомендаций покупки.'
                if index == 0 else f'Синтетическая тема космоса, пункт {index}.')
        req = session.request(text, 'seed-'+str(index))
        manager.brain.memory.start(req)
        manager.brain.memory.finish(req, 'completed', 'Синтетический ответ '+str(index),
                                    'openai:synthetic-fixture', [])
    return original, board, manager, session, provider


async def ask(session, text='Какие особенности бензина?'):
    await session.wake('wake-'+str(time.monotonic_ns()))
    # Synthetic final ASR at the same gate as a physical committed question.
    session.input_open = False
    session.input_mode = 'processing'
    turn = await session.new_turn('input-'+str(time.monotonic_ns()))
    await session.input_text(turn, text)
    await session.response()
    for _ in range(100):
        if session.live_response:
            return turn, session.live_response
        await asyncio.sleep(.001)
    raise AssertionError('mock response acknowledgement missing')


async def complete(session, response, text='Синтетическое основное объяснение.'):
    await session.handle({'type': 'response.output_audio_transcript.delta',
                          'response_id': response, 'delta': text})
    await session.handle({'type': 'response.output_audio.delta', 'response_id': response,
                          'delta': base64.b64encode(bytes(4800)).decode()})
    await session.playback_started(response)
    await session.handle({'type': 'response.done', 'response': {
        'id': response, 'status': 'completed', 'usage': {
            'total_tokens': 20, 'input_tokens': 10, 'output_tokens': 10}}})
    return await session.playback_finished(response)


def requests(provider):
    return [event for socket in provider.sockets for event in socket.sent
            if event['type'] == 'response.create']


def context_items(provider):
    return [event for socket in provider.sockets for event in socket.sent
            if event['type'] == 'conversation.item.create'
            and event.get('item', {}).get('id', '').startswith('memory_')]


def test_every_ordinary_question_starts_lookup_and_hot_context_precedes_first_response(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup_memory(tmp_path, settings)
        calls = []
        real = manager.brain.memory.recall
        def observed(req, **kwargs):
            calls.append(req.text)
            return real(req, **kwargs)
        monkeypatch.setattr(manager.brain.memory, 'recall', observed)
        try:
            turn, response = await ask(session)
            await session.memory_flow.turn['task']
            assert calls == ['Какие особенности бензина?']
            sent = provider.sockets[-1].sent
            first_response = next(i for i, event in enumerate(sent) if event['type'] == 'response.create')
            assert any(event['type'] == 'conversation.item.create' and
                       event.get('item', {}).get('id', '').startswith('memory_')
                       for event in sent[:first_response])
            assert len(requests(provider)) == 1  # retrieval itself never generates
            assert session.memory_flow.last['queries'] == 1
            await session.stop()
            await ask(session, 'Как приготовить омлет?')
            await session.memory_flow.turn['task']
            assert calls == ['Какие особенности бензина?', 'Как приготовить омлет?']
            assert session.memory_flow.last['queries'] == 2
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_late_context_adds_one_same_turn_response_only_after_physical_playback(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup_memory(tmp_path, settings)
        release = threading.Event()
        real = manager.brain.memory.recall
        def delayed(req, **kwargs):
            assert release.wait(2)
            return real(req, **kwargs)
        monkeypatch.setattr(manager.brain.memory, 'recall', delayed)
        try:
            turn, response = await ask(session)
            release.set()
            await session.memory_flow.turn['task']
            assert session.memory_flow.turn['late']
            assert len(requests(provider)) == 1
            await complete(session, response)
            for _ in range(100):
                if session.live_response and session.live_response != response:
                    break
                await asyncio.sleep(.001)
            assert len(requests(provider)) == 2
            assert session.current is turn and turn.memory_supplement
            assert requests(provider)[-1]['response']['tool_choice'] == 'none'
            assert requests(provider)[-1]['response']['max_output_tokens'] == 384
            second = session.live_response
            assert second and second != response
            await complete(session, second, 'Короткое синтетическое дополнение с учётом темы.')
            await asyncio.sleep(.02)
            assert len(requests(provider)) == 2
            assert session.memory_flow.last['supplements'] == 1
            assert board.budget.board_status()['response_attempts'] == 2
            context = manager.brain.memory.context(session.request('Дальше', 'after'))
            assert any('Короткое синтетическое дополнение' in item['content'] for item in context['messages'])
        finally:
            release.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('action', ['stop', 'new_turn', 'revision'])
def test_late_retrieval_cannot_cross_stop_new_question_or_input_revision(tmp_path, settings, monkeypatch, action):
    async def run():
        original, board, manager, session, provider = await setup_memory(tmp_path, settings)
        release = threading.Event()
        real = manager.brain.memory.recall
        def delayed(req, **kwargs):
            release.wait(2)
            return real(req, **kwargs)
        monkeypatch.setattr(manager.brain.memory, 'recall', delayed)
        try:
            turn, response = await ask(session)
            state = session.memory_flow.turn
            count = len(context_items(provider))
            if action == 'stop':
                await session.stop()
            elif action == 'new_turn':
                await session.new_turn('new-user-input')
            else:
                turn.input_revision += 1
            release.set()
            await asyncio.gather(state['task'], return_exceptions=True)
            assert len(context_items(provider)) == count
            assert len(requests(provider)) == 1
            assert session.memory_flow.last['supplements'] == 0
        finally:
            release.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_context_already_delivered_before_answer_does_not_generate_a_second_answer(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup_memory(tmp_path, settings)
        try:
            await session.wake('preseed')
            session.input_open = False
            turn = await session.new_turn('i')
            await session.input_text(turn, 'Какие особенности бензина?')
            await session.memory_flow.before_response(turn)
            await session.memory_flow.turn['task']
            assert not session.memory_flow.turn['late']
            await session.response()
            for _ in range(100):
                if session.live_response:
                    break
                await asyncio.sleep(.001)
            await complete(session, session.live_response)
            assert len(requests(provider)) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_clear_rotates_provider_and_cannot_reload_deleted_working_context(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup_memory(tmp_path, settings)
        try:
            before = len(provider.sockets)
            state = await session.memory_flow.clear()
            assert len(provider.sockets) == before+1
            assert state['working']['source_count'] == 0
            assert not manager.brain.memory.context(session.request('Дальше', 'next'))['messages']
            assert len(requests(provider)) == 0
            assert session.memory_flow.policy['enabled']
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('malformed', ['missing_field', 'non_object'])
def test_invalid_policy_unregisters_persistence_and_can_recover_same_policy(tmp_path, settings, malformed):
    async def run():
        original, board, manager, session, provider = await setup_memory(tmp_path, settings)
        try:
            path = manager.memory_policy_store.path
            good = path.read_text(encoding='utf-8')
            data = json.loads(good)
            key = next(iter(data['bindings']))
            if malformed == 'missing_field':
                data['bindings'][key].pop('enabled')
            else:
                data['bindings'][key] = []
            path.write_text(json.dumps(data), encoding='utf-8')
            await session.memory_flow.configure()
            state = session.memory_flow.status()
            assert not state['enabled'] and not state['working']['enabled']
            assert not state['working']['persistence_requested']
            assert state['lookup']['state'] == 'configuration_unavailable'
            path.write_text(good, encoding='utf-8')
            await session.memory_flow.configure()
            assert session.memory_flow.enabled
            assert session.memory_flow.status()['working']['enabled']
            assert len(requests(provider)) == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('action', ['stop', 'new_question'])
def test_old_input_cannot_replace_current_lookup_after_configuration_await(tmp_path, settings, monkeypatch, action):
    async def run():
        original, board, manager, session, provider = await setup_memory(tmp_path, settings)
        release, entered = asyncio.Event(), asyncio.Event()
        try:
            turn, _ = await ask(session)
            configure = session.memory_flow.configure
            calls = 0
            async def delayed_once():
                nonlocal calls
                calls += 1
                if calls == 1:
                    entered.set()
                    await release.wait()
                return await configure()
            monkeypatch.setattr(session.memory_flow, 'configure', delayed_once)
            pending = asyncio.create_task(session.memory_flow.on_input(turn))
            await asyncio.wait_for(entered.wait(), 1)
            if action == 'stop':
                await session.stop()
                expected = None
            else:
                newer = await session.new_turn('newer-question')
                await session.input_text(newer, 'Как сварить рис?')
                expected = session.memory_flow.turn
                assert expected and expected['turn'] is newer
            release.set()
            await asyncio.wait_for(pending, 1)
            assert session.memory_flow.turn is expected
            if expected:
                assert not expected['task'].cancelled()
            assert len(requests(provider)) == 1
        finally:
            release.set()
            await cleanup(original, board, manager)
    asyncio.run(run())
