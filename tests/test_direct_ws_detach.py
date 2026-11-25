"""Real direct session/API lifecycle with controllable subscriber I/O.

The provider and subscriber are in-memory fixtures. No model or device calls.
The blocked writes reproduce transport pressure without relying on TCP sizing.
"""
import asyncio
import json

from fastapi import FastAPI
import pytest

from gobot import realtime_ws_api
from test_realtime_ws import cleanup, offer, setup


TOKEN = 'x' * 48


class Subscriber:
    def __init__(self, *, block_kind=None):
        self.headers = {'authorization': 'Bearer ' + TOKEN}
        self.incoming = asyncio.Queue()
        self.sent = []
        self.changed = asyncio.Event()
        self.receiving = asyncio.Event()
        self.blocked = asyncio.Event()
        self.release = asyncio.Event()
        self.block_kind = block_kind
        self.cancelled_sends = []
        self.active_sends = 0
        self.max_active_sends = 0
        self.close_codes = []

    async def accept(self):
        pass

    async def receive_text(self):
        return json.dumps({'type': 'hello', 'source': 'device', 'offer': offer().model_dump()})

    async def receive(self):
        self.receiving.set()
        return await self.incoming.get()

    async def send_json(self, event):
        self.active_sends += 1
        self.max_active_sends = max(self.max_active_sends, self.active_sends)
        try:
            if event['type'] == self.block_kind:
                self.blocked.set()
                await self.release.wait()
            self.sent.append(event)
            self.changed.set()
        except asyncio.CancelledError:
            self.cancelled_sends.append(event['type'])
            raise
        finally:
            self.active_sends -= 1

    async def close(self, code=1000):
        assert not self.active_sends, 'A close cannot race the previous output writer'
        self.close_codes.append(code)

    async def wait_kind(self, kind):
        async with asyncio.timeout(2):
            while True:
                for event in self.sent:
                    if event['type'] == kind:
                        return event
                self.changed.clear()
                await self.changed.wait()

    def disconnect(self):
        self.incoming.put_nowait({'type': 'websocket.disconnect'})


def endpoint(manager):
    app = FastAPI()
    realtime_ws_api.attach_brain_direct_voice(app, None, manager, lambda: None, TOKEN)
    return next(route.endpoint for route in app.routes
                if route.path == '/api/v1/voice-ws/stream')


def no_generation(board, provider):
    assert board.budget.status()['sessions_reserved'] == 0
    assert not any(event['type'] in {'response.create', 'input_audio_buffer.append'}
                   for socket in provider.sockets for event in socket.sent)


