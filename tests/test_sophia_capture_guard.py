"""Delayed capture cannot bypass the physical post-playback input floor."""
import asyncio
import hashlib
import json
import struct

import pytest

from test_sophia_gateway import connection
from sophia_audio import AudioContinuityError, ContinuousPcm24
from sophia_connection import POST_PLAYBACK_CAPTURE_GUARD_SAMPLES


def frame(index, *, epoch='capture'):
    return {'stream_epoch': epoch, 'frame_id': index,
            'sample_start': index*960, 'sample_count': 960}


def pcm(index):
    return struct.pack('<960h', *range(index*960, (index+1)*960))


async def completed(c, *, physical_floor=4800, received_frames=4):
    c.ring.append(frame(0), pcm(0))
    await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'capture-guard-response'}})
    for index in range(1, received_frames):
        c.ring.append(frame(index), pcm(index))
    fields = c.output_fields()
    await c.receipt({**fields, 'state': 'playback_started'})
    await c.cloud_event({'type': 'audio_stop', 'data': {'response_id': 'capture-guard-response'}})
    await c.receipt({**fields, 'state': 'playback_finished', 'whole_response': True,
        'stream_epoch': 'capture', 'sample_floor': physical_floor})
    return fields


def test_delayed_capture_after_wall_guard_excludes_exact_post_playback_samples():
    async def run():
        c = connection()
        await completed(c)
        expected = 4800+POST_PLAYBACK_CAPTURE_GUARD_SAMPLES
        assert c.ring.end == 3840 and c.ring.floor == expected and c.ring.blocked
        # Brain's wall guard has finished, but the queued microphone packets
        # have not arrived. No assumption about LAN delay may shorten the
        # minimum capture-coordinate interval that must still be discarded.
        await c.cloud_event({'type': 'followup', 'data': {'mode': 'fast'}})
        assert c.ring.cursor.selected_start == expected
        parts = []
        for index in range(4, 12):
            c.ring.append(frame(index), pcm(index))
            parts.extend(c.ring.read_available())
        original = b''.join(pcm(index) for index in range(12))
        assert parts[0][0] == expected
        assert b''.join(data for _, data in parts) == original[expected*2:]
        assert not c.ring.read_available()  # No duplicate replay.
        await asyncio.gather(*list(c.tasks))
    asyncio.run(run())


def test_already_newer_capture_is_not_replayed_by_completion_guard():
    async def run():
        c = connection()
        await completed(c, received_frames=12)
        assert c.ring.floor == 11520  # Later than physical floor + 3200.
        await c.cloud_event({'type': 'followup', 'data': {'mode': 'fast'}})
        assert c.ring.cursor.selected_start == 11520
        c.ring.append(frame(12), pcm(12))
        assert c.ring.read_available() == [(11520, pcm(12))]
        await asyncio.gather(*list(c.tasks))
    asyncio.run(run())


def test_confirmed_floor_survives_pause_stop_mute_and_late_cancel_receipts():
    async def run():
        c = connection()
        fields = await completed(c)
        expected = c.ring.floor
        for event in ({'type': 'input_closed', 'data': {'reason': 'provider_endpoint', 'resume_pending': True}},
                      {'type': 'followup_closed', 'data': {'reason': 'silence'}},
                      {'type': 'audio_cancel', 'data': {'response_id': 'capture-guard-response'}},
                      {'type': 'muted', 'data': {'muted': True}},
                      {'type': 'muted', 'data': {'muted': False}}):
            await c.cloud_event(event)
            assert c.ring.floor == expected and not c.forward
        # This old output no longer owns playback and cannot lower its floor.
        await c.receipt({**fields, 'state': 'stopped', 'output_epoch': fields['output_epoch']+1})
        assert c.ring.floor == expected and c.stats['playback_finished'] == 1
        c.ring.begin({'wake_id': 'new-explicit-wake', 'stream_epoch': 'capture',
                      'detector_sample': expected}, pre_roll_seconds=1.)
        parts = []
        for index in range(4, 10):
            c.ring.append(frame(index), pcm(index))
            parts.extend(c.ring.read_available())
        assert parts[0][0] == expected
        await asyncio.gather(*list(c.tasks))
    asyncio.run(run())


def test_fresh_capture_epoch_drops_old_frames_and_preserves_initial_wake_preroll():
    async def run():
        c = connection()
        await completed(c)
        c.ring.reset('fresh-capture')
        assert c.ring.floor == c.ring.end == 0 and not c.ring.blocks
        with pytest.raises(AudioContinuityError, match='epoch'):
            c.ring.append(frame(4), pcm(4))
        # Initial wake uses the same one-second pre-roll. A fresh connection
        # starts with a fresh ring; old stream coordinates are never reused.
        fresh = connection()
        for index in range(30):
            fresh.ring.append(frame(index), pcm(index))
        fresh.ring.begin({'wake_id': 'owner-best-v4-wake', 'stream_epoch': 'capture',
                         'detector_sample': 25000}, pre_roll_seconds=1.)
        parts = fresh.ring.read_available()
        assert parts[0][0] == 9000
        assert b''.join(data for _, data in parts) == b''.join(pcm(index) for index in range(30))[18000:]
        await asyncio.gather(*list(c.tasks))
    asyncio.run(run())


