"""Physical mute races at the real gateway; synthetic sockets/audio only."""
import asyncio

import pytest

from test_sophia_gateway import connection
from test_sophia_barge import control, finish_tasks, messages, stop_command, until


@pytest.mark.parametrize('phase', ['ready', 'listening', 'thinking', 'speaking'])
def test_hold_mutes_before_provider_ack_and_rejects_wake_and_queued_media(phase):
    async def run():
        c = connection()
        c.cloud_ready.set()
        c.stats['voice_phase'] = phase
        c.forward = phase == 'listening'
        c.stats['input_open'] = c.forward
        if phase == 'speaking':
            await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'old-answer'}})
            c.output['done'] = True
            fields = c.output_fields()
        receiver = asyncio.create_task(c.receive())
        try:
            await c.device.queue.put(control(c, type='gobot_host_mute', muted=True))
            await until(lambda: any(m['type'] == 'mute' for m in messages(c.brain)))
            assert c.muted and c.ring.blocked and not c.forward and not c.stats['input_open']
            assert not c.device_activation({'wake_id': 'after-hold', 'stream_epoch': 'capture',
                'detector_sample': 0}, trigger='wake_word', control={})
            if phase == 'speaking':
                assert c.output['cancel_pending']
                await c.receipt({**fields, 'state': 'playback_finished', 'whole_response': True,
                    'stream_epoch': 'capture', 'sample_floor': 0})
                assert c.stats['playback_finished'] == 0
            await c.cloud_event({'type': 'audio_start', 'data': {'response_id': 'late-answer'}})
            await c.cloud_event({'type': 'audio_chunk', 'data': {'response_id': 'late-answer',
                'pcm': 'invalid-if-decoded'}})
            await c.cloud_event({'type': 'listening', 'data': {}})
            await c.cloud_event({'type': 'followup', 'data': {}})
            await c.cloud_event({'type': 'ready', 'data': {'generation_allowed': True}})
            assert c.stats['muted_events_dropped'] == 2
            assert not c.forward and c.ring.blocked
            assert c.output is None or c.output['response_id'] == 'old-answer'
            assert not any(m['type'] in {'wake', 'playback_finished'} for m in messages(c.brain))
            states = [m['state'] for m in messages(c.device) if m['type'] == 'gobot_host_state']
            assert states[-1] == 'muted'
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            await finish_tasks(c)
    asyncio.run(run())


def test_hold_during_pending_interrupt_cannot_reopen_after_physical_quiet():
    async def run():
        c = connection()
        c.cloud_ready.set()
        c.stats['voice_phase'] = 'thinking'
        c.device_activation({'wake_id': 'tap-before-hold', 'stream_epoch': 'capture',
            'detector_sample': 0}, trigger='touch', control={'interrupt_requested': True})
        stop = await stop_command(c)
        receiver = asyncio.create_task(c.receive())
        try:
            await c.device.queue.put(control(c, type='gobot_host_mute', muted=True))
            await until(lambda: c.muted)
            c.interrupt_quiet_receipt({'event_id': 'tap-before-hold',
                'stream_epoch': 'capture', 'sample_floor': 0})
            await c.cloud_event({'type': 'stopped', 'data': {'request_id': stop['request_id']}})
            await until(lambda: c.pending_interrupt is None)
            assert c.muted and c.ring.blocked and not c.forward
            assert not any(m['type'] == 'wake' for m in messages(c.brain))
            completion = next(m for m in messages(c.device) if m['type'] == 'gobot_host_interrupt_complete')
            assert completion['outcome'] == 'ready'
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            await finish_tasks(c)
    asyncio.run(run())


def test_unmute_is_explicit_and_does_not_itself_admit_a_question():
    async def run():
        c = connection()
        c.cloud_ready.set()
        c.muted = True
        c.ring.set_blocked(True, reason='mute')
        receiver = asyncio.create_task(c.receive())
        try:
            await c.device.queue.put(control(c, type='gobot_host_mute', muted=False))
            await until(lambda: any(m['type'] == 'mute' for m in messages(c.brain)))
            assert not c.muted and not c.forward and c.ring.cursor is None
            sent = messages(c.brain)
            assert len(sent) == 1 and sent[0]['type'] == 'mute' and sent[0]['muted'] is False
            assert sent[0]['request_id'] == c.latest_physical_mute_request
            await c.device.queue.put(control(c, type='gobot_host_touch', action='activate',
                event_id='tap-unmute', stream_epoch='capture', detector_sample=0))
            await until(lambda: any(m['type'] == 'wake' for m in messages(c.brain)))
            assert not c.forward
            assert next(m for m in messages(c.brain) if m['type'] == 'wake')['trigger'] == 'touch'
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            await finish_tasks(c)
    asyncio.run(run())


def test_short_tap_in_listening_cancels_capture_without_submitting_it():
    async def run():
        c = connection()
        c.cloud_ready.set()
        c.ring.begin({'wake_id': 'open-question', 'stream_epoch': 'capture', 'detector_sample': 0},
            pre_roll_seconds=0.)
        c.forward = True
        c.stats.update(voice_phase='listening', input_open=True)
        receiver = asyncio.create_task(c.receive())
        try:
            await c.device.queue.put(control(c, type='gobot_host_touch', action='stop', gesture='tap',
                event_id='tap-stop', interrupt_requested=True))
            stop = await stop_command(c)
            assert not c.forward and c.ring.blocked
            c.interrupt_quiet_receipt({'event_id': 'tap-stop', 'stream_epoch': 'capture', 'sample_floor': 0})
            await c.cloud_event({'type': 'stopped', 'data': {'request_id': stop['request_id']}})
            await until(lambda: c.pending_interrupt is None)
            assert not c.muted and not c.forward and c.ring.cursor is None
            assert not any(m['type'] in {'wake', 'commit'} for m in messages(c.brain))
            assert next(m for m in messages(c.device) if m['type'] == 'gobot_host_interrupt_complete')['outcome'] == 'ready'
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            await finish_tasks(c)
    asyncio.run(run())


def test_second_short_tap_cancels_pending_listen_without_second_stop_task():
    async def run():
        c = connection()
        c.cloud_ready.set()
        c.device_activation({'wake_id': 'first-tap', 'stream_epoch': 'capture', 'detector_sample': 0},
            trigger='touch', control={'interrupt_requested': True})
        stop = await stop_command(c)
        intent = c.pending_interrupt
        receiver = asyncio.create_task(c.receive())
        try:
            await c.device.queue.put(control(c, type='gobot_host_touch', action='stop', gesture='tap',
                event_id='first-tap', interrupt_requested=True))
            await until(lambda: intent['wake'] is None)
            assert c.pending_interrupt is intent
            c.interrupt_quiet_receipt({'event_id': 'first-tap', 'stream_epoch': 'capture', 'sample_floor': 0})
            await c.cloud_event({'type': 'stopped', 'data': {'request_id': stop['request_id']}})
            await until(lambda: c.pending_interrupt is None)
            assert not c.forward and c.ring.cursor is None
            assert [m['type'] for m in messages(c.brain) if m['type'] != 'telemetry'] == ['stop']
        finally:
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)
            await finish_tasks(c)
    asyncio.run(run())
