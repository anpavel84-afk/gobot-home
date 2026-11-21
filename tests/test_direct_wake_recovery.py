"""A provider gap must not destroy an authenticated physical capture pipe.

Exercise the real DirectSession, WS API and Gateway using local ledgers and the
existing in-memory provider. No provider, CLI or device network calls occur.
"""
import asyncio
import json

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from gobot.realtime_ws_api import attach_brain_direct_voice
from test_realtime_ws import cleanup, offer, setup
from test_sophia_gateway import connection


TOKEN = 'x' * 48


async def lose_provider(session):
    await session.ws.close()
    await asyncio.wait_for(asyncio.shield(session.reader), 1)
    # Hold the existing empty-transport recovery scheduler until the test
    # explicitly releases it. A physical wake must not reset this schedule.
    session._reconnect_after = float('inf')
    assert not session.ready and session.attached and not session.closed


def receive_kind(ws, kind):
    for _ in range(32):
        event = ws.receive_json()
        if event['type'] == kind:
            return event
    raise AssertionError('expected_event_not_received:' + kind)


def assert_no_generation(board, provider):
    assert board.budget.status()['sessions_reserved'] == 0
    assert not any(event['type'] in {'response.create', 'input_audio_buffer.append'}
                   for socket in provider.sockets for event in socket.sent)


def test_provider_gap_refuses_wake_keeps_controls_and_requires_fresh_activation(tmp_path, settings):
    original, board, manager, provider = setup(tmp_path, settings)
    app = FastAPI()

    async def auth(request: Request):
        if request.headers.get('authorization') != 'Bearer ' + TOKEN:
            raise HTTPException(401)

    attach_brain_direct_voice(app, None, manager, auth, TOKEN)
    headers = {'Authorization': 'Bearer ' + TOKEN}
    offered = offer()
    gateway = connection()
    with TestClient(app) as client:
        try:
            with pytest.raises(WebSocketDisconnect) as denied_auth:
                with client.websocket_connect('/api/v1/voice-ws/stream'):
                    pass
            assert denied_auth.value.code == 1008
            assert not manager.sessions and not provider.sockets
            with client.websocket_connect('/api/v1/voice-ws/stream', headers=headers) as ws:
                ws.send_json({'type': 'hello', 'source': 'device', 'offer': offered.model_dump()})
                assert ws.receive_json()['type'] == 'transport_attached'
                receive_kind(ws, 'ready')
                session = manager.sessions[offered.session_id]
                returns = []
                wake = session.wake

                async def observed_wake(*args, **kwargs):
                    value = await wake(*args, **kwargs)
                    returns.append(value)
                    return value

                session.wake = observed_wake
                client.portal.call(lose_provider, session)
                receive_kind(ws, 'transport_disconnected')
                epoch = session._input_gate_epoch
                assert gateway.ring.begin({'wake_id': 'gap-wake', 'stream_epoch': 'capture',
                                           'detector_sample': 0})
                gateway.stats['generation_allowed'] = True
                ws.send_json({'type': 'wake', 'wake_id': 'gap-wake', 'trigger': 'wake_word'})
                denied = receive_kind(ws, 'admission_denied')
                assert returns == [{'accepted': False, 'reason': 'transport_unavailable',
                                    'input_open': False, 'mode': 'fast'}]
                assert denied['data']['reason'] == 'transport_unavailable'
                assert denied['data']['generation_allowed'] is True
                assert denied['data']['input_open'] is False
                assert denied['data']['automatic_retry'] is False
                assert session._input_gate_epoch == epoch
                assert session._reconnect_after == float('inf')
                assert not session.input_open and session.operation_id is None
                assert not session._admission_attempts and session._stt_reservation is None
                assert len(provider.sockets) == 1
                assert_no_generation(board, provider)

                # The real denial closes only the unadmitted Gateway cursor.
                client.portal.call(gateway.cloud_event, denied)
                assert gateway.ring.cursor is None and not gateway.forward
                assert not gateway.ring.blocked and not gateway.closed
                assert gateway.stats['generation_allowed'] is True
                assert gateway.stats['last_error'] == 'transport_unavailable'
                assert not gateway.brain.sent
                controls = [json.loads(raw) for raw in gateway.device.sent]
                assert [c['state'] for c in controls if c['type'] == 'gobot_host_state'] == ['ready']

                # These controls traverse the same actual WS after the denial.
                ws.send_bytes(bytes(4800))
                ws.send_json({'type': 'ping'})
                assert receive_kind(ws, 'pong')['type'] == 'pong'
                ws.send_json({'type': 'stop', 'request_id': 'during-provider-gap'})
                assert receive_kind(ws, 'stopped')['data']['request_id'] == 'during-provider-gap'
                status = client.get('/api/v1/voice-ws/status', headers=headers,
                                    params={'source': 'device', 'device_id': 'board'}).json()
                live = status['sessions'][0]
                assert live['capture_connected'] and live['lifecycle']['attached']
                assert not live['ready'] and live['state'] == 'disconnected'
                for muted in (True, False):
                    response = client.post('/api/v1/voice-ws/control', headers=headers,
                                           json={'source': 'device', 'device_id': 'board',
                                                 'action': 'mute', 'muted': muted})
                    assert response.status_code == 200
                    assert receive_kind(ws, 'muted')['data']['muted'] is muted
                assert session._duplex_attached and session.detached_at is None
                assert_no_generation(board, provider)

                # Only the existing empty-transport maintenance path recovers.
                client.portal.call(setattr, session, '_reconnect_after', 0.)
                recovered = receive_kind(ws, 'ready')
                assert recovered['data']['recovered'] is True
                assert recovered['data']['lost_input_replayed'] is False
                assert len(provider.sockets) == 2 and session.ready
                assert not session.input_open and session.operation_id is None
                client.portal.call(gateway.cloud_event, recovered)
                assert gateway.stats['last_error'] is None
                assert gateway.ring.cursor is None and not gateway.forward
                assert not gateway.brain.sent
                ws.send_json({'type': 'wake', 'wake_id': 'gap-wake', 'trigger': 'wake_word'})
                ws.send_json({'type': 'ping'})
                receive_kind(ws, 'pong')
                assert returns[-1] == {'accepted': False, 'duplicate': True}
                assert_no_generation(board, provider)

                ws.send_json({'type': 'wake', 'wake_id': 'fresh-wake', 'trigger': 'wake_word'})
                receive_kind(ws, 'listening')
                assert receive_kind(ws, 'wake_accepted')['data']['wake_id'] == 'fresh-wake'
                assert returns[-1]['accepted'] is True
                ws.send_json({'type': 'wake', 'wake_id': 'fresh-wake', 'trigger': 'wake_word'})
                ws.send_json({'type': 'ping'})
                receive_kind(ws, 'pong')
                assert returns[-1] == {'accepted': False, 'duplicate': True}
                assert board.budget.status()['sessions_reserved'] == 1
                assert sum(event['type'] == 'wake_accepted' for event in session.events) == 1
                assert not any(event['type'] in {'response.create', 'input_audio_buffer.append'}
                               for socket in provider.sockets for event in socket.sent)
        finally:
            client.portal.call(cleanup, original, board, manager)