def test_boundary_metadata_describes_successfully_sent_source_without_pcm_or_raw_ids():
    async def run():
        c = connection()
        await completed(c)
        await c.cloud_event({'type': 'followup', 'data': {'mode': 'fast'}})
        for index in range(4, 12):
            c.ring.append(frame(index), pcm(index))
        sent = asyncio.Event()
        original_send = c.brain.send
        async def observe_send(item):
            await original_send(item)
            if isinstance(item, str):
                event = json.loads(item)
                if event.get('event') == 'capture_boundary' and event.get('stage') == 'first_uplink':
                    sent.set()
        c.brain.send = observe_send
        uplink = asyncio.create_task(c.uplink())
        try:
            await asyncio.wait_for(sent.wait(), 2)
        finally:
            uplink.cancel()
            await asyncio.gather(uplink, return_exceptions=True)
        await asyncio.gather(*list(c.tasks))
        messages = [json.loads(item) for item in c.brain.sent if isinstance(item, str)]
        boundaries = [item for item in messages if item.get('event') == 'capture_boundary']
        assert [item['stage'] for item in boundaries] == ['playback_finished', 'followup_opened', 'first_uplink']
        finish, opened, first = boundaries
        assert finish['physical_sample_floor'] == 4800 and finish['ring_end'] == 3840
        assert finish['sample_floor'] == opened['selected_start'] == first['source_sample_start'] == 8000
        assert first['source_sample_end'] == 11520
        assert finish['guard_samples'] == opened['guard_samples'] == POST_PLAYBACK_CAPTURE_GUARD_SAMPLES
        assert messages.index(next(item for item in messages if item['type'] == 'playback_finished')) < messages.index(finish)
        wire = c.brain.sent
        assert next(i for i, item in enumerate(wire) if isinstance(item, bytes)) < next(
            i for i, item in enumerate(wire) if isinstance(item, str) and json.loads(item).get('stage') == 'first_uplink')
        saved = c.stats['capture_boundaries']
        assert len(saved) == 3 and c.stats['capture_boundaries_sent'] == 3
        assert saved['playback_finished']['response_id_sha256'] == hashlib.sha256(b'capture-guard-response').hexdigest()
        assert 'capture-guard-response' not in json.dumps(saved)
        assert all('pcm' not in item and 'audio' not in item and 'text' not in item for item in boundaries)
    asyncio.run(run())


def test_boundary_diagnostic_send_failure_does_not_change_capture_or_output():
    async def run():
        c = connection()
        c.brain = None
        before = (c.ring.floor, c.ring.cursor, c.ring.blocked, c.forward, c.output)
        c.queue_capture_boundary('first_uplink', wake_id='fixture', selected_start=0,
            source_sample_start=0, source_sample_end=960)
        await asyncio.gather(*list(c.tasks))
        assert (c.ring.floor, c.ring.cursor, c.ring.blocked, c.forward, c.output) == before
        assert c.stats['capture_boundaries_dropped'] == 1 and c.stats['capture_boundaries_sent'] == 0
    asyncio.run(run())


def test_inflight_old_pcm_cannot_change_replacement_expert_endpoint():
    async def run():
        c = connection()
        c.ring.append(frame(0), pcm(0))
        c.ring.begin({'wake_id': 'old-fast-input', 'stream_epoch': 'capture', 'detector_sample': 0},
                     pre_roll_seconds=0.)
        c.resampler, c.forward = ContinuousPcm24(), True
        entered, release, endpoint_seen = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_send = c.brain.send
        first = True
        async def paused_send(item):
            nonlocal first
            if isinstance(item, bytes) and first:
                first = False
                entered.set()
                await release.wait()
            await original_send(item)
        endpoints = []
        async def expert_endpoint(data, position):
            endpoints.append((position, len(data)//2))
            if position == 960:
                endpoint_seen.set()
        c.brain.send, c.expert_endpoint = paused_send, expert_endpoint
        c.input_changed.set()
        task = asyncio.create_task(c.uplink())
        try:
            await asyncio.wait_for(entered.wait(), 2)
            c.forward = False
            c.ring.set_blocked(False, reason='stop')
            c.selected_input_mode('expert')
            c.ring.begin({'wake_id': 'new-expert-input', 'stream_epoch': 'capture', 'detector_sample': 960},
                         pre_roll_seconds=0.)
            c.resampler, c.forward = ContinuousPcm24(), True
            c.ring.append(frame(1), pcm(1))
            release.set()
            await asyncio.wait_for(endpoint_seen.wait(), 2)
            assert endpoints == [(960, 960)]
            assert c.stats['capture_boundaries']['first_uplink']['source_sample_start'] == 960
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await asyncio.gather(*list(c.tasks))
    asyncio.run(run())
