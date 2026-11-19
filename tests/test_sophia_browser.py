"""Offline browser boundary/lifecycle tests. No network, provider or microphone."""
import asyncio
import base64
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from gobot.device_store import DeviceStore
from gobot.realtime_ws_api import attach_brain_direct_voice
from gobot.sophia_panel import (BROWSER_COOKIE, BROWSER_COOKIE_AGE, BROWSER_COOKIE_PURPOSE,
    BROWSER_HOST, BrowserPlaybackCredit, attach_sophia_panel, browser_cookie_token, browser_guest_binding)

ORIGIN = 'https://plan.tailffc57c.ts.net'
HELLO = dict(type='hello', session_id='browser-session-1', conversation_id='browser-conversation-1',
             mode='fast', consent=True)


class Upstream:
    def __init__(self):
        self.messages = []
        self.bytes = 0
        self.queue = asyncio.Queue()
        self.tone = False
        self.late_tone = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.queue.get()

    async def emit(self, kind, **data):
        await self.queue.put(json.dumps({'type': kind, 'data': data}))

    async def send(self, raw):
        self.messages.append(raw)
        if isinstance(raw, bytes):
            self.bytes += len(raw)
            return
        message = json.loads(raw)
        kind = message['type']
        if kind == 'hello':
            await self.emit('ready', configuration_confirmed=True, generation_allowed=True)
        elif kind == 'wake':
            await self.emit('listening', mode=message.get('mode', 'fast'))
            if self.tone:
                await self.emit('audio_start', response_id='two-second-answer')
                await self.emit('audio_chunk', response_id='two-second-answer', sample_rate=24000,
                                pcm=base64.b64encode(b'\x01\x00'*48000).decode())
                await self.emit('audio_segment_done', response_id='two-second-answer', segment_id='first')
                await self.emit('audio_stop', response_id='two-second-answer', reason='finished')
        elif kind == 'ping':
            if self.late_tone:
                await self.emit('audio_start', response_id='late-cancelled-answer')
                await self.emit('audio_chunk', response_id='late-cancelled-answer', sample_rate=24000,
                                pcm=base64.b64encode(b'\x01\x00'*2400).decode())
            await self.emit('pong', received_pcm_bytes=self.bytes)
        elif kind == 'stop':
            await self.emit('stopped')
        elif kind == 'mute':
            await self.emit('muted', muted=message['muted'])
        elif kind == 'input_end':
            await self.emit('input_closed')


def panel(tmp_path, *, existing=True):
    (tmp_path/'run').mkdir()
    (tmp_path/'run/keys.json').write_text(json.dumps({'api_token': 'server-secret-not-browser'}))
    private = tmp_path/'data/hardware/gobot-v1'
    private.mkdir(parents=True)
    (private/'gateway.json').write_text(json.dumps({'device_id': 'actual-board', 'unified_voice': {'enabled': True}}))
    (private/'gateway-status.json').write_text(json.dumps({'unified': {
        'device_protocol_confirmed': True, 'generation_allowed': False,
        'last_wake_ui_visible_ms': 12, 'last_wake_lvgl_refresh_ready_ms': 12,
        'wake_ui_measurement': 'lvgl_refr_ready_not_panel_dma'}}))
    nonce = 'a'*32
    owner = 'browser-sophia-'+nonce
    profile = DeviceStore(tmp_path/'data/browser-devices').profile(owner+'@sophia') if existing else None
    cookie = browser_cookie_token(nonce, 'server-secret-not-browser') if existing else None
    state = {'admission': dict(allowed=True, generation_allowed=True, expert_available=True,
        code='manual_activation_available', model='gpt-realtime-2.1-mini'), 'sessions': []}
    board = {'sessions': [{'state': 'ready', 'generation_allowed': False}]}
    calls, upstreams, connectors = [], [], []

    def backend(request):
        calls.append(request)
        if request.url.path.endswith('/status'):
            return httpx.Response(200, json=state if request.url.params.get('source') == 'browser' else board)
        return httpx.Response(200, json={'accepted': True})

    def connector(url, **kwargs):
        connectors.append((url, kwargs))
        upstream = Upstream()
        upstreams.append(upstream)
        return upstream

    app = FastAPI()
    attach_sophia_panel(app, tmp_path, client_factory=lambda **kw: httpx.AsyncClient(
        transport=httpx.MockTransport(backend), **kw), ws_connector=connector)
    client = TestClient(app, base_url=ORIGIN, client=('127.0.0.1', 50000))
    if cookie:
        client.cookies.set(BROWSER_COOKIE, cookie, domain=BROWSER_HOST, path='/')
    return SimpleNamespace(app=app, client=client, profile=profile, owner=owner, cookie=cookie, state=state, board=board,
                           calls=calls, upstreams=upstreams, connectors=connectors)


