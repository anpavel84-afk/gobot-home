"""Physical timer transport: no provider, device, network or paid calls."""
import asyncio
import json
import struct
from uuid import uuid4

import pytest

from test_sophia_gateway import connection
from sophia_timer import alarm_pcm, MAX_TIMERS


def events(socket):
    return [json.loads(item) for item in socket.sent if isinstance(item, str)]


def ready(*, display=False):
    c = connection()
    c.stats.update(device_protocol_confirmed=True, voice_phase='ready')
    c.cloud_ready.set()
    c.timers.clock = lambda: 100.
    c.timers.configure({'host_stream': {'timer_display': 1 if display else 0}})
    return c


def alarm(**changes):
    return {'alarm_id': str(uuid4()), 'claim_id': str(uuid4()), 'timer_id': str(uuid4()),
            'revision': 1, 'expires_at': 220., **changes}


def snapshot(revision=1, *, timer_id=None, state='running', deadline=110.):
    return {'revision': revision, 'timers': [{'timer_id': timer_id or str(uuid4()),
            'revision': revision, 'state': state, 'deadline': deadline,
            'remaining_ms': 10000 if state == 'running' else 0}]}


async def until(check):
    for _ in range(1000):
        if check():
            return
        await asyncio.sleep(0)
    raise AssertionError('local task did not reach expected boundary')


async def start(c, claim=None):
    claim = claim or alarm()
    await c.cloud_event({'type': 'timer_alarm', 'data': claim})
    task = asyncio.create_task(c.timers.tick())
    await until(lambda: c.output is not None and c.output.get('done'))
    return task, claim, c.output_fields()


async def finish(c, fields, *, floor=960):
    await c.receipt({**fields, 'state': 'segment_finished', 'whole_response': False,
                     'stream_epoch': 'capture', 'sample_floor': floor})


async def settle(c):
    await asyncio.gather(*list(c.tasks))


def test_fixed_local_signal_and_honest_v420_capabilities():
    pcm = alarm_pcm()
    samples = struct.unpack('<8640h', pcm)
    assert samples[0] == samples[-1] == 0 and max(map(abs, samples)) <= 2200
    assert any(samples) and pcm == alarm_pcm()
    async def run():
        c = ready()
        await c.timers.announce()
        assert events(c.brain) == [{'type': 'timer_capabilities',
                                   'display_supported': False, 'signal_supported': True}]
        assert c.timers.stats['signal'] == 'unconfirmed'
        await c.timers.snapshot(snapshot())
        assert not c.device.sent
        c.timers.configure({'host_stream': {'timer_display': True}})
        assert not c.timers.display_supported  # Explicit integer capability only.
        c.encoder_factory = lambda: (_ for _ in ()).throw(RuntimeError('no local codec'))
        c.timers.configure({'host_stream': {'timer_display': 1}})
        assert c.timers.stats['signal'] == 'unavailable'
        assert c.timers.stats['display'] == 'unconfirmed'
        assert not c.forward and c.ring.cursor is None
    asyncio.run(run())


def test_real_local_encoder_produces_bounded_existing_opus_frames():
    from gobot_device_gateway import OpusOutput
    c = ready()
    c.encoder_factory = OpusOutput
    c.timers.configure({'host_stream': {}})
    assert 6 <= len(c.timers.packets) <= 8
    assert all(0 < len(packet) <= 4096 for packet in c.timers.packets)


