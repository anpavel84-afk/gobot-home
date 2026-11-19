"""Risks at the actual firmware/Brain boundary, without provider calls."""
import asyncio
import base64
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'services/voice'))
from sophia_connection import SophiaConnection, PrefetchedSocket, supports_sophia_v2


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
        await c.cloud_event({'type': 'admission_denied', 'data': {'reason': 'board_budget_inactive'}})
        assert c.brain.sent == [] and not c.forward
        assert c.stats['last_error'] == 'board_budget_inactive'
        assert c.ring.cursor is None
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
        assert c.forward and not c.ring.blocked and c.ring.cursor.position == 0
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
