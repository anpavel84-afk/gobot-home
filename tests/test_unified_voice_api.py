import asyncio
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from gobot.realtime_ws_api import attach_brain_direct_voice


TOKEN = 'x'*48


class Session:
    def __init__(self, offer):
        self.offer = offer
        self.id = offer.session_id
        self.closed = False
        self.ready = True
        self.state = 'ready'
        self.selected_mode = 'fast'
        self.muted = False
        self.queue = asyncio.Queue()
        self.detach_count = 0
        self.received_pcm = 0
    def generation_allowed(self):
        return False
    def emit(self, kind, **data):
        self.queue.put_nowait({'type': kind, 'data': data})
    async def next_event(self):
        return await self.queue.get()
    async def wake(self, *args, **kwargs):
        self.emit('admission_denied', reason='board_budget_inactive')
        raise PermissionError('board_budget_inactive')
    async def append_pcm(self, pcm):
        # Exactly the behavior of a closed generation gate.
        return False
    async def detach(self):
        self.detach_count += 1
    async def select_mode(self, mode):
        self.selected_mode = mode
    async def stop(self):
        self.emit('stopped')
    async def mute(self, value):
        self.muted = value


class Manager:
    def __init__(self):
        self.sessions = {}
    async def accept(self, offer):
        session = self.sessions.setdefault(offer.session_id, Session(offer))
        return session
    def status(self):
        return {'budget': {'enabled': False}}


def setup():
    app = FastAPI()
    async def auth(request: Request):
        if request.headers.get('authorization') != 'Bearer '+TOKEN:
            raise HTTPException(401)
    board, browser = Manager(), Manager()
    attach_brain_direct_voice(app, browser, board, auth, TOKEN)
    return app, board, browser


def test_closed_lifecycle_diagnostics_are_bounded_and_exactly_scoped():
    from gobot.realtime_ws import DirectOffer
    app, board, _ = setup()
    board.admission_preview = lambda **kwargs: {'allowed': False, 'generation_allowed': False}
    for index in range(12):
        data = {**hello()['offer'], 'session_id': 'closed-'+str(index)}
        if index == 11: data['client_id'] = 'other-client'
        if index == 10: data['device_id'] = 'other-device'
        session = Session(DirectOffer.model_validate(data))
        session.closed = True
        session.closed_at = index
        session.lifecycle_status = lambda: {'close_reason': 'detached_expired', 'empty_restore_eligible': True}
        board.sessions[session.id] = session
    with TestClient(app) as client:
        result = client.get('/api/v1/voice-ws/status', params={
            'source': 'device', 'device_id': 'board', 'client_id': 'board'},
            headers={'Authorization': 'Bearer '+TOKEN}).json()
        assert result['sessions'] == []
        assert [s['session_id'] for s in result['closed_sessions']] == ['closed-'+str(i) for i in range(9, 1, -1)]
        assert all(s['lifecycle']['empty_restore_eligible'] for s in result['closed_sessions'])
        anonymous = client.get('/api/v1/voice-ws/status', headers={'Authorization': 'Bearer '+TOKEN}).json()
        assert anonymous['closed_sessions'] == []


def test_closed_old_capture_lease_does_not_prevent_manager_authorized_empty_restore():
    from gobot.realtime_ws import DirectOffer
    app, board, _ = setup()
    old = Session(DirectOffer.model_validate(hello()['offer']))
    old.closed = True
    old._duplex_attached = True
    board.sessions[old.id] = old
    async def restore(offer):
        session = Session(offer)
        board.sessions[session.id] = session
        return session
    board.accept = restore  # The real manager owns the tested empty-only admission.
    with TestClient(app) as client:
        with client.websocket_connect('/api/v1/voice-ws/stream', headers={'Authorization': 'Bearer '+TOKEN}) as ws:
            ws.send_json(hello())
            assert ws.receive_json()['type'] == 'transport_attached'
            assert board.sessions[old.id] is not old
            ws.send_json({'type': 'ping'})
            assert ws.receive_json()['type'] == 'pong'


def hello(source='device'):
    return {'type': 'hello', 'source': source, 'offer': {
        'session_id': 'session', 'conversation_id': 'conversation',
        'device_id': 'board', 'client_id': 'board', 'client_kind': 'device',
        'consent': True, 'speak': True}}


def test_denied_paid_wake_keeps_empty_transport_and_status_is_false():
    app, board, _ = setup()
    with TestClient(app) as client:
        with client.websocket_connect('/api/v1/voice-ws/stream', headers={'Authorization': 'Bearer '+TOKEN}) as ws:
            ws.send_json(hello())
            assert ws.receive_json()['type'] == 'transport_attached'
            ws.send_json({'type': 'wake', 'wake_id': 'w1'})
            assert ws.receive_json()['type'] == 'admission_denied'
            ws.send_json({'type': 'ping'})
            assert ws.receive_json()['type'] == 'pong'
            status = client.get('/api/v1/voice-ws/status?source=device&device_id=board',
                                headers={'Authorization': 'Bearer '+TOKEN}).json()
            assert status['sessions'][0]['generation_allowed'] is False
            # A second subscription must not detach the valid microphone lease.
            with client.websocket_connect('/api/v1/voice-ws/stream', headers={'Authorization': 'Bearer '+TOKEN}) as duplicate:
                duplicate.send_json(hello())
                assert duplicate.receive_json()['data']['code'] == 'microphone_source_already_attached'
            assert board.sessions['session'].detach_count == 0
            ws.send_json({'type': 'ping'})
            assert ws.receive_json()['type'] == 'pong'
        assert board.sessions['session'].detach_count == 1


def test_browser_cannot_claim_physical_source_scope():
    app, board, browser = setup()
    with TestClient(app) as client:
        with client.websocket_connect('/api/v1/voice-ws/stream', headers={'Authorization': 'Bearer '+TOKEN}) as ws:
            ws.send_json(hello(source='browser'))
            assert ws.receive_json()['data']['code'] == 'microphone_source_scope_mismatch'
        assert not board.sessions and not browser.sessions


def test_control_only_selected_device_and_unknown_fields_denied():
    app, board, _ = setup()
    with TestClient(app) as client:
        bad = client.post('/api/v1/voice-ws/control', headers={'Authorization': 'Bearer '+TOKEN},
                          json={'source': 'device', 'device_id': 'board', 'action': 'stop', 'policy': {'enabled': True}})
        assert bad.status_code == 422
        assert client.get('/api/v1/voice-ws/status').status_code == 401
