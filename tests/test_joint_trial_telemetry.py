"""The human trial must distinguish physical receipts from later notifications."""
import asyncio
import base64
import json

import pytest

from gobot.unified_voice_journal import metadata
from test_realtime_ws import setup, offer, cleanup
from test_sophia_wake_fragment import begin, transcript


def test_receipt_precedes_heard_context_and_stale_or_segment_receipts_do_not_prove_it(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('known-human-wake')
            wake = next(e['data'] for e in session.events if e['type'] == 'wake_accepted')
            assert 0 < wake['wake_received_monotonic'] <= wake['plan_monotonic']
            await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'known-question'})
            await asyncio.sleep(.02)
            response, turn = session.live_response, session.current
            await session.handle({'type': 'response.output_audio.delta', 'response_id': response,
                'delta': base64.b64encode(bytes(2880)).decode()})
            await session.handle({'type': 'response.done', 'response': {'id': response, 'status': 'completed'}})
            observed = []
            emit = session.emit
            def inspect(kind, **data):
                if data.get('event') in {'playback_receipt_received', 'heard_context_committed'}:
                    observed.append((data['event'], turn.stored, data.copy()))
                return emit(kind, **data)
            session.emit = inspect
            with pytest.raises(ValueError, match='not_confirmed'):
                await session.playback_finished(response)
            await session.playback_started(response)
            await session.playback_finished(response, segment_id='segment-only')
            await session.playback_finished('stale-response')
            assert not observed and not turn.stored
            await session.playback_finished(response, sample_floor=42000)
            assert [(event, stored) for event, stored, _ in observed] == [
                ('playback_receipt_received', False), ('heard_context_committed', True)]
            received, committed = (row[2] for row in observed)
            assert received['heard'] is False and committed['heard'] is True
            assert received['plan_monotonic'] <= committed['plan_monotonic']
            await session.playback_finished(response, sample_floor=42000)
            assert len(observed) == 2
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_short_real_question_has_measurable_gate_wait_without_recording_speech(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            fragment = await begin(session)
            private = 'София, сколько будет два плюс три?'
            await transcript(session, private)
            await fragment['task']
            events = [e['data'] for e in session.events if e['type'] == 'telemetry'
                      and e['data'].get('event') in {'wake_fragment_pending', 'wake_fragment_question_ready'}]
            assert [e['event'] for e in events] == ['wake_fragment_pending', 'wake_fragment_question_ready']
            assert events[0]['plan_monotonic'] <= events[1]['plan_monotonic']
            safe = [metadata({**e, 'text': private, 'pcm': private}) for e in events]
            assert private not in json.dumps(safe, ensure_ascii=False)
            assert [e['event'] for e in safe] == ['wake_fragment_pending', 'wake_fragment_question_ready']
            assert sum(e['type'] == 'response.create' for e in session.ws.sent) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_new_receipt_evidence_keeps_only_hashes_numbers_and_fixed_events():
    private = 'private-question-and-answer'
    for event in ('playback_receipt_received', 'heard_context_committed'):
        safe = metadata({'event': event, 'response_id': private, 'plan_monotonic': 5.2,
                         'wake_received_monotonic': 4.1, 'heard': True,
                         'text': private, 'transcript': private, 'pcm': private})
        assert safe['event'] == event and safe['plan_monotonic'] == 5.2
        assert safe['wake_received_monotonic'] == 4.1 and len(safe['response_id']) == 64
        assert private not in json.dumps(safe)


def test_retry_after_failed_context_finish_never_claims_a_successful_commit(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('known-human-wake')
            await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'known-question'})
            await asyncio.sleep(.02)
            response, turn = session.live_response, session.current
            await session.handle({'type': 'response.output_audio.delta', 'response_id': response,
                'delta': base64.b64encode(bytes(2880)).decode()})
            await session.handle({'type': 'response.done', 'response': {'id': response, 'status': 'completed'}})
            await session.playback_started(response)
            finish = session.maybe_finish
            async def failing_finish(current):
                current.stored = True  # Native finish sets this before its awaited memory write.
                raise RuntimeError('fixture_memory_write_failed')
            session.maybe_finish = failing_finish
            with pytest.raises(RuntimeError, match='fixture_memory_write_failed'):
                await session.playback_finished(response, sample_floor=42000)
            session.maybe_finish = finish
            await session.playback_finished(response, sample_floor=42000)
            assert not any(e['data'].get('event') == 'heard_context_committed' for e in session.events)
            receipts = [e['data'] for e in session.events
                        if e['data'].get('event') == 'playback_receipt_received']
            assert [e['heard'] for e in receipts] == [False, True]
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
