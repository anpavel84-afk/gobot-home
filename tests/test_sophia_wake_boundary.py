"""Bound ambiguous wake fragments without discarding explicitly named questions."""
import asyncio
import base64
import hashlib

import pytest

from test_realtime_ws import setup, offer, cleanup
from gobot.unified_voice_journal import capture_boundary, metadata


CAPTURE = {'stream_epoch': 'synthetic-capture', 'selected_start': 40000,
           'detector_sample': 56000, 'sample_rate': 16000, 'interrupt': False}
QUESTION = 'София, сколько углов у квадрата?'
UNRELATED_ASR = 'Случайная гипотеза.'


def responses(session):
    return [event for event in session.ws.sent if event['type'] == 'response.create']


async def append_samples(session, count):
    blocks = []
    while count:
        length = min(count, 24000)
        pcm = b'\x03\x00'*length
        await session.append_pcm(pcm)
        blocks.append(pcm)
        count -= length
    return blocks


async def final(session, item_id, text, *, failed=False):
    await session.handle({'type': 'conversation.item.input_audio_transcription.'+
        ('failed' if failed else 'completed'), 'item_id': item_id, 'transcript': text})


async def commit(session, item_id, endpoint=None):
    if endpoint is not None:
        await session.handle({'type': 'input_audio_buffer.speech_stopped',
                              'item_id': item_id, 'audio_end_ms': endpoint})
    await session.handle({'type': 'input_audio_buffer.committed', 'item_id': item_id})
    return session._wake_fragment


@pytest.mark.parametrize('early_asr', [False, True])
def test_wake_candidate_uses_existing_final_gate_then_keeps_following_question(tmp_path, settings, early_asr):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('synthetic-wake', trigger='wake_word', capture=CAPTURE)
            session._fast_capture_started -= 20  # Host scheduling delay is not speech evidence.
            pcm = await append_samples(session, 48840)  # Deliberately exceeds the former two-second cap.
            if early_asr:
                await final(session, 'wake-item', UNRELATED_ASR)
            clears = sum(e['type'] == 'input_audio_buffer.clear' for e in session.ws.sent)
            gate = await commit(session, 'wake-item', 1472)
            assert gate['activation_candidate'] and gate['wake_resume']
            if not early_asr:
                await asyncio.sleep(0)
                assert not gate['task'].done() and not responses(session)
                await final(session, 'wake-item', UNRELATED_ASR)
            await asyncio.wait_for(gate['task'], 1)
            activation = session.current
            assert activation.cancelled and activation.direct_activation_only
            assert session.input_open and session.state == 'listening'
            assert not responses(session) and not session.response_requested
            assert sum(e['type'] == 'input_audio_buffer.clear' for e in session.ws.sent) == clears
            assert [e['item_id'] for e in session.ws.sent if e['type'] == 'conversation.item.delete'] == ['wake-item']
            assert any(e['type'] == 'telemetry' and e['data']['event'] == 'wake_activation_candidate'
                       for e in session.events)
            assert any(e['type'] == 'listening' and e['data'].get('resume_capture') for e in session.events)
            # The following actual question retains the same provider buffer
            # and microphone operation; it is not sent as a text replacement.
            await session.handle({'type': 'input_audio_buffer.speech_started', 'item_id': 'question'})
            pcm.extend(await append_samples(session, 12000))
            question_gate = await commit(session, 'question', 2400)
            assert not question_gate['activation_candidate']
            await final(session, 'wake-item', UNRELATED_ASR)  # A late final must not claim this new turn.
            assert session.current.input_id == 'question' and session.current.query == ''
            await final(session, 'question', QUESTION)
            await question_gate['task']
            assert session.current.query == QUESTION and len(responses(session)) == 1
            assert activation.query == ''
            sent = [base64.b64decode(e['audio']) for e in session.ws.sent
                    if e['type'] == 'input_audio_buffer.append']
            assert sent == pcm
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('endpoint', [1504, 1952])
def test_joined_question_past_wake_boundary_adds_no_hold_after_its_own_final(tmp_path, settings, endpoint):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('joined', trigger='wake_word', capture=CAPTURE)
            await append_samples(session, 48840)
            gate = await commit(session, 'joined-question', endpoint)
            assert not gate['activation_candidate'] and not responses(session)
            await final(session, 'joined-question', QUESTION)
            await asyncio.wait_for(gate['task'], 1)
            assert len(responses(session)) == 1 and session.current.query == QUESTION
            assert not any(e['type'] == 'conversation.item.delete' for e in session.ws.sent)
            assert not any(e['type'] == 'listening' and e['data'].get('resume_capture') for e in session.events)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('text', [
    'София, сколько углов у квадрата?',
    'Сколько углов у квадрата, София?',
    'Sophia, how many sides has a square?',
])
def test_named_question_survives_delayed_detector_or_wake_at_end(tmp_path, settings, text):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            # The detector callback is after the complete speech endpoint.
            # That position is not proof of the acoustic wake-word boundary.
            capture = {**CAPTURE, 'detector_sample': 57600}
            await session.wake('delayed-detector', trigger='wake_word', capture=capture)
            await append_samples(session, 48840)
            gate = await commit(session, 'named-question', 1472)
            assert gate['activation_candidate']
            await final(session, 'named-question', text)
            await asyncio.wait_for(gate['task'], 1)
            assert len(responses(session)) == 1 and session.current.query == text
            assert not any(e['type'] == 'conversation.item.delete' for e in session.ws.sent)
            assert not any(e['type'] == 'listening' and e['data'].get('resume_capture') for e in session.events)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('text,failed', [('', False), ('', True), (QUESTION, True)])