def open_browser(client):
    return client.websocket_connect('wss://plan.tailffc57c.ts.net/api/sophia/browser/stream', headers={'Origin': ORIGIN})


def test_missing_binding_does_not_enroll_or_contact_brain(tmp_path):
    p = panel(tmp_path, existing=False)
    with p.client as client:
        result = client.get('/api/sophia/browser/status')
        assert result.status_code == 200
        assert result.json()['code'] == 'browser_binding_missing'
        assert result.json()['available'] is False
        with open_browser(client) as ws:
            ws.send_json(HELLO)
            assert ws.receive_json()['data']['code'] == 'browser_binding_missing'
    assert not (tmp_path/'data/browser-devices').exists()
    assert not p.calls and not p.connectors


def test_binding_uses_signed_browser_cookie_not_forwarded_or_peer_identity(tmp_path):
    p = panel(tmp_path)
    with p.client as client:
        result = client.get('/api/sophia/browser/status', headers={'X-Forwarded-For': '100.90.228.125'})
        assert result.json()['available'] is True
        params = p.calls[-1].url.params
        assert params['device_id'] == p.owner
        assert params['client_id'] == p.profile.client_id
        assert 'owner_test_binding' not in params
        assert 'server-secret-not-browser' not in result.text
        assert browser_guest_binding(tmp_path, p.cookie, 'server-secret-not-browser')['client_id'] == p.profile.client_id
        result = client.get('/api/sophia/status')
        assert 'last_wake_ui_visible_ms' not in result.json()['device']
        assert result.json()['device']['wake_ui_measurement'] == 'lvgl_refr_ready_not_panel_dma'


@pytest.mark.parametrize('headers,peer', [
    ({'Origin': 'https://foreign.invalid'}, '127.0.0.1'),
    ({'Origin': ORIGIN, 'Host': 'foreign.invalid'}, '127.0.0.1'),
    ({'Origin': ORIGIN, 'Sec-Fetch-Site': 'cross-site'}, '127.0.0.1'),
    ({'Origin': ORIGIN}, '192.0.2.2'),
    ({}, '127.0.0.1'),
])
def test_ws_boundary_denies_before_authority_or_upstream(tmp_path, headers, peer):
    p = panel(tmp_path)
    with TestClient(p.app, base_url=ORIGIN, client=(peer, 50000)) as client:
        with pytest.raises(WebSocketDisconnect) as error:
            with client.websocket_connect('wss://plan.tailffc57c.ts.net/api/sophia/browser/stream', headers=headers):
                pytest.fail('boundary accepted foreign request')
        assert error.value.code == 1008
    assert not p.calls and not p.connectors


@pytest.mark.parametrize('change', [
    {'client_id': 'owner-phone'}, {'owner_test_binding': 'owner-phone'},
    {'source': 'device'}, {'remember': True}, {'consent': False},
    {'conversation_id': 'bad conversation'}, {'mode': 'hidden-expensive'},
])
def test_browser_cannot_supply_scope_or_relax_consent(tmp_path, change):
    p = panel(tmp_path)
    with p.client as client, open_browser(client) as ws:
        ws.send_json({**HELLO, **change})
        assert ws.receive_json()['data']['code'] == 'invalid_browser_voice_hello'
    assert not p.calls and not p.connectors


