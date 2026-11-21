"""Actual ASGI command reader remains responsive during background memory work.

The network is loopback only. Provider acknowledgements, transcripts and PCM
are synthetic; no microphone, model API or paid service is called.
"""
import asyncio
import base64
import json
import threading

from fastapi import FastAPI
from websockets.asyncio.client import connect

from gobot import realtime_ws_api
from test_brain_ws_transport import loopback, until
from test_direct_working_memory import ask, complete, context_items, requests, setup_memory
from test_direct_ws_detach import TOKEN
from test_realtime_ws import cleanup


async def receive_until(client, predicate, *, timeout=2):
    async with asyncio.timeout(timeout):
        while True:
            event = json.loads(await client.recv())
            if predicate(event):
                return event


def test_stop_on_actual_websocket_overtakes_playback_memory_wait(
        tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup_memory(tmp_path, settings)
        release = threading.Event()
        lookup_started = asyncio.Event()
        lookup_returned = asyncio.Event()
        playback_waiting = asyncio.Event()
        loop = asyncio.get_running_loop()
        recall = manager.brain.memory.recall
        after_playback = session.memory_flow.after_playback

        def delayed_recall(req, **kwargs):
            loop.call_soon_threadsafe(lookup_started.set)
            try:
                assert release.wait(5), 'Test did not release the synthetic lookup'
                return recall(req, **kwargs)
            finally:
                loop.call_soon_threadsafe(lookup_returned.set)

        async def observed_after_playback(turn):
            playback_waiting.set()
            return await after_playback(turn)

        monkeypatch.setattr(manager.brain.memory, 'recall', delayed_recall)
        monkeypatch.setattr(session.memory_flow, 'after_playback', observed_after_playback)
        app = FastAPI()
        realtime_ws_api.attach_brain_direct_voice(app, None, manager, lambda: None, TOKEN)
        headers = {'Authorization': 'Bearer ' + TOKEN}
        greeting = json.dumps({'type': 'hello', 'source': 'device',
                               'offer': session.offer.model_dump()})
        try:
            # Hand the existing synthetic session to the real ASGI attachment.
            await session.detach(reason='client_disconnected')
            async with loopback(app) as (url, _):
                async with connect(url + '/api/v1/voice-ws/stream',
                        additional_headers=headers, compression=None,
                        ping_interval=None) as client:
                    await client.send(greeting)
                    await receive_until(client, lambda event: event['type'] == 'ready')
                    assert manager.sessions[session.id] is session
                    turn, response = await ask(session)
                    await asyncio.wait_for(lookup_started.wait(), 1)
                    lookup_task = session.memory_flow.turn['task']
                    assert not lookup_task.done()
                    assert len(requests(provider)) == 1

                    await session.handle({'type': 'response.output_audio_transcript.delta',
                        'response_id': response, 'delta': 'Синтетическое основное объяснение.'})
                    await session.handle({'type': 'response.output_audio.delta',
                        'response_id': response,
                        'delta': base64.b64encode(bytes(4800)).decode()})
                    await client.send(json.dumps({'type': 'playback_started',
                                                  'response_id': response}))
                    await until(lambda: session.output_started, timeout=1)
                    await session.handle({'type': 'response.done', 'response': {
                        'id': response, 'status': 'completed',
                        'usage': {'input_tokens': 10, 'output_tokens': 10,
                                  'total_tokens': 20}}})

                    # Both commands traverse the SAME serial WS reader. A direct
                    # concurrent session.stop() call would miss the regression.
                    await client.send(json.dumps({'type': 'playback_finished',
                                                  'response_id': response}))
                    await asyncio.wait_for(playback_waiting.wait(), 1)
                    assert turn.stored and not lookup_task.done()
                    guard = session._guard_task
                    delivered_before_stop = len(context_items(provider))
                    await client.send(json.dumps({'type': 'stop',
                                                  'request_id': 'stop-during-memory'}))
                    stopped = await receive_until(client, lambda event:
                        event['type'] == 'stopped' and
                        event['data'].get('request_id') == 'stop-during-memory', timeout=.75)
                    assert stopped['data']['input_open'] is False
                    assert not release.is_set(), 'Stop must not wait for lookup completion'
                    assert session.memory_flow.turn is None
                    assert session.state == 'ready' and not session.input_open
                    assert not session.generating and not session.response_requested
                    assert guard is not None
                    await asyncio.gather(guard, lookup_task, return_exceptions=True)
                    assert guard.cancelled() and lookup_task.cancelled()

                    # An uncancellable worker thread may return after Stop. Its
                    # result cannot inject context, reopen input or emit speech.
                    release.set()
                    await asyncio.wait_for(lookup_returned.wait(), 1)
                    assert len(context_items(provider)) == delivered_before_stop
                    assert len(requests(provider)) == 1
                    assert session.memory_flow.last['supplements'] == 0
                    assert session.state == 'ready' and not session.input_open
                    assert board.budget.board_status()['response_attempts'] == 1
        finally:
            release.set()
            await cleanup(original, board, manager)

    asyncio.run(run())


def test_normal_tool_continuation_consumes_late_context_without_third_answer(
        tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup_memory(tmp_path, settings)
        release = threading.Event()
        recall = manager.brain.memory.recall

        def delayed_recall(req, **kwargs):
            assert release.wait(5), 'Test did not release the synthetic lookup'
            return recall(req, **kwargs)

        monkeypatch.setattr(manager.brain.memory, 'recall', delayed_recall)
        try:
            turn, first = await ask(session)
            assert turn.generation_sequence == 1
            release.set()
            state = session.memory_flow.turn
            await asyncio.wait_for(state['task'], 1)
            assert state['late'] and state['result_sequence'] == 1
            assert state['result'] and len(requests(provider)) == 1

            # The real read-only tool dispatcher returns its ordinary local
            # result and requests a continuation while reply one is active.
            # No external verification or provider operation exists for this
            # synthetic general query; it stays in the normal native flow.
            await session.tool('synthetic-tool-continuation', 'gobot_tool',
                               json.dumps({'query': turn.query}), turn)
            assert session.pending_response
            assert any(event.get('item', {}).get('type') == 'function_call_output'
                       and event['item']['call_id'] == 'synthetic-tool-continuation'
                       for event in provider.sockets[-1].sent)

            await complete(session, first)
            await until(lambda: session.live_response not in (None, first), timeout=1)
            second = session.live_response
            assert len(requests(provider)) == 2
            assert turn.generation_sequence == 2
            assert not turn.memory_supplement
            assert state['result_sequence'] < turn.generation_sequence
            events = provider.sockets[-1].sent
            context_index = max(index for index, event in enumerate(events)
                if event.get('item', {}).get('id', '').startswith('memory_'))
            response_indices = [index for index, event in enumerate(events)
                                if event['type'] == 'response.create']
            assert response_indices[0] < context_index < response_indices[1]

            await complete(session, second, 'Синтетическое пояснение результата инструмента.')
            guard = session._guard_task
            assert guard is not None
            await asyncio.wait_for(asyncio.shield(guard), 1)
            assert len(requests(provider)) == 2
            assert session.current is turn and not turn.memory_supplement
            assert session.memory_flow.last['supplements'] == 0
            assert board.budget.board_status()['response_attempts'] == 2
        finally:
            release.set()
            await cleanup(original, board, manager)

    asyncio.run(run())


def test_unacknowledged_context_does_not_authorize_spoken_supplement(
        tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup_memory(
            tmp_path, settings, ack_context=False)
        release = threading.Event()
        recall = manager.brain.memory.recall

        def delayed_recall(req, **kwargs):
            assert release.wait(5), 'Test did not release the synthetic lookup'
            return recall(req, **kwargs)

        monkeypatch.setattr(manager.brain.memory, 'recall', delayed_recall)
        try:
            known = set(session.memory_flow.known_sources)
            turn, response = await ask(session)
            release.set()
            state = session.memory_flow.turn
            await asyncio.wait_for(state['task'], 1)
            assert context_items(provider), 'Context must actually reach the transport'
            assert session.memory_flow.last['state'] == 'context_ack_unconfirmed'
            assert not state['late'] and state['result'] is None
            assert session.memory_flow.known_sources == known

            await complete(session, response)
            guard = session._guard_task
            assert guard is not None
            await asyncio.wait_for(asyncio.shield(guard), 1)
            assert len(requests(provider)) == 1
            assert not turn.memory_supplement
            assert session.memory_flow.last['supplements'] == 0
            assert board.budget.board_status()['response_attempts'] == 1
        finally:
            release.set()
            await cleanup(original, board, manager)

    asyncio.run(run())
