"""Wire-lock races for physical mute; no real device, microphone or provider."""
import asyncio

import pytest

from test_sophia_gateway import connection
from test_sophia_capture_guard import frame, pcm
from test_sophia_barge import control, messages, until
from sophia_audio import ContinuousPcm24


async def cleanup(c, *tasks):
    if c.device_send_lock.locked():
        c.device_send_lock.release()
    if c.brain_send_lock.locked():
        c.brain_send_lock.release()
    pending = {*tasks, *c.tasks} - {None}
    for task in pending:
        task.cancel()
    await asyncio.gather(*pending, return_exceptions=True)


def test_hold_fences_output_start_already_waiting_for_device_wire_lock():
    async def run():
        c = connection()
        await c.device_send_lock.acquire()
        output = asyncio.create_task(c.cloud_event({
            'type': 'audio_start', 'data': {'response_id': 'queued-before-hold'}}))
        receiver = None
        try:
            await until(lambda: c.output is not None)
            state = c.output
            assert state['start_sent'] is False
            receiver = asyncio.create_task(c.receive())
            await c.device.queue.put(control(c, type='gobot_host_mute', muted=True))
            await until(lambda: c.muted)
            assert state['cancel_pending'] and c.ring.blocked
            c.device_send_lock.release()
            await asyncio.wait_for(output, 1)
            assert not any(m['type'] == 'gobot_host_output_start' for m in messages(c.device))
            # Nothing reached ESP, so a cancel must not wait for a receipt
            # from a physical output owner which was never created.
            await asyncio.wait_for(c.cloud_event({
                'type': 'audio_cancel', 'data': {'response_id': 'queued-before-hold'}}), .5)
            assert c.output is None and c.muted and c.ring.blocked
            assert c.stats['playback_finished'] == 0
            assert not any(m['type'] in {'gobot_host_output_start', 'gobot_host_output_cancel'}
                           for m in messages(c.device))
            assert not any(m['type'] == 'playback_finished' for m in messages(c.brain))
        finally:
            await cleanup(c, output, receiver)
    asyncio.run(run())


def test_old_unmute_ack_cannot_undo_new_hold_but_later_admin_unmute_works():
    async def run():
        c = connection()
        c.muted = True
        c.ring.set_blocked(True, reason='mute')
        receiver = asyncio.create_task(c.receive())
        try:
            await c.device.queue.put(control(c, type='gobot_host_mute', muted=False))
            await until(lambda: len([m for m in messages(c.brain) if m['type'] == 'mute']) == 1)
            unmute = next(m for m in messages(c.brain) if m['type'] == 'mute')
            await c.device.queue.put(control(c, type='gobot_host_mute', muted=True))
            await until(lambda: len([m for m in messages(c.brain) if m['type'] == 'mute']) == 2)
            mute = [m for m in messages(c.brain) if m['type'] == 'mute'][-1]
            assert unmute['request_id'] != mute['request_id']
            await c.cloud_event({'type': 'muted', 'data': {
                'muted': False, 'request_id': unmute['request_id']}})
            await c.cloud_event({'type': 'muted', 'data': {'muted': False}})
            assert c.muted and c.ring.blocked and not c.forward
            assert not any(m['type'] == 'gobot_host_mute' and m['muted'] is False
                           for m in messages(c.device))
            await c.cloud_event({'type': 'muted', 'data': {
                'muted': True, 'request_id': mute['request_id']}})
            assert c.latest_physical_mute_request is None and c.muted
            # A repeated old correlated ACK is still old after the current
            # one completed; it is never an uncorrelated admin action.
            await c.cloud_event({'type': 'muted', 'data': {
                'muted': False, 'request_id': unmute['request_id']}})
            assert c.muted and c.ring.blocked
            # A new owner admin command remains usable after physical ACK.
            await c.cloud_event({'type': 'muted', 'data': {'muted': False}})
            assert not c.muted and not c.ring.blocked and not c.forward
            assert c.ring.cursor is None
            assert not any(m['type'] == 'wake' for m in messages(c.brain))
        finally:
            await cleanup(c, receiver)
    asyncio.run(run())


