"""Physical interruption keeps two cancellation barriers and the next question.

Synthetic PCM and socket fixtures only; no provider, microphone or live device.
"""
import asyncio
import base64
import json
import time

from fastapi.testclient import TestClient
import pytest

from test_sophia_gateway import connection
from test_sophia_capture_guard import frame, pcm
from test_unified_voice_api import TOKEN, setup, hello


def messages(socket):
    return [json.loads(value) for value in socket.sent if isinstance(value, str)]


async def until(predicate):
    async with asyncio.timeout(2):
        while not predicate():
            await asyncio.sleep(.001)


async def finish_tasks(c):
    for task in list(c.tasks):
        if not task.done():
            task.cancel()
    await asyncio.gather(*list(c.tasks), return_exceptions=True)


def control(c, **fields):
    return json.dumps({'session_id': c.transport, 'epoch': c.epoch, **fields})


def interruption_owner(c):
    return {'interrupt_requested': True,
            **{'interrupted_'+key: value for key, value in c.output_fields().items()}}


async def stop_command(c):
    await until(lambda: any(item['type'] == 'stop' for item in messages(c.brain)))
    return next(item for item in messages(c.brain) if item['type'] == 'stop')


def test_idle_wake_preserves_exact_v4_preroll_and_sends_capture_anchor_before_admission():
    async def run():
        c = connection()
        c.cloud_ready.set()
        for index in range(30):
            c.ring.append(frame(index), pcm(index))
        wake = {'wake_id': 'idle-sophia', 'stream_epoch': 'capture', 'detector_sample': 25000}
        assert c.device_activation(wake, trigger='wake_word', control=wake)
        await asyncio.gather(*list(c.tasks))
        sent = messages(c.brain)
        assert len(sent) == 1 and sent[0]['type'] == 'wake'
        assert sent[0]['trigger'] == 'wake_word'
        assert sent[0]['capture'] == {'stream_epoch': 'capture', 'selected_start': 9000,
            'detector_sample': 25000, 'sample_rate': 16000, 'interrupt': False}
        assert not c.forward and not any(isinstance(value, bytes) for value in c.brain.sent)
        assert not c.device_activation(wake, trigger='wake_word', control=wake)
    asyncio.run(run())


def test_wake_interrupts_paced_audio_and_preserves_post_quiet_question_until_exact_stop_ack():
    async def run():
        c = connection()
        c.cloud_ready.set()
        for index in range(4):
            c.ring.append(frame(index), pcm(index))
        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'old-answer'}})
        fields = c.output_fields()
        state = c.output
        state['started_at'], state['seq'] = time.monotonic()+10, 8
        paced = asyncio.create_task(c.output_packet(b'must-not-play'))
        await asyncio.sleep(0)
        wake = {'wake_id': 'barge-sophia', 'stream_epoch': 'capture', 'detector_sample': 3500}
        assert c.device_activation(wake, trigger='wake_word', control=interruption_owner(c))
        assert state['cancel_pending'] and not c.forward and c.ring.blocked
        # A finish receipt already queued when the gesture arrived cannot make
        # the interrupted answer "heard" or open its automatic follow-up.
        await c.receipt({**fields, 'state': 'playback_finished', 'whole_response': True,
                         'stream_epoch': 'capture', 'sample_floor': 4800})
        assert c.stats['playback_finished'] == 0
        await until(lambda: any(item['type'] == 'gobot_host_output_cancel' for item in messages(c.device)))
        await c.receipt({**fields, 'state': 'stopped', 'output_epoch': fields['output_epoch']+1,
                         'stream_epoch': 'capture', 'sample_floor': 4800})
        await asyncio.wait_for(paced, .2)  # Must not sleep out the old audio clock.
        stop = await stop_command(c)
        for index in range(4, 12):
            c.ring.append(frame(index), pcm(index))
        await until(lambda: c.ring.cursor is not None)
        cursor = c.ring.cursor
        assert cursor.selected_start == 4800 and not c.forward
        for old in (
            {'type': 'listening', 'data': {}},
            {'type': 'input_closed', 'data': {'reason': 'provider_endpoint'}},
            {'type': 'audio_start', 'data': {'response_id': 'queued-old-answer'}},
            {'type': 'audio_chunk', 'data': {'response_id': 'old-answer', 'pcm': base64.b64encode(b'old').decode()}},
            {'type': 'stopped', 'data': {}},
            {'type': 'stopped', 'data': {'request_id': 'some-other-stop'}},
            {'type': 'error', 'data': {'code': 'old-input-failure'}},
        ):
            await c.cloud_event(old)
        assert c.ring.cursor is cursor and c.pending_interrupt is not None and not c.forward
        assert not any(item['type'] == 'wake' for item in messages(c.brain))
        await c.cloud_event({'type': 'stopped', 'data': {'request_id': stop['request_id']}})
        await until(lambda: any(item['type'] == 'wake' for item in messages(c.brain)))
        assert c.pending_interrupt is None and c.output is None and not c.forward
        sent = messages(c.brain)
        new_wake = next(item for item in sent if item['type'] == 'wake')
        assert sent.index(stop) < sent.index(new_wake)
        assert new_wake['capture'] == {'stream_epoch': 'capture', 'selected_start': 4800,
            'detector_sample': 3500, 'sample_rate': 16000, 'interrupt': True}
        assert not any(item['type'] == 'playback_finished' for item in sent)
        complete = [item for item in messages(c.device) if item['type'] == 'gobot_host_interrupt_complete']
        assert len(complete) == 1 and complete[0]['event_id'] == 'barge-sophia'
        assert complete[0]['outcome'] == 'listening'
        assert b'must-not-play' not in c.device.sent
        await c.cloud_event({'type': 'listening', 'data': {}})
        assert c.forward and c.ring.cursor is cursor
        parts = c.ring.read_available()
        assert parts[0][0] == 4800
        assert b''.join(data for _, data in parts) == b''.join(pcm(index) for index in range(5, 12))
        # A duplicate stop ACK or late old cancel cannot erase the new input.
        await c.cloud_event({'type': 'stopped', 'data': {'request_id': stop['request_id']}})
        await c.cloud_event({'type': 'audio_cancel', 'data': {'response_id': 'old-answer'}})
        assert c.ring.cursor is cursor and c.forward
        assert not c.device_activation(wake, trigger='wake_word', control={**interruption_owner(c)} if c.output else {'interrupt_requested': True})
        await finish_tasks(c)
    asyncio.run(run())


