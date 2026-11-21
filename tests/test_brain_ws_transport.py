"""Actual Brain WS backend on loopback, synthetic bytes, no model providers.

Transport callbacks force a small, deterministic backpressure condition instead
of depending on platform-specific TCP buffer sizes or allocating long audio.
The sockets, ASGI sends, Ping/Pong, auth and closing handshakes remain real.
"""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
import os
from pathlib import Path
import socket
from unittest.mock import patch

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
import pytest
import uvicorn
from uvicorn.protocols.websockets.websockets_sansio_impl import WebSocketsSansIOProtocol
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from gobot.websocket_transport import BrainWebSocketProtocol
from test_unified_voice_api import TOKEN, Session, hello, setup


def worker_arguments(name='brain'):
    """Read the real worker configuration without starting a worker or factory."""
    filename = Path(__file__).resolve().parents[1]/'scripts/manage.py'
    spec = importlib.util.spec_from_file_location('gobot_ws_launcher_fixture', filename)
    module = importlib.util.module_from_spec(spec)
    previous = Path.cwd()
    try:
        spec.loader.exec_module(module)
        with patch.object(uvicorn, 'run') as started:
            module.worker(name)
        assert started.call_count == 1
        return started.call_args.args, started.call_args.kwargs
    finally:
        os.chdir(previous)


async def until(predicate, timeout=3):
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(.005)


@asynccontextmanager
async def loopback(app):
    _, actual = worker_arguments()
    config = uvicorn.Config(app, host='127.0.0.1', port=0, ws=actual['ws'],
        loop='asyncio', lifespan='off', log_level='error', access_log=False,
        ws_max_size=1048576, ws_max_queue=16, ws_per_message_deflate=False,
        ws_ping_interval=None, ws_ping_timeout=None, timeout_graceful_shutdown=1)
    config.load()
    assert config.ws_protocol_class is BrainWebSocketProtocol
    assert issubclass(config.ws_protocol_class, WebSocketsSansIOProtocol)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(('127.0.0.1', 0))
    listener.listen(8)
    listener.setblocking(False)
    address = listener.getsockname()
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        await until(lambda: server.started or task.done())
        if task.done():
            task.result()
        assert server.started
        yield 'ws://127.0.0.1:'+str(address[1]), server
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 3)
        except TimeoutError:
            server.force_exit = True
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
        finally:
            listener.close()


def test_only_brain_worker_selects_supported_sansio_backend():
    for name, port in (('brain', 18781), ('bridge', 18782), ('images', 18784)):
        args, kwargs = worker_arguments(name)
        assert kwargs['host'] == '127.0.0.1' and kwargs['port'] == port
        assert kwargs['factory'] is True and kwargs['server_header'] is False
        assert args == ({'brain': 'gobot.brain:create_app', 'bridge': 'gobot.bridge:create_app',
                         'images': 'gobot.voice_mock:image_app'}[name],)
        assert kwargs.get('ws', 'auto') == (BrainWebSocketProtocol if name == 'brain' else 'auto')


def test_real_brain_route_auth_binary_stop_and_clean_disconnect():
    async def run():
        app, board, browser = setup()
        class CountedSession(Session):
            def __init__(self, offer):
                super().__init__(offer)
                self.binary_sizes = []
            async def append_pcm(self, pcm):
                self.binary_sizes.append(len(pcm))
                return False  # Closed spending gate; no provider or microphone admission.
        async def accept(offer):
            value = board.sessions.setdefault(offer.session_id, CountedSession(offer))
            return value
        board.accept = accept
        async with loopback(app) as (url, server):
            with pytest.raises(InvalidStatus) as denied:
                async with connect(url+'/api/v1/voice-ws/stream', compression=None):
                    pass
            assert denied.value.response.status_code == 403
            assert not board.sessions and not browser.sessions
            async with connect(url+'/api/v1/voice-ws/stream',
                    additional_headers={'Authorization': 'Bearer '+TOKEN},
                    compression=None, ping_interval=None) as client:
                await client.send(json.dumps(hello()))
                attached = json.loads(await asyncio.wait_for(client.recv(), 2))
                assert attached['type'] == 'transport_attached'
                session = board.sessions['session']
                await client.send(bytes(2880))
                await client.send(json.dumps({'type': 'ping'}))
                assert json.loads(await asyncio.wait_for(client.recv(), 2))['type'] == 'pong'
                assert session.binary_sizes == [2880]
                assert not session.generation_allowed()
                await asyncio.wait_for(await client.ping(b'actual-control-ping'), 1)
                await client.send(json.dumps({'type': 'stop'}))
                assert json.loads(await asyncio.wait_for(client.recv(), 2))['type'] == 'stopped'
            await until(lambda: session.detach_count == 1)
            assert session._duplex_attached is False
            assert not browser.sessions
    asyncio.run(run())


