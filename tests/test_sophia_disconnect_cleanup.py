"""Brain loss clears physical output while the real receipt reader is alive.

Only synthetic bytes and in-memory device/Brain sockets; no provider calls.
"""
import asyncio
import base64
import json
import time

import pytest

from test_sophia_gateway import Socket, connection
import sophia_connection


class Brain(Socket):
    def __init__(self):
        super().__init__()
        self.disconnected = asyncio.Event()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        self.disconnected.set()

    def __aiter__(self):
        return self

    async def __anext__(self):
        event = await self.queue.get()
        if event is None:
            raise StopAsyncIteration
        if isinstance(event, Exception):
            raise event
        return event

    async def wait_closed(self):
        await self.disconnected.wait()

    def emit(self, kind, **data):
        self.queue.put_nowait(json.dumps({'type': kind, 'data': data}))

    def end(self, error=None):
        self.disconnected.set()
        self.queue.put_nowait(error)

    async def send(self, raw):
        await super().send(raw)
        event = json.loads(raw)
        if event['type'] == 'hello':
            self.emit('ready', configuration_confirmed=True, generation_allowed=False)
        elif event['type'] == 'mute':
            self.emit('muted', **{key: event[key] for key in ('muted', 'request_id')})


class Device(Socket):
    def __init__(self, gateway, *, acknowledge=True):
        super().__init__()
        self.gateway = gateway
        self.acknowledge = acknowledge
        self.cancel_sent = asyncio.Event()

    def emit(self, **fields):
        self.queue.put_nowait(json.dumps({'session_id': self.gateway.transport,
            'epoch': self.gateway.epoch, **fields}))

    async def recv(self):
        value = await super().recv()
        if isinstance(value, Exception):
            raise value
        return value

    async def send(self, raw):
        await super().send(raw)
        if not isinstance(raw, str):
            return
        event = json.loads(raw)
        if event['type'] != 'gobot_host_output_cancel':
            return
        self.cancel_sent.set()
        if self.acknowledge:
            owner = {key: event[key] for key in ('response_id', 'playback_id', 'output_epoch')}
            # A completion already in flight must not mark an interrupted
            # answer heard. Only the matching stopped receipt releases it.
            self.emit(type='gobot_host_playback', state='playback_finished',
                whole_response=True, stream_epoch='capture', sample_floor=0, **owner)
            self.emit(type='gobot_host_playback', state='stopped',
                stream_epoch='capture', sample_floor=0,
                **{**owner, 'output_epoch': owner['output_epoch']+1})


def controls(socket):
    return [json.loads(raw) for raw in socket.sent if isinstance(raw, str)]


async def until(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0)


async def start(*, muted=False, acknowledge=True):
    gateway = connection()
    brain = Brain()
    gateway.connector = lambda *args, **kwargs: brain
    gateway.device = device = Device(gateway, acknowledge=acknowledge)
    device.emit(type='gobot_host_ready_ack', protocol=2, frame_samples=960,
        pcm_stage='pre_afe', stream_epoch='capture', sample_start=0,
        muted=muted, mute_revision=4)
    hello = {'host_stream': {'version': 2, 'local_wake_enabled': True,
                            'capture': 'continuous', 'pcm_stage': 'pre_afe'}}
    task = asyncio.create_task(gateway.run(device, hello, lambda _: True))
    await until(lambda: gateway.cloud_ready.is_set() and gateway.latest_physical_mute_request is None)
    return gateway, brain, device, task


async def begin_output(gateway, brain):
    brain.emit('audio_start', response_id='synthetic-response')
    await until(lambda: gateway.output is not None and gateway.output['start_sent'])
    return gateway.output


def assert_ended(gateway, brain):
    assert gateway.closed and gateway.transport_ending
    assert not gateway.forward and not gateway.cloud_ready.is_set()
    assert not gateway.stats['cloud_ready'] and not gateway.stats['input_open']
    assert not gateway.stats['device_protocol_confirmed']
    assert gateway.ring.cursor is None and gateway.ring.blocked
    assert gateway.stats['playback_finished'] == 0
    assert not any(event['type'] in {'playback_finished', 'wake', 'input_end'}
                   for event in controls(brain))
    assert not any(isinstance(raw, bytes) for raw in brain.sent)
    assert not gateway.tasks


@pytest.mark.parametrize('failure', [False, True], ids=['clean_eof', 'connection_failure'])
def test_brain_exit_cancels_with_live_receipt_reader_and_preserves_failure(failure):
    async def run():
        gateway, brain, device, task = await start()
        try:
            output = await begin_output(gateway, brain)
            brain.emit('audio_chunk', response_id='synthetic-response',
                       pcm=base64.b64encode(bytes(2880)).decode())
            await until(lambda: gateway.stats['downlink_packets'] == 1)
            brain.end(ConnectionError('synthetic disconnect') if failure else None)
            if failure:
                with pytest.raises(ConnectionError, match='synthetic disconnect'):
                    await asyncio.wait_for(task, .5)
            else:
                await asyncio.wait_for(task, .5)
            assert_ended(gateway, brain)
            assert gateway.output is None and gateway.output_epoch == 1
            assert gateway.stats['voice_phase'] == 'disconnected'
            assert gateway.stats['output_active_before_cleanup'] is True
            assert gateway.stats['output_cleanup_status'] == 'stopped_receipt'
            assert output['cancel_pending'] and output['cancel_signal'].is_set()
            assert output['metrics'].get('stop_receipt_wall') is not None
            assert output['metrics'].get('whole_finish_receipt_wall') is None
            cancel = [event for event in controls(device) if event['type'] == 'gobot_host_output_cancel']
            assert len(cancel) == 1 and cancel[0]['playback_id'] == output['playback_id']
            assert not any(event['type'] == 'gobot_host_output_end' for event in controls(device))
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


