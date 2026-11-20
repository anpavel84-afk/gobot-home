"""Risks at the actual firmware/Brain boundary, without provider calls."""
import asyncio
import base64
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'services/voice'))
from sophia_connection import (SophiaConnection, PrefetchedSocket, supports_sophia_v2,
                              POST_PLAYBACK_CAPTURE_GUARD_SAMPLES)


class Socket:
    def __init__(self):
        self.sent = []
        self.queue = asyncio.Queue()
    async def send(self, item):
        self.sent.append(item)
    async def recv(self):
        return await self.queue.get()


class Encoder:
    def __init__(self):
        self.closed = False
    def feed(self, data, rate):
        assert rate == 24000
        return [b'encoded'] if data else []
    def finish(self):
        self.closed = True
        return []


def connection():
    c = SophiaConnection({'brain_url': 'http://127.0.0.1:18781', 'device_id': 'board',
                          'unified_voice': {'lan_stream_consent': True}},
                         'x'*48, session_id='session', conversation_id='conversation',
                         encoder_factory=Encoder)
    c.device, c.brain = Socket(), Socket()
    c.ring.reset('capture')
    return c


def test_capability_cannot_silently_enable_old_host_firmware():
    assert not supports_sophia_v2({'host_stream': {'version': 1, 'capture': 'continuous'}})
    assert not supports_sophia_v2({'host_stream': {'version': 2, 'capture': 'continuous',
                                                  'local_wake_enabled': False, 'pcm_stage': 'pre_afe'}})
    assert supports_sophia_v2({'host_stream': {'version': 2, 'capture': 'continuous',
                                              'local_wake_enabled': True, 'pcm_stage': 'pre_afe'}})


def test_transport_failure_retains_continuity_cause_without_household_content():
    from gobot_device_gateway import sophia_transport_failure
    stats = {'input_open': False, 'received_packets': 25, 'downlink_packets': 90,
             'wake_events': 1, 'playback_started': 1, 'playback_finished': 0,
             'device_resources': {'encode_drops': 2, 'private': 'household text'},
             'transcript': 'never record this'}
    result = sophia_transport_failure(ValueError('frame_gap_requires_new_epoch'), stats,
                                     output_active=True, age_seconds=18.2)
    assert result['code'] == 'frame_gap_requires_new_epoch'
    assert result['output_active'] and not result['input_open']
    assert result['encode_drops'] == 2 and result['playback_finished'] == 0
    assert 'private' not in json.dumps(result) and 'household' not in json.dumps(result)
    hidden = sophia_transport_failure(RuntimeError('Bearer secret and private transcript'), stats)
    assert hidden['code'] == 'other' and hidden['kind'] == 'RuntimeError'
    assert 'secret' not in json.dumps(hidden) and 'transcript' not in json.dumps(hidden)
    cleaned = sophia_transport_failure(TimeoutError(),
        {**stats, 'input_open_before_cleanup': True, 'output_active_before_cleanup': True})
    assert cleaned['input_open'] and cleaned['output_active']


def test_gateway_restart_preserves_logical_scope_but_device_boot_gets_new_wake():
    from gobot_device_gateway import Gateway
    from types import SimpleNamespace
    config={'mode':'realtime_b','device_id':'board','conversation_id':'conversation'}
    first,second=Gateway(config,'token'),Gateway(config,'token')
    assert first.unified_session_id==second.unified_session_id
    assert first.unified_conversation_id==second.unified_conversation_id
    assert first.unified_session_id!=Gateway({**config,'device_id':'other'},'token').unified_session_id
    async def run():
        c=connection();c.cloud_ready.set()
        c.ring.cursor=SimpleNamespace(wake_id='sophia-1')
        for epoch in ('first-boot','first-boot','second-boot'):
            await c.activate({'wake_id':'sophia-1','stream_epoch':epoch})
        ids=[json.loads(item)['wake_id'] for item in c.brain.sent]
        assert ids[0]==ids[1] and ids[1]!=ids[2]
    asyncio.run(run())


def test_legacy_prefetch_keeps_first_message_and_original_socket():
    async def run():
        ws = Socket()
        await ws.queue.put('second')
        wrapped = PrefetchedSocket(ws, 'first')
        assert await wrapped.recv() == 'first'
        assert await wrapped.recv() == 'second'
        await wrapped.send('unchanged')
        assert ws.sent == ['unchanged']
    asyncio.run(run())


