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
from gobot.sophia_panel import BrowserPlaybackCredit, attach_sophia_panel, existing_browser_binding

ORIGIN = 'http://127.0.0.1:18811'
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
    profile = DeviceStore(tmp_path/'data/browser-devices').profile('browser-127-0-0-1@127.0.0.1') if existing else None
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
    return SimpleNamespace(app=app, client=client, profile=profile, state=state, board=board,
                           calls=calls, upstreams=upstreams, connectors=connectors)


def open_browser(client):
    return client.websocket_connect('ws://127.0.0.1:18811/api/sophia/browser/stream', headers={'Origin': ORIGIN})


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


def test_binding_uses_exact_existing_peer_not_forwarded_or_policy_identity(tmp_path):
    p = panel(tmp_path)
    with p.client as client:
        result = client.get('/api/sophia/browser/status', headers={'X-Forwarded-For': '100.90.228.125'})
        assert result.json()['available'] is True
        params = p.calls[-1].url.params
        assert params['device_id'] == 'browser-127-0-0-1'
        assert params['client_id'] == params['owner_test_binding'] == p.profile.client_id
        assert 'server-secret-not-browser' not in result.text
        assert existing_browser_binding(tmp_path, '127.0.0.1')['client_id'] == p.profile.client_id
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
            with client.websocket_connect('ws://127.0.0.1:18811/api/sophia/browser/stream', headers=headers):
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
            assert sent == {**body, 'source': 'browser', 'device_id': 'browser-127-0-0-1',
                            'client_id': p.profile.client_id, 'owner_test_binding': p.profile.client_id}
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
            assert offer['offer']['client_id'] == offer['offer']['owner_test_binding'] == p.profile.client_id
            assert offer['offer']['device_id'] == 'browser-127-0-0-1'
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
