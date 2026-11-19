"""Sophia controls on the existing private HTTPS application, not a new daemon.

The panel controls only the already-enrolled column. Browser Lab keeps its own
identity/ledger and microphone path; its comparison link never lends that grant
to the physical device. No provider key or owner grant is writable here.
"""
import asyncio
import ipaddress
import json
from pathlib import Path

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse


def attach_sophia_panel(app, main_root, *, client_factory=httpx.AsyncClient):
    root = Path(main_root)
    assets = root/'services/phone/dist'
    allowed_hosts = {'plan.tailffc57c.ts.net', '127.0.0.1:18811', 'localhost:18811'}
    origins = {'https://plan.tailffc57c.ts.net', 'http://127.0.0.1:18811', 'http://localhost:18811'}

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

    def connection():
        config = json.loads((root/'data/hardware/gobot-v1/gateway.json').read_text(encoding='utf-8'))
        key = json.loads((root/'run/keys.json').read_text(encoding='utf-8'))['api_token']
        return config, {'Authorization': 'Bearer '+key}

    @app.get('/sophia')
    async def page(request: Request):
        boundary(request)
        return FileResponse(assets/'sophia.html', media_type='text/html',
                            headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})

    @app.get('/sophia/{asset}')
    async def asset(asset: str, request: Request):
        boundary(request)
        if asset not in {'sophia.js', 'sophia.css'}:
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
                'last_wake_ui_visible_ms', 'device_resources', 'device_protocol_confirmed'}}
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
