"""A spoken name must not spend a response or discard the following question."""
import asyncio
import base64

import pytest

from test_realtime_ws import setup, offer, cleanup


async def begin(session, *, early=None, trigger='wake_word'):
    await session.wake('wake-1', trigger=trigger)
    await session.append_pcm(b'\x01\x00'*4800)
    if early is not None:
        await session.handle({'type': 'conversation.item.input_audio_transcription.completed',
                              'item_id': 'wake-item', 'transcript': early})
    await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'wake-item'})
    return session._wake_fragment


async def transcript(session, text='София!'):
    await session.handle({'type': 'conversation.item.input_audio_transcription.completed',
                          'item_id': 'wake-item', 'transcript': text})


def response_count(session):
    return sum(e['type'] == 'response.create' for e in session.ws.sent)


@pytest.mark.parametrize('early', [False, True])
def test_name_only_holds_inflight_pcm_then_forwards_once_without_another_start(tmp_path, settings, early):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            fragment = await begin(session, early='София!' if early else None)
            clears = sum(e['type'] == 'input_audio_buffer.clear' for e in session.ws.sent)
            queued = [b'\x02\x00'*1440, b'\x03\x00'*1440]
            for pcm in queued:
                assert await session.append_pcm(pcm)
            assert response_count(session) == 0
            assert len([e for e in session.ws.sent if e['type'] == 'input_audio_buffer.append']) == 1
            if not early:
                await transcript(session)
            await fragment['task']
            assert session.input_open and session._wake_fragment is None
            assert response_count(session) == 0
            sent = [base64.b64decode(e['audio']) for e in session.ws.sent
                    if e['type'] == 'input_audio_buffer.append']
            assert sent == [b'\x01\x00'*4800, *queued]
            assert sum(e['type'] == 'input_audio_buffer.clear' for e in session.ws.sent) == clears
            assert board.budget.status()['sessions_reserved'] == 1
            with board.budget.connect() as db:
                assert db.execute('SELECT responses FROM sessions').fetchone()[0] == 0
            assert any(e['type'] == 'listening' and e['data'].get('resume_capture') for e in session.events)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('text', ['София, сколько будет два плюс три?', 'Который час?', 'София да'])
def test_real_short_question_is_dispatched_once_as_soon_as_transcript_is_final(tmp_path, settings, text):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            fragment = await begin(session)
            await transcript(session, text)
            await fragment['task']
            assert session.current.query == text
            assert response_count(session) == 1
            assert not session.input_open
            assert not any(e['type'] == 'conversation.item.delete' for e in session.ws.sent)
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_second_question_committed_during_pause_retains_its_early_transcript(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            fragment = await begin(session)
            await session.handle({'type': 'conversation.item.input_audio_transcription.completed',
                                  'item_id': 'question', 'transcript': 'Сколько будет два плюс три?'})
            await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'question'})
            await transcript(session)
            await fragment['task']
            assert session.current.input_id == 'question'
            assert session.current.query == 'Сколько будет два плюс три?'
            assert response_count(session) == 1
            assert [e['item_id'] for e in session.ws.sent if e['type'] == 'conversation.item.delete'] == ['wake-item']
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('terminal', ['stop', 'failed', 'timeout', 'buffer_limit', 'overlap'])
def test_pending_name_fragment_fails_closed_without_guess_or_paid_retry(tmp_path, settings, terminal):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            fragment = await begin(session)
            if terminal == 'stop':
                await session.stop()
                await transcript(session)
            elif terminal == 'failed':
                await session.handle({'type': 'conversation.item.input_audio_transcription.failed',
                                      'item_id': 'wake-item', 'error': {'message': 'private content'}})
            elif terminal == 'buffer_limit':
                for _ in range(3):
                    await session.append_pcm(bytes(48000))
            elif terminal == 'overlap':
                await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'second'})
                await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'third'})
            await asyncio.gather(fragment['task'], return_exceptions=True)
            assert session._wake_fragment is None and not session.input_open
            assert not fragment['pcm']
            assert response_count(session) == 0
            assert not any(e['type'] == 'listening' and e['data'].get('resume_capture') for e in session.events)
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('trigger', ['touch', 'manual'])
def test_manual_or_touch_activation_does_not_apply_wake_word_gate(tmp_path, settings, trigger):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            assert await begin(session, trigger=trigger) is None
            assert response_count(session) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_gateway_pause_retains_unsent_burst_and_stateful_resampler():
    from test_sophia_gateway import connection
    async def run():
        gateway = connection()
        for i in range(16):
            gateway.ring.append({'stream_epoch': 'capture', 'frame_id': i,
                'sample_start': i*960, 'sample_count': 960}, bytes([i, 0])*960)
        gateway.ring.begin({'wake_id': 'name', 'stream_epoch': 'capture', 'detector_sample': 0},
                           pre_roll_seconds=0)
        class Resampler:
            output_samples = 0
            def feed(self, pcm):
                self.output_samples += len(pcm)//2
                return pcm
        resampler = gateway.resampler = Resampler()
        sent = []
        async def send(pcm):
            sent.append(pcm)
            if len(sent) == 1:
                await gateway.cloud_event({'type': 'input_closed', 'data': {
                    'reason': 'provider_endpoint', 'resume_pending': True}})
        gateway.to_brain = send
        gateway.forward = True
        gateway.input_changed.set()
        task = asyncio.create_task(gateway.uplink())
        try:
            await asyncio.sleep(.02)
            assert gateway.ring.cursor.position == 8000 and not gateway.forward
            assert gateway.resampler is resampler
            await gateway.cloud_event({'type': 'listening', 'data': {'resume_capture': True}})
            await asyncio.sleep(.02)
            assert gateway.ring.cursor.position == 16*960
            assert b''.join(sent) == b''.join(bytes([i, 0])*960 for i in range(16))
            assert gateway.resampler is resampler
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