@pytest.mark.parametrize('last_error,recovered', [
    ('transport_unavailable', False),
    ('transport_unavailable', 1),
    ('physical_playback_capture_floor_missing', True),
], ids=['ordinary-ready', 'nonboolean-recovery', 'unrelated-error'])
def test_ready_does_not_clear_unconfirmed_or_unrelated_failure(last_error, recovered):
    async def run():
        gateway = connection()
        gateway.stats['last_error'] = last_error
        await gateway.cloud_event({'type': 'ready', 'data': {
            'generation_allowed': True, 'recovered': recovered}})
        assert gateway.stats['last_error'] == last_error
        assert not gateway.forward and not gateway.brain.sent
    asyncio.run(run())


@pytest.mark.parametrize('flags,arguments,error,code', [
    ({'closed': True}, {}, ValueError, 'cloud_not_ready'),
    ({'attached': False}, {}, ValueError, 'cloud_not_ready'),
    ({'muted': True}, {}, PermissionError, 'microphone_muted'),
    ({'_stop_count': 1}, {}, PermissionError, 'voice_stopping'),
    ({'input_open': True}, {}, ValueError, 'conversation_busy'),
    ({}, {'wake_id': None}, ValueError, 'invalid_wake_id'),
    ({}, {'source': 'browser'}, PermissionError, 'microphone_source_mismatch'),
    ({}, {'trigger': 'unknown'}, ValueError, 'invalid_voice_activation_trigger'),
    ({}, {'mode': {'invalid': True}}, ValueError, 'invalid_voice_mode'),
    ({}, {'capture': {'stream_epoch': 'capture'}}, ValueError, 'invalid_wake_capture_anchor'),
], ids=['closed', 'detached', 'muted', 'stopping', 'busy', 'bad-id',
        'wrong-source', 'bad-trigger', 'bad-mode', 'bad-capture'])
def test_provider_gap_does_not_relax_other_activation_gates(tmp_path, settings, flags, arguments, error, code):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        session = None
        previous = {}
        try:
            session = await manager.accept(offer())
            await lose_provider(session)
            previous = {key: getattr(session, key) for key in flags}
            for key, value in flags.items():
                setattr(session, key, value)
            before = len(session.events)
            with pytest.raises(error, match='^' + code + '$'):
                await session.wake(**{'wake_id': 'rejected-wake', 'trigger': 'wake_word', **arguments})
            assert 'rejected-wake' not in session.seen_wakes
            assert not any(e['type'] == 'admission_denied' for e in list(session.events)[before:])
            assert_no_generation(board, provider)
            assert len(provider.sockets) == 1
        finally:
            if session is not None:
                for key, value in previous.items():
                    setattr(session, key, value)
            await cleanup(original, board, manager)
    asyncio.run(run())