def test_denied_admission_never_opens_upstream_and_cleanup_still_scoped(tmp_path):
    p = panel(tmp_path)
    p.state['admission'].update(allowed=False, generation_allowed=False, code='exact_authorized_client_required')
    with p.client as client:
        with open_browser(client) as ws:
            ws.send_json(HELLO)
            assert ws.receive_json()['data']['code'] == 'exact_authorized_client_required'
        assert not p.connectors
        for body in ({'action': 'stop'}, {'action': 'mute', 'muted': True}):
            response = client.post('/api/sophia/browser/control', headers={'Origin': ORIGIN}, json=body)
            assert response.status_code == 200
            sent = json.loads(p.calls[-1].content)
            assert sent == {**body, 'source': 'browser', 'device_id': p.owner,
                            'client_id': p.profile.client_id}
        response = client.post('/api/sophia/browser/control', headers={'Origin': ORIGIN},
                               json={'action': 'stop', 'client_id': 'phone-owner'})
        assert response.status_code == 422


def test_source_switch_during_board_utterance_is_denied_before_upstream(tmp_path):
    p = panel(tmp_path)
    p.board['sessions'][0]['state'] = 'listening'
    with p.client as client, open_browser(client) as ws:
        ws.send_json(HELLO)
        assert ws.receive_json()['data']['code'] == 'microphone_source_change_requires_idle'
    assert not p.connectors


def test_bound_guest_offer_pcm_gate_stop_and_transport_lease_cleanup(tmp_path):
    p = panel(tmp_path)
    with p.client as client:
        with open_browser(client) as ws:
            ws.send_json(HELLO)
            assert ws.receive_json()['type'] == 'ready'
            offer = json.loads(p.upstreams[0].messages[0])
            assert offer['source'] == 'browser'
            assert offer['offer']['client_id'] == p.profile.client_id
            assert 'owner_test_binding' not in offer['offer']
            assert offer['offer']['device_id'] == p.owner
            assert offer['offer']['client_kind'] == 'panel'
            assert offer['offer']['remember'] is False
            assert offer['offer']['speaker_consent'] is False
            assert offer['offer']['personalization_mode'] == 'guest'
            assert offer['offer']['requested_voice'] == 'marin'
            url, options = p.connectors[0]
            assert url == 'ws://127.0.0.1:18781/api/v1/voice-ws/stream'
            assert options['additional_headers']['Authorization'] == 'Bearer server-secret-not-browser'
            ws.send_bytes(b'\x00\x00'*12)  # empty connection cannot forward idle mic.
            ws.send_json({'type': 'ping'})
            assert ws.receive_json()['data']['received_pcm_bytes'] == 0
            ws.send_json({'type': 'wake', 'wake_id': 'one-manual-wake', 'mode': 'fast'})
            assert ws.receive_json()['type'] == 'listening'
            ws.send_bytes(b'\x01\x00'*12)
            ws.send_json({'type': 'ping'})
            assert ws.receive_json()['data']['received_pcm_bytes'] == 24
            ws.send_json({'type': 'stop'})
            assert ws.receive_json()['type'] == 'stopped'
            ws.send_bytes(b'\x01\x00'*12)
            ws.send_json({'type': 'ping'})
            assert ws.receive_json()['data']['received_pcm_bytes'] == 24
            with open_browser(client) as duplicate:
                duplicate.send_json(HELLO)
                assert duplicate.receive_json()['data']['code'] == 'microphone_source_already_attached'
        with open_browser(client) as recovered:
            recovered.send_json(HELLO)
            assert recovered.receive_json()['type'] == 'ready'
    assert len(p.connectors) == 2
    # TCP close did not invent another stop/job cancellation.
    assert sum(json.loads(m).get('type') == 'stop' for u in p.upstreams for m in u.messages if isinstance(m, str)) == 1