@pytest.mark.parametrize('action,outcome', [('activate', 'listening'), ('interrupt', 'listening'), ('stop', 'ready')])
def test_real_touch_control_route_tap_reopens_but_explicit_stop_finishes(action, outcome):
    async def run():
        c = connection()
        c.cloud_ready.set()
        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'touch-answer'}})
        fields = c.output_fields()
        owner = interruption_owner(c)
        receiver = asyncio.create_task(c.receive())
        try:
            await c.device.queue.put(control(c, type='gobot_host_touch', action=action,
                gesture='tap' if outcome == 'listening' else 'hold', event_id='touch-42',
                stream_epoch='capture', detector_sample=0, **owner))
            await until(lambda: any(item['type'] == 'gobot_host_output_cancel' for item in messages(c.device)))
            await c.device.queue.put(control(c, type='gobot_host_playback',
                **{**fields, 'output_epoch': fields['output_epoch']+1}, state='stopped',
                stream_epoch='capture', sample_floor=0))
            stop = await stop_command(c)
            await c.cloud_event({'type': 'stopped', 'data': {'request_id': stop['request_id']}})
            await until(lambda: any(item['type'] == 'gobot_host_interrupt_complete' for item in messages(c.device)))
            complete = next(item for item in messages(c.device) if item['type'] == 'gobot_host_interrupt_complete')
            assert complete['event_id'] == 'touch-42' and complete['outcome'] == outcome
            if outcome == 'listening':
                await until(lambda: any(item['type'] == 'wake' for item in messages(c.brain)))
                assert next(item for item in messages(c.brain) if item['type'] == 'wake')['trigger'] == 'touch'
                assert c.ring.cursor is not None and not c.forward
            else:
                assert not any(item['type'] == 'wake' for item in messages(c.brain))
                assert c.ring.cursor is None and not c.forward and not c.ring.blocked
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            await finish_tasks(c)
    asyncio.run(run())


def test_missing_physical_quiet_floor_never_admits_replacement_question():
    async def run():
        c = connection()
        c.cloud_ready.set()
        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'needs-physical-floor'}})
        fields = c.output_fields()
        c.device_activation({'wake_id': 'w', 'stream_epoch': 'capture', 'detector_sample': 0},
                            trigger='wake_word', control=interruption_owner(c))
        await until(lambda: any(item['type'] == 'gobot_host_output_cancel' for item in messages(c.device)))
        with pytest.raises(ValueError, match='physical_cancel_capture_floor_missing'):
            await c.receipt({**fields, 'state': 'stopped', 'output_epoch': fields['output_epoch']+1})
        assert c.ring.blocked and not c.forward
        assert not any(item['type'] == 'wake' for item in messages(c.brain))
        await finish_tasks(c)
    asyncio.run(run())


