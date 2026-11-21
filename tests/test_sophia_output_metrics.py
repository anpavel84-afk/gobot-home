"""Passive output diagnostics retain bounded numbers, never audio or identifiers."""
import asyncio
import base64
import hashlib
import json

from test_sophia_gateway import connection


def test_completion_capture_position_is_bounded_metadata():
    async def run():
        c = connection()
        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'bounded'}})
        for floor in (-1, 10**15+1, True, 'private'):
            c.output_receipt_metrics(c.output, {'state': 'playback_finished', 'sample_floor': floor})
            assert 'completion_capture_sample_floor' not in c.output['metrics']
        c.output_receipt_metrics(c.output, {'state': 'playback_finished', 'sample_floor': 0})
        assert c.output['metrics']['completion_capture_sample_floor'] == 0
    asyncio.run(run())


def test_progress_metrics_are_bounded_sanitized_and_do_not_invent_underruns():
    async def run():
        c = connection()
        private = 'private-response-or-transcript'
        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': private}})
        c.output['seq'] = 100
        fields = c.output_fields()
        for sequence in range(1, 101):
            await c.receipt({**fields, 'state': 'progress', 'packets_consumed': sequence,
                'decode_pending': sequence % 3, 'output_pending': 0,
                'output_in_flight': False, 'decode_in_flight': True,
                'text': private, 'pcm': private, 'unexpected': private})
        await c.receipt({**fields, 'state': 'progress', 'packets_consumed': 100})
        await c.receipt({**fields, 'state': 'progress', 'packets_consumed': 101})
        await c.receipt({**fields, 'state': 'progress', 'packets_consumed': 5})
        metrics = c.stats['output_metrics'][0]
        assert metrics['response_sha256'] == hashlib.sha256(private.encode()).hexdigest()
        assert len(metrics['progress_points']) == 64
        assert metrics['progress_receipts'] == 100
        assert metrics['duplicate_progress_receipts'] == 1
        assert metrics['invalid_progress_receipts'] == 2
        assert metrics['last_packets_consumed'] == c.output['consumed'] == 100
        assert (metrics['min_decode_pending'], metrics['max_decode_pending']) == (0, 2)
        assert metrics['empty_software_queue_samples'] == 33
        assert metrics['empty_queue_and_idle_writer_samples'] == 33
        assert metrics['underrun_count'] is None and metrics['underrun_measurement'] == 'not_instrumented'
        assert private not in json.dumps(metrics)
    asyncio.run(run())


def test_packet_and_physical_receipts_keep_time_domains_and_only_two_responses():
    async def run():
        c = connection()
        for response in ('first', 'second', 'third'):
            await c.cloud_event({'type': 'audio_start', 'data': {'response_id': response}})
            fields = c.output_fields()
            await c.cloud_event({'type': 'audio_chunk', 'data': {
                'response_id': response, 'pcm': base64.b64encode(bytes(2880)).decode()}})
            await c.receipt({**fields, 'state': 'playback_started'})
            await c.cloud_event({'type': 'audio_stop', 'data': {'response_id': response}})
            await c.receipt({**fields, 'state': 'playback_finished', 'whole_response': True,
                             'stream_epoch': 'capture', 'sample_floor': 0})
        assert len(c.stats['output_metrics']) == 2
        metrics = c.stats['output_metrics'][-1]
        assert metrics['packets_sent'] == 1
        assert metrics['first_packet_sent_monotonic'] <= metrics['driver_submit_receipt_monotonic']
        assert metrics['output_end_sent_monotonic'] <= metrics['whole_finish_receipt_monotonic']
        assert metrics['completion_capture_sample_floor'] == 0
        assert metrics['progress_receipts'] == 0
        assert metrics['min_output_pending'] is None
        assert metrics['underrun_count'] is None
    asyncio.run(run())