def test_last_admitted_start_resumes_only_exact_known_conversation(tmp_path):
    p = panel(tmp_path)
    p.state['admission'].update(allowed=False, generation_allowed=False, code='realtime_session_budget_exhausted')
    p.state['sessions'] = [{**{k: HELLO[k] for k in ('session_id', 'conversation_id')},
                            'generation_allowed': True, 'expert_active': False, 'state': 'detached'}]
    with p.client as client:
        with open_browser(client) as wrong:
            wrong.send_json({**HELLO, 'conversation_id': 'new-foreign-conversation'})
            assert wrong.receive_json()['data']['code'] == 'realtime_audio_session_already_active'
        assert not p.connectors
        with open_browser(client) as ws:
            ws.send_json(HELLO)
            assert ws.receive_json()['type'] == 'ready'
            ws.send_json({'type': 'wake', 'wake_id': 'resume-explicit', 'mode': 'fast'})
            assert ws.receive_json()['type'] == 'listening'
        p.state['admission']['code'] = 'owner_api_estimate_limit'
        with open_browser(client) as denied:
            denied.send_json(HELLO)
            assert denied.receive_json()['data']['code'] == 'owner_api_estimate_limit'
    assert len(p.connectors) == 1


def test_running_expert_can_reattach_empty_but_never_reopen_microphone(tmp_path):
    p = panel(tmp_path)
    p.state['admission'].update(allowed=False, generation_allowed=False, code='realtime_budget_missing_or_expired')
    p.state['sessions'] = [{**{k: HELLO[k] for k in ('session_id', 'conversation_id')},
                            'generation_allowed': False, 'expert_active': True, 'input_mode': 'expert'}]
    with p.client as client:
        with open_browser(client) as ws:
            ws.send_json(HELLO)
            assert ws.receive_json()['type'] == 'ready'
            ws.send_bytes(b'\x01\x00'*120)
            ws.send_json({'type': 'ping'})
            assert ws.receive_json()['data']['received_pcm_bytes'] == 0
            ws.send_json({'type': 'wake', 'wake_id': 'forbidden', 'mode': 'fast'})
            assert ws.receive_json()['data']['code'] == 'expert_subscriber_has_no_microphone'
        p.state['admission']['code'] = 'exact_authorized_client_required'
        with open_browser(client) as denied:
            denied.send_json(HELLO)
            assert denied.receive_json()['data']['code'] == 'exact_authorized_client_required'
    assert len(p.connectors) == 1


def test_authenticated_brain_status_and_control_preserve_exact_client_binding():
    stops = []
    async def auth():
        pass
    async def stop():
        stops.append('current')
    sessions = {}
    for client_id in ('current', 'previous'):
        sessions[client_id] = SimpleNamespace(id=client_id, closed=False, ready=True, state='ready',
            offer=SimpleNamespace(device_id='same-peer', client_id=client_id, owner_test_binding=client_id,
                                  conversation_id=client_id+'-conversation', input_mode='fast'),
            experts=SimpleNamespace(active=lambda: False), generation_allowed=lambda: False, stop=stop)
    manager = SimpleNamespace(sessions=sessions, status=lambda: {}, admission_preview=lambda **kw: {
        'allowed': False, 'code': 'realtime_budget_missing_or_expired'})
    app = FastAPI()
    attach_brain_direct_voice(app, manager, manager, auth, 'test-token')
    with TestClient(app) as client:
        query = dict(source='browser', device_id='same-peer', client_id='current', owner_test_binding='current')
        result = client.get('/api/v1/voice-ws/status', params=query).json()
        assert [s['session_id'] for s in result['sessions']] == ['current']
        assert result['sessions'][0]['expert_active'] is False
        assert result['admission']['allowed'] is False
        assert client.post('/api/v1/voice-ws/control', json={**query, 'action': 'stop'}).status_code == 200
        assert client.post('/api/v1/voice-ws/control', json={**query, 'owner_test_binding': 'previous', 'action': 'stop'}).status_code == 409
        assert stops == ['current']


def test_browser_audio_and_ui_offline_contract():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node is unavailable for offline WebAudio/worklet/UI contract fixtures')
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([node, '--test', str(root/'tests/sophia_browser_audio.cjs')],
                            cwd=root, text=True, capture_output=True, timeout=25)
    assert result.returncode == 0, result.stdout+'\n'+result.stderr


