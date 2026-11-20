"""Observed wake-only failures replayed without audio, a device or model calls."""
import asyncio
import base64
import time

import pytest

from gobot.unified_voice_journal import metadata
from test_realtime_ws import setup, offer, cleanup
from test_sophia_wake_boundary import CAPTURE, QUESTION, append_samples, commit, final, responses


def decision(session):
    return [event['data'] for event in session.events if event['type'] == 'telemetry'
            and event['data'].get('event') == 'wake_input_classified'][-1]


@pytest.mark.parametrize('endpoint,samples,boundary', [
    (1536, 41112, 'after_detector'),
    (5984, 38808, 'unmapped'),
])
def test_observed_single_word_hypothesis_waits_for_actual_question(
        tmp_path, settings, endpoint, samples, boundary):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('synthetic-only-name', trigger='wake_word', capture=CAPTURE)
            pcm = await append_samples(session, samples)
            gate = await commit(session, 'ambiguous-name', endpoint)
            held = b'\x04\x00'*960
            assert await session.append_pcm(held)
            # Synthetic Latin token with no similarity to a supported name;
            # no household ASR text is copied into a regression fixture.
            await final(session, 'ambiguous-name', 'sample')
            await gate['task']
            assert not responses(session) and session.input_open and session.state == 'listening'
            assert session.current.cancelled and session.current.direct_activation_only
            record = decision(session)
            assert record['reason'] == 'wake_single_token_ambiguous'
            assert record['boundary'] == boundary and record['activation_only']
            assert record['provider_audio_end_ms'] == endpoint
            assert record['captured_samples'] == samples and record['token_count'] == 1
            assert record['wake_offset_ms'] == 1000 and not record['named_question']
            assert 'sample' not in metadata(record).values()
            sent = [base64.b64decode(event['audio']) for event in session.ws.sent
                    if event['type'] == 'input_audio_buffer.append']
            assert sent == [*pcm, held]
            with board.budget.connect() as db:
                assert db.execute('SELECT sum(responses) FROM sessions').fetchone()[0] == 0
            assert board.budget.status()['sessions_reserved'] == 1
            # A short legitimate next question does not need another wake or
            # another operation, and may itself be just one word.
            await session.append_pcm(b'\x06\x00'*4800)
            next_gate = await commit(session, 'actual-question', endpoint+1600)
            await final(session, 'actual-question', 'Погода')
            await next_gate['task']
            assert len(responses(session)) == 1 and session.current.query == 'Погода'
            assert board.budget.status()['sessions_reserved'] == 1
            await final(session, 'ambiguous-name', QUESTION)
            assert len(responses(session)) == 1 and session.current.query == 'Погода'
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('endpoint,samples', [(1536, 41112), (5984, 38808)])
def test_named_joined_question_never_waits_for_another_speech_segment(
        tmp_path, settings, endpoint, samples):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('joined', trigger='wake_word', capture=CAPTURE)
            await append_samples(session, samples)
            gate = await commit(session, 'joined-question', endpoint)
            await final(session, 'joined-question', QUESTION)
            await asyncio.wait_for(gate['task'], 1)
            assert len(responses(session)) == 1 and session.current.query == QUESTION
            assert not session.input_open
            assert decision(session)['reason'] == 'wake_named_question'
            assert not any(event['type'] == 'listening' and event['data'].get('resume_capture')
                           for event in session.events)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('samples,expected', [(38808, False), (120000, True)])
