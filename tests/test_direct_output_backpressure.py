"""Burst provider / paced subscriber regressions; mock transport, no model calls."""
import asyncio
import base64

import pytest

from gobot.realtime_output_queue import DirectOutputQueue
from test_realtime_ws import cleanup, complete_input, offer, setup


def test_audio_capacity_preserves_order_and_reserves_end_marker_space():
    async def run():
        queue = DirectOutputQueue(audio_limit=2, control_limit=2)
        first = {'type': 'audio_chunk', 'data': {'seq': 0}}
        second = {'type': 'audio_chunk', 'data': {'seq': 1}}
        start = {'type': 'audio_start'}
        end = {'type': 'audio_stop'}
        queue.put_nowait(start)
        await queue.put(first)
        await queue.put(second)
        queue.put_nowait(end)
        assert queue.qsize() == queue.maxsize == 4
        with pytest.raises(asyncio.QueueFull):
            queue.put_nowait({'type': 'telemetry'})
        with pytest.raises(asyncio.QueueFull):
            queue.put_nowait(first)
        assert [await queue.get() for _ in range(4)] == [start, first, second, end]
        assert queue.empty()
    asyncio.run(run())


async def start_response(session, number):
    await session.wake('wake-'+str(number))
    item = 'input-'+str(number)
    await session.handle({'type': 'input_audio_buffer.committed', 'item_id': item})
    await complete_input(session, item_id=item)
    for _ in range(100):
        if session.live_response:
            return session.live_response
        await asyncio.sleep(.001)
    raise AssertionError('mock response was not acknowledged')


def test_two_burst_answers_finish_with_paced_output_and_many_caption_deltas(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            # A smaller audio reservation forces real awaited backpressure.
            # The production total is still bounded to 128 events.
            session.outgoing = DirectOutputQueue(audio_limit=3, control_limit=64)
            for number in (1, 2):
                ident = await start_response(session, number)
                frames, controls = [], []
                done = asyncio.Event()

                async def paced_subscriber():
                    while True:
                        event = await session.next_event()
                        kind, data = event['type'], event['data']
                        controls.append(kind)
                        if kind == 'audio_chunk':
                            frames.append((data['seq'], base64.b64decode(data['pcm'])))
                            await asyncio.sleep(.001)
                        elif kind == 'audio_stop':
                            assert data['response_id'] == ident
                            done.set()
                            return

                consumer = asyncio.create_task(paced_subscriber())
                try:
                    for seq in range(80):
                        # Three caption events per audio frame reproduced the
                        # old mixed-queue overflow, even with a healthy consumer.
                        for _ in range(3):
                            await session.handle({'type': 'response.output_audio_transcript.delta',
                                'response_id': ident, 'delta': 'а'})
                        await session.handle({'type': 'response.output_audio.delta',
                            'response_id': ident,
                            'delta': base64.b64encode(bytes([seq, 0])*120).decode()})
                    await session.handle({'type': 'response.done', 'response': {
                        'id': ident, 'status': 'completed', 'usage': {'total_tokens': 23}}})
                    await asyncio.wait_for(done.wait(), 2)
                    await consumer
                finally:
                    consumer.cancel()
                    await asyncio.gather(consumer, return_exceptions=True)
                assert frames == [(seq, bytes([seq, 0])*120) for seq in range(80)]
                assert 'text_delta' not in controls
                assert any(event['type'] == 'text_delta' for event in session.events)
                assert session.current.answer == 'а'*240
                assert session.attached and not session._wire_overflow
                assert session.speaking and not session.input_open
                # A generation/end marker is still not proof of heard speech.
                assert not session.current.drained
                await session.playback_started(ident)
                await session.playback_finished(ident, sample_floor=number*100000)
                assert session.current.drained
                assert session.current.stored and not session.current.cancelled
                await session.stop()  # Retire automatic follow-up for the next manual fixture turn.
            assert board.budget.total_tokens(session.operation_id) == 46
            assert not session.subscriber_detached.is_set()
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_blocked_pcm_cannot_cross_detach_and_reattach_or_advance_new_sequence(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            session.outgoing = DirectOutputQueue(audio_limit=1, control_limit=64)
            assert await session.publish_audio(bytes(240), 'old')
            pending = asyncio.create_task(session.publish_audio(bytes(240), 'old'))
            await asyncio.sleep(.01)
            assert not pending.done()
            old_signal = session.subscriber_detached
            await session.detach(reason='output_backpressure')
            assert old_signal.is_set()
            await session.detach()  # API cleanup preserves the actual reason.
            assert session.last_detach_reason == 'output_backpressure'
            await session.reattach()
            assert not session.subscriber_detached.is_set()
            assert session.subscriber_detached is not old_signal
            assert await pending is False
            assert await session.publish_audio(bytes(240), 'new')
            chunks = [event for event in session.outgoing._queue
                      if event and event['type'] == 'audio_chunk']
            assert len(chunks) == 1 and chunks[0]['data']['response_id'] == 'new'
            assert chunks[0]['data']['seq'] == 0 and session.output_sequence == 1
            assert len(provider.sockets) == 1
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('failure', ['control_overflow', 'audio_stall'])
def test_real_stall_detaches_but_retains_late_usage_without_heard_completion(
        tmp_path, settings, monkeypatch, failure):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            ident = await start_response(session, 1)
            session.outgoing = DirectOutputQueue(audio_limit=1, control_limit=4)
            await session.publish_audio(bytes(240), ident)
            if failure == 'control_overflow':
                for i in range(8):
                    session.emit('telemetry', event='fixture_control', number=i)
                await asyncio.wait_for(session.subscriber_detached.wait(), .5)
                await session.detach()
            else:
                monkeypatch.setattr('gobot.realtime_ws._OUTPUT_CAPACITY_TIMEOUT_SECONDS', .02)
                assert not await session.publish_audio(bytes(240), ident)
            assert not session.attached and session.subscriber_detached.is_set()
            assert session.last_detach_reason == 'output_backpressure'
            assert not session.speaking and not session.input_open
            assert session.current.cancelled and not session.current.drained
            assert session.reader and not session.reader.done() and session.ready
            await session.handle({'type': 'response.done', 'response': {
                'id': ident, 'status': 'cancelled', 'usage': {'total_tokens': 37}}})
            assert board.budget.total_tokens(session.operation_id) == 37
            assert not session.current.drained
            assert session.outgoing.empty()
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