@pytest.mark.parametrize('provider_code,public_code', [
    ('openai_key_missing', 'openai_key_missing'),
    ('realtime_settings_not_acknowledged', 'realtime_settings_not_acknowledged'),
    ('private-provider-response-secret', 'direct_voice_transport_failed'),
])
def test_known_configuration_errors_are_actionable_without_leaking_provider_details(provider_code, public_code):
    from gobot.realtime_provider import RealtimeProviderError
    async def auth():
        pass
    async def reject(_):
        raise RealtimeProviderError(provider_code)
    manager = SimpleNamespace(sessions={}, accept=reject)
    app = FastAPI()
    attach_brain_direct_voice(app, manager, manager, auth, 'test-token')
    with TestClient(app) as client, client.websocket_connect('/api/v1/voice-ws/stream',
            headers={'Authorization': 'Bearer test-token'}) as ws:
        ws.send_json({'type': 'hello', 'source': 'browser', 'offer': {
            'session_id': 'known-session', 'conversation_id': 'known-conversation',
            'device_id': 'browser-peer', 'client_id': 'existing-client',
            'client_kind': 'panel', 'consent': True, 'speak': True}})
        message = ws.receive_json()
        assert message == {'type': 'error', 'data': {'code': public_code}}
        assert 'private-provider-response-secret' not in json.dumps(message)


def test_slow_playback_keeps_sixty_seconds_bounded_and_splits_large_provider_chunks():
    async def scenario():
        clock = [100.0]
        credit = BrowserPlaybackCredit(enabled=True, clock=lambda: clock[0])
        owner = credit.begin('long-answer')
        sent_frames = 0
        largest_pending = 0
        async def send(event, current, samples):
            nonlocal sent_frames, largest_pending
            if not credit.owns(current):
                return False
            assert samples <= 2400
            assert len(base64.b64decode(event['data']['pcm'])) == samples*2
            credit.sent(current, samples)
            sent_frames += 1
            largest_pending = max(largest_pending, current['sent']-current['played'])
            assert len(current['pending']) <= 4
            return True
        event = {'type': 'audio_chunk', 'data': {'response_id': 'long-answer', 'sample_rate': 24000,
                 'pcm': base64.b64encode(b'\x00\x00'*48000).decode()}}  # one upstream chunk is two seconds.
        async def produce():
            for _ in range(30):
                await credit.pcm(event, owner, send)
        producer = asyncio.create_task(produce())
        async def sent_at_least(samples):
            while owner['sent'] < samples:
                await asyncio.sleep(0)
        await asyncio.wait_for(sent_at_least(9600), 1)
        assert sent_frames == 4 and not producer.done()
        credit.segment(owner, 'first-window')
        with pytest.raises(ValueError, match='before_completion'):
            credit.receipt({'type': 'playback_finished', 'response_id': 'long-answer', 'segment_id': 'first-window'})
        with pytest.raises(ValueError, match='ahead_of_output'):
            credit.progress({'response_id': 'long-answer', 'played_samples': 9600})
        with pytest.raises(ValueError, match='invalid_browser_playback_progress'):
            credit.progress({'response_id': 'long-answer', 'played_samples': True})
        for sample in range(2400, 60*24000+1, 2400):
            await asyncio.wait_for(sent_at_least(sample), 1)
            clock[0] += .1
            assert credit.progress({'response_id': 'long-answer', 'played_samples': sample})
        await asyncio.wait_for(producer, 1)
        assert sent_frames == 600 and largest_pending == 9600
        assert credit.receipt({'type': 'playback_finished', 'response_id': 'long-answer', 'segment_id': 'first-window'})
        with pytest.raises(ValueError, match='before_completion'):
            credit.receipt({'type': 'playback_finished', 'response_id': 'long-answer'})
        owner['sealed'] = True
        assert credit.receipt({'type': 'playback_finished', 'response_id': 'long-answer'})
        assert not credit.receipt({'type': 'playback_finished', 'response_id': 'long-answer'})
    asyncio.run(scenario())


