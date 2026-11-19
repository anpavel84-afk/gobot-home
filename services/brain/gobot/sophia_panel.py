"""Sophia controls on the existing private HTTPS application, not a new daemon.

The column and the browser keep their existing, independent identities/grants.
Browser Lab keeps its private implementation and ledger. Explicit browser setup
creates only a dedicated guest profile, never a column/phone/Lab spending grant.
"""
import asyncio
import base64
from collections import deque
import contextlib
import hashlib
import hmac
import ipaddress
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time

import anyio
import httpx
from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from websockets.asyncio.client import connect


BROWSER_COOKIE = '__Host-gobot_sophia_guest'
BROWSER_COOKIE_AGE = 30*24*60*60
BROWSER_COOKIE_PURPOSE = b'gobot:sophia-browser-guest:v1\0'
BROWSER_HOST = 'plan.tailffc57c.ts.net'
BROWSER_ORIGIN = 'https://'+BROWSER_HOST


def browser_cookie_token(nonce, key, *, now=None):
    """Only the explicit bind route mints this guest credential."""
    if not isinstance(nonce, str) or not re.fullmatch(r'[a-f0-9]{32}', nonce) or not key:
        raise ValueError('invalid_browser_guest_identity')
    claims = {'v': 1, 'id': nonce, 'exp': int(time.time() if now is None else now)+BROWSER_COOKIE_AGE}
    payload = base64.urlsafe_b64encode(json.dumps(claims, separators=(',', ':')).encode()).rstrip(b'=').decode()
    signature = hmac.new(key.encode(), BROWSER_COOKIE_PURPOSE+payload.encode(), hashlib.sha256).hexdigest()
    return payload+'.'+signature


def browser_cookie_nonce(cookie, key, *, now=None):
    if not cookie:
        raise PermissionError('browser_binding_missing')
    if not isinstance(cookie, str) or len(cookie) > 512 or not key:
        raise PermissionError('browser_binding_invalid')
    try:
        payload, signature = cookie.split('.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,400}', payload) or not re.fullmatch(r'[a-f0-9]{64}', signature):
            raise ValueError()
        expected = hmac.new(key.encode(), BROWSER_COOKIE_PURPOSE+payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError()
        claims = json.loads(base64.urlsafe_b64decode(payload+'='*(-len(payload) % 4)))
        if (not isinstance(claims, dict) or set(claims) != {'v', 'id', 'exp'} or
                type(claims['v']) is not int or claims['v'] != 1 or
                not isinstance(claims['id'], str) or not re.fullmatch(r'[a-f0-9]{32}', claims['id']) or
                type(claims['exp']) is not int):
            raise ValueError()
        remaining = claims['exp']-int(time.time() if now is None else now)
        if remaining <= 0:
            raise PermissionError('browser_binding_expired')
        if remaining > BROWSER_COOKIE_AGE:
            raise ValueError()
        return claims['id']
    except (ValueError, TypeError, KeyError):
        raise PermissionError('browser_binding_invalid') from None


def browser_guest_binding(root, cookie, key, *, now=None):
    """Cookie-only exact lookup; reads never enroll or fall back to a peer IP."""
    nonce = browser_cookie_nonce(cookie, key, now=now)
    owner = 'browser-sophia-'+nonce
    path = Path(root)/'data/browser-devices/profiles.sqlite'
    if path.is_symlink() or path.parent.is_symlink():
        raise PermissionError('browser_binding_unavailable')
    if not path.is_file():
        raise PermissionError('browser_binding_missing')
    try:
        with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True, timeout=2) as db:
            row = db.execute('SELECT profile FROM profiles WHERE owner=?', (owner+'@sophia',)).fetchone()
        if not row:
            raise PermissionError('browser_binding_missing')
        from .device_contract import DeviceProfile
        profile = DeviceProfile.model_validate_json(row[0])
        if profile.client_kind != 'browser_device':
            raise PermissionError('browser_binding_unavailable')
    except (sqlite3.Error, ValueError):
        raise PermissionError('browser_binding_unavailable') from None
    # A guest credential is not an owner/adult/private-memory authorization.
    return {'device_id': owner, 'client_id': profile.client_id}