def test_mute_during_stop_barriers_cancels_new_listening_intent():
    async def run():
        c = connection()
        c.cloud_ready.set()
        c.stats['voice_phase'] = 'thinking'
        c.device_activation({'wake_id': 'mute-crossing', 'stream_epoch': 'capture', 'detector_sample': 0},
                            trigger='wake_word', control={'interrupt_requested': True})
        stop = await stop_command(c)
        c.interrupt_quiet_receipt({'event_id': 'mute-crossing', 'stream_epoch': 'capture', 'sample_floor': 0})
        await c.cloud_event({'type': 'muted', 'data': {'muted': True}})
        await c.cloud_event({'type': 'stopped', 'data': {'request_id': stop['request_id']}})
        await until(lambda: c.pending_interrupt is None)
        assert c.muted and not c.forward and c.ring.blocked
        assert not any(item['type'] == 'wake' for item in messages(c.brain))
        complete = next(item for item in messages(c.device) if item['type'] == 'gobot_host_interrupt_complete')
        assert complete['outcome'] == 'ready'
        await finish_tasks(c)
    asyncio.run(run())


def test_stop_ack_timeout_closes_transport_without_replaying_a_question(monkeypatch):
    import sophia_connection
    monkeypatch.setattr(sophia_connection, 'INTERRUPT_STOP_ACK_SECONDS', .02)
    async def run():
        c = connection()
        c.cloud_ready.set()
        closed = []
        async def close(**kwargs):
            closed.append(kwargs)
        c.brain.close = close
        c.device_activation({'wake_id': 'no-ack', 'stream_epoch': 'capture', 'detector_sample': 0},
                            trigger='wake_word', control={'interrupt_requested': True})
        c.interrupt_quiet_receipt({'event_id': 'no-ack', 'stream_epoch': 'capture', 'sample_floor': 0})
        await until(lambda: bool(closed))
        assert closed == [{'code': 1011, 'reason': 'interrupt_barrier_failed'}]
        assert c.ring.blocked and not c.forward
        assert len([item for item in messages(c.brain) if item['type'] == 'stop']) == 1
        assert not any(item['type'] == 'wake' for item in messages(c.brain))
        assert not any(item['type'] == 'gobot_host_interrupt_complete' for item in messages(c.device))
        await finish_tasks(c)
    asyncio.run(run())


def test_stale_owner_cannot_interrupt_a_new_playback_and_locked_old_packet_is_fenced():
    async def run():
        c = connection()
        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'new-owner'}})
        state = c.output
        bad = {**interruption_owner(c), 'interrupted_response_id': 'old-owner'}
        assert not c.device_activation({'wake_id': 'stale', 'stream_epoch': 'capture', 'detector_sample': 0},
                                       trigger='wake_word', control=bad)
        assert c.output is state and c.pending_interrupt is None
        await c.device_send_lock.acquire()
        pending = asyncio.create_task(c.output_packet(b'old-packet-behind-lock'))
        await asyncio.sleep(0)
        c.fence_interruption('explicit-owner-stop')
        c.device_send_lock.release()
        await asyncio.wait_for(pending, .2)
        assert b'old-packet-behind-lock' not in c.device.sent
        assert state['seq'] == 0 and c.stats['downlink_packets'] == 0
    asyncio.run(run())


def test_actual_ws_api_forwards_capture_anchor_and_stop_request_correlation():
    app, board, _ = setup()
    with TestClient(app) as client:
        with client.websocket_connect('/api/v1/voice-ws/stream', headers={'Authorization': 'Bearer '+TOKEN}) as ws:
            ws.send_json(hello())
            assert ws.receive_json()['type'] == 'transport_attached'
            session = board.sessions['session']
            seen = []
            async def wake(ident, **kwargs):
                seen.append((ident, kwargs))
                session.emit('listening')
            async def stop(*, request_id):
                seen.append(('stop', request_id))
                session.emit('stopped', request_id=request_id)
            session.wake, session.stop = wake, stop
            capture = {'stream_epoch': 'actual-clock', 'selected_start': 4000,
                       'detector_sample': 20000, 'sample_rate': 16000, 'interrupt': False}
            ws.send_json({'type': 'wake', 'wake_id': 'w', 'trigger': 'wake_word', 'capture': capture})
            assert ws.receive_json()['type'] == 'listening'
            assert seen[0][1]['capture'] == capture
            ws.send_json({'type': 'stop', 'request_id': 'opaque_stop_42'})
            assert ws.receive_json() == {'type': 'stopped', 'data': {'request_id': 'opaque_stop_42'}}
            assert seen[-1] == ('stop', 'opaque_stop_42')


