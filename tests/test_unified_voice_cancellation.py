"""Concurrent cancellation at real DirectSession asynchronous boundaries."""
import asyncio

import pytest

from test_realtime_ws import cleanup
from test_unified_board_admission import setup, offline_expert_registry


class Recognition:
    def __init__(self): self.received = 0

    async def live(self, chunks, **kwargs):
        async for chunk in chunks:
            self.received += len(chunk)
        if False: yield None


async def interrupt_and_restore(session, boundary):
    if boundary == 'stop':
        await session.stop()
    elif boundary == 'mute':
        await session.mute(True)
        await session.mute(False)
    else:
        await session.detach()
        await session.reattach()


@pytest.mark.parametrize('phase', ['admission', 'input_ack'])
@pytest.mark.parametrize('boundary', ['stop', 'mute', 'detach'])
def test_pending_followup_is_cancelled_before_slow_stop_cleanup(tmp_path, settings, phase, boundary):
    async def run():
        original, board, manager, session, _ = await setup(tmp_path, settings)
        pending, release = asyncio.Event(), asyncio.Event()
        cleanup_started, cleanup_release = asyncio.Event(), asyncio.Event()
        stop_task = None
        guard = None
        stopping = False
        try:
            await session.wake('manual')
            session.input_open = False
            original_admission, original_update, original_send = session.admission, session.update_input, session.send
            async def admission(**kwargs):
                if phase == 'admission' and asyncio.current_task() is guard:
                    pending.set(); await release.wait()
                return await original_admission(**kwargs)
            async def update(value):
                if phase == 'input_ack' and asyncio.current_task() is guard:
                    pending.set(); await release.wait()
                return await original_update(value)
            async def send(event, **kwargs):
                if stopping and not cleanup_started.is_set() and event['type'] == 'input_audio_buffer.clear':
                    cleanup_started.set(); await cleanup_release.wait()
                return await original_send(event, **kwargs)
            session.admission, session.update_input, session.send = admission, update, send
            guard = session.spawn(session.open_followup_after_guard())
            session._guard_task = guard
            async with asyncio.timeout(3):
                await pending.wait()
                stopping = True
                stop_task = asyncio.create_task(interrupt_and_restore(session, boundary))
                await cleanup_started.wait()
                # The old admission/ACK is released while Stop itself is still
                # awaiting transport cleanup: the original bug reopened input.
                release.set()
                await asyncio.sleep(0)
                assert session._guard_task is None
                cleanup_release.set()
                await stop_task
                await asyncio.gather(guard, return_exceptions=True)
            assert not session.input_open and not await session.append_pcm(bytes(4800))
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            release.set(); cleanup_release.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('next_mode', ['fast', 'expert'])
def test_retired_stt_cleanup_cannot_close_reconnected_capture(tmp_path, settings, next_mode):
    async def run():
        cleanup_started, cleanup_release = asyncio.Event(), asyncio.Event()
        class SlowCloseRecognition(Recognition):
            def __init__(self):
                super().__init__()
                self.calls = 0
            async def live(self, chunks, **kwargs):
                self.calls += 1
                call = self.calls
                try:
                    async for chunk in chunks: self.received += len(chunk)
                finally:
                    if call == 1:
                        cleanup_started.set(); await cleanup_release.wait()
                if False: yield None
        recognition = SlowCloseRecognition()
        original, board, manager, session, _ = await setup(tmp_path, settings, recognition=recognition)
        try:
            await session.wake('first', mode='expert')
            old_task = session._stt_task
            await asyncio.sleep(0)
            await session.detach()
            async with asyncio.timeout(3):
                await cleanup_started.wait()
                await session.reattach()
                await session.wake('second', mode=next_mode)
                new_queue = session._stt_queue
                cleanup_release.set()
                await asyncio.gather(old_task, return_exceptions=True)
            assert session.input_open
            if next_mode == 'expert':
                assert session._stt_queue is new_queue and new_queue is not None
            else:
                assert session._stt_queue is None
            assert await session.append_pcm(bytes(4800))
        finally:
            cleanup_release.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('phase', ['guard_sleep', 'admission'])
@pytest.mark.parametrize('activation', ['wake', 'mode_only'])
def test_new_explicit_expert_intent_supersedes_old_followup_even_after_admission_await(tmp_path, settings, phase, activation):
    async def run():
        original, board, manager, session, _ = await setup(tmp_path, settings, recognition=Recognition())
        pending, release = asyncio.Event(), asyncio.Event()
        guard = None
        try:
            await session.wake('first-fast')
            session.input_open = False
            actual_admission = session.admission
            async def admission(**kwargs):
                if asyncio.current_task() is guard:
                    pending.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        # Model a non-cancellable reservation finishing after
                        # cancellation: the epoch must still suppress its input.
                        await release.wait()
                return await actual_admission(**kwargs)
            if phase == 'admission': session.admission = admission
            guard = session.spawn(session.open_followup_after_guard())
            session._guard_task = guard
            if phase == 'admission':
                async with asyncio.timeout(3): await pending.wait()
            else:
                await asyncio.sleep(0)
            if activation == 'wake':
                await session.wake('explicit-expert', mode='expert')
            else:
                await session.select_mode('expert')
            release.set()
            await asyncio.gather(guard, return_exceptions=True)
            assert session.selected_mode == 'expert'
            assert session.input_open == (activation == 'wake')
            assert (session._stt_queue is not None) == (activation == 'wake')
            assert board.budget.status()['sessions_reserved'] == 1
            assert manager.board_speech_ledger.status()['operations'].get('stt', {}).get('attempts', 0) == (1 if activation == 'wake' else 0)
            events = []
            while not session.outgoing.empty(): events.append(session.outgoing.get_nowait())
            assert not any(e and e['type'] == 'followup_closed' for e in events)
        finally:
            release.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('phase', ['fast_admission', 'fast_ack', 'stt_authorizer'])