def test_empty_ready_and_denied_wake_never_send_audio_or_open_input():
    async def run():
        c = connection()
        await c.cloud_event({'type': 'ready', 'data': {'generation_allowed': False}})
        assert c.cloud_ready.is_set() and not c.forward
        assert c.stats['selected_mode'] == 'fast'
        await c.cloud_event({'type': 'mode_selected', 'data': {'mode': 'expert'}})
        assert c.stats['selected_mode'] == c.mode == 'expert'
        assert c.brain.sent == [] and not c.forward and c.ring.cursor is None
        await c.cloud_event({'type': 'mode_selected', 'data': {'mode': 'fast'}})
        assert c.stats['selected_mode'] == c.mode == 'fast'
        await c.cloud_event({'type': 'admission_denied', 'data': {'reason': 'board_budget_inactive'}})
        assert c.brain.sent == [] and not c.forward
        assert c.stats['last_error'] == 'board_budget_inactive'
        assert c.ring.cursor is None
    asyncio.run(run())


def test_device_stack_measurement_survives_numeric_resource_filter():
    async def run():
        c = connection()
        envelope = {'session_id': c.transport, 'epoch': c.epoch}
        await c.device.queue.put(json.dumps({**envelope, 'type': 'gobot_host_stats',
            'audio_input_stack_hwm_bytes': 2520, 'audio_input_task_present': True,
            'input_blocks': 50, 'unrecognized_private_text': 'must not persist'}))
        await c.device.queue.put(json.dumps({**envelope, 'type': 'end_test'}))
        with pytest.raises(ValueError, match='unsupported_sophia_control'):
            await c.receive()
        resources = c.stats['device_resources']
        assert resources['audio_input_stack_hwm_bytes'] == 2520
        assert resources['audio_input_stack_hwm_units'] == 'bytes'
        assert resources['audio_input_task_present'] is True
        assert 'unrecognized_private_text' not in resources
    asyncio.run(run())


async def receive_resource_snapshot(c, fields):
    envelope = {'session_id': c.transport, 'epoch': c.epoch}
    await c.device.queue.put(json.dumps({**envelope, 'type': 'gobot_host_stats', **fields}))
    await c.device.queue.put(json.dumps({**envelope, 'type': 'end_test'}))
    with pytest.raises(ValueError, match='unsupported_sophia_control'):
        await c.receive()
    return c.stats['device_resources']


@pytest.mark.parametrize('wake_mode', [0, 1, 2, 3])
def test_playback_wake_diagnostics_survive_without_changing_audio_authority(wake_mode):
    async def run():
        c = connection()
        c.stats['voice_phase'] = 'speaking'
        output = c.output = {'owner': 'existing-output'}
        c.ring.set_blocked(True, reason='playback')
        fields = {
            'host_wake_mode': wake_mode,
            'wake_barge_frames': 186, 'wake_barge_gaps': 0,
            'wake_barge_resets': 2, 'wake_barge_detections': 1,
            'wake_barge_accepted': 1, 'aec_clean_zero_frames': 4,
            'wake_barge_process_max_us': 25900, 'wake_barge_processing_overrun_frames': 0,
            'barge_duck_started': 1, 'barge_duck_restored': 1, 'barge_duck_active': False,
            'aec_level_frame': 190,
            'aec_mic_avg_abs': 580, 'aec_ref_avg_abs': 1024,
            'aec_clean_avg_abs': 68, 'aec_mic_peak': 32768,
            'aec_ref_peak': 24576, 'aec_clean_peak': 296,
        }
        resources = await receive_resource_snapshot(c, {
            **fields, 'unrecognized_private_text': 'must not persist',
            'aec_clean_samples': [1, 2, 3],
        })
        assert resources == {**fields, 'underrun_measurement': 'not_instrumented'}
        assert c.output is output and c.ring.blocked and not c.forward
        assert c.stats['voice_phase'] == 'speaking' and c.stats['wake_events'] == 0
        assert c.pending_interrupt is None
        assert c.device.sent == c.brain.sent == []
    asyncio.run(run())


@pytest.mark.parametrize('field,maximum', [
    ('host_wake_mode', 3), ('wake_barge_frames', 2**63-1),
    ('aec_clean_zero_frames', 2**63-1), ('aec_level_frame', 2**63-1),
    ('wake_barge_process_max_us', 2**63-1), ('wake_barge_processing_overrun_frames', 2**63-1),
    ('barge_duck_started', 2**63-1), ('barge_duck_restored', 2**63-1),
    ('aec_mic_avg_abs', 32768), ('aec_clean_peak', 32768),
])
def test_playback_wake_diagnostics_reject_noninteger_and_out_of_range_fields(field, maximum):
    async def run():
        c = connection()
        for value in (-1, maximum+1, True, '1', None, [], {}, 1.0, 1.5,
                      float('nan'), float('inf'), float('-inf')):
            resources = await receive_resource_snapshot(c, {field: value})
            assert field not in resources
            json.dumps(resources, allow_nan=False)
        for value in (0, maximum):
            resources = await receive_resource_snapshot(c, {field: value})
            assert resources[field] == value
    asyncio.run(run())