@pytest.mark.parametrize('waiting', ['pacing', 'credit'])
def test_socket_close_interrupts_cloud_chunk_waiting_for_pacing_or_credit(waiting):
    async def run():
        gateway, brain, device, task = await start()
        try:
            output = await begin_output(gateway, brain)
            output.update(seq=8, started_at=time.monotonic()+(30 if waiting == 'pacing' else -30),
                          progress_seen=waiting == 'credit', consumed=0)
            entered = asyncio.Event()
            original_feed = output['encoder'].feed
            def feed(pcm, rate):
                entered.set()
                return original_feed(pcm, rate)
            output['encoder'].feed = feed
            brain.emit('audio_chunk', response_id='synthetic-response',
                       pcm=base64.b64encode(bytes(2880)).decode())
            await entered.wait()
            await asyncio.sleep(0)
            assert not task.done() and not gateway.transport_ending
            brain.end()
            await asyncio.wait_for(task, .5)
            assert_ended(gateway, brain)
            assert output['cancel_signal'].is_set() and gateway.output_credit.is_set()
            assert gateway.output is None and device.cancel_sent.is_set()
            assert gateway.stats['downlink_packets'] == 0
            assert not any(isinstance(raw, bytes) for raw in device.sent)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


@pytest.mark.parametrize('failure', [False, True], ids=['clean_eof', 'connection_failure'])
def test_brain_exit_preserves_physical_mute_and_cannot_reopen_late_audio(failure):
    async def run():
        gateway, brain, device, task = await start(muted=True)
        try:
            brain.end(ConnectionError('synthetic disconnect') if failure else None)
            result = await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), .5)
            if failure:
                assert isinstance(result[0], ConnectionError)
            else:
                assert result == [None]
            assert_ended(gateway, brain)
            assert gateway.muted and gateway.device_mute_revision == 4
            assert gateway.stats['voice_phase'] == 'muted'
            assert gateway.stats['output_cleanup_status'] == 'no_output'
            before = len(device.sent)
            await gateway.cloud_event({'type': 'muted', 'data': {'muted': False}})
            await gateway.cloud_event({'type': 'audio_start', 'data': {'response_id': 'late'}})
            assert gateway.muted and gateway.output is None and len(device.sent) == before
            assert not gateway.device_activation({}, trigger='wake_word', control={})
            assert all(event.get('muted') is not False for event in controls(device)
                       if event['type'] == 'gobot_host_mute')
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


@pytest.mark.parametrize('muted', [True, False], ids=['physical_hold', 'physical_unmute'])
def test_physical_mute_change_during_cancel_is_kept_without_reopening_input(muted):
    async def run():
        gateway, brain, device, task = await start(acknowledge=False)
        try:
            output = await begin_output(gateway, brain)
            brain.end()
            await asyncio.wait_for(device.cancel_sent.wait(), .5)
            device.emit(type='gobot_host_mute', muted=muted, mute_revision=5)
            device.emit(type='gobot_host_touch', action='activate')
            device.emit(type='gobot_host_playback', state='stopped',
                response_id=output['response_id'], playback_id=output['playback_id'],
                output_epoch=output['output_epoch']+1, stream_epoch='capture', sample_floor=0)
            await asyncio.wait_for(task, .5)
            assert_ended(gateway, brain)
            assert gateway.muted is muted and gateway.device_mute_revision == 5
            assert gateway.stats['voice_phase'] == ('muted' if muted else 'disconnected')
            assert gateway.stats['output_cleanup_status'] == 'stopped_receipt'
            assert gateway.output is None
            assert len([event for event in controls(brain) if event['type'] == 'mute']) == 1
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_missing_stop_receipt_is_bounded_and_never_claims_physical_completion(monkeypatch):
    monkeypatch.setattr(sophia_connection, 'TRANSPORT_OUTPUT_CANCEL_SECONDS', .03)
    async def run():
        gateway, brain, device, task = await start(acknowledge=False)
        try:
            output = await begin_output(gateway, brain)
            brain.end()
            await asyncio.wait_for(task, .5)
            assert_ended(gateway, brain)
            assert device.cancel_sent.is_set() and gateway.output is output
            assert gateway.stats['output_cleanup_status'] == 'unconfirmed'
            assert gateway.stats['voice_phase'] == 'disconnected'
            assert output['metrics'].get('stop_receipt_wall') is None
            assert output['cancel_pending'] and gateway.output_epoch == 0
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())


def test_dead_device_reader_uses_transport_close_fallback_without_waiting_for_ack():
    async def run():
        gateway, brain, device, task = await start()
        try:
            output = await begin_output(gateway, brain)
            device.queue.put_nowait(ConnectionError('synthetic device lost'))
            with pytest.raises(ConnectionError, match='synthetic device lost'):
                await asyncio.wait_for(task, .5)
            assert_ended(gateway, brain)
            assert gateway.stats['output_cleanup_status'] == 'receiver_unavailable'
            assert gateway.stats['voice_phase'] == 'disconnected'
            assert gateway.output is output and output['cancel_pending']
            assert not device.cancel_sent.is_set()
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(run())