def test_snapshot_cancel_replay_reconnect_and_actual_framebuffer_receipt():
    async def run():
        c = ready(display=True)
        current = snapshot()
        await c.timers.snapshot(current)
        wire = events(c.device)[-1]
        assert wire == {'type': 'gobot_host_timer', 'revision': 1, 'timer_id': current['timers'][0]['timer_id'],
                        'state': 'running', 'remaining_ms': 10000, 'session_id': c.transport, 'epoch': c.epoch}
        c.timers.clock = lambda: 104.
        await c.timers.snapshot({**current, 'timers': [{**current['timers'][0], 'remaining_ms': 6000}]})
        assert len(c.device.sent) == 1  # Native local countdown is not reset.
        ack = {**wire, 'type': 'gobot_host_timer_ack', 'rendered': True,
               'evidence': 'native_framebuffer_invalidated'}
        await c.timers.display_receipt({**ack, 'revision': 0})
        assert c.timers.stats['display'] == 'unconfirmed'
        await c.timers.display_receipt(ack)
        assert c.timers.stats['display'] == 'confirmed'
        assert events(c.brain)[-1] == {'type': 'timer_display_ack', 'snapshot_revision': 1,
            'state': 'running', 'rendered': True, 'evidence': 'native_framebuffer_invalidated'}
        await c.timers.snapshot(snapshot(2, timer_id=wire['timer_id'], state='cancelled'))
        assert events(c.device)[-1]['state'] == 'clear'
        await c.timers.display_receipt(ack)
        assert c.timers.stats['display_receipt'] is None
        await c.timers.snapshot(current)
        assert len(c.device.sent) == 2
        fresh = ready(display=True)
        fresh.timers.clock = lambda: 104.
        await fresh.timers.snapshot(current)
        resumed = events(fresh.device)[-1]
        assert resumed['revision'] == 1 and resumed['remaining_ms'] == 6000
        assert resumed['epoch'] != wire['epoch']
        assert not fresh.forward and fresh.ring.cursor is None
    asyncio.run(run())


@pytest.mark.parametrize('bad', [None, [], {'revision': True, 'timers': []},
    {'revision': 1, 'timers': [None]}, {'revision': 1, 'timers': [{}]},
    {'revision': 1, 'timers': [snapshot()['timers'][0]]*17}])
def test_malformed_snapshot_cannot_mutate_voice_or_send_native_commands(bad):
    async def run():
        c = ready(display=True)
        await c.timers.snapshot(bad)
        assert not c.device.sent and c.timers.snapshot_revision == -1
        assert not c.forward and c.ring.cursor is None and c.output is None
    asyncio.run(run())


def test_alarm_actual_cue_receipts_are_distinct_and_never_open_followup():
    async def run():
        c = ready()
        task, claim, fields = await start(c)
        sent = events(c.device)
        assert sent[0]['kind'] == 'cue' and sent[-1]['whole_response'] is False
        assert c.timers.stats['signal'] == 'unconfirmed'
        assert not [e for e in events(c.brain) if e['type'] == 'timer_alarm_ack']
        await c.receipt({**fields, 'output_epoch': 5, 'state': 'playback_started'})
        assert not [e for e in events(c.brain) if e['type'] == 'timer_alarm_ack']
        await c.receipt({**fields, 'state': 'playback_started'})
        await c.receipt({**fields, 'state': 'playback_started'})
        await c.receipt({**fields, 'state': 'playback_finished', 'whole_response': True})
        assert c.output is not None
        await finish(c, fields)
        await task
        await c.timers.alarm(claim)
        await c.timers.tick()
        await settle(c)
        receipts = [e['state'] for e in events(c.brain) if e['type'] == 'timer_alarm_ack']
        assert receipts == ['started', 'finished']
        assert not [e for e in events(c.brain) if e['type'] in {'wake', 'playback_started', 'playback_finished'}]
        assert c.timers.stats['signal'] == 'confirmed'
        assert c.output is None and not c.forward and c.ring.cursor is None
        assert c.ring.floor == 4160 and not c.ring.blocked
        assert len([e for e in events(c.device) if e['type'] == 'gobot_host_output_start']) == 1
        # Installed cue completion keeps native response_busy for an expert's
        # next answer. Our independent cue explicitly restores native idle.
        assert [e['state'] for e in events(c.device) if e['type'] == 'gobot_host_state'] == ['ready']
    asyncio.run(run())