def test_credit_cancel_unblocks_writer_and_same_turn_intro_handoff_keeps_authority():
    async def scenario():
        credit = BrowserPlaybackCredit(enabled=True, clock=lambda: 0.0)
        intro = credit.begin('intro')
        frames = []
        async def send(event, owner, samples):
            if credit.owns(owner):
                credit.sent(owner, samples)
                frames.append((owner['id'], samples))
        event = {'type': 'audio_chunk', 'data': {'response_id': 'intro',
                 'pcm': base64.b64encode(b'\x01\x00'*48000).decode()}}
        writer = asyncio.create_task(credit.pcm(event, intro, send))
        while len(frames) < 4:
            await asyncio.sleep(0)
        assert not writer.done()
        assert credit.cancel('intro', revoke=False)
        await asyncio.wait_for(writer, 1)
        assert len(frames) == 4
        assert credit.begin('intro') is None
        expert = credit.begin('accepted-expert')
        assert expert is not None  # Matching upstream intro cancellation is not Stop.
        credit.sent(expert, 2400)
        assert not credit.progress({'response_id': 'intro', 'played_samples': 9600})
        assert expert['played'] == 0 and len(expert['pending']) == 1
        credit.cancel()  # Explicit Stop revokes the turn.
        assert credit.begin('late-expert-replacement') is None
    asyncio.run(scenario())


def test_proxy_stop_and_control_bypass_a_large_chunk_waiting_for_render_credit(tmp_path):
    p = panel(tmp_path)
    with p.client as client, open_browser(client) as ws:
        ws.send_json(HELLO)
        assert ws.receive_json()['type'] == 'ready'
        p.upstreams[0].tone = True
        ws.send_json({'type': 'wake', 'wake_id': 'manual-credit-test', 'mode': 'fast'})
        assert ws.receive_json()['type'] == 'listening'
        assert ws.receive_json()['type'] == 'audio_start'
        for _ in range(4):
            event = ws.receive_json()
            assert event['type'] == 'audio_chunk'
            assert len(base64.b64decode(event['data']['pcm'])) == 4800
        ws.send_json({'type': 'ping'})
        assert ws.receive_json()['type'] == 'pong'  # Does not wait behind the two-second chunk.
        ws.send_json({'type': 'stop'})
        assert ws.receive_json()['type'] == 'stopped'
        p.upstreams[0].late_tone = True
        ws.send_json({'type': 'playback_progress', 'response_id': 'two-second-answer', 'played_samples': 999999})
        ws.send_json({'type': 'ping'})
        assert ws.receive_json()['type'] == 'pong'  # Late media was discarded, never restarted.
    assert not any(json.loads(m).get('type') == 'playback_finished' for m in p.upstreams[0].messages if isinstance(m, str))


@pytest.mark.parametrize('receipt', [
    {'type': 'playback_finished', 'response_id': 'two-second-answer'},
    {'type': 'playback_finished', 'response_id': 'two-second-answer', 'segment_id': 'first'},
    {'type': 'playback_progress', 'response_id': 'two-second-answer', 'played_samples': 999999},
])
def test_proxy_rejects_forged_early_playback_receipts_before_brain(tmp_path, receipt):
    p = panel(tmp_path)
    with p.client as client, open_browser(client) as ws:
        ws.send_json(HELLO)
        assert ws.receive_json()['type'] == 'ready'
        p.upstreams[0].tone = True
        ws.send_json({'type': 'wake', 'wake_id': 'manual-receipt-test', 'mode': 'fast'})
        assert ws.receive_json()['type'] == 'listening'
        assert ws.receive_json()['type'] == 'audio_start'
        for _ in range(4):
            assert ws.receive_json()['type'] == 'audio_chunk'
        ws.send_json(receipt)
        assert ws.receive_json()['type'] == 'error'
    assert not any(json.loads(m).get('type') in {'playback_progress', 'playback_finished'}
                   for m in p.upstreams[0].messages if isinstance(m, str))