@pytest.mark.parametrize('boundary', ['stop', 'mute', 'detach'])
def test_pending_explicit_activation_cannot_outlive_stop_unmute_or_reattach(tmp_path, settings, phase, boundary):
    async def run():
        recognition = Recognition()
        original, board, manager, session, _ = await setup(tmp_path, settings, recognition=recognition)
        pending, release = asyncio.Event(), asyncio.Event()
        wake = None
        try:
            actual_admission, actual_update = session.admission, session.update_input
            actual_authorizer = manager.transcription_authorizer
            async def admission(**kwargs):
                result = await actual_admission(**kwargs)
                if phase == 'fast_admission':
                    pending.set(); await release.wait()
                return result
            async def update(value):
                result = await actual_update(value)
                if phase == 'fast_ack':
                    pending.set(); await release.wait()
                return result
            async def authorizer(s):
                result = await actual_authorizer(s)
                pending.set(); await release.wait()
                return result
            session.admission, session.update_input = admission, update
            manager.transcription_authorizer = authorizer
            wake = asyncio.create_task(session.wake('manual', mode='expert' if phase == 'stt_authorizer' else 'fast'))
            async with asyncio.timeout(3):
                await pending.wait()
                await interrupt_and_restore(session, boundary)
                # Restore mute/connection BEFORE releasing the old activation;
                # current booleans alone cannot detect the stale operation.
                release.set()
                with pytest.raises(PermissionError, match='voice_activation_cancelled'):
                    await wake
            assert not session.input_open and session._stt_queue is None
            assert not await session.append_pcm(bytes(4800)) and recognition.received == 0
            assert not any(e['type'] == 'input_audio_buffer.append'
                           for socket in manager.provider.sockets for e in socket.sent)
            # A racing durable reservation is retained, never silently refunded.
            if phase == 'stt_authorizer':
                assert board.budget.status()['sessions_reserved'] == 0
                assert manager.board_speech_ledger.status()['operations']['stt']['pending_usage'] == 1
            else:
                assert board.budget.status()['sessions_reserved'] == 1
        finally:
            release.set()
            if wake and not wake.done():
                wake.cancel(); await asyncio.gather(wake, return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('phase', ['fast_admission', 'send_lock', 'stt_validator'])
def test_queued_pcm_cannot_cross_stop_during_admission_validation_or_send_lock(tmp_path, settings, phase):
    async def run():
        recognition = Recognition()
        original, board, manager, session, _ = await setup(tmp_path, settings, recognition=recognition)
        pending, release = asyncio.Event(), asyncio.Event()
        append = stop = None
        locked = False
        try:
            await session.wake('manual', mode='expert' if phase == 'stt_validator' else 'fast')
            if phase == 'fast_admission':
                original_admission = session.admission
                async def admission(**kwargs):
                    result = await original_admission(**kwargs)
                    if asyncio.current_task() is append:
                        pending.set(); await release.wait()
                    return result
                session.admission = admission
            elif phase == 'stt_validator':
                validate = session._stt_reservation['validate']
                async def delayed_validator():
                    await validate(); pending.set(); await release.wait()
                session._stt_reservation['validate'] = delayed_validator
            else:
                await session.send_lock.acquire(); locked = True
                original_send = session.send
                async def send(event, **kwargs):
                    if event['type'] == 'input_audio_buffer.append': pending.set()
                    return await original_send(event, **kwargs)
                session.send = send
            append = asyncio.create_task(session.append_pcm(bytes(4800)))
            epoch = session._input_gate_epoch
            async with asyncio.timeout(3):
                await pending.wait()
                stop = asyncio.create_task(session.stop())
                while session._input_gate_epoch == epoch: await asyncio.sleep(0)
                release.set()
                if locked:
                    session.send_lock.release(); locked = False
                assert await append is False
                await stop
            assert not session.input_open and recognition.received == 0
            assert not any(e['type'] == 'input_audio_buffer.append'
                           for socket in manager.provider.sockets for e in socket.sent)
        finally:
            release.set()
            if locked: session.send_lock.release()
            for task in (append, stop):
                if task and not task.done(): task.cancel()
            await asyncio.gather(*(t for t in (append, stop) if t), return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())
