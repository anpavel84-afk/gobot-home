"""Persistent output diagnostics use the existing opt-in, never playback authority."""
import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from gobot.debug_journal import DebugJournal
from gobot.unified_voice_journal import ContentFreeJournal, playback_buffer_summary
from test_sophia_gateway import connection
from test_unified_voice_api import TOKEN, hello, setup


def summary(response='response-summary'):
    return {'type': 'telemetry', 'event': 'playback_buffer_summary',
        'response_id': response, 'audio_role': 'fast_answer', 'reason': 'finished',
        'packets_sent': 20, 'max_packet_send_gap_ms': 71.5,
        'max_progress_receipt_gap_ms': 123., 'min_output_pending': 0,
        'empty_software_queue_samples': 2, 'empty_queue_and_idle_writer_samples': 1,
        'encode_drops_observed_delta': 3}


def test_summary_validation_cannot_invent_underrun_or_accept_non_numeric_counters():
    private = 'private text or PCM'
    safe = playback_buffer_summary({**summary(), 'text': private, 'pcm': private,
        'underrun_count': 0, 'underrun_measurement': 'dma_confirmed', 'generation_allowed': True})
    assert safe['underrun_measurement'] == 'not_instrumented'
    assert safe['device_reported'] and safe['not_acoustic_proof']
    assert 'underrun_count' not in safe and 'generation_allowed' not in safe
    assert private not in json.dumps(safe)
    for change in ({'packets_sent': True}, {'min_output_pending': -1},
                   {'packets_sent': 1.5}, {'packets_sent': 10**1000},
                   {'max_packet_send_gap_ms': float('nan')},
                   {'max_progress_receipt_gap_ms': float('inf')},
                   {'audio_role': []}, {'reason': []}, {'event': 'admission_status'}):
        assert playback_buffer_summary({**summary(), **change}) is None


def test_gateway_finished_and_cancelled_summaries_are_once_and_preserve_receipt_order():
    async def run():
        c = connection()
        c.stats['device_resources'] = {'encode_drops': 7}
        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'finished-output'}})
        state, fields = c.output, c.output_fields()
        await c.cloud_event({'type': 'audio_chunk', 'data': {'response_id': 'finished-output',
            'pcm': base64.b64encode(bytes(2880)).decode()}})
        await c.receipt({**fields, 'state': 'progress', 'packets_consumed': 1,
            'decode_pending': 0, 'output_pending': 0, 'output_in_flight': False})
        await c.receipt({**fields, 'state': 'playback_started'})
        await c.cloud_event({'type': 'audio_stop', 'data': {'response_id': 'finished-output'}})
        c.stats['device_resources']['encode_drops'] = 10
        await c.receipt({**fields, 'state': 'playback_finished', 'whole_response': True,
            'stream_epoch': 'capture', 'sample_floor': 0})
        c.queue_output_summary(state, 'finished')  # Duplicate callback is harmless.
        await asyncio.gather(*list(c.tasks))
        messages = [json.loads(item) for item in c.brain.sent]
        finished = next(item for item in messages if item['type'] == 'telemetry')
        assert messages.index(next(item for item in messages if item['type'] == 'playback_finished')) < messages.index(finished)
        assert finished['reason'] == 'finished' and finished['packets_sent'] == 1
        assert finished['encode_drops_observed_delta'] == 3
        assert finished['empty_queue_and_idle_writer_samples'] == 1
        assert len([item for item in messages if item['type'] == 'telemetry']) == 1
        assert c.output is None and c.stats['playback_finished'] == 1

        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'cancelled-output'}})
        fields = c.output_fields()
        cancel = asyncio.create_task(c.clear_output())
        while not c.output.get('cancel_pending'):
            await asyncio.sleep(0)
        await c.receipt({**fields, 'state': 'stopped', 'output_epoch': fields['output_epoch']+1})
        await cancel
        await asyncio.gather(*list(c.tasks))
        messages = [json.loads(item) for item in c.brain.sent]
        interrupted = [item for item in messages if item.get('event') == 'playback_buffer_summary'][-1]
        assert interrupted['reason'] == 'interrupted'
        assert interrupted['response_id'] == 'cancelled-output'
        assert c.output is None and c.stats['playback_finished'] == 1
        assert c.stats['output_summaries_sent'] == 2
        assert c.stats['output_summaries_dropped'] == 0
    asyncio.run(run())


def test_summary_send_failure_does_not_fail_control_or_change_output():
    async def run():
        c = connection()
        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'unreported-output'}})
        state = c.output
        c.brain = None
        c.queue_output_summary(state, 'interrupted')
        await asyncio.gather(*list(c.tasks))
        assert c.output is state and c.stats['playback_finished'] == 0
        assert c.stats['output_summaries_dropped'] == 1
        assert c.stats['output_summaries_sent'] == 0
    asyncio.run(run())


def test_authenticated_summary_persists_only_through_existing_opt_in_without_voice_actions(tmp_path):
    class Owner:
        enabled = False
        def bound(self, binding):
            return False
        def policy(self):
            return SimpleNamespace(debug_journal_enabled=self.enabled,
                debug_journal_device_bindings=['board'], debug_journal_retention_days=7)

    owner = Owner()
    journal = DebugJournal(tmp_path/'journal', owner,
        protect=lambda raw: raw, unprotect=lambda raw: raw)
    app, board, _ = setup()
    board.journal = ContentFreeJournal(journal)
    try:
        with TestClient(app) as client:
            with client.websocket_connect('/api/v1/voice-ws/stream', headers={'Authorization': 'Bearer '+TOKEN}) as ws:
                ws.send_json(hello())
                assert ws.receive_json()['type'] == 'transport_attached'
                session = board.sessions['session']
                session.owner_test_binding, session.current = 'board', None
                original = (session.state, session.ready, session.selected_mode,
                            session.received_pcm, session.detach_count)
                ws.send_json(summary('opted-out'))
                ws.send_json({'type': 'ping'})
                assert ws.receive_json()['type'] == 'pong'  # Summary has no wire echo.
                assert not journal.path.exists()
                owner.enabled = True
                private = 'must never persist conversation text or raw audio'
                finished = {**summary('recorded-finish'), 'text': private, 'audio': private,
                    'underrun_measurement': 'verified_zero', 'underrun_count': 0,
                    'input_allowed': True}
                ws.send_json(finished)
                ws.send_json(finished)
                ws.send_json({**summary('recorded-cancel'), 'reason': 'interrupted'})
                ws.send_json({**summary('invalid-counter'), 'packets_sent': True})
                ws.send_json({'type': 'ping'})
                assert ws.receive_json()['type'] == 'pong'
                assert (session.state, session.ready, session.selected_mode,
                        session.received_pcm, session.detach_count) == original
                assert asyncio.run(journal.flush())
                scope = journal.scope('board', 'board')
                rows = journal.read(scope, 'session')['events']
                assert len(rows) == 2
                assert all(row['kind'] == 'telemetry' for row in rows)
                assert [row['data']['reason'] for row in rows] == ['finished', 'interrupted']
                assert rows[0]['data']['response_id'] == hashlib.sha256(b'recorded-finish').hexdigest()
                assert rows[0]['data']['max_packet_send_gap_ms'] == 71.5
                assert rows[0]['data']['encode_drops_observed_delta'] == 3
                assert all(row['data']['underrun_measurement'] == 'not_instrumented' for row in rows)
                serialized = json.dumps(rows)
                assert private not in serialized and 'recorded-finish' not in serialized
                assert 'underrun_count' not in serialized and 'input_allowed' not in serialized
    finally:
        asyncio.run(journal.close())