def test_explicit_guest_binding_is_secure_idempotent_and_creates_no_grant(tmp_path):
    import sqlite3
    from gobot.device_contract import DeviceProfile
    from gobot.family_access import IdentityAccessManager
    from gobot.realtime_ws import DirectOffer
    p = panel(tmp_path, existing=False)
    p.state['admission'].update(allowed=False, generation_allowed=False, code='exact_authorized_client_required')
    protected = {}
    for name in ('realtime', 'owner-full-test', 'voice-ab-b', 'voice-ab-c', 'browser-lab'):
        path = tmp_path/'run'/name/'policy.json'
        path.parent.mkdir()
        value = json.dumps({'authorization': name+'-existing', 'allowed_client_id': 'original-'+name})
        path.write_text(value)
        protected[path] = value
    with p.client as client:
        assert client.get('/api/sophia/browser/status').json()['binding_present'] is False
        assert not p.calls and not p.connectors
        result = client.post('/api/sophia/browser/bind', headers={'Origin': ORIGIN}, json={})
        assert result.status_code == 200
        binding = result.json()
        assert binding['created'] is True and binding['guest'] is True
        assert binding['paid_grant_created'] is False and binding['private_memory_allowed'] is False
        assert binding['microphone_started'] is False
        assert binding['device_id'].startswith('browser-sophia-')
        cookie_header = result.headers['set-cookie']
        assert cookie_header.startswith(BROWSER_COOKIE+'=')
        assert '; Secure' in cookie_header and '; HttpOnly' in cookie_header
        assert '; SameSite=strict' in cookie_header and '; Path=/' in cookie_header
        assert 'Domain=' not in cookie_header and f'Max-Age={BROWSER_COOKIE_AGE}' in cookie_header
        assert 'server-secret-not-browser' not in result.text
        assert BROWSER_COOKIE not in result.text and 'owner_test_binding' not in binding
        assert not p.calls and not p.connectors
        repeated = client.post('/api/sophia/browser/bind', headers={'Origin': ORIGIN}, json={})
        assert repeated.status_code == 200 and repeated.json()['created'] is False
        assert repeated.json()['client_id'] == binding['client_id']
        assert 'set-cookie' not in repeated.headers  # Idempotence does not silently renew authentication.
        status = client.get('/api/sophia/browser/status').json()
        assert status['binding_present'] is True and status['available'] is False
        assert status['code'] == 'exact_authorized_client_required'
        assert not p.connectors
        with sqlite3.connect(tmp_path/'data/browser-devices/profiles.sqlite') as db:
            rows = db.execute('SELECT owner,profile FROM profiles').fetchall()
        assert len(rows) == 1 and rows[0][0] == binding['device_id']+'@sophia'
        profile = DeviceProfile.model_validate_json(rows[0][1])
        assert profile.client_id == binding['client_id']
        assert profile.voice.realtime_consent is False and profile.voice.expert_quota_consent is False
        offer = DirectOffer(session_id='guest-session', conversation_id='guest-conversation',
            device_id=binding['device_id'], client_id=binding['client_id'], client_kind='panel',
            remember=False, personalization_mode='guest', speaker_consent=False)
        access = IdentityAccessManager(None).native(offer)
        assert access.confirmed_profile_id is None and access.private_access is False
        assert access.child_restrictions is True and access.memory_mode == 'guest_ram_only'
        assert offer.owner_test_binding is None and offer.confirmed_profile_epoch is None
        assert DeviceStore(tmp_path/'data/browser-devices').scoped_owner(
            binding['device_id'], binding['client_id']) == rows[0][0]
    assert all(path.read_text() == value for path, value in protected.items())


def test_distinct_cookie_jars_behind_same_peer_never_inherit_legacy_loopback_profile(tmp_path):
    import sqlite3
    p = panel(tmp_path, existing=False)
    store = DeviceStore(tmp_path/'data/browser-devices')
    legacy = store.profile('browser-127-0-0-1@127.0.0.1')
    legacy_json = legacy.model_dump_json()
    bindings = []
    for _ in range(2):
        with TestClient(p.app, base_url=ORIGIN, client=('127.0.0.1', 50000)) as client:
            assert client.get('/api/sophia/browser/status').json()['code'] == 'browser_binding_missing'
            response = client.post('/api/sophia/browser/bind', headers={'Origin': ORIGIN}, json={})
            assert response.status_code == 200
            binding = response.json()
            bindings.append(binding)
            for _ in range(2):
                assert client.get('/api/sophia/browser/status').json()['binding_present'] is True
            assert p.calls[-1].url.params['client_id'] == binding['client_id']
    assert bindings[0]['device_id'] != bindings[1]['device_id']
    assert bindings[0]['client_id'] != bindings[1]['client_id']
    assert legacy.client_id not in {b['client_id'] for b in bindings}
    with sqlite3.connect(store.db) as db:
        assert db.execute('SELECT count(*) FROM profiles').fetchone()[0] == 3
        assert db.execute('SELECT profile FROM profiles WHERE owner=?',
            ('browser-127-0-0-1@127.0.0.1',)).fetchone()[0] == legacy_json


