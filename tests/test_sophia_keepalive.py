"""Keep installed V4's application control channel alive during long idle.

The fixture below models the pinned firmware's asymmetric guards: HostControl
requires recent inbound application data; SendAudio only needs a connected
socket; WebSocket Ping/Pong does not refresh the application-data timestamp.
It is protocol regression evidence, not physical/acoustic acceptance.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

from test_sophia_gateway import Socket, connection
import sophia_connection


class LegacyIdleBoard(Socket):
    def __init__(self, clock, *, timeout=120):
        super().__init__()
        self.clock, self.timeout = clock, timeout
        self.last_application_data = clock.now
        self.connected = True
        self.phase = 'ready'
        self.pings = self.pcm_packets = 0

    async def send(self, item):
        # Actual installed OnData advances last_incoming_time_ for the scoped
        # unknown gobot_host_* no-op, without a HostOnControl phase transition.
        message = json.loads(item)
        assert set(message) == {'type', 'session_id', 'epoch'}
        assert message['type'] == 'gobot_host_keepalive'
        self.last_application_data = self.clock.now
        self.sent.append(message)

    def ping_and_send_pcm(self):
        self.pings += 1
        if self.connected:
            self.pcm_packets += 1

    def can_send_control(self):
        # Pinned Protocol::IsTimeout truncates to seconds, then compares >120.
        return self.connected and int(self.clock.now-self.last_application_data) <= self.timeout


def test_long_idle_without_application_data_suppresses_controls_but_keepalive_preserves_them(monkeypatch):
    async def run():
        clock = SimpleNamespace(now=0.)
        old = LegacyIdleBoard(clock)
        clock.now = 120.999
        assert old.can_send_control()
        clock.now = 121
        assert not old.can_send_control()
        clock.now = 0.
        for _ in range(61):
            clock.now += 5
            old.ping_and_send_pcm()
        assert old.pcm_packets == old.pings == 61
        assert not old.can_send_control()  # The owner's failure, despite live PCM/Ping.

        clock.now = 0.
        c = connection()
        c.device = board = LegacyIdleBoard(clock)
        monkeypatch.setattr(sophia_connection, 'time', SimpleNamespace(monotonic=lambda: clock.now))
        actual_sleep = asyncio.sleep
        samples = []
        c.on_status = lambda: samples.append((clock.now, board.can_send_control()))

        async def advance(delay):
            assert delay == 5
            board.ping_and_send_pcm()
            if clock.now >= 300:
                raise asyncio.CancelledError
            clock.now += delay
            await actual_sleep(0)

        monkeypatch.setattr(sophia_connection.asyncio, 'sleep', advance)
        with pytest.raises(asyncio.CancelledError):
            await c.status_tick()
        assert len(samples) == 61 and all(allowed for _, allowed in samples)
        assert board.can_send_control() and board.phase == 'ready'
        assert c.stats['application_keepalives_sent'] == 61
        assert c.stats['last_application_keepalive_monotonic'] == 300
        assert c.stats['device_control_age_seconds'] is None
        assert c.brain.sent == [] and c.ring.cursor is None and not c.forward
        assert c.stats['wake_events'] == c.stats['downlink_packets'] == 0
        assert not c.stats['input_open']
    asyncio.run(run())


def test_keepalive_cannot_split_metadata_opus_pair_or_change_active_phase():
    async def run():
        c = connection()
        started, release, heartbeat = asyncio.Event(), asyncio.Event(), asyncio.Event()
        original_send = c.device.send

        async def blocked_send(item):
            await original_send(item)
            if isinstance(item, str) and json.loads(item)['type'] == 'gobot_host_output_frame':
                started.set()
                await release.wait()
            elif isinstance(item, str) and json.loads(item)['type'] == 'gobot_host_keepalive':
                heartbeat.set()

        c.device.send = blocked_send
        c.forward = True
        c.stats.update(input_open=True, voice_phase='listening')
        c.ring.begin({'wake_id': 'one', 'stream_epoch': 'capture', 'detector_sample': 0})
        cursor = c.ring.cursor
        output = c.output = {'response_id': 'existing-owner'}
        audio = asyncio.create_task(c.send({'type': 'gobot_host_output_frame'}, b'opus'))
        await started.wait()
        ticking = asyncio.create_task(c.status_tick())
        await asyncio.sleep(0)
        assert not heartbeat.is_set()
        release.set()
        await audio
        await asyncio.wait_for(heartbeat.wait(), 1)
        ticking.cancel()
        with pytest.raises(asyncio.CancelledError):
            await ticking
        sent = c.device.sent
        assert json.loads(sent[0])['type'] == 'gobot_host_output_frame'
        assert sent[1] == b'opus'
        assert json.loads(sent[2])['type'] == 'gobot_host_keepalive'
        assert c.forward and c.stats['input_open'] and c.stats['voice_phase'] == 'listening'
        assert c.ring.cursor is cursor and c.output is output and c.brain.sent == []
    asyncio.run(run())


def test_failed_keepalive_exits_core_loop_and_closes_all_connection_tasks():
    async def run():
        c = connection()
        cancelled = set()

        async def parked(name):
            try:
                await asyncio.Future()
            finally:
                cancelled.add(name)

        c.receive = lambda: parked('device')
        c.uplink = lambda: parked('uplink')
        c.cloud = lambda: parked('brain')
        original_send = c.device.send

        async def failed_send(item):
            if json.loads(item)['type'] == 'gobot_host_keepalive':
                raise ConnectionError('closed socket')
            await original_send(item)

        c.device.send = failed_send
        await c.device.queue.put(json.dumps({'type': 'gobot_host_ready_ack', 'protocol': 2,
            'session_id': c.transport, 'epoch': c.epoch, 'frame_samples': 960,
            'pcm_stage': 'pre_afe', 'stream_epoch': 'capture', 'sample_start': 0}))
        hello = {'host_stream': {'version': 2, 'local_wake_enabled': True,
                                'capture': 'continuous', 'pcm_stage': 'pre_afe'}}
        with pytest.raises(ConnectionError, match='closed socket'):
            await c.run(c.device, hello, lambda _: True)
        assert cancelled == {'device', 'uplink', 'brain'}
        assert c.closed and not c.forward and not c.stats['cloud_ready']
        assert not c.stats['input_open'] and not c.stats['device_protocol_confirmed']
        assert c.stats['application_keepalives_sent'] == 0
        assert c.brain.sent == []
    asyncio.run(run())


def test_control_freshness_ignores_audio_metadata_and_rejects_stale_scope(monkeypatch):
    async def run():
        c = connection()
        monkeypatch.setattr(sophia_connection, 'time', SimpleNamespace(monotonic=lambda: 123.))
        envelope = {'session_id': c.transport, 'epoch': c.epoch}
        await c.device.queue.put(json.dumps({**envelope, 'type': 'gobot_host_stats',
                                            'input_blocks': 55, 'private': 'must not persist'}))
        await c.device.queue.put(json.dumps({**envelope, 'type': 'gobot_host_frame'}))
        await c.device.queue.put(json.dumps({**envelope, 'type': 'gobot_host_stats'}))
        with pytest.raises(ValueError, match='sophia_missing_opus_frame'):
            await c.receive()
        assert c.stats['device_control_messages'] == 1
        assert c.stats['last_device_control_monotonic'] == 123
        assert c.stats['device_control_age_seconds'] == 0
        assert 'private' not in json.dumps(c.stats)

        await c.device.queue.put(json.dumps({**envelope, 'epoch': 'stale', 'type': 'gobot_host_stats'}))
        with pytest.raises(ValueError, match='stale_sophia_transport'):
            await c.receive()
        assert c.stats['device_control_messages'] == 1
    asyncio.run(run())