def test_timer_ready_waiting_on_wire_lock_cannot_override_new_followup():
    async def run():
        c = ready()
        task, _, fields = await start(c)
        await c.device_send_lock.acquire()
        completed = asyncio.create_task(finish(c, fields))
        await until(lambda: c.output is None)
        followup = asyncio.create_task(c.cloud_event({'type': 'followup', 'data': {}}))
        await until(lambda: c.forward)
        cursor = c.ring.cursor
        c.device_send_lock.release()
        await completed
        await followup
        await task
        await settle(c)
        assert c.ring.cursor is cursor and c.forward and not c.ring.blocked
        assert [e['state'] for e in events(c.device) if e['type'] == 'gobot_host_state'] == ['listening']
    asyncio.run(run())


def test_busy_alarm_queue_is_bounded_expiring_and_stop_mute_suppress_without_audio():
    async def run():
        c = ready()
        c.stats['voice_phase'] = 'thinking'
        for _ in range(MAX_TIMERS+1):
            await c.timers.alarm(alarm())
        assert len(c.timers.pending) == MAX_TIMERS
        assert c.timers.stats['delivery_state'] == 'postponed'
        assert c.timers.stats['delay_reason'] == 'conversation_busy'
        await c.timers.tick()
        assert not c.device.sent
        c.timers.clock = lambda: 221.
        await c.timers.tick()
        assert not c.timers.pending
        assert c.timers.stats['delivery_state'] == 'suppressed'
        assert c.timers.stats['last_outcome_reason'] == 'expired'
        assert c.timers.stats['suppressed_count'] == MAX_TIMERS+1
        assert [e['state'] for e in events(c.brain)] == ['suppressed']*(MAX_TIMERS+1)
        c.timers.clock = lambda: 100.
        await c.timers.alarm(alarm())
        c.fence_interruption('physical_stop')
        await settle(c)
        assert not c.timers.pending
        c.muted = True
        await c.timers.alarm(alarm())
        assert not c.device.sent and c.output is None
    asyncio.run(run())


def test_followup_has_priority_then_idle_delivers_once_without_new_input():
    async def run():
        c = ready()
        await c.cloud_event({'type': 'followup', 'data': {}})
        claim = alarm()
        await c.timers.alarm(claim)
        await c.timers.tick()
        assert c.output is None and c.forward
        assert c.timers.stats['delivery_state'] == 'postponed'
        assert c.timers.stats['delay_reason'] == 'input_open'
        assert c.timers.stats['postponed_count'] == 1
        await c.cloud_event({'type': 'followup_closed', 'data': {'reason': 'silence'}})
        task = asyncio.create_task(c.timers.tick())
        await until(lambda: c.output is not None and c.output.get('done'))
        assert c.timers.stats['delivery_state'] == 'playing'
        await finish(c, c.output_fields())
        await task
        await settle(c)
        assert c.timers.stats['delivery_state'] == 'finished'
        assert c.timers.stats['finished_count'] == 1
        assert not c.forward and c.ring.cursor is None
    asyncio.run(run())


def test_continuous_input_past_alarm_deadline_suppresses_without_interrupting_input():
    async def run():
        c = ready()
        await c.cloud_event({'type': 'followup', 'data': {}})
        cursor = c.ring.cursor
        await c.timers.alarm(alarm())
        c.timers.clock = lambda: 220.
        await c.timers.tick()
        assert c.forward and c.ring.cursor is cursor and c.output is None
        assert c.timers.stats['delivery_state'] == 'suppressed'
        assert c.timers.stats['last_outcome_reason'] == 'expired'
        assert not [e for e in events(c.device) if e['type'].startswith('gobot_host_output')]
        await settle(c)
    asyncio.run(run())


