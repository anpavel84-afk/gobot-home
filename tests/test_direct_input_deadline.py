"""Bounded direct-WS input after a missing endpoint; all provider I/O is mocked."""
import asyncio
import json
import time

from test_realtime_ws import setup, offer, cleanup


async def pending_name(session):
    await session.wake('name', trigger='wake_word')
    await session.handle({'type': 'input_audio_buffer.speech_started'})
    assert session.auto_input_deadline > time.monotonic()
    await session.append_pcm(bytes(9600))
    await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'name-item'})
    assert session._wake_fragment is not None
    assert session.auto_input_deadline is None
    return session._wake_fragment


async def resolve_name(session, fragment):
    await session.handle({'type': 'conversation.item.input_audio_transcription.completed',
                          'item_id': 'name-item', 'transcript': 'София'})
    await fragment['task']


def test_missing_endpoint_closes_fast_input_before_operation_expiry(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('first')
            await session.handle({'type': 'input_audio_buffer.speech_started'})
            deadline = session.auto_input_deadline
            assert 29 < deadline-time.monotonic() <= 30
            # Repeated provider events must not renew the speech window.
            await session.handle({'type': 'input_audio_buffer.speech_started'})
            assert session.auto_input_deadline == deadline
            session.auto_input_deadline = time.monotonic()-1
            await asyncio.sleep(.2)
            assert session.ready and not session.closed and not session.input_open
            assert session.state == 'ready' and session.input_mode == 'idle'
            assert session.auto_input_deadline is None and session.followup_deadline is None
            assert not session._input_started
            assert any(event['type'] == 'input_closed' and
                       event['data'].get('reason') == 'input_time_limit' and
                       event['data'].get('input_open') is False and
                       event['data'].get('automatic_retry') is False
                       for event in session.events)
            assert not any(event['type'] == 'response.create' for event in session.ws.sent)
            assert board.budget.status()['sessions_reserved'] == 1
            # An explicit next wake remains usable inside the same paid start.
            result = await session.wake('second')
            assert result['accepted'] and session.input_open
            assert session.auto_input_deadline is None
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_stop_then_new_wake_does_not_inherit_speech_deadline(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('first')
            await session.handle({'type': 'input_audio_buffer.speech_started'})
            assert session.auto_input_deadline is not None
            await session.stop()
            assert session.auto_input_deadline is None
            await session.wake('second')
            assert session.input_open and session.auto_input_deadline is None
            await session.handle({'type': 'input_audio_buffer.speech_started'})
            assert 29 < session.auto_input_deadline-time.monotonic() <= 30
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_delayed_timeout_cannot_close_a_new_activation(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        entered, release = asyncio.Event(), asyncio.Event()
        try:
            session = await manager.accept(offer())
            await session.wake('first')
            await session.handle({'type': 'input_audio_buffer.speech_started'})
            old_epoch = session._input_gate_epoch
            native_close = session.close_fast_input

            async def delayed_close(reason, **kwargs):
                if reason == 'input_time_limit':
                    assert kwargs['input_epoch'] == old_epoch
                    entered.set()
                    await release.wait()
                return await native_close(reason, **kwargs)

            session.close_fast_input = delayed_close
            session.auto_input_deadline = time.monotonic()-1
            await asyncio.wait_for(entered.wait(), 1)
            await session.stop()
            await session.wake('second')
            release.set()
            await asyncio.sleep(.2)
            assert session.input_open and session.state == 'listening'
            assert session.auto_input_deadline is None
            assert session._input_gate_epoch != old_epoch
            assert not any(event['type'] == 'input_closed' and
                           event['data'].get('reason') == 'input_time_limit'
                           for event in session.events)
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            release.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_name_only_waits_for_question_without_inheriting_name_deadline(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            fragment = await pending_name(session)
            await resolve_name(session, fragment)
            assert session.input_open and not session._input_started
            assert session.auto_input_deadline is None
            assert 7 < session.followup_deadline-time.monotonic() <= 8
            await session.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'question'})
            assert session.followup_deadline is None
            assert 29 < session.auto_input_deadline-time.monotonic() <= 30
            assert not any(event['type'] == 'response.create' for event in session.ws.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_question_during_name_asr_keeps_its_original_speech_deadline(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            fragment = await pending_name(session)
            await session.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'question'})
            started_at = fragment['speech_started_at']
            assert started_at > 0
            await session.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'question'})
            assert fragment['speech_started_at'] == started_at
            await resolve_name(session, fragment)
            assert session.input_open and session._input_started
            assert session.followup_deadline is None
            assert session.auto_input_deadline == started_at+30
            session.auto_input_deadline = time.monotonic()-1
            await asyncio.sleep(.2)
            assert not session.input_open and session.ready
            assert not any(event['type'] == 'response.create' for event in session.ws.sent)
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_question_during_name_pcm_flush_also_arms_a_deadline(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        entered, release = asyncio.Event(), asyncio.Event()
        try:
            session = await manager.accept(offer())
            fragment = await pending_name(session)
            await session.append_pcm(bytes([9, 0])*2400)
            native_send = session.ws.send

            async def delayed_send(raw):
                if json.loads(raw)['type'] == 'input_audio_buffer.append':
                    entered.set()
                    await release.wait()
                await native_send(raw)

            session.ws.send = delayed_send
            await session.handle({'type': 'conversation.item.input_audio_transcription.completed',
                                  'item_id': 'name-item', 'transcript': 'София'})
            await asyncio.wait_for(entered.wait(), 1)
            await session.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'question'})
            started_at = fragment['speech_started_at']
            release.set()
            await fragment['task']
            assert session.input_open and session._input_started
            assert session.followup_deadline is None
            assert session.auto_input_deadline == started_at+30
        finally:
            release.set()
            await cleanup(original, board, manager)
    asyncio.run(run())