def test_playback_duck_active_requires_an_actual_boolean():
    async def run():
        c = connection()
        for value in (0, 1, 'true', None, float('nan'), float('inf')):
            resources = await receive_resource_snapshot(c, {'barge_duck_active': value})
            assert 'barge_duck_active' not in resources
        for value in (False, True):
            resources = await receive_resource_snapshot(c, {'barge_duck_active': value})
            assert resources['barge_duck_active'] is value
    asyncio.run(run())


def test_nonfinite_and_invalid_legacy_counters_cannot_poison_resource_status():
    async def run():
        c = connection()
        resources = await receive_resource_snapshot(c, {
            'aec_frames': float('nan'), 'aec_reference_frames': float('inf'),
            'aec_process_max_us': float('-inf'), 'barge_wakes': -1,
            'barge_taps': True, 'input_blocks': 2**64, 'encode_drops': '0',
            'audio_input_stack_hwm_bytes': 1216, 'aec_ready': True,
        })
        assert resources == {
            'audio_input_stack_hwm_bytes': 1216, 'audio_input_stack_hwm_units': 'bytes',
            'aec_ready': True, 'underrun_measurement': 'not_instrumented',
        }
        json.dumps(resources, allow_nan=False)
    asyncio.run(run())


def test_legacy_ui_visible_wire_ack_is_only_lvgl_refresh_evidence():
    async def run():
        c = connection()
        envelope = {'session_id': c.transport, 'epoch': c.epoch}
        await c.device.queue.put(json.dumps({**envelope, 'type': 'gobot_host_ack',
            'event': 'ui_visible', 'callback_monotonic_us': 1000,
            'device_monotonic_us': 63200}))
        await c.device.queue.put(json.dumps({**envelope, 'type': 'end_test'}))
        with pytest.raises(ValueError, match='unsupported_sophia_control'):
            await c.receive()
        assert c.stats['last_wake_lvgl_refresh_ready_ms'] == 62.2
        assert c.stats['wake_ui_measurement'] == 'lvgl_refr_ready_not_panel_dma'
        assert 'last_wake_ui_visible_ms' not in c.stats
    asyncio.run(run())


def test_whole_physical_playback_receipt_required_and_stale_audio_dropped():
    async def run():
        c = connection()
        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'r1'}})
        assert c.ring.blocked and not c.forward
        fields = c.output_fields()
        with pytest.raises(ValueError, match='before_whole_response'):
            await c.receipt({**fields, 'state': 'playback_finished', 'whole_response': True,
                             'stream_epoch': 'capture', 'sample_floor': 0})
        await c.receipt({**fields, 'state': 'playback_started'})
        await c.cloud_event({'type': 'audio_chunk', 'data': {
            'response_id': 'r1', 'pcm': base64.b64encode(bytes(2880)).decode()}})
        await c.cloud_event({'type': 'audio_stop', 'data': {'response_id': 'r1'}})
        await c.receipt({**fields, 'state': 'playback_finished', 'whole_response': True,
                         'stream_epoch': 'capture', 'sample_floor': 0})
        assert c.output is None and c.ring.blocked and not c.forward
        brain = [json.loads(x) for x in c.brain.sent]
        assert [x['type'] for x in brain] == ['playback_started', 'playback_finished']
        # Only Brain's post-playback guard may now open followup.
        await c.cloud_event({'type': 'followup', 'data': {'mode': 'fast'}})
        assert c.forward and not c.ring.blocked
        assert c.ring.cursor.position == POST_PLAYBACK_CAPTURE_GUARD_SAMPLES
        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'r2'}})
        fields = c.output_fields()
        cancel = asyncio.create_task(c.cloud_event({'type': 'audio_cancel', 'data': {'response_id': 'r2'}}))
        await asyncio.sleep(.01)
        await c.receipt({**fields, 'state': 'playback_finished', 'whole_response': True,
                         'stream_epoch': 'capture', 'sample_floor': 0})
        assert c.output is not None and not cancel.done()
        await c.receipt({**fields, 'state': 'stopped', 'output_epoch': fields['output_epoch']+1})
        await cancel
        count = len(c.device.sent)
        await c.cloud_event({'type': 'audio_chunk', 'data': {
            'response_id': 'r2', 'pcm': base64.b64encode(bytes(2880)).decode()}})
        assert len(c.device.sent) == count
    asyncio.run(run())


def test_service_cue_finish_never_opens_microphone_by_itself():
    async def run():
        c = connection()
        await c.cloud_event({'type': 'audio_start', 'data': {
            'response_id': 'cue', 'audio_role': 'service_cue'}})
        fields = c.output_fields()
        await c.cloud_event({'type': 'audio_stop', 'data': {'response_id': 'cue'}})
        await c.receipt({**fields, 'state': 'segment_finished', 'whole_response': False,
                         'stream_epoch': 'capture', 'sample_floor': 0})
        assert not c.forward and c.ring.blocked and c.ring.cursor is None
    asyncio.run(run())