async def finish_tasks(tasks):
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize('reason,close_code', [
    ('output_backpressure', 1011), ('transport_disconnected', 1000),
])
def test_internal_detach_wakes_idle_writer_cancels_output_and_releases_capture(
        tmp_path, settings, reason, close_code):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        subscriber = Subscriber()
        task = asyncio.create_task(endpoint(manager)(subscriber))
        try:
            await subscriber.wait_kind('ready')
            session = manager.sessions[offer().session_id]
            await session.publish_audio(bytes(4800), 'synthetic-output')
            await subscriber.wait_kind('audio_chunk')
            assert session._duplex_attached
            await session.detach(reason=reason)
            await asyncio.wait_for(task, 2)
            cancel = [e for e in subscriber.sent if e['type'] == 'audio_cancel']
            assert cancel and cancel[-1]['data']['response_id'] is None
            assert subscriber.close_codes == [close_code]
            assert subscriber.max_active_sends == 1
            assert not session._duplex_attached and not session.attached
            assert session.last_detach_reason == reason
            assert session.ready and not session.closed
            assert session.output_response is None
            assert not any(e['type'] == 'playback_finished' for e in subscriber.sent)
            no_generation(board, provider)
        finally:
            await finish_tasks([task])
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_queue_overflow_cancels_blocked_writer_and_closes_physical_subscriber(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        subscriber = Subscriber(block_kind='ready')
        task = asyncio.create_task(endpoint(manager)(subscriber))
        try:
            await asyncio.wait_for(subscriber.blocked.wait(), 2)
            session = manager.sessions[offer().session_id]
            # No consumer can drain this queue while its ASGI write is stalled.
            while not session.outgoing.full():
                session.emit('telemetry', event='synthetic_queue_pressure')
            session.emit('telemetry', event='synthetic_queue_overflow')
            await asyncio.wait_for(task, 2)
            assert subscriber.cancelled_sends == ['ready']
            assert subscriber.close_codes == [1011]
            assert subscriber.max_active_sends == 1
            assert [e['type'] for e in subscriber.sent][-1] == 'audio_cancel'
            assert session.last_detach_reason == 'output_backpressure'
            assert not session._duplex_attached and not session.attached
            assert session.ready and not session.closed
            no_generation(board, provider)
        finally:
            subscriber.release.set()
            await finish_tasks([task])
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_stalled_cancellation_frame_does_not_prevent_close(tmp_path, settings, monkeypatch):
    monkeypatch.setattr(realtime_ws_api, '_TERMINAL_SEND_TIMEOUT', .01)

    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        subscriber = Subscriber(block_kind='audio_cancel')
        task = asyncio.create_task(endpoint(manager)(subscriber))
        try:
            await subscriber.wait_kind('ready')
            session = manager.sessions[offer().session_id]
            await session.detach(reason='output_backpressure')
            await asyncio.wait_for(task, 1)
            assert subscriber.cancelled_sends == ['audio_cancel']
            assert subscriber.close_codes == [1011]
            assert not session._duplex_attached
            assert subscriber.max_active_sends == 1
            no_generation(board, provider)
        finally:
            subscriber.release.set()
            await finish_tasks([task])
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('previous_detach', [None, 'output_backpressure'])
def test_logical_close_cancels_blocked_writer_and_sends_terminal_browser_event(
        tmp_path, settings, previous_detach):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        subscriber = Subscriber(block_kind='ready')
        task = asyncio.create_task(endpoint(manager)(subscriber))
        try:
            await asyncio.wait_for(subscriber.blocked.wait(), 2)
            session = manager.sessions[offer().session_id]
            session.last_detach_reason = previous_detach
            result = await manager.close(session.id, session.offer.device_id,
                session.offer.client_id, session.offer.profile_epoch, 'closed')
            await asyncio.wait_for(task, 1)
            assert result == {'closed': True, 'hangup_confirmed': True}
            assert subscriber.cancelled_sends == ['ready']
            assert [e['type'] for e in subscriber.sent][-2:] == ['audio_cancel', 'closed']
            assert not any(e['type'] == 'error' for e in subscriber.sent)
            assert subscriber.close_codes == [1000]
            assert subscriber.max_active_sends == 1
            assert session.closed and not session._duplex_attached
            assert session.close_reason == 'closed'
            assert session.last_detach_reason == previous_detach
            assert provider.sockets[0].closed
            with pytest.raises(ValueError, match='logical_conversation_closed'):
                await manager.accept(offer())
            no_generation(board, provider)
        finally:
            subscriber.release.set()
            await finish_tasks([task])
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_old_cleanup_holds_capture_lease_until_detach_finishes_then_reattaches(
        tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        serve = endpoint(manager)
        first = Subscriber()
        tasks = [asyncio.create_task(serve(first))]
        release_detach = asyncio.Event()
        try:
            await first.wait_kind('ready')
            session = manager.sessions[offer().session_id]
            old_signal = session.subscriber_detached
            detach_started = asyncio.Event()
            send = session.send

            async def held_clear(event, **kwargs):
                if event['type'] == 'input_audio_buffer.clear':
                    detach_started.set()
                    await release_detach.wait()
                return await send(event, **kwargs)

            session.send = held_clear
            first.disconnect()
            await asyncio.wait_for(detach_started.wait(), 1)
            assert not session.attached and old_signal.is_set()
            assert session._duplex_attached

            # A racing reconnect must be rejected before manager.accept can
            # attach it. Old cleanup still owns the capture lease.
            duplicate = Subscriber()
            tasks.append(asyncio.create_task(serve(duplicate)))
            await asyncio.wait_for(tasks[-1], 1)
            error = await duplicate.wait_kind('error')
            assert error['data']['code'] == 'microphone_source_already_attached'
            assert session._duplex_attached and not session.attached
            assert not tasks[0].done()

            release_detach.set()
            await asyncio.wait_for(tasks[0], 1)
            assert not session._duplex_attached
            recovered = Subscriber()
            tasks.append(asyncio.create_task(serve(recovered)))
            ready = await recovered.wait_kind('ready')
            assert ready['data']['recovered'] is True
            assert manager.sessions[session.id] is session
            assert session._duplex_attached and session.attached
            assert session.subscriber_detached is not old_signal
            assert not session.subscriber_detached.is_set()
            assert len(provider.sockets) == 1
            recovered.disconnect()
            await asyncio.wait_for(tasks[-1], 1)
            no_generation(board, provider)
        finally:
            release_detach.set()
            await finish_tasks(tasks)
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_real_paused_asgi_output_overflow_closes_socket_and_reclaims_capture(
        tmp_path, settings, monkeypatch):
    from websockets.asyncio.client import connect
    from websockets.exceptions import ConnectionClosed

    from gobot.websocket_transport import BrainWebSocketProtocol
    from test_brain_ws_transport import loopback, until, websocket_protocol

    # Keep the real protocol pause/resume implementation. Shorten only the
    # terminal grace periods; the transport stays paused through cancellation.
    monkeypatch.setattr(realtime_ws_api, '_TERMINAL_SEND_TIMEOUT', .01)
    monkeypatch.setattr(realtime_ws_api, '_TERMINAL_CLOSE_TIMEOUT', .01)

    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        app = FastAPI()
        realtime_ws_api.attach_brain_direct_voice(app, None, manager, lambda: None, TOKEN)
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        protocol_send = BrainWebSocketProtocol.send

        async def observed_send(protocol, message):
            audio_start = (message['type'] == 'websocket.send' and
                           json.loads(message.get('text', '{}')).get('type') == 'audio_start')
            if audio_start:
                entered.set()
            try:
                await protocol_send(protocol, message)
            except asyncio.CancelledError:
                if audio_start:
                    cancelled.set()
                raise

        monkeypatch.setattr(BrainWebSocketProtocol, 'send', observed_send)
        headers = {'Authorization': 'Bearer ' + TOKEN}
        greeting = json.dumps({'type': 'hello', 'source': 'device', 'offer': offer().model_dump()})

        async def ready(client):
            for _ in range(16):
                event = json.loads(await asyncio.wait_for(client.recv(), 2))
                if event['type'] == 'ready':
                    return event
            raise AssertionError('No ready event on the actual socket')

        try:
            async with loopback(app) as (url, server):
                async with connect(url + '/api/v1/voice-ws/stream', additional_headers=headers,
                                   compression=None, ping_interval=None) as client:
                    await client.send(greeting)
                    await ready(client)
                    session = manager.sessions[offer().session_id]
                    protocol = websocket_protocol(server)
                    protocol.pause_writing()
                    await session.publish_audio(bytes(4800), 'synthetic-paused-output')
                    await asyncio.wait_for(entered.wait(), 1)
                    assert not protocol.writable.is_set()
                    while not session.outgoing.full():
                        session.emit('telemetry', event='synthetic_queue_pressure')
                    session.emit('telemetry', event='synthetic_queue_overflow')
                    await asyncio.wait_for(cancelled.wait(), 1)

                    # Even cancel and close frames cannot pass this paused
                    # transport. Returning from bounded ASGI cleanup closes TCP;
                    # it must not strand the Gateway's old physical output.
                    async with asyncio.timeout(2):
                        while True:
                            try:
                                event = json.loads(await client.recv())
                                assert event['type'] not in {'audio_start', 'audio_chunk'}
                            except ConnectionClosed:
                                break
                    assert client.close_code == 1006  # Close frame was also blocked.
                    await until(lambda: not session._duplex_attached)
                    assert protocol._gobot_disconnected and protocol.writable.is_set()
                    assert session.last_detach_reason == 'output_backpressure'

                async with connect(url + '/api/v1/voice-ws/stream', additional_headers=headers,
                                   compression=None, ping_interval=None) as recovered:
                    await recovered.send(greeting)
                    event = await ready(recovered)
                    assert event['data']['recovered'] is True
                    assert manager.sessions[session.id] is session
                    assert session._duplex_attached and session.attached
                    assert session.output_response is None and not session.input_open
                    assert len(provider.sockets) == 1
                    no_generation(board, provider)
                await until(lambda: not session._duplex_attached)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