def test_ack_already_waiting_for_device_lock_cannot_unmute_a_newer_hold():
    async def run():
        c = connection()
        c.device_mute_snapshot({'mute_revision': 0, 'muted': True}, initial=True)
        receiver = asyncio.create_task(c.receive())
        old_ack = None
        try:
            await c.device.queue.put(control(c, type='gobot_host_mute', muted=False, mute_revision=1))
            await until(lambda: len(c.device.sent) >= 2)
            unmute = next(m for m in messages(c.brain) if m['type'] == 'mute')
            await c.device_send_lock.acquire()
            old_ack = asyncio.create_task(c.cloud_event({'type': 'muted', 'data': {
                'muted': False, 'request_id': unmute['request_id']}}))
            await until(lambda: c.latest_physical_mute_request is None)
            await c.device.queue.put(control(c, type='gobot_host_mute', muted=True, mute_revision=2))
            await until(lambda: c.muted and c.latest_physical_mute_request is not None)
            c.device_send_lock.release()
            await asyncio.wait_for(old_ack, 1)
            await until(lambda: any(m.get('state') == 'muted' for m in messages(c.device)))
            assert c.muted and c.ring.blocked and not c.forward
            assert c.device_mute_revision == 2
            assert not any(m['type'] == 'gobot_host_mute' and not m['muted']
                           for m in messages(c.device))
            mute = [m for m in messages(c.brain) if m['type'] == 'mute'][-1]
            await c.cloud_event({'type': 'muted', 'data': {
                'muted': True, 'request_id': mute['request_id']}})
            sent = [m for m in messages(c.device) if m['type'] == 'gobot_host_mute']
            assert len(sent) == 1 and sent[0]['muted'] and sent[0]['mute_revision'] == 2
        finally:
            await cleanup(c, old_ack, receiver)
    asyncio.run(run())


def test_reconnect_adopts_physical_mute_and_echoes_revision_for_later_admin_control():
    async def run():
        c = connection()
        assert c.device_mute_snapshot({'mute_revision': 14, 'muted': True}, initial=True)
        assert c.muted and c.ring.blocked and c.ring.cursor is None
        await c.notify_physical_mute()
        request = next(m for m in messages(c.brain) if m['type'] == 'mute')
        await c.cloud_event({'type': 'muted', 'data': {'muted': False}})
        assert c.muted and not c.device.sent
        await c.cloud_event({'type': 'muted', 'data': {
            'muted': True, 'request_id': request['request_id']}})
        await c.cloud_event({'type': 'muted', 'data': {'muted': False}})
        controls = [m for m in messages(c.device) if m['type'] == 'gobot_host_mute']
        assert [m['muted'] for m in controls] == [True, False]
        assert all(m['mute_revision'] == 14 for m in controls)
        assert not c.muted and not c.forward and c.ring.cursor is None
        assert not any(m['type'] == 'wake' for m in messages(c.brain))
    asyncio.run(run())


def test_same_state_uncorrelated_echo_cannot_orphan_pending_physical_mute():
    async def run():
        c = connection()
        c.device_mute_snapshot({'mute_revision': 2, 'muted': True}, initial=True)
        await c.brain_send_lock.acquire()
        notify = asyncio.create_task(c.notify_physical_mute())
        try:
            await until(lambda: c.latest_physical_mute_request is not None)
            request_id = c.latest_physical_mute_request
            epoch = c.mute_control_epoch
            await c.cloud_event({'type': 'muted', 'data': {'muted': True}})
            assert c.mute_control_epoch == epoch
            c.brain_send_lock.release()
            assert await asyncio.wait_for(notify, 1)
            assert len(messages(c.brain)) == 1
            await c.cloud_event({'type': 'muted', 'data': {
                'muted': True, 'request_id': request_id}})
            assert c.latest_physical_mute_request is None
            await c.cloud_event({'type': 'muted', 'data': {'muted': False}})
            assert not c.muted and not c.forward and c.ring.cursor is None
        finally:
            await cleanup(c, notify)
    asyncio.run(run())


def test_stale_mute_ack_cannot_cancel_a_newer_pending_tap():
    async def run():
        c = connection()
        c.physical_mute_requests['old-hold'] = True
        c.physical_mute_requests['current-unmute'] = False
        c.latest_physical_mute_request = 'current-unmute'
        intent = c.pending_interrupt = {'wake': {'wake_id': 'new-tap'}, 'request_id': 'stop-new-tap'}
        wake = intent['wake']
        await c.cloud_event({'type': 'muted', 'data': {'muted': True, 'request_id': 'old-hold'}})
        assert not c.muted and intent['wake'] is wake
        assert c.latest_physical_mute_request == 'current-unmute' and not c.device.sent
        await c.cloud_event({'type': 'muted', 'data': {'muted': False, 'request_id': 'current-unmute'}})
        assert c.latest_physical_mute_request is None and intent['wake'] is wake
        assert not c.muted and not c.forward
        assert [m['muted'] for m in messages(c.device) if m['type'] == 'gobot_host_mute'] == [False]
    asyncio.run(run())