@pytest.mark.parametrize('frame', [b'\x00', bytes(48002)],
                         ids=['odd-byte', 'oversized-frame'])
def test_real_brain_route_keeps_pcm_frame_bounds(frame):
    async def run():
        app, board, _ = setup()
        async with loopback(app) as (url, server):
            async with connect(url+'/api/v1/voice-ws/stream',
                    additional_headers={'Authorization': 'Bearer '+TOKEN},
                    compression=None, ping_interval=None) as client:
                await client.send(json.dumps(hello()))
                assert json.loads(await client.recv())['type'] == 'transport_attached'
                await client.send(frame)
                error = json.loads(await asyncio.wait_for(client.recv(), 2))
                assert error == {'type': 'error', 'data': {'code': 'invalid_pcm24_frame'}}
                with pytest.raises(ConnectionClosed):
                    await asyncio.wait_for(client.recv(), 2)
            assert board.sessions['session'].received_pcm == 0
    asyncio.run(run())


def pressure_app():
    app = FastAPI()
    state = {'entered': asyncio.Event(), 'finished': asyncio.Event(), 'sent': False,
             'disconnected': False, 'errors': []}
    @app.websocket('/pressure')
    async def stream(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text('ready')
        await websocket.receive_text()
        state['entered'].set()
        try:
            await websocket.send_bytes(b'synthetic-bounded-audio')
            state['sent'] = True
            await websocket.receive_text()
        except WebSocketDisconnect:
            state['disconnected'] = True
        except Exception as error:
            state['errors'].append(type(error).__name__)
        finally:
            state['finished'].set()
    return app, state


def websocket_protocol(server):
    matches = [value for value in server.server_state.connections
               if isinstance(value, WebSocketsSansIOProtocol)]
    assert len(matches) == 1
    return matches[0]


def test_paused_audio_send_keeps_control_pong_live_then_resumes_exact_bytes():
    async def run():
        app, state = pressure_app()
        async with loopback(app) as (url, server):
            async with connect(url+'/pressure', compression=None, ping_interval=None) as client:
                assert await client.recv() == 'ready'
                protocol = websocket_protocol(server)
                protocol.pause_writing()  # Deterministic transport high-water callback.
                assert not protocol.writable.is_set(), 'ASGI audio must honor transport backpressure'
                try:
                    await client.send('send bounded audio')
                    await asyncio.wait_for(state['entered'].wait(), 1)
                    await asyncio.sleep(0)
                    assert not state['sent'] and not state['finished'].is_set()
                    # This Pong is generated by the real protocol concurrently
                    # with the blocked ASGI writer, the failing legacy boundary.
                    await asyncio.wait_for(await client.ping(b'while-audio-paused'), 1)
                    assert not state['sent'] and not state['errors']
                finally:
                    protocol.resume_writing()
                assert protocol.writable.is_set()
                assert await asyncio.wait_for(client.recv(), 1) == b'synthetic-bounded-audio'
            await asyncio.wait_for(state['finished'].wait(), 1)
            assert state['sent'] and state['disconnected'] and not state['errors']
    asyncio.run(run())


@pytest.mark.parametrize('abrupt', [False, True])
def test_peer_close_releases_paused_asgi_writer_without_assert_or_hanging(abrupt):
    async def run():
        app, state = pressure_app()
        async with loopback(app) as (url, server):
            async with connect(url+'/pressure', compression=None, ping_interval=None) as client:
                assert await client.recv() == 'ready'
                protocol = websocket_protocol(server)
                protocol.pause_writing()
                assert not protocol.writable.is_set(), 'ASGI audio must honor transport backpressure'
                await client.send('send bounded audio')
                await asyncio.wait_for(state['entered'].wait(), 1)
                assert not state['sent']
                if abrupt:
                    client.transport.abort()
                    await client.wait_closed()
                else:
                    await client.close(code=1000)
            # asyncio doesn't call resume_writing after a lost paused transport.
            # The protocol must release this waiter itself on connection_lost.
            await asyncio.wait_for(state['finished'].wait(), 1)
            assert protocol._gobot_disconnected and protocol.writable.is_set()
            assert state['disconnected'] and not state['sent'] and not state['errors']
    asyncio.run(run())