def test_activation_candidate_empty_or_failed_asr_waits_for_question_without_generation(tmp_path, settings, text, failed):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('ambiguous', trigger='wake_word', capture=CAPTURE)
            await append_samples(session, 48840)
            gate = await commit(session, 'ambiguous-activation', 1472)
            await final(session, 'ambiguous-activation', text, failed=failed)
            await asyncio.wait_for(gate['task'], 1)
            assert session.input_open and not responses(session)
            assert session.current.cancelled and session.current.query == ''
            assert session.followup_deadline is not None
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_activation_candidate_asr_timeout_is_bounded_and_late_result_cannot_generate(tmp_path, settings, monkeypatch):
    from gobot import realtime_ws
    monkeypatch.setattr(realtime_ws, '_FAST_TRANSCRIPT_TIMEOUT_SECONDS', .01)
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('no-asr', trigger='wake_word', capture=CAPTURE)
            await append_samples(session, 48840)
            gate = await commit(session, 'asr-never-arrived', 1472)
            await asyncio.wait_for(gate['task'], 1)
            assert session.input_open and not responses(session)
            assert session.followup_deadline is not None and session.current.cancelled
            await final(session, 'asr-never-arrived', QUESTION)
            assert session.input_open and not responses(session) and session.current.query == ''
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('text', ['София', '«Sofia!»', 'СОФЬЯ... София!', 'Sophia?'])
def test_unambiguous_name_remains_waiting_even_after_slow_input_delivery(tmp_path, settings, text):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('slow-name', trigger='wake_word')
            session._fast_capture_started -= 20
            await append_samples(session, 48840)
            gate = await commit(session, 'name-without-anchor')
            assert gate['wake_resume'] and not gate['activation_candidate']
            await final(session, 'name-without-anchor', text)
            await gate['task']
            assert session.input_open and not responses(session)
            assert session.followup_deadline is not None and not session._input_started
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_endpoint_before_stop_cannot_classify_new_window_after_clear(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('old', trigger='wake_word', capture=CAPTURE)
            await append_samples(session, 48840)
            await session.handle({'type': 'input_audio_buffer.speech_stopped',
                                  'item_id': 'not-yet-committed', 'audio_end_ms': 1472})
            await session.stop(request_id='stop-old')
            await session.wake('fresh', trigger='wake_word', capture=CAPTURE)
            assert not session._fast_speech_ends
            await append_samples(session, 48840)
            gate = await commit(session, 'not-yet-committed')
            assert not gate['activation_candidate']
            await final(session, 'not-yet-committed', QUESTION)
            await gate['task']
            assert len(responses(session)) == 1 and session.current.query == QUESTION
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('endpoint', [None, -1, 0, True, 10**9])
def test_missing_or_invalid_endpoint_never_implies_activation_candidate(tmp_path, settings, endpoint):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('uncertain', trigger='wake_word', capture=CAPTURE)
            await append_samples(session, 48840)
            gate = await commit(session, 'unknown-endpoint', endpoint)
            assert not gate['activation_candidate'] and not responses(session)
            await final(session, 'unknown-endpoint', QUESTION)
            await gate['task']
            assert len(responses(session)) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('trigger', ['wake_word', 'touch'])
def test_post_interrupt_audio_after_original_wake_has_no_activation_span(tmp_path, settings, trigger):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            capture = {**CAPTURE, 'selected_start': 58000, 'interrupt': True}
            await session.wake('after-interrupt', trigger=trigger, capture=capture)
            await append_samples(session, 18000)
            gate = await commit(session, 'new-question', 608)
            assert not gate['activation_candidate']
            await final(session, 'new-question', QUESTION)
            await gate['task']
            assert len(responses(session)) == 1
            accepted = next(e for e in session.events if e['type'] == 'wake_accepted')
            assert accepted['data']['trigger'] == trigger
            assert accepted['data']['selected_start'] == 58000 and accepted['data']['interrupt']
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('change', [
    {'sample_rate': 24000}, {'sample_rate': True}, {'selected_start': -1},
    {'detector_sample': True}, {'detector_sample': 80001}, {'detector_sample': 39999},
    {'interrupt': 1}, {'stream_epoch': 'not a capture'}, {'private_text': 'not allowed'},
])
def test_capture_contract_rejected_before_opening_operation(tmp_path, settings, change):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            with pytest.raises(ValueError, match='invalid_wake_capture_anchor'):
                await session.wake('invalid', trigger='wake_word', capture={**CAPTURE, **change})
            assert not session.input_open and 'invalid' not in session.seen_wakes
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('request_id', ['', 'x'*129, True, 42, 'contains space', 'сбой', 'bad\n'])
def test_invalid_stop_nonce_cannot_change_current_input(tmp_path, settings, request_id):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('current')
            epoch, count = session._input_gate_epoch, len(session.ws.sent)
            with pytest.raises(ValueError, match='invalid_stop_request_id'):
                await session.stop(request_id=request_id)
            assert session.input_open and session._input_gate_epoch == epoch
            assert len(session.ws.sent) == count and not session._stop_count
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_stop_nonce_is_echoed_only_after_input_and_old_reply_ownership_end(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('old')
            await session.stop(request_id='opaque_123-abc')
            stop = [e for e in session.events if e['type'] == 'stopped'][-1]
            assert stop['data'] == {'input_open': False, 'request_id': 'opaque_123-abc'}
            assert not session.input_open and not session._stop_count and session.state == 'ready'
            assert not session.output_owner and not session.response_requested
            await session.wake('new')
            assert session.input_open and not responses(session)
            await session.stop()
            assert [e for e in session.events if e['type'] == 'stopped'][-1]['data'] == {'input_open': False}
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_interrupt_quiet_metadata_is_numeric_evidence_and_grants_no_authority():
    event = {'event': 'capture_boundary', 'stage': 'interrupt_quiet',
        'stream_epoch': 'capture-1', 'ring_end': 4800, 'sample_floor': 4800,
        'physical_sample_floor': 4800, 'guard_samples': 0, 'selected_start': 4800,
        'response_id': 'old-response', 'wake_id': 'barge-wake', 'plan_monotonic': 12.5}
    safe = capture_boundary({**event, 'input_allowed': True, 'text': 'forbidden'})
    assert safe['stage'] == 'interrupt_quiet' and safe['not_acoustic_proof']
    assert safe['guard_samples'] == 0 and 'input_allowed' not in safe and 'text' not in safe
    assert metadata(safe)['wake_id'] == hashlib.sha256(b'barge-wake').hexdigest()
    for key in event:
        missing = dict(event)
        del missing[key]
        if key == 'response_id':
            without_owner = capture_boundary(missing)
            assert without_owner['stage'] == 'interrupt_quiet' and 'response_id' not in without_owner
        else:
            assert capture_boundary(missing) is None
    assert capture_boundary({**event, 'physical_sample_floor': True}) is None
    assert capture_boundary({**event, 'response_id': None}) is None