@pytest.mark.parametrize('kind,expected', [
    ('tampered', 'browser_binding_invalid'), ('wrong_purpose', 'browser_binding_invalid'),
    ('expired', 'browser_binding_expired'), ('signed_missing_row', 'browser_binding_missing'),
])
def test_invalid_or_unregistered_cookie_cannot_create_or_access_browser_scope(tmp_path, kind, expected):
    import hashlib
    import hmac
    import time
    p = panel(tmp_path, existing=False)
    cookie = browser_cookie_token('c'*32, 'server-secret-not-browser')
    if kind == 'tampered':
        cookie = cookie[:-1]+('0' if cookie[-1] != '0' else '1')
    elif kind == 'wrong_purpose':
        payload = cookie.split('.')[0]
        cookie = payload+'.'+hmac.new(b'server-secret-not-browser', b'profile:'+payload.encode(), hashlib.sha256).hexdigest()
    elif kind == 'expired':
        cookie = browser_cookie_token('c'*32, 'server-secret-not-browser', now=time.time()-BROWSER_COOKIE_AGE-1)
    p.client.cookies.set(BROWSER_COOKIE, cookie, domain=BROWSER_HOST, path='/')
    with p.client as client:
        status = client.get('/api/sophia/browser/status').json()
        assert status['binding_present'] is False and status['code'] == expected
        assert client.post('/api/sophia/browser/control', headers={'Origin': ORIGIN}, json={'action': 'stop'}).status_code == 403
        with open_browser(client) as ws:
            ws.send_json(HELLO)
            assert ws.receive_json()['data']['code'] == expected
    assert not (tmp_path/'data/browser-devices').exists()
    assert not p.calls and not p.connectors


@pytest.mark.parametrize('body', [
    {'client_id': 'original-phone'}, {'device_id': 'spotpear-existing'},
    {'owner_test_binding': 'original-phone'}, {'profile_epoch': 'owner'},
    {'confirmed_profile_epoch': 'adult'}, {'consent': True}, {'remember': True},
    {'source': 'browser-voice-existing-lab'},
])
def test_bind_cannot_accept_identity_privilege_or_expense_fields(tmp_path, body):
    p = panel(tmp_path, existing=False)
    with p.client as client:
        result = client.post('/api/sophia/browser/bind', headers={'Origin': ORIGIN}, json=body)
        assert result.status_code == 422
    assert not (tmp_path/'data/browser-devices').exists()
    assert not p.calls and not p.connectors


@pytest.mark.parametrize('origin,host,peer', [
    ('https://foreign.invalid', BROWSER_HOST, '127.0.0.1'),
    (ORIGIN, '127.0.0.1:18811', '127.0.0.1'),
    ('http://127.0.0.1:18811', '127.0.0.1:18811', '127.0.0.1'),
    (ORIGIN, BROWSER_HOST, '192.0.2.40'),
    ('', BROWSER_HOST, '127.0.0.1'),
])
def test_bind_requires_exact_private_https_origin_and_loopback_proxy(tmp_path, origin, host, peer):
    p = panel(tmp_path, existing=False)
    with TestClient(p.app, base_url=ORIGIN, client=(peer, 50000)) as client:
        response = client.post('/api/sophia/browser/bind', headers={
            'Origin': origin, 'Host': host, 'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '127.0.0.1'}, json={})
        assert response.status_code == 403
    assert not (tmp_path/'data/browser-devices').exists()


def test_serve_http_upstream_still_sets_secure_cookie_for_exact_owner_https(tmp_path):
    p = panel(tmp_path, existing=False)
    with TestClient(p.app, base_url='http://'+BROWSER_HOST, client=('127.0.0.1', 50000)) as client:
        result = client.post('/api/sophia/browser/bind', headers={'Origin': ORIGIN}, json={})
        assert result.status_code == 200
        assert '; Secure' in result.headers['set-cookie']
        assert '; HttpOnly' in result.headers['set-cookie']
    assert not p.calls and not p.connectors