def test_unmapped_clock_requires_substantial_question_evidence_when_name_was_omitted(
        tmp_path, settings, samples, expected):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('unmapped', trigger='wake_word', capture=CAPTURE)
            await append_samples(session, samples)
            gate = await commit(session, 'omitted-name', 15984)
            text = 'Расскажи, почему происходит смена времён года.'
            await final(session, 'omitted-name', text)
            await asyncio.wait_for(gate['task'], 1)
            assert bool(responses(session)) is expected
            assert session.input_open is not expected
            record = decision(session)
            assert record['boundary'] == 'unmapped'
            assert record['reason'] == ('wake_substantial_question' if expected else 'wake_endpoint_unmapped')
            if expected:
                assert session.current.query == text
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('text', ['Который час?', 'Какая погода?'])
@pytest.mark.parametrize('samples,expected', [(38808, False), (58776, False), (58800, True), (120000, True)])
def test_anchored_short_question_with_unmapped_clock_keeps_post_detector_audio_guard(
        tmp_path, settings, text, samples, expected):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('anchored-short-question', trigger='wake_word', capture=CAPTURE)
            await append_samples(session, samples)
            gate = await commit(session, 'two-word-question', 15984)
            await final(session, 'two-word-question', text)
            await asyncio.wait_for(gate['task'], 1)
            record = decision(session)
            assert record['boundary'] == 'unmapped' and record['token_count'] == 2
            assert record['wake_offset_ms'] == 1000 and not record['named_question']
            assert bool(responses(session)) is expected
            assert session.input_open is not expected
            assert record['reason'] == ('wake_substantial_question' if expected else 'wake_endpoint_unmapped')
            if expected:
                assert len(responses(session)) == 1 and session.current.query == text
                assert not any(event['type'] == 'listening' and event['data'].get('resume_capture')
                               for event in session.events)
            else:
                assert session.current.cancelled and session.current.direct_activation_only
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_raw_provider_offset_can_fall_without_guessing_a_new_clock_origin(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            epoch = session.transport_epoch
            for index, (endpoint, samples) in enumerate(((1536, 41112), (5984, 38808))):
                await session.wake('wake-'+str(index), trigger='wake_word', capture=CAPTURE)
                await append_samples(session, samples)
                gate = await commit(session, 'fragment-'+str(index), endpoint)
                await final(session, 'fragment-'+str(index), 'sample')
                await gate['task']
                assert session.input_open and not responses(session)
                await session.stop()
            await session.wake('deliberate-touch', trigger='touch', capture=CAPTURE)
            await append_samples(session, 130296)
            gate = await commit(session, 'touch-question', 5216)
            await final(session, 'touch-question', 'Погода')
            await gate['task']
            assert len(responses(session)) == 1 and session.current.query == 'Погода'
            assert session.transport_epoch == epoch
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('trigger', ['wake_word', 'touch'])
def test_post_interrupt_capture_keeps_one_word_question(tmp_path, settings, trigger):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            capture = {**CAPTURE, 'selected_start': CAPTURE['detector_sample'], 'interrupt': True}
            await session.wake('after-interrupt', trigger=trigger, capture=capture)
            await append_samples(session, 18000)
            gate = await commit(session, 'one-word-question', 5984)
            await final(session, 'one-word-question', 'Погода')
            await gate['task']
            assert len(responses(session)) == 1 and session.current.query == 'Погода'
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['manual', 'touch', 'followup'])
def test_name_in_open_window_keeps_same_capture_until_question_or_silence(tmp_path, settings, mode):
    from test_sophia_gateway import connection
    from sophia_audio import ContinuousPcm24
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('open-window', trigger='manual' if mode == 'followup' else mode)
            if mode == 'followup':
                session.input_open = False
                await session.start_fast_input(followup=True)
            gateway = connection()
            for index in range(10):
                gateway.ring.append({'stream_epoch': 'capture', 'frame_id': index,
                    'sample_start': index*960, 'sample_count': 960}, bytes(1920))
            gateway.ring.begin({'wake_id': 'window', 'stream_epoch': 'capture', 'detector_sample': 0},
                               pre_roll_seconds=0)
            gateway.resampler = ContinuousPcm24()
            cursor, resampler = gateway.ring.cursor, gateway.resampler
            await append_samples(session, 12000)
            event_start = len(session.events)
            gate = await commit(session, 'name-in-window', 608)
            await final(session, 'name-in-window', 'София')
            await gate['task']
            for event in session.events[event_start:]:
                if event['type'] in {'input_closed', 'listening'}:
                    await gateway.cloud_event(event)
            assert gateway.ring.cursor is cursor and gateway.resampler is resampler
            assert gateway.forward and session.input_open and not responses(session)
            assert 0 < session.followup_deadline-time.monotonic() <= 8
            assert decision(session)['reason'] == 'wake_exact_name'
            assert board.budget.status()['sessions_reserved'] == 1
            await final(session, 'name-in-window', 'Старый результат не является новым вопросом.')
            assert not responses(session)
            # The preserved window still closes on real silence; name-only
            # continuation does not leave a permanently open cloud microphone.
            session.followup_deadline = time.monotonic()-1
            async with asyncio.timeout(2):
                while session.input_open:
                    await asyncio.sleep(.01)
            assert not responses(session) and session.state == 'ready'
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('endpoint', [1536, 5984])
def test_deliberate_stop_is_local_even_in_ambiguous_wake_fragment(tmp_path, settings, endpoint):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('wake-stop', trigger='wake_word', capture=CAPTURE)
            await append_samples(session, 41112)
            gate = await commit(session, 'stop-item', endpoint)
            await final(session, 'stop-item', 'Стоп')
            await gate['task']
            assert not session.input_open and session.current.local_control
            assert not responses(session) and session.state == 'ready'
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_classification_journal_retains_only_safe_numeric_and_enum_evidence():
    safe = metadata({'event': 'wake_input_classified', 'reason': 'wake_single_token_ambiguous',
        'boundary': 'unmapped', 'provider_audio_end_ms': 5984, 'captured_samples': 38808,
        'wake_offset_ms': 1000, 'token_count': 1, 'named_question': False,
        'activation_only': True, 'text': 'private phrase', 'words': ['private'],
        'transcript': 'private phrase', 'pcm': 'private bytes'})
    assert safe == {'event': 'wake_input_classified', 'reason': 'wake_single_token_ambiguous',
        'boundary': 'unmapped', 'provider_audio_end_ms': 5984, 'captured_samples': 38808,
        'wake_offset_ms': 1000, 'token_count': 1, 'named_question': False,
        'activation_only': True}


def test_provider_start_and_end_are_correlated_numeric_evidence_without_content(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('diagnostic', trigger='wake_word', capture=CAPTURE)
            await append_samples(session, 38808)
            await session.handle({'type': 'input_audio_buffer.speech_started',
                'item_id': 'current-input', 'audio_start_ms': 5010, 'private': 'not retained'})
            await session.handle({'type': 'input_audio_buffer.speech_stopped',
                'item_id': 'current-input', 'audio_end_ms': 5984, 'private': 'not retained'})
            data = [metadata(event['data']) for event in session.events if event['type'] == 'telemetry'
                    and event['data'].get('event') in {'start_of_speech', 'end_of_speech'}]
            assert len(data) == 2 and data[0]['item_id'] == data[1]['item_id']
            assert len(data[0]['item_id']) == 64
            assert data[0]['provider_audio_start_ms'] == 5010 and data[1]['provider_audio_end_ms'] == 5984
            assert not any('private' in row for row in data)
            assert not responses(session)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