@pytest.mark.parametrize('tombstone', [True, False])
def test_new_authoritative_snapshot_suppresses_queued_or_late_cancelled_alarm(tombstone):
    async def run():
        c = ready()
        c.stats['voice_phase'] = 'thinking'
        claim = alarm()
        await c.timers.alarm(claim)
        state = snapshot(2, timer_id=claim['timer_id'], state='cancelled') if tombstone else {'revision': 2, 'timers': []}
        await c.timers.snapshot(state)
        assert not c.timers.pending
        assert c.timers.stats['last_outcome_reason'] == 'timer_cancelled'
        fresh = ready()
        await fresh.timers.snapshot(state)
        await fresh.timers.alarm(claim)
        assert not fresh.timers.pending and fresh.output is None
        assert events(fresh.brain)[-1]['state'] == 'suppressed'
        assert not c.device.sent and not fresh.device.sent
    asyncio.run(run())


def test_cancelled_snapshot_stops_active_alarm_at_actual_dma_barrier():
    async def run():
        c = ready()
        task, claim, fields = await start(c)
        cancel = asyncio.create_task(c.timers.snapshot({'revision': 2, 'timers': []}))
        await until(lambda: any(e['type'] == 'gobot_host_output_cancel' for e in events(c.device)))
        assert c.output is not None and not cancel.done()
        await c.receipt({**fields, 'state': 'stopped', 'output_epoch': fields['output_epoch']+1,
                         'stream_epoch': 'capture', 'sample_floor': 960})
        await cancel
        await task
        await settle(c)
        assert c.output is None and c.timers.seen[claim['alarm_id']]['state'] == 'cancelled'
        assert c.timers.stats['last_outcome_reason'] == 'timer_cancelled'
        assert c.ring.floor == 4160 and not c.forward
    asyncio.run(run())


def test_unknown_first_send_failure_is_never_retried():
    async def run():
        c = ready()
        claim = alarm()
        await c.timers.alarm(claim)
        attempted = 0
        async def fail_send(item):
            nonlocal attempted
            attempted += 1
            raise OSError('uncertain_send')
        c.device.send = fail_send
        with pytest.raises(OSError, match='uncertain_send'):
            await c.timers.tick()
        assert c.timers.seen[claim['alarm_id']]['state'] == 'unknown'
        await c.timers.alarm(claim)
        await c.timers.tick()
        assert attempted == 1 and not c.timers.pending
        assert events(c.brain)[-1]['state'] == 'unknown'
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['audio_start', 'followup', 'listening'])
def test_normal_output_or_capture_waits_for_real_physical_stop(kind):
    async def run():
        c = ready()
        task, _, fields = await start(c)
        data = {'response_id': 'normal-answer'} if kind == 'audio_start' else {}
        next_event = asyncio.create_task(c.cloud_event({'type': kind, 'data': data}))
        await until(lambda: any(e['type'] == 'gobot_host_output_cancel' for e in events(c.device)))
        assert not next_event.done() and not c.forward and c.ring.cursor is None
        assert c.timers.owns()
        await c.receipt({**fields, 'state': 'stopped', 'output_epoch': fields['output_epoch']+1,
                         'stream_epoch': 'capture', 'sample_floor': 1920})
        await next_event
        await task
        assert c.ring.floor >= 5120
        if kind == 'audio_start':
            assert c.output['response_id'] == 'normal-answer' and not c.forward
        else:
            assert c.forward
            if kind == 'followup':
                assert c.ring.cursor.selected_start >= 5120
        await settle(c)
        assert [e['state'] for e in events(c.brain) if e['type'] == 'timer_alarm_ack'] == ['cancelled']
        assert not [e for e in events(c.brain) if e['type'] == 'playback_finished']
    asyncio.run(run())


def test_mute_wins_while_first_output_start_waits_for_device_lock():
    async def run():
        c = ready()
        await c.device_send_lock.acquire()
        await c.timers.alarm(alarm())
        task = asyncio.create_task(c.timers.tick())
        await until(lambda: c.output is not None)
        mute = asyncio.create_task(c.cloud_event({'type': 'muted', 'data': {'muted': True}}))
        await until(lambda: c.muted)
        c.device_send_lock.release()
        await mute
        await task
        await settle(c)
        assert c.output is None and not c.forward and c.ring.blocked
        assert not [e for e in events(c.device) if e['type'].startswith('gobot_host_output')]
        assert events(c.brain)[-1]['type'] != 'wake'
    asyncio.run(run())


