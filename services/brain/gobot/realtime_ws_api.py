"""Authenticated, bounded duplex entry into the existing Brain.

The device and browser managers retain their own original authorization/ledger.
Opening an empty transport cannot borrow a different source's spending grant.
"""
import asyncio
import contextlib
import hmac
import json

import anyio
from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .realtime_api import bounded_json
from .realtime_provider import RealtimeProviderError


def attach_brain_direct_voice(app, browser_manager, board_manager, auth, api_token):
    managers = {'browser': browser_manager, 'device': board_manager}
    capture_lock = asyncio.Lock()

    def manager_for(source):
        manager = managers.get(source)
        if manager is None:
            raise PermissionError('voice_source_not_mounted')
        return manager

    def sessions_for(manager, device):
        return [s for s in manager.sessions.values()
                if not s.closed and s.offer.device_id == device]

    def expert_active(session):
        active = getattr(getattr(session, 'experts', None), 'active', False)
        return bool(active() if callable(active) else active)

    @app.get('/api/v1/voice-ws/status', dependencies=[Depends(auth)])
    async def status(source: str = 'device', device_id: str = '', client_id: str = '',
                     owner_test_binding: str | None = None):
        try:
            manager = manager_for(source)
            state = manager.status()
            if asyncio.iscoroutine(state):
                state = await state
            sessions = sessions_for(manager, device_id) if device_id else []
            if client_id:
                sessions = [s for s in sessions if s.offer.client_id == client_id and
                            s.offer.owner_test_binding == owner_test_binding]
            safe = [{
                'session_id': s.id, 'conversation_id': s.offer.conversation_id,
                'ready': bool(s.ready), 'state': s.state,
                'input_mode': getattr(s, 'selected_mode', getattr(s.offer, 'input_mode', 'fast')),
                'muted': bool(getattr(s, 'muted', False)),
                'capture_connected': bool(getattr(s, '_duplex_attached', False)),
                'generation_allowed': bool(s.generation_allowed()),
                'expert_active': expert_active(s),
            } for s in sessions]
            result = {'source': source, 'transport': 'B_WS', 'status': state, 'sessions': safe}
            if client_id:
                preview = await asyncio.to_thread(manager.admission_preview,
                    client_id=client_id, device_id=device_id,
                    owner_test_binding=owner_test_binding, developer_acceptance=False)
                result['admission'] = await preview if asyncio.iscoroutine(preview) else preview
            return JSONResponse(result,
                                headers={'Cache-Control': 'no-store'})
        except PermissionError as error:
            return JSONResponse({'source': source, 'ready': False, 'code': str(error)},
                                status_code=409, headers={'Cache-Control': 'no-store'})

    @app.post('/api/v1/voice-ws/control', dependencies=[Depends(auth)])
    async def control(request: Request):
        data = await bounded_json(request, 2000)
        if set(data) - {'source', 'device_id', 'client_id', 'owner_test_binding', 'action', 'mode', 'muted'}:
            raise HTTPException(422, 'invalid_voice_control')
        try:
            manager = manager_for(data.get('source'))
            active = sessions_for(manager, data.get('device_id'))
            if 'client_id' in data:
                active = [s for s in active if s.offer.client_id == data['client_id'] and
                          s.offer.owner_test_binding == data.get('owner_test_binding')]
            if len(active) != 1:
                raise HTTPException(409, 'voice_device_not_connected')
            session = active[0]
            action = data.get('action')
            if action == 'mode' and data.get('mode') in {'fast', 'expert'}:
                await session.select_mode(data['mode'])
            elif action == 'mute' and type(data.get('muted')) is bool:
                await session.mute(data['muted'])
            elif action == 'stop':
                await session.stop()
            else:
                raise HTTPException(422, 'invalid_voice_control')
            return {'accepted': True, 'action': action}
        except PermissionError as error:
            raise HTTPException(403, str(error)) from None
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.websocket('/api/v1/voice-ws/stream')
    async def stream(ws: WebSocket):
        if not hmac.compare_digest(ws.headers.get('authorization', ''), 'Bearer ' + api_token):
            await ws.close(code=1008)
            return
        await ws.accept()
        session = None
        owns_capture = False
        reader = writer = None
        try:
            raw = await asyncio.wait_for(ws.receive_text(), 8)
            if len(raw.encode()) > 12000:
                raise ValueError('voice_hello_too_large')
            hello = json.loads(raw)
            if not isinstance(hello, dict) or set(hello) != {'type', 'source', 'offer'} or hello['type'] != 'hello':
                raise ValueError('voice_hello_required')
            manager = manager_for(hello['source'])
            from .realtime_ws import DirectOffer
            offer = DirectOffer.model_validate(hello['offer'])
            if (hello['source'] == 'device') != (offer.client_kind == 'device'):
                raise PermissionError('microphone_source_scope_mismatch')
            async with capture_lock:
                existing = manager.sessions.get(offer.session_id)
                if existing and getattr(existing, '_duplex_attached', False):
                    raise PermissionError('microphone_source_already_attached')
                session = await manager.accept(offer)
                if getattr(session, '_duplex_attached', False):
                    raise PermissionError('microphone_source_already_attached')
                session._duplex_attached = True
                owns_capture = True
            await ws.send_json({'type': 'transport_attached', 'data': {
                'session_id': session.id, 'conversation_id': offer.conversation_id,
                'source': hello['source'], 'sample_rate': 24000, 'protocol': 2}})

            async def commands():
                while True:
                    message = await ws.receive()
                    if message['type'] == 'websocket.disconnect':
                        return
                    if message.get('bytes') is not None:
                        pcm = message['bytes']
                        if not 0 < len(pcm) <= 48000 or len(pcm) % 2:
                            raise ValueError('invalid_pcm24_frame')
                        await session.append_pcm(pcm)
                        continue
                    text = message.get('text', '')
                    if len(text.encode()) > 4096:
                        raise ValueError('voice_control_too_large')
                    obj = json.loads(text)
                    if not isinstance(obj, dict):
                        raise ValueError('voice_control_required')
                    kind = obj.get('type')
                    if kind == 'wake':
                        try:
                            await session.wake(obj.get('wake_id'), source=hello['source'],
                                mode=obj.get('mode', getattr(session, 'selected_mode', 'fast')))
                        except PermissionError:
                            # The session emitted admission_denied. Preserve the
                            # empty pipe and local Sophia; do not retry spending.
                            continue
                    elif kind == 'playback_started':
                        await session.playback_started(obj.get('response_id'))
                    elif kind == 'playback_finished':
                        await session.playback_finished(obj.get('response_id'),
                            sample_floor=obj.get('sample_floor'), segment_id=obj.get('segment_id'))
                    elif kind == 'mute' and type(obj.get('muted')) is bool:
                        await session.mute(obj['muted'])
                    elif kind == 'stop':
                        await session.stop()
                    elif kind == 'mode' and obj.get('mode') in {'fast', 'expert'}:
                        await session.select_mode(obj['mode'])
                    elif kind == 'input_end':
                        await session.finish_input()
                    elif kind == 'ping':
                        session.emit('pong')
                    else:
                        raise ValueError('unsupported_voice_control')

            async def events():
                while not session.closed:
                    await ws.send_json(await session.next_event())

            reader = asyncio.create_task(commands())
            writer = asyncio.create_task(events())
            done, _ = await asyncio.wait({reader, writer}, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except (PermissionError, ValueError) as error:
            with contextlib.suppress(Exception):
                await ws.send_json({'type': 'error', 'data': {'code': str(error)[:160]}})
        except RealtimeProviderError as error:
            code = str(error)
            if code not in {'openai_key_missing', 'realtime_network_error',
                            'realtime_configuration_rejected', 'realtime_settings_not_acknowledged'}:
                code = 'direct_voice_transport_failed'
            with contextlib.suppress(Exception):
                await ws.send_json({'type': 'error', 'data': {'code': code}})
        except Exception:
            with contextlib.suppress(Exception):
                await ws.send_json({'type': 'error', 'data': {'code': 'direct_voice_transport_failed'}})
        finally:
            # Disconnect can cancel the ASGI scope while its reader/writer are
            # still unwinding. Always release the capture lease and detach the
            # output subscriber; otherwise the next connection remains locked.
            with anyio.CancelScope(shield=True):
                if session and owns_capture:
                    session._duplex_attached = False
                for task in (reader, writer):
                    if task:
                        task.cancel()
                await asyncio.gather(*(t for t in (reader, writer) if t), return_exceptions=True)
                if session and owns_capture:
                    # A dropped transport is not an explicit expert-task cancellation.
                    await session.detach()
                with contextlib.suppress(Exception):
                    await ws.close()
