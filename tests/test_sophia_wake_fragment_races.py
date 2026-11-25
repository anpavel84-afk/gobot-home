"""First-question preservation while a name-only wake item awaits existing ASR."""
import asyncio
import base64
import json

import pytest

from test_realtime_ws import setup, offer, cleanup


async def pending_fragment(session):
    await session.wake('local-name', trigger='wake_word')
    await session.append_pcm(bytes(9600))
    await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'name-item'})
    assert session._wake_fragment is not None
    return session._wake_fragment


def test_pending_name_fragment_blocks_new_activation_and_mode_switch(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            fragment = await pending_fragment(s)
            epoch = s._input_gate_epoch
            with pytest.raises(ValueError, match='conversation_busy'):
                await s.wake('too-soon')
            with pytest.raises(ValueError, match='mode_change_requires_idle'):
                await s.select_mode('expert')
            assert not await s.rotate()
            assert s._wake_fragment is fragment and s._input_gate_epoch == epoch
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_terminal_input_expiry_discards_pending_name_ram_and_late_asr(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            fragment = await pending_fragment(s)
            assert await s.append_pcm(bytes([3, 0])*2400)
            assert fragment['pcm']
            s.operation_started -= 61
            await s.close_fast_input('paid_operation_expired_new_wake_required', input_epoch=fragment['epoch'])
            await asyncio.sleep(0)
            assert s._wake_fragment is None and not fragment['pcm']
            assert not s.input_open
            await s.handle({'type': 'conversation.item.input_audio_transcription.completed',
                            'item_id': 'name-item', 'transcript': 'София'})
            await asyncio.sleep(.01)
            assert not s.input_open
            assert not any(e['type'] == 'response.create' for e in s.ws.sent)
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_first_question_pcm_is_held_during_async_previous_turn_cleanup(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        entered, release = asyncio.Event(), asyncio.Event()
        commit = None
        try:
            s = await manager.accept(offer())
            await s.wake('local-name', trigger='wake_word')
            await s.append_pcm(bytes(9600))
            native_new_turn = s.new_turn
            async def delayed_new_turn(*args, **kwargs):
                entered.set()
                await release.wait()
                return await native_new_turn(*args, **kwargs)
            s.new_turn = delayed_new_turn
            commit = asyncio.create_task(s.handle({
                'type': 'input_audio_buffer.committed', 'item_id': 'name-item'}))
            await entered.wait()
            question_pcm = bytes([7, 0])*2400
            assert await s.append_pcm(question_pcm)
            release.set()
            await commit
            fragment = s._wake_fragment
            await s.handle({'type': 'conversation.item.input_audio_transcription.completed',
                            'item_id': 'name-item', 'transcript': 'София'})
            await fragment['task']
            appended = [base64.b64decode(e['audio']) for e in s.ws.sent
                        if e['type'] == 'input_audio_buffer.append']
            assert appended == [bytes(9600), question_pcm]
            assert s.input_open and s._wake_fragment is None
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            release.set()
            if commit:
                await asyncio.gather(commit, return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_question_started_during_name_asr_is_not_an_eight_second_silence_window(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            fragment = await pending_fragment(s)
            await s.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'question-item'})
            await s.handle({'type': 'conversation.item.input_audio_transcription.completed',
                            'item_id': 'name-item', 'transcript': 'София'})
            await fragment['task']
            assert s.input_open and s._input_started
            assert s.followup_deadline is None
            assert not any(e['type'] == 'response.create' for e in s.ws.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_question_started_while_held_pcm_flushes_cancels_silence_deadline(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        entered, release = asyncio.Event(), asyncio.Event()
        try:
            s = await manager.accept(offer())
            fragment = await pending_fragment(s)
            held = bytes([9, 0])*2400
            await s.append_pcm(held)
            original_send = s.ws.send
            async def delayed_send(raw):
                event = json.loads(raw)
                if event['type'] == 'input_audio_buffer.append':
                    entered.set()
                    await release.wait()
                await original_send(raw)
            s.ws.send = delayed_send
            await s.handle({'type': 'conversation.item.input_audio_transcription.completed',
                            'item_id': 'name-item', 'transcript': 'София'})
            await asyncio.wait_for(entered.wait(), 1)
            await s.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'question-item'})
            release.set()
            await fragment['task']
            assert s.input_open and s._input_started and s.followup_deadline is None
        finally:
            release.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('stop_during_cleanup', [False, True])
def test_replayed_question_preserves_concurrent_final_asr_and_honors_stop(
        tmp_path, settings, stop_during_cleanup):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        entered, release = asyncio.Event(), asyncio.Event()
        try:
            s = await manager.accept(offer())
            fragment = await pending_fragment(s)
            await s.handle({'type': 'input_audio_buffer.committed', 'item_id': 'question-item'})
            native_new_turn = s.new_turn
            async def delayed_new_turn(item_id, *args, **kwargs):
                if item_id == 'question-item':
                    entered.set()
                    await release.wait()
                return await native_new_turn(item_id, *args, **kwargs)
            s.new_turn = delayed_new_turn
            await s.handle({'type': 'conversation.item.input_audio_transcription.completed',
                            'item_id': 'name-item', 'transcript': 'София'})
            await asyncio.wait_for(entered.wait(), 1)
            question = 'Сколько будет два плюс три?'
            await s.handle({'type': 'conversation.item.input_audio_transcription.completed',
                            'item_id': 'question-item', 'transcript': question})
            if stop_during_cleanup:
                await s.stop()
            release.set()
            await fragment['task']
            if stop_during_cleanup:
                assert not any(e['type'] == 'response.create' for e in s.ws.sent)
                assert not s.input_open
            else:
                assert s.current.input_id == 'question-item' and s.current.query == question
                assert sum(e['type'] == 'response.create' for e in s.ws.sent) == 1
            assert s._wake_replay_fragment is None
        finally:
            release.set()
            await cleanup(original, board, manager)
    asyncio.run(run())