@pytest.mark.parametrize('native_interrupt_flag', [True, False])
def test_manual_wake_stops_alarm_then_uses_existing_stop_ack_before_capture(native_interrupt_flag):
    async def run():
        c = ready()
        task, _, fields = await start(c)
        control = {'interrupt_requested': native_interrupt_flag, 'event_id': 'wake-1',
                   'interrupted_response_id': fields['response_id'],
                   'interrupted_playback_id': fields['playback_id'],
                   'interrupted_output_epoch': fields['output_epoch']}
        if not native_interrupt_flag:
            control = {}  # Idle native wake arrived before its cue start.
        assert c.device_activation({'wake_id': 'wake-1', 'stream_epoch': 'capture', 'detector_sample': 0},
                                   trigger='wake_word', control=control)
        await until(lambda: any(e['type'] == 'gobot_host_output_cancel' for e in events(c.device)))
        await c.receipt({**fields, 'state': 'stopped', 'output_epoch': fields['output_epoch']+1,
                         'stream_epoch': 'capture', 'sample_floor': 960})
        await until(lambda: any(e['type'] == 'stop' for e in events(c.brain)))
        assert not [e for e in events(c.brain) if e['type'] == 'wake']
        request = next(e['request_id'] for e in events(c.brain) if e['type'] == 'stop')
        await c.cloud_event({'type': 'stopped', 'data': {'request_id': request}})
        await task
        await settle(c)
        assert len([e for e in events(c.brain) if e['type'] == 'wake']) == 1
        assert c.ring.cursor.selected_start == 960
        assert not [e for e in events(c.brain) if e['type'] == 'playback_finished']
    asyncio.run(run())


def test_ordinary_wake_cancels_unstarted_timer_reservation_without_physical_stop():
    async def run():
        c = ready()
        await c.device_send_lock.acquire()
        await c.timers.alarm(alarm())
        task = asyncio.create_task(c.timers.tick())
        await until(lambda: c.output is not None)
        assert c.output['start_sent'] is False
        assert c.device_activation({'wake_id': 'prestart-wake', 'stream_epoch': 'capture', 'detector_sample': 0},
                                   trigger='wake_word', control={})
        cursor = c.ring.cursor
        assert c.output is None and cursor is not None
        c.device_send_lock.release()
        await task
        await settle(c)
        assert not [e for e in events(c.device) if e['type'].startswith('gobot_host_output')]
        assert not [e for e in events(c.brain) if e['type'] == 'stop']
        assert len([e for e in events(c.brain) if e['type'] == 'wake']) == 1
        assert c.ring.cursor is cursor and not c.ring.blocked
        assert c.timers.stats['last_outcome_reason'] == 'manual_wake_before_output'
    asyncio.run(run())


def test_timer_role_without_exact_local_claim_is_not_an_alarm_owner():
    c = ready()
    assert not c.timers.owns({'role': 'timer_alarm'})
    assert not c.timers.owns({'role': 'timer_alarm', 'timer': alarm()})


def test_transport_loss_keeps_claim_unknown_and_never_replays_on_same_transport():
    async def run():
        c = ready()
        task, claim, fields = await start(c)
        c.fence_transport_end()
        await until(lambda: c.timers.seen[claim['alarm_id']]['state'] == 'unknown')
        await until(lambda: any(e['type'] == 'gobot_host_output_cancel' for e in events(c.device)))
        await c.receipt({**fields, 'state': 'stopped', 'output_epoch': fields['output_epoch']+1,
                         'stream_epoch': 'capture', 'sample_floor': 960})
        await task
        await settle(c)
        await c.cloud_event({'type': 'timer_alarm', 'data': claim})
        assert c.timers.seen[claim['alarm_id']]['state'] == 'unknown'
        assert not c.timers.pending and c.ring.blocked and not c.forward
        assert len([e for e in events(c.device) if e['type'] == 'gobot_host_output_start']) == 1
    asyncio.run(run())