def browser_resume(state, admission, hello):
    """A spent start does not erase an admitted logical conversation.

    Status sessions are filtered by the exact server-owned browser binding.
    An active expert may have an empty subscriber even after the next-input
    allowance has closed; this never authorizes microphone capture or a wake.
    """
    existing = next((s for s in state.get('sessions', [])
        if s.get('session_id') == hello['session_id'] and
        s.get('conversation_id') == hello['conversation_id']), None)
    code = admission.get('code')
    input_allowed = admission.get('allowed') is True or bool(existing and
        existing.get('generation_allowed') is True and code == 'realtime_session_budget_exhausted')
    expert_only = bool(existing and existing.get('expert_active') is True and code in {
        'manual_activation_available', 'realtime_session_budget_exhausted',
        'owner_realtime_daily_limit', 'owner_api_estimate_limit',
        'realtime_budget_missing_or_expired'})
    return existing, input_allowed, expert_only


class BrowserPlaybackCredit:
    """Bounded browser render credit, never a provider or acoustic receipt.

    PCM is split into 100 ms frames with at most four frames in flight. Only
    contiguous, actually sent sample fences may advance progress. Segment and
    whole-response receipts remain separate and cannot outrun that progress.
    """
    FRAME_SAMPLES = 2400
    MAX_FRAMES = 4

    def __init__(self, *, enabled=False, clock=time.monotonic):
        self.enabled = enabled
        self.current = None
        self.clock = clock
        self.changed = asyncio.Event()
        self.retired = set()
        self.retired_order = deque()

    def retire(self, response_id):
        if response_id in self.retired:
            return
        self.retired.add(response_id)
        self.retired_order.append(response_id)
        if len(self.retired_order) > 128:
            self.retired.discard(self.retired_order.popleft())

    def owns(self, owner):
        return self.enabled and owner is not None and self.current is owner

    def begin(self, response_id):
        if not self.enabled:
            return None
        if not isinstance(response_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', response_id):
            raise ValueError('invalid_browser_output_identity')
        if response_id in self.retired:
            return None
        if self.current is not None:
            raise ValueError('browser_output_owner_conflict')
        self.current = {'id': response_id, 'sent': 0, 'played': 0, 'pending': deque(),
                        'segments': {}, 'sealed': False, 'started': False, 'first_send': None}
        return self.current

    def owner(self, response_id):
        owner = self.current
        return owner if self.owns(owner) and owner['id'] == response_id else None

    def cancel(self, response_id=None, *, revoke=True):
        if response_id is not None and not self.owner(response_id):
            return False
        if revoke:
            self.enabled = False
        if self.current is not None:
            self.retire(self.current['id'])
        self.current = None
        self.changed.set()
        return True

    def permit_input(self):
        if self.current is not None:
            raise ValueError('conversation_busy')
        self.enabled = True

    async def pcm(self, event, owner, send):
        data = event['data']
        if data.get('sample_rate', 24000) != 24000 or not isinstance(data.get('pcm'), str):
            raise ValueError('invalid_browser_pcm24')
        try:
            raw = base64.b64decode(data['pcm'], validate=True)
        except ValueError:
            raise ValueError('invalid_browser_pcm24') from None
        if not raw or len(raw) % 2 or len(raw) > 131072:
            raise ValueError('invalid_browser_pcm24')
        for offset in range(0, len(raw), self.FRAME_SAMPLES*2):
            piece = raw[offset:offset+self.FRAME_SAMPLES*2]
            samples = len(piece)//2
            while self.owns(owner) and (len(owner['pending']) >= self.MAX_FRAMES or
                    owner['sent']-owner['played']+samples > self.FRAME_SAMPLES*self.MAX_FRAMES):
                self.changed.clear()
                try:
                    await asyncio.wait_for(self.changed.wait(), 3)
                except asyncio.TimeoutError:
                    raise ValueError('browser_playback_progress_timeout') from None
            if not self.owns(owner):
                return
            # The sender checks ownership again under its send lock. Stop can
            # invalidate a blocked writer without waiting for any audio credit.
            await send({**event, 'data': {**data, 'pcm': base64.b64encode(piece).decode('ascii')}},
                       owner, samples)

    def sent(self, owner, samples):
        if not self.owns(owner):
            return False
        if owner['first_send'] is None:
            owner['first_send'] = self.clock()
        owner['sent'] += samples
        owner['pending'].append(owner['sent'])
        return True

    def progress(self, data):
        owner = self.owner(data.get('response_id'))
        if owner is None:
            return False
        played = data.get('played_samples')
        if type(played) is not int or played < 0 or played > owner['sent']:
            raise ValueError('invalid_browser_playback_progress')
        if played <= owner['played']:
            return False
        if played not in owner['pending'] or owner['first_send'] is None or played > (
                int(max(0, self.clock()-owner['first_send'])*24000)+self.FRAME_SAMPLES):
            raise ValueError('browser_playback_progress_ahead_of_output')
        owner['played'] = played
        while owner['pending'] and owner['pending'][0] <= played:
            owner['pending'].popleft()
        self.changed.set()
        return True

    def segment(self, owner, segment_id):
        if not self.owns(owner):
            return
        if (not isinstance(segment_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', segment_id)
                or not owner['sent'] or len(owner['segments']) >= 256):
            raise ValueError('invalid_browser_segment_fence')
        owner['segments'].setdefault(segment_id, [owner['sent'], False])

    def receipt(self, data):
        owner = self.owner(data.get('response_id'))
        if owner is None:
            return False
        if data['type'] == 'playback_started':
            if not owner['sent']:
                raise ValueError('browser_playback_receipt_before_output')
            if owner['started']:
                return False
            owner['started'] = True
            return True
        segment_id = data.get('segment_id')
        if segment_id is not None:
            fence = owner['segments'].get(segment_id)
            if fence is None or owner['played'] < fence[0]:
                raise ValueError('browser_playback_receipt_before_completion')
            if fence[1]:
                return False
            fence[1] = True
            return True
        if not owner['sealed'] or not owner['sent'] or owner['played'] != owner['sent'] or owner['pending']:
            raise ValueError('browser_playback_receipt_before_completion')
        self.retire(owner['id'])
        self.current = None
        self.changed.set()
        return True


def attach_sophia_panel(app, main_root, *, client_factory=httpx.AsyncClient,
                        ws_connector=connect):
    root = Path(main_root)
    assets = root/'services/phone/dist'
    allowed_hosts = {'plan.tailffc57c.ts.net', '127.0.0.1:18811', 'localhost:18811'}
    origins = {'https://plan.tailffc57c.ts.net', 'http://127.0.0.1:18811', 'http://localhost:18811'}
    browser_leases = set()
    lease_lock = asyncio.Lock()
    backend = 'http://127.0.0.1:18781/api/v1/voice-ws'

    def boundary(request, mutation=False):
        try:
            local = ipaddress.ip_address(request.client.host).is_loopback
        except (ValueError, AttributeError):
            local = False
        if (not local or request.headers.get('host') not in allowed_hosts
                or request.headers.get('sec-fetch-site') == 'cross-site'
                or (request.headers.get('origin') not in origins if mutation
                    else request.headers.get('origin') not in origins | {None})):
            raise HTTPException(403, 'private_voice_panel_only')

    def brain_key():
        return json.loads((root/'run/keys.json').read_text(encoding='utf-8'))['api_token']

    def brain_auth():
        return {'Authorization': 'Bearer '+brain_key()}

    async def browser_scope(request):
        cookie = request.cookies.get(BROWSER_COOKIE)
        if not cookie:
            raise PermissionError('browser_binding_missing')
        key = await asyncio.to_thread(brain_key)
        scope = await asyncio.to_thread(browser_guest_binding, root, cookie, key)
        return scope, {'Authorization': 'Bearer '+key}

    def connection():
        config = json.loads((root/'data/hardware/gobot-v1/gateway.json').read_text(encoding='utf-8'))
        return config, brain_auth()

    async def browser_state(request):
        scope, auth = await browser_scope(request)
        async with client_factory(trust_env=False, timeout=4) as client:
            response = await client.get(backend+'/status', headers=auth,
                                        params={'source': 'browser', **scope})
        if response.status_code != 200:
            raise PermissionError('browser_voice_status_unavailable')
        result = response.json()
        admission = result.get('admission', {})
        return scope, auth, result, admission

    async def board_idle(auth):
        config, _ = await asyncio.to_thread(connection)
        async with client_factory(trust_env=False, timeout=4) as client:
            result = await client.get(backend+'/status', headers=auth,
                params={'source': 'device', 'device_id': config['device_id']})
        if result.status_code != 200:
            raise PermissionError('microphone_source_state_unavailable')
        if any(s.get('state') not in {'ready', 'blocked', 'muted', 'closed'} or s.get('expert_active')
               for s in result.json().get('sessions', [])):
            raise PermissionError('microphone_source_change_requires_idle')

    @app.get('/sophia')
    async def page(request: Request):
        boundary(request)
        return FileResponse(assets/'sophia.html', media_type='text/html',
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/sophia/{asset}')
    async def asset(asset: str, request: Request):
        boundary(request)
        if asset not in {'sophia.js', 'sophia.css', 'sophia-audio.js', 'sophia-pcm-worklet.js'}:
            raise HTTPException(404)
        return FileResponse(assets/asset, media_type='text/javascript' if asset.endswith('.js') else 'text/css',
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/api/sophia/status')
    async def status(request: Request):
        boundary(request)
        try:
            config, auth = await asyncio.to_thread(connection)
            async with client_factory(trust_env=False, timeout=4) as client:
                result = await client.get('http://127.0.0.1:18781/api/v1/voice-ws/status',
                    headers=auth, params={'source': 'device', 'device_id': config['device_id']})
            state = result.json()
            try:
                gateway = json.loads((root/'data/hardware/gobot-v1/gateway-status.json').read_text())
                unified = gateway.get('unified', {})
            except (OSError, ValueError):
                unified = {}
            safe = {k: v for k, v in unified.items() if k in {
                'protocol', 'mode', 'voice', 'wake_location', 'pcm_stage', 'cloud_ready',
                'generation_allowed', 'received_packets', 'downlink_packets', 'input_open', 'voice_phase',
                'last_error', 'wake_events', 'playback_started', 'playback_finished',
                'last_wake_lvgl_refresh_ready_ms', 'wake_ui_measurement',
                'device_resources', 'device_protocol_confirmed'}}
            return JSONResponse({'brain': state, 'device': safe,
                'configured': config.get('unified_voice', {}).get('enabled') is True,
                'source': 'spotpear', 'browser_comparison_url': '/',
                'wake_baseline': 'Sophia V4 / DET_MODE_95',
                'status': 'connected' if safe.get('device_protocol_confirmed') else 'waiting_for_device'},
                headers={'Cache-Control': 'no-store'})
        except Exception:
            return JSONResponse({'status': 'unavailable', 'code': 'brain_or_gateway_unavailable'},
                                status_code=503, headers={'Cache-Control': 'no-store'})

    @app.post('/api/sophia/control')
    async def control(request: Request):
        boundary(request, mutation=True)
        from .realtime_api import bounded_json
        body = await bounded_json(request, 1024)
        if set(body)-{'action', 'mode', 'muted'} or body.get('action') not in {'mode', 'mute', 'stop'}:
            raise HTTPException(422, 'invalid_sophia_control')
        config, auth = await asyncio.to_thread(connection)
        try:
            async with client_factory(trust_env=False, timeout=5) as client:
                result = await client.post('http://127.0.0.1:18781/api/v1/voice-ws/control',
                    headers=auth, json={**body, 'source': 'device', 'device_id': config['device_id']})
            return JSONResponse(result.json(), status_code=result.status_code,
                                headers={'Cache-Control': 'no-store'})
        except httpx.HTTPError:
            raise HTTPException(503, 'voice_control_unavailable') from None

    @app.post('/api/sophia/browser/bind')
    async def browser_bind(request: Request):
        boundary(request, mutation=True)
        # Serve terminates TLS and uvicorn keeps proxy_headers=False. Only the
        # exact private HTTPS Host/Origin authorizes cookie enrollment; never XFF.
        if request.headers.get('host') != BROWSER_HOST or request.headers.get('origin') != BROWSER_ORIGIN:
            raise HTTPException(403, 'browser_binding_requires_private_https')
        from .realtime_api import bounded_json
        if await bounded_json(request, 256) != {}:
            raise HTTPException(422, 'browser_guest_bind_empty_object_required')
        key = await asyncio.to_thread(brain_key)
        if not isinstance(key, str) or not key:
            raise HTTPException(503, 'browser_binding_unavailable')
        try:
            scope = await asyncio.to_thread(browser_guest_binding, root,
                request.cookies.get(BROWSER_COOKIE), key)
            created = False
            cookie = None
        except PermissionError as error:
            if str(error) not in {'browser_binding_missing', 'browser_binding_invalid', 'browser_binding_expired'}:
                raise HTTPException(409, str(error)) from None
            # Explicit user setup can replace a missing/expired credential, but
            # the caller cannot supply any identity, role, consent or policy ID.
            nonce = secrets.token_hex(16)
            owner = 'browser-sophia-'+nonce
            def create_guest():
                from .device_store import DeviceStore
                directory = root/'data/browser-devices'
                if directory.is_symlink() or (directory/'profiles.sqlite').is_symlink():
                    raise PermissionError('browser_binding_unavailable')
                store = DeviceStore(directory)
                return store.profile(owner+'@sophia')
            try:
                profile = await asyncio.to_thread(create_guest)
            except PermissionError as error:
                raise HTTPException(409, str(error)) from None
            scope = {'device_id': owner, 'client_id': profile.client_id}
            created = True
            cookie = browser_cookie_token(nonce, key)
        response = JSONResponse({'binding_present': True, 'created': created,
            'guest': True, 'device_id': scope['device_id'], 'client_id': scope['client_id'],
            'private_memory_allowed': False, 'paid_grant_created': False,
            'microphone_started': False, 'requires_explicit_start': True},
            headers={'Cache-Control': 'no-store'})
        if cookie:
            response.set_cookie(BROWSER_COOKIE, cookie, max_age=BROWSER_COOKIE_AGE,
                secure=True, httponly=True, samesite='strict', path='/')
        return response

    @app.get('/api/sophia/browser/status')
    async def browser_status(request: Request):
        boundary(request)
        try:
            _, _, state, admission = await browser_state(request)
            return JSONResponse({'source': 'browser', 'binding_present': True,
                'available': admission.get('allowed') is True,
                'generation_allowed': admission.get('generation_allowed') is True,
                'expert_available': admission.get('expert_available') is True,
                'code': admission.get('code', 'browser_admission_unavailable'),
                'brain': state, 'transport': 'B_WS', 'voice': 'marin',
                'requires_explicit_start': True, 'private_memory_allowed': False},
                headers={'Cache-Control': 'no-store'})
        except PermissionError as error:
            return JSONResponse({'source': 'browser', 'binding_present': False,
                'available': False, 'generation_allowed': False, 'code': str(error),
                'requires_explicit_start': True}, headers={'Cache-Control': 'no-store'})
        except Exception:
            return JSONResponse({'source': 'browser', 'available': False,
                'generation_allowed': False, 'code': 'browser_voice_status_unavailable'},
                status_code=503, headers={'Cache-Control': 'no-store'})

    @app.post('/api/sophia/browser/control')
    async def browser_control(request: Request):
        boundary(request, mutation=True)
        from .realtime_api import bounded_json
        body = await bounded_json(request, 1024)
        if set(body)-{'action', 'mode', 'muted'} or body.get('action') not in {'mode', 'mute', 'stop'}:
            raise HTTPException(422, 'invalid_sophia_control')
        try:
            scope, auth = await browser_scope(request)
            # Stop/Mute must remain usable when the spending grant has expired.
            async with client_factory(trust_env=False, timeout=5) as client:
                result = await client.post(backend+'/control', headers=auth,
                    json={**body, 'source': 'browser', **scope})
            return JSONResponse(result.json(), status_code=result.status_code,
                                headers={'Cache-Control': 'no-store'})
        except PermissionError as error:
            raise HTTPException(403, str(error)) from None
        except httpx.HTTPError:
            raise HTTPException(503, 'voice_control_unavailable') from None

    @app.websocket('/api/sophia/browser/stream')
    async def browser_stream(ws: WebSocket):
        try:
            boundary(ws, mutation=True)
        except HTTPException:
            await ws.close(code=1008)
            return
        await ws.accept()
        lease = None
        tasks = []
        try:
            raw = await asyncio.wait_for(ws.receive_text(), 8)
            if len(raw.encode()) > 1024:
                raise ValueError('invalid_browser_voice_hello')
            hello = json.loads(raw)
            if (not isinstance(hello, dict) or set(hello) != {
                    'type', 'session_id', 'conversation_id', 'mode', 'consent'} or
                    hello.get('type') != 'hello' or hello.get('consent') is not True or
                    hello.get('mode') not in {'fast', 'expert'} or
                    any(not isinstance(hello.get(k), str) or not re.fullmatch(
                        r'[A-Za-z0-9_.:-]{1,100}', hello[k]) for k in ('session_id', 'conversation_id'))):
                raise ValueError('invalid_browser_voice_hello')
            scope, auth, state, admission = await browser_state(ws)
            existing, input_allowed, expert_only = browser_resume(state, admission, hello)
            if state.get('sessions') and not existing:
                raise PermissionError('realtime_audio_session_already_active')
            if not input_allowed and not expert_only:
                raise PermissionError(admission.get('code', 'browser_admission_unavailable'))
            if not existing and hello['mode'] == 'expert' and admission.get('expert_available') is not True:
                raise PermissionError('browser_expert_not_authorized')
            await board_idle(auth)
            async with lease_lock:
                if scope['client_id'] in browser_leases:
                    raise PermissionError('microphone_source_already_attached')
                browser_leases.add(scope['client_id'])
                lease = scope['client_id']
            model = admission.get('model')
            if model not in {'gpt-realtime-2.1-mini', 'gpt-realtime-2.1'}:
                raise PermissionError('realtime_model_not_allowed')
            offer = {**scope, 'session_id': hello['session_id'],
                'conversation_id': hello['conversation_id'], 'client_kind': 'panel',
                'consent': True, 'expert_quota_consent': admission.get('expert_available') is True,
                'remember': False, 'speak': True, 'personalization_mode': 'guest',
                'speaker_consent': False, 'requested_voice': 'marin', 'requested_model': model,
                'input_mode': existing.get('input_mode', hello['mode']) if expert_only else hello['mode'],
                'endpointing': 'server_450'}
            async with ws_connector('ws://127.0.0.1:18781/api/v1/voice-ws/stream',
                    additional_headers=auth, proxy=None, open_timeout=5, close_timeout=2,
                    max_size=1048576, max_queue=4) as upstream:
                await upstream.send(json.dumps({'type': 'hello', 'source': 'browser', 'offer': offer}))
                input_open = False
                input_eligible = False
                media = asyncio.Queue(maxsize=8)
                send_lock = asyncio.Lock()
                credit = BrowserPlaybackCredit(enabled=expert_only)

                def discard_media():
                    while not media.empty():
                        media.get_nowait()

                async def send_browser(event, owner=None, samples=0):
                    async with send_lock:
                        if owner is not None and not credit.owns(owner):
                            return False
                        if samples and not credit.sent(owner, samples):
                            return False
                        await asyncio.wait_for(ws.send_json(event), 3)
                        return True

                async def from_browser():
                    nonlocal input_open, input_eligible
                    allowed = {
                        'wake': {'type', 'wake_id', 'mode'}, 'mode': {'type', 'mode'},
                        'mute': {'type', 'muted'}, 'stop': {'type'}, 'input_end': {'type'},
                        'playback_started': {'type', 'response_id'},
                        'playback_finished': {'type', 'response_id', 'segment_id'},
                        'playback_progress': {'type', 'response_id', 'played_samples'},
                        'ping': {'type'},
                    }
                    while True:
                        message = await asyncio.wait_for(ws.receive(), 75)
                        if message['type'] == 'websocket.disconnect':
                            return
                        pcm = message.get('bytes')
                        if pcm is not None:
                            if not 0 < len(pcm) <= 48000 or len(pcm) % 2:
                                raise ValueError('invalid_pcm24_frame')
                            if input_open:
                                await asyncio.wait_for(upstream.send(pcm), 3)
                            continue
                        text = message.get('text', '')
                        if len(text.encode()) > 4096:
                            raise ValueError('browser_voice_control_too_large')
                        obj = json.loads(text)
                        if not isinstance(obj, dict) or obj.get('type') not in allowed or set(obj)-allowed[obj['type']]:
                            raise ValueError('invalid_browser_voice_control')
                        kind = obj['type']
                        if kind == 'playback_progress':
                            credit.progress(obj)
                            continue  # Proxy-local flow credit is not a Brain playback receipt.
                        if kind in {'playback_started', 'playback_finished'} and not credit.receipt(obj):
                            continue
                        if expert_only and kind in {'wake', 'input_end'}:
                            raise PermissionError('expert_subscriber_has_no_microphone')
                        if kind == 'wake':
                            if not input_allowed:
                                raise PermissionError('browser_admission_unavailable')
                            credit.permit_input()
                            input_eligible = True
                        if kind in {'stop', 'mute', 'input_end'}:
                            input_open = False
                        if kind == 'stop' or kind == 'mute' and obj.get('muted') is True:
                            # Release a blocked writer BEFORE touching the upstream
                            # socket. Late PCM belongs to the revoked output owner.
                            input_eligible = False
                            credit.cancel()
                            discard_media()
                        await asyncio.wait_for(upstream.send(text), 3)

                async def to_browser():
                    nonlocal input_open, input_eligible
                    ordered_audio = {'audio_start', 'audio_chunk', 'audio_segment_done', 'audio_stop'}
                    priority = {'ready', 'listening', 'followup', 'input_closed', 'followup_closed',
                                'stopped', 'muted', 'closed', 'admission_denied', 'error',
                                'audio_cancel', 'mode_selected', 'pong', 'transport_disconnected',
                                'transport_reconnecting', 'transport_detached'}
                    async for raw in upstream:
                        if not isinstance(raw, str) or len(raw.encode()) > 1048576:
                            raise ValueError('invalid_brain_voice_event')
                        event = json.loads(raw)
                        if not isinstance(event, dict) or not isinstance(event.get('data', {}), dict):
                            raise ValueError('invalid_brain_voice_event')
                        kind, data = event.get('type'), event.get('data', {})
                        if kind in {'listening', 'followup'}:
                            input_open = input_eligible and input_allowed and not expert_only
                        elif kind in {'input_closed', 'followup_closed', 'audio_start', 'audio_cancel',
                                      'stopped', 'muted', 'closed', 'admission_denied', 'error',
                                      'transport_disconnected', 'transport_reconnecting'}:
                            input_open = False
                        if kind in {'stopped', 'closed', 'admission_denied', 'error', 'followup_closed'}:
                            input_eligible = False
                        if kind == 'audio_cancel':
                            if not credit.cancel(data.get('response_id'), revoke=False):
                                continue
                            discard_media()
                        elif kind in {'stopped', 'closed', 'admission_denied', 'error'} or kind == 'muted' and data.get('muted') is True:
                            credit.cancel()
                            discard_media()
                        if kind in ordered_audio:
                            owner = credit.begin(data.get('response_id')) if kind == 'audio_start' else credit.owner(data.get('response_id'))
                            if owner is None:
                                continue
                            if kind == 'audio_stop' and data.get('reason') != 'finished':
                                credit.cancel(data.get('response_id'), revoke=False)
                                discard_media()
                                await send_browser(event)
                            else:
                                await media.put((owner, event))
                        elif kind in priority:
                            await send_browser(event)
                        else:
                            # Captions/results remain ordered around their audio.
                            # Only transport/control events bypass the media writer.
                            await media.put((None, event))

                async def playback():
                    while True:
                        owner, event = await media.get()
                        if owner is not None and not credit.owns(owner):
                            continue
                        kind, data = event.get('type'), event.get('data', {})
                        if kind == 'audio_chunk':
                            await credit.pcm(event, owner, send_browser)
                        else:
                            if kind == 'audio_segment_done':
                                credit.segment(owner, data.get('segment_id'))
                            elif kind == 'audio_stop':
                                owner['sealed'] = True
                            await send_browser(event, owner)

                tasks = [asyncio.create_task(from_browser()), asyncio.create_task(to_browser()),
                         asyncio.create_task(playback())]
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    task.result()
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except (PermissionError, ValueError) as error:
            with contextlib.suppress(Exception):
                await ws.send_json({'type': 'error', 'data': {'code': str(error)[:160]}})
        except Exception:
            with contextlib.suppress(Exception):
                await ws.send_json({'type': 'error', 'data': {'code': 'browser_voice_transport_failed'}})
        finally:
            with anyio.CancelScope(shield=True):
                if lease:
                    browser_leases.discard(lease)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                # Transport detach preserves logical expert jobs; explicit Stop is
                # a separately forwarded command and never inferred from TCP close.
                with contextlib.suppress(Exception):
                    await ws.close()