def test_current_unmute_ack_preserves_the_input_opened_after_physical_tap():
    async def run():
        c = connection()
        c.device_mute_snapshot({'mute_revision': 3, 'muted': False}, initial=True)
        await c.notify_physical_mute()
        request_id = c.latest_physical_mute_request
        cursor, resampler = active_capture(c)
        await c.cloud_event({'type': 'muted', 'data': {'muted': False, 'request_id': request_id}})
        assert c.latest_physical_mute_request is None
        assert c.ring.cursor is cursor and c.resampler is resampler
        assert c.forward and c.stats['input_open'] and not c.ring.blocked
        assert [m['mute_revision'] for m in messages(c.device) if m['type'] == 'gobot_host_mute'] == [3]
    asyncio.run(run())


def test_old_physical_revision_cannot_replace_a_newer_hold():
    c = connection()
    assert c.device_mute_snapshot({'mute_revision': 12, 'muted': True}, initial=True)
    assert not c.device_mute_snapshot({'mute_revision': 11, 'muted': False})
    assert not c.device_mute_snapshot({'mute_revision': 12, 'muted': False})
    assert c.muted and c.ring.blocked and c.device_mute_revision == 12
    assert c.device_mute_snapshot({'mute_revision': 13, 'muted': False})
    assert not c.muted and not c.forward and c.ring.cursor is None


@pytest.mark.parametrize('invalid', [None, True, -1, 2**32, 1.5, '12'])
def test_negotiated_mute_revision_must_be_a_valid_unsigned_integer(invalid):
    c = connection()
    with pytest.raises(ValueError, match='invalid_physical_mute_revision'):
        c.device_mute_snapshot({'mute_revision': invalid, 'muted': True}, initial=True)
    c.device_mute_snapshot({'mute_revision': 2, 'muted': True}, initial=True)
    with pytest.raises(ValueError, match='invalid_physical_mute_revision'):
        c.device_mute_snapshot({'muted': False})
    assert c.muted and c.ring.blocked


def active_capture(c):
    c.ring.append(frame(0), pcm(0))
    c.ring.begin({'wake_id': 'current-input', 'stream_epoch': 'capture',
                  'detector_sample': 0}, pre_roll_seconds=0.)
    c.resampler = ContinuousPcm24()
    c.forward = True
    c.stats['input_open'] = True
    c.input_changed.set()
    return c.ring.cursor, c.resampler


def test_hold_discards_unsent_pcm_waiting_for_brain_wire_lock():
    async def run():
        c = connection()
        cursor, _ = active_capture(c)
        await c.brain_send_lock.acquire()
        uplink = asyncio.create_task(c.uplink())
        receiver = None
        try:
            await until(lambda: cursor.position == 960)
            receiver = asyncio.create_task(c.receive())
            await c.device.queue.put(control(c, type='gobot_host_mute', muted=True))
            await until(lambda: c.muted and c.latest_physical_mute_request is not None)
            assert c.ring.cursor is None and c.ring.blocked
            c.brain_send_lock.release()
            await until(lambda: any(m['type'] == 'mute' for m in messages(c.brain)))
            assert not any(isinstance(item, bytes) for item in c.brain.sent)
            assert c.first_uplink_cursor is None
            assert not c.forward and not c.stats['input_open']
        finally:
            await cleanup(c, uplink, receiver)
    asyncio.run(run())


def test_asr_pause_keeps_inflight_pcm_for_same_retained_input_cursor():
    async def run():
        c = connection()
        cursor, resampler = active_capture(c)
        await c.brain_send_lock.acquire()
        uplink = asyncio.create_task(c.uplink())
        try:
            await until(lambda: cursor.position == 960)
            expected_first_bytes = resampler.output_samples*2
            assert expected_first_bytes > 0
            # The first wake fragment is being transcribed. This is a pause,
            # not a physical stop: Brain's fragment buffer accepts bytes which
            # crossed it in flight, preserving the following question.
            await c.cloud_event({'type': 'input_closed', 'data': {
                'reason': 'provider_endpoint', 'resume_pending': True}})
            assert not c.forward and c.ring.cursor is cursor and not c.ring.blocked
            c.brain_send_lock.release()
            await until(lambda: any(isinstance(item, bytes) for item in c.brain.sent))
            packets = [item for item in c.brain.sent if isinstance(item, bytes)]
            assert len(packets) == 1 and len(packets[0]) == expected_first_bytes
            assert c.ring.cursor is cursor and c.resampler is resampler
            assert cursor.sent_samples == 960
            await c.cloud_event({'type': 'listening', 'data': {'resume_capture': True}})
            c.ring.append(frame(1), pcm(1))
            c.input_changed.set()
            await until(lambda: len([item for item in c.brain.sent if isinstance(item, bytes)]) == 2)
            packets = [item for item in c.brain.sent if isinstance(item, bytes)]
            assert sum(map(len, packets)) == resampler.output_samples*2
            assert cursor.position == cursor.sent_samples == 1920
            assert c.ring.cursor is cursor and c.resampler is resampler and c.forward
        finally:
            await cleanup(c, uplink)
    asyncio.run(run())