@pytest.mark.parametrize('boundary', ['cloud_ready', 'brain_send_lock'])
def test_old_activation_cannot_cross_stop_and_send_using_replacement_cursor(boundary):
    async def run():
        c = connection()
        old = {'wake_id': 'old-wake', 'stream_epoch': 'capture', 'detector_sample': 0}
        c.ring.begin(old, pre_roll_seconds=0.)
        if boundary == 'brain_send_lock':
            c.cloud_ready.set()
            await c.brain_send_lock.acquire()
        pending = asyncio.create_task(c.activate(old, trigger='wake_word'))
        await asyncio.sleep(.01)
        assert not pending.done()
        c.ring.set_blocked(False, reason='stop-and-new-activation')
        fresh = {'wake_id': 'fresh-wake', 'stream_epoch': 'capture', 'detector_sample': 0}
        c.ring.begin(fresh, pre_roll_seconds=0.)
        if boundary == 'cloud_ready':
            c.cloud_ready.set()
        else:
            c.brain_send_lock.release()
        await asyncio.wait_for(pending, .2)
        assert messages(c.brain) == []
        await c.activate(fresh, trigger='wake_word')
        assert len(messages(c.brain)) == 1
        assert messages(c.brain)[0]['type'] == 'wake'
        assert c.ring.cursor.wake_id == 'fresh-wake'
    asyncio.run(run())


def test_server_stop_ack_alone_cannot_release_physical_pending_output():
    async def run():
        c = connection()
        c.cloud_ready.set()
        await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'physical-still-draining'}})
        fields = c.output_fields()
        c.device_activation({'wake_id': 'wait-quiet', 'stream_epoch': 'capture', 'detector_sample': 0},
                            trigger='wake_word', control=interruption_owner(c))
        stop = await stop_command(c)
        await c.cloud_event({'type': 'stopped', 'data': {'request_id': stop['request_id']}})
        await c.cloud_event({'type': 'stopped', 'data': {'request_id': stop['request_id']}})
        c.interrupt_quiet_receipt({'event_id': 'wait-quiet', 'stream_epoch': 'capture', 'sample_floor': 0})
        await asyncio.sleep(.01)
        assert c.pending_interrupt is not None and c.output is not None and c.ring.blocked
        assert not any(item['type'] == 'wake' for item in messages(c.brain))
        assert not any(item['type'] == 'gobot_host_interrupt_complete' for item in messages(c.device))
        await c.receipt({**fields, 'state': 'stopped', 'output_epoch': fields['output_epoch']+1,
                         'stream_epoch': 'capture', 'sample_floor': 0})
        await until(lambda: any(item['type'] == 'wake' for item in messages(c.brain)))
        assert c.output is None and c.pending_interrupt is None
        await finish_tasks(c)
    asyncio.run(run())


def test_thinking_waits_exact_no_owner_quiet_and_duplicate_stop_cannot_erase_waiting_new_wake():
    async def run():
        c = connection()
        c.cloud_ready.set()
        c.stats['voice_phase'] = 'thinking'
        c.ring.append(frame(0), pcm(0))
        receiver = asyncio.create_task(c.receive())
        locked = False
        try:
            await c.device.queue.put(control(c, type='gobot_host_wake', wake_id='thinking-wake',
                stream_epoch='capture', detector_sample=900, interrupt_requested=True))
            stop = await stop_command(c)
            await c.cloud_event({'type': 'stopped', 'data': {'request_id': stop['request_id']}})
            await c.device.queue.put(control(c, type='gobot_host_ack', event='interrupt_quiet',
                event_id='some-other-wake', stream_epoch='capture', sample_floor=1920))
            await asyncio.sleep(.01)
            assert c.pending_interrupt is not None and c.ring.blocked
            assert not any(item['type'] == 'gobot_host_interrupt_complete' for item in messages(c.device))
            await c.brain_send_lock.acquire()
            locked = True
            await c.device.queue.put(control(c, type='gobot_host_ack', event='interrupt_quiet',
                event_id='thinking-wake', stream_epoch='capture', sample_floor=1920))
            await until(lambda: c.pending_interrupt is None)
            cursor = c.ring.cursor
            assert cursor.selected_start == 1920 and not c.forward
            # Fresh activate is waiting on this lock; this is the exact race
            # where retiring the nonce only in the worker finally is too late.
            await c.cloud_event({'type': 'stopped', 'data': {'request_id': stop['request_id']}})
            assert c.ring.cursor is cursor
            c.brain_send_lock.release()
            locked = False
            await until(lambda: any(item['type'] == 'wake' for item in messages(c.brain)))
            event = next(item for item in messages(c.brain) if item['type'] == 'wake')
            assert event['capture']['selected_start'] == 1920 and event['capture']['detector_sample'] == 900
            assert event['capture']['interrupt'] is True
            quiet = c.stats['capture_boundaries']['interrupt_quiet']
            assert quiet['physical_sample_floor'] == quiet['selected_start'] == 1920
            assert 'response_id_sha256' not in quiet
        finally:
            if locked:
                c.brain_send_lock.release()
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            await finish_tasks(c)
    asyncio.run(run())
