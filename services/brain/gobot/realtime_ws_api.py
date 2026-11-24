"""Authenticated, bounded duplex entry into the existing Brain.

The device and browser managers retain their own original authorization/ledger.
Opening an empty transport cannot borrow a different source's spending grant.
"""
import asyncio
import contextlib
import hmac
import json
import math
from pathlib import Path
import re
import sqlite3
import time
from collections import deque

import anyio
from fastapi import Depends, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from .realtime_api import bounded_json
from .realtime_provider import RealtimeProviderError


# A terminal output failure must also terminate the physical subscriber. Neither
# its cancellation frame nor the close handshake may wait behind a stalled send.
_TERMINAL_SEND_TIMEOUT = .5
_TERMINAL_CLOSE_TIMEOUT = 2.

_MEMORY_LOOKUP_STATES = frozenset({'disabled','ready','configuration_unavailable',
    'searching','hot_context_unavailable','no_related_context','delivered_late',
    'delivered_before_answer','lookup_timeout','lookup_unavailable','supplement_requested',
    'context_ack_unconfirmed'})
_MEMORY_SUMMARY_STATES = frozenset({'idle','unconfigured','budget_wait','queued','stale',
    'input_over_budget','budget_busy_or_already_attempted','counting','generating',
    'input_or_daily_budget_exceeded','applied','stale_or_rejected','cancelled',
    'invalid_or_unconfirmed_result','count_or_key_unavailable','usage_unknown',
    'count_unavailable','worker_failed','invalidated','completed','not_generated'})
_MEMORY_ERRORS = frozenset({'working_memory_owner_binding_required',
    'working_memory_change_requires_idle','working_memory_unavailable',
    'working_memory_policy_fields','working_memory_policy_boolean',
    'working_memory_ttl_range','working_memory_policy_invalid',
    'working_memory_policy_capacity','voice_source_not_mounted'})


def safe_working_memory_status(value):
    """Public owner diagnostics, never transcript, scope IDs, sources or secrets."""
    value=value if isinstance(value,dict) else {}
    def fields(obj,booleans=(),numbers=()):
        obj=obj if isinstance(obj,dict) else {}
        result={key:obj[key] for key in booleans if type(obj.get(key)) is bool}
        for key in numbers:
            number=obj.get(key)
            if type(number) not in (int,float) or number<0:continue
            try:
                if math.isfinite(number):result[key]=number
            except OverflowError:pass
        return result
    result=fields(value,('available','enabled','private_archive','diagnostics_available'),
                  ('supplements_per_question',))
    if value.get('trigger')=='every_question':result['trigger']='every_question'
    policy=value.get('policy',{})
    result['policy']=fields(policy,('enabled','persist','summarize','background','supplement'),('ttl_seconds',))
    lookup=value.get('lookup',{})
    result['lookup']=fields(lookup,(),('queries','useful_results','supplements','discarded',
        'hot_messages','hot_tokens','last_lookup_ms','last_sources'))
    if isinstance(lookup,dict):
        state=lookup.get('state')
        result['lookup']['state']=state if isinstance(state,str) and state in _MEMORY_LOOKUP_STATES else 'unavailable'
        omitted=lookup.get('omitted')
        if isinstance(omitted,list):
            allowed={'unheard_assistant_excluded','orphan_answer_excluded',
                'recent_exchange_over_budget','recent_exchange_excerpted','legacy_summary_contains_diagnostics',
                'summary_overlaps_recent_sources','summary_over_budget','facts_fragment_over_budget',
                'retrieved_fragment_over_budget'}
            result['lookup']['omitted']=[item for item in omitted[:24] if isinstance(item,str) and item in allowed]
    working=value.get('working',{})
    result['working']=fields(working,('enabled','persistence_requested','persisted'),
        ('version','ttl_seconds','source_count','available_exchanges','completed_exchanges',
         'restored_exchanges','expires'))
    if isinstance(working,dict):
        if isinstance(working.get('summary_kind'),str) and working['summary_kind'] in {'grounded_semantic_working_summary','attributed_working_sources'}:
            result['working']['summary_kind']=working['summary_kind']
        if working.get('coverage')=='scoped_partial_working_memory':result['working']['coverage']=working['coverage']
        error=working.get('error')
        result['working']['error']=error if error is None or isinstance(error,str) and error in {
            'checkpoint_decryption_unavailable','checkpoint_encryption_or_write_unavailable'} else 'unavailable'
    worker=value.get('summary_worker',{})
    result['summary_worker']=fields(worker,('enabled_for_scope','active'),
        ('daily_token_limit','primary_usage_fraction_limit','known_primary_tokens',
         'scope_tokens_used_or_reserved','global_tokens_used_or_reserved','available_tokens',
         'unknown_usage_attempts','queued','spoken_responses_created'))
    if isinstance(worker,dict):
        if worker.get('model')=='gpt-6-luna':result['summary_worker']['model']=worker['model']
        if isinstance(worker.get('budget_day_utc'),str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',worker['budget_day_utc']):
            result['summary_worker']['budget_day_utc']=worker['budget_day_utc']
        state=worker.get('last_state')
        result['summary_worker']['last_state']=state if isinstance(state,str) and state in _MEMORY_SUMMARY_STATES else 'unavailable'
    return result


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

    def memory_session(source,device_id,client_id,owner_test_binding=None):
        if (not isinstance(source,str) or source not in managers or
                not all(isinstance(value,str) and 0<len(value)<=256 for value in (device_id,client_id)) or
                owner_test_binding is not None and
                (not isinstance(owner_test_binding,str) or not 0<len(owner_test_binding)<=256)):
            raise HTTPException(422,'working_memory_exact_device_required')
        manager=manager_for(source)
        active=[session for session in sessions_for(manager,device_id)
                if session.offer.client_id==client_id and
                session.offer.owner_test_binding==owner_test_binding]
        if len(active)!=1:raise HTTPException(409,'voice_device_not_connected')
        flow=getattr(active[0],'memory_flow',None)
        if flow is None:raise HTTPException(409,'working_memory_unavailable')
        return flow

    def archive_context(source, device_id, client_id):
        """The permanent column archive does not require a paid/live session."""
        from .sophia_admin import SophiaAdmin
        if (source != 'device' or not isinstance(device_id, str)
                or not isinstance(client_id, str) or device_id != client_id
                or not re.fullmatch(r'spotpear-[a-f0-9]{12}', device_id)):
            raise HTTPException(422, 'archive_exact_device_required')
        manager = manager_for('device')
        memory = getattr(getattr(manager, 'brain', None), 'memory', None)
        service = getattr(memory, 'native_archive', None)
        if service is None:
            raise HTTPException(503, 'archive_unavailable')
        admin = SophiaAdmin(Path(memory.path).resolve().parent.parent)
        binding, record = admin.archive_binding()
        if device_id != record['target']:
            raise HTTPException(403, 'archive_exact_device_required')
        return service, admin, binding, record

    def archive_public(state, record):
        from .sophia_admin_access import safe_archive_status
        state = dict(state)
        skill = record['profile'].conversation.skills.memory
        state['lookup_blocked_by_skill'] = not skill
        state['read_effective'] = skill and state.get('policy', {}).get('read_enabled') is True
        return safe_archive_status(state)

    def archive_error(error):
        from .sophia_admin_access import ARCHIVE_ERROR_CODES
        code = str(error)
        code = code if code in ARCHIVE_ERROR_CODES else 'archive_unavailable'
        status = (409 if code in {'archive_revision_conflict', 'archive_operation_conflict',
                                  'archive_context_changed', 'archive_change_requires_idle'}
                  else 403 if code in {'archive_owner_required', 'archive_binding_invalid'}
                  else 503 if code in {'archive_unavailable', 'archive_context_reset_required'} else 422)
        return HTTPException(status, code)

    @app.get('/api/v1/voice-ws/archive', dependencies=[Depends(auth)])
    async def archive_status(request: Request, source: str = 'device', device_id: str = '',
                             client_id: str = '', operation_id: str | None = None,
                             actor_id: str | None = None):
        fields = {'source', 'device_id', 'client_id', 'operation_id', 'actor_id'}
        if (set(request.query_params)-fields
                or any(len(request.query_params.getlist(key)) != 1 for key in request.query_params)
                or operation_id is not None and (not re.fullmatch(r'[A-Za-z0-9_-]{16,80}', operation_id)
                    or actor_id is None or not re.fullmatch(r'[a-f0-9]{64}', actor_id))
                or operation_id is None and actor_id is not None):
            raise HTTPException(422, 'invalid_archive_control')
        try:
            service, admin, binding, record = await asyncio.to_thread(
                archive_context, source, device_id, client_id)
            state = await asyncio.to_thread(service.status, binding,
                                           operation_id=operation_id, actor_id=actor_id)
            if not await asyncio.to_thread(admin.archive_binding_current, binding):
                raise HTTPException(409, 'archive_context_changed')
            return JSONResponse({'archive': archive_public(state, record), 'observed_at': time.time()},
                                headers={'Cache-Control': 'no-store, private'})
        except (PermissionError, ValueError, TypeError) as error:
            raise archive_error(error) from None
        except RuntimeError as error:
            raise archive_error(error) from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, 'archive_unavailable') from None

    @app.post('/api/v1/voice-ws/archive', dependencies=[Depends(auth)])
    async def archive_control(request: Request):
        from .sophia_admin import validate_archive_control
        data = await bounded_json(request, 2500)
        scope_fields = {'source', 'device_id', 'client_id', 'actor_id'}
        body = {key: value for key, value in data.items() if key not in scope_fields}
        validate_archive_control(body)
        if (not isinstance(data.get('actor_id'), str)
                or not re.fullmatch(r'[a-f0-9]{64}', data['actor_id'])):
            raise HTTPException(422, 'archive_owner_required')
        try:
            service, admin, binding, record = await asyncio.to_thread(
                archive_context, data.get('source'), data.get('device_id'), data.get('client_id'))
            sessions = [session for session in sessions_for(manager_for('device'), binding.device_id)
                        if session.offer.client_id == binding.client_id]
            flows = []
            async with contextlib.AsyncExitStack() as locks:
                for session in sorted(sessions, key=lambda item: item.id):
                    flow = getattr(session, 'memory_flow', None)
                    if flow is None or not hasattr(flow, 'require_archive_idle'):
                        raise HTTPException(409, 'archive_change_requires_idle')
                    await locks.enter_async_context(session.lock)
                    await locks.enter_async_context(session.activation_lock)
                    flow.require_archive_idle()
                    flows.append(flow)

                def current():
                    if not admin.archive_binding_current(binding):
                        return False
                    try:
                        for flow in flows:
                            if flow.session.closed:
                                return False
                            flow.require_archive_idle()
                        return True
                    except (ValueError, PermissionError):
                        return False

                previous = await asyncio.to_thread(service.status, binding)
                method = service.configure if body['action'] == 'configure' else service.clear
                args = [binding]
                if body['action'] == 'configure':
                    args.append(body['values'])
                args.append(body['expected_revision'])
                state = await asyncio.to_thread(method, *args, operation_id=body['operation_id'],
                    actor_id=data['actor_id'], is_current=current)
                old_policy, policy = previous['policy'], state['policy']
                shorter = policy['retention_days'] > 0 and (old_policy['retention_days'] == 0
                    or policy['retention_days'] < old_policy['retention_days'])
                clear_context = body['action'] == 'clear' or shorter or (
                    old_policy['read_enabled'] and not policy['read_enabled'])
                if state.get('operation', {}).get('replayed') is not True:
                    for flow in flows:
                        await flow.archive_changed(clear_context=clear_context)
            public = archive_public(state, record)
            if (not public.get('operation') or public['operation']['id'] != body['operation_id']
                    or public['operation']['applied_revision'] != body['expected_revision']+1):
                raise HTTPException(503, 'archive_unavailable')
            return JSONResponse({'accepted': True, 'archive': public, 'observed_at': time.time()},
                                headers={'Cache-Control': 'no-store, private'})
        except (PermissionError, ValueError, TypeError) as error:
            raise archive_error(error) from None
        except RuntimeError as error:
            raise archive_error(error) from None
        except (OSError, sqlite3.Error):
            raise HTTPException(503, 'archive_unavailable') from None

    @app.get('/api/v1/voice-ws/memory',dependencies=[Depends(auth)])
    async def memory_status(source:str='device',device_id:str='',client_id:str='',
                            owner_test_binding:str|None=None):
        try:
            flow=memory_session(source,device_id,client_id,owner_test_binding)
            state=await asyncio.to_thread(flow.status)
            if asyncio.iscoroutine(state):state=await state
            return JSONResponse({'memory':safe_working_memory_status(state),'observed_at':time.time()},
                                headers={'Cache-Control':'no-store'})
        except PermissionError as error:
            raise HTTPException(403,str(error) if str(error) in _MEMORY_ERRORS else 'working_memory_unavailable') from None
        except (ValueError,OSError,RuntimeError):
            raise HTTPException(503,'working_memory_unavailable') from None

    @app.post('/api/v1/voice-ws/memory',dependencies=[Depends(auth)])
    async def memory_control(request:Request):
        data=await bounded_json(request,2000)
        if set(data)-{'source','device_id','client_id','owner_test_binding','action','values','confirm'}:
            raise HTTPException(422,'invalid_working_memory_control')
        try:
            flow=memory_session(data.get('source'),data.get('device_id'),data.get('client_id'),data.get('owner_test_binding'))
            if data.get('action')=='configure' and set(data)<= {'source','device_id','client_id','owner_test_binding','action','values'}:
                from .working_memory_policy import WorkingMemoryPolicyStore
                values=WorkingMemoryPolicyStore.validate(data.get('values'))
                state=await flow.set_policy(values)
            elif data.get('action')=='clear' and set(data)<= {'source','device_id','client_id','owner_test_binding','action','confirm'}:
                if data.get('confirm') is not True:raise HTTPException(422,'working_memory_clear_confirmation_required')
                state=await flow.clear()
            else:raise HTTPException(422,'invalid_working_memory_control')
            return JSONResponse({'accepted':True,'memory':safe_working_memory_status(state),'observed_at':time.time()},
                                headers={'Cache-Control':'no-store'})
        except PermissionError as error:
            raise HTTPException(403,str(error) if str(error) in _MEMORY_ERRORS else 'working_memory_unavailable') from None
        except ValueError as error:
            code=str(error) if str(error) in _MEMORY_ERRORS else 'invalid_working_memory_control'
            raise HTTPException(409 if code=='working_memory_change_requires_idle' else 422,code) from None
        except (OSError,RuntimeError,RealtimeProviderError):
            raise HTTPException(503,'working_memory_unavailable') from None

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
                'selected_expert': s.selected_expert_status() if hasattr(s, 'selected_expert_status') else None,
                'capabilities': s.capabilities.public() if hasattr(s, 'capabilities') else None,
                'lifecycle': s.lifecycle_status() if hasattr(s, 'lifecycle_status') else {},
            } for s in sessions]
            # Closed sessions remain explicit tombstones, including unknown
            # paid usage. Diagnostics expose no question/audio/provider payload.
            closed = [s for s in manager.sessions.values() if s.closed and device_id and
                      s.offer.device_id == device_id and (not client_id or
                      (s.offer.client_id == client_id and s.offer.owner_test_binding == owner_test_binding))]
            closed.sort(key=lambda s: getattr(s, 'closed_at', 0) or 0, reverse=True)
            tombstones = [{'session_id': s.id, 'conversation_id': s.offer.conversation_id,
                'lifecycle': s.lifecycle_status() if hasattr(s, 'lifecycle_status') else {}}
                for s in closed[:8]]
            result = {'source': source, 'transport': 'B_WS', 'status': state, 'sessions': safe,
                      'closed_sessions': tombstones}
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
        reader = writer = detached = None
        terminal_cancel = False
        error_code = None
        close_code = 1000
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
                if existing and not existing.closed and getattr(existing, '_duplex_attached', False):
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
                buffer_summaries = deque(maxlen=128)
                capture_boundaries = deque(maxlen=128)
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
                            capture = {'capture': obj['capture']} if 'capture' in obj else {}
                            await session.wake(obj.get('wake_id'), source=hello['source'],
                                mode=obj.get('mode', getattr(session, 'selected_mode', 'fast')),
                                trigger=obj.get('trigger', 'manual'), **capture)
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
                        request = {'request_id': obj['request_id']} if 'request_id' in obj else {}
                        await session.mute(obj['muted'], **request)
                    elif kind == 'stop':
                        request = {'request_id': obj['request_id']} if 'request_id' in obj else {}
                        await session.stop(**request)
                    elif kind == 'mode' and obj.get('mode') in {'fast', 'expert'}:
                        await session.select_mode(obj['mode'])
                    elif kind == 'input_end':
                        await session.finish_input()
                    elif kind == 'timer_capabilities' and hello['source'] == 'device':
                        session.timers.capabilities(obj)
                        await session.timers.refresh(force=True)
                    elif kind in {'timer_alarm_ack','timer_output_activity','timer_display_ack'} and hello['source'] == 'device':
                        await session.timers.command(obj)
                    elif kind == 'telemetry' and hello['source'] == 'device':
                        from .unified_voice_journal import capture_boundary, playback_buffer_summary
                        summary = playback_buffer_summary(obj)
                        if summary and summary['response_id'] not in buffer_summaries:
                            buffer_summaries.append(summary['response_id'])
                            # Existing opted-in content-free journal only. This
                            # cannot complete playback, open input or call a model.
                            # Do not echo it into the bounded audio/control queue.
                            with contextlib.suppress(Exception):
                                manager.journal.session_event(session, 'B', 'telemetry', summary)
                        boundary = capture_boundary(obj)
                        if boundary:
                            key = (boundary['stream_epoch'], boundary['stage'],
                                   boundary.get('wake_id'), boundary.get('response_id'))
                            if key not in capture_boundaries:
                                capture_boundaries.append(key)
                                # Numeric diagnostics only. An opaque cursor or
                                # floor never authorizes microphone/audio state.
                                with contextlib.suppress(Exception):
                                    manager.journal.session_event(session, 'B', 'telemetry', boundary)
                    elif kind == 'ping':
                        session.emit('pong')
                    else:
                        raise ValueError('unsupported_voice_control')

            async def events():
                while not session.closed:
                    await ws.send_json(await session.next_event())

            reader = asyncio.create_task(commands())
            writer = asyncio.create_task(events())
            watched = {reader, writer}
            signal = getattr(session, 'subscriber_detached', None)
            if signal is not None:
                # Capture this attachment's event. Reattachment installs a new
                # event and cannot revive an old subscriber's writer.
                detached = asyncio.create_task(signal.wait())
                watched.add(detached)
            done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
            if detached in done or signal is not None and signal.is_set():
                terminal_cancel = True
                if not session.closed and session.last_detach_reason == 'output_backpressure':
                    close_code = 1011
            else:
                for task in done:
                    task.result()
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        except (PermissionError, ValueError) as error:
            error_code = str(error)[:160]
        except RealtimeProviderError as error:
            code = str(error)
            if code not in {'openai_key_missing', 'realtime_network_error',
                            'realtime_configuration_rejected', 'realtime_settings_not_acknowledged'}:
                code = 'direct_voice_transport_failed'
            error_code = code
        except Exception:
            error_code = 'direct_voice_transport_failed'
        finally:
            # Disconnect can cancel the ASGI scope while its reader/writer are
            # still unwinding. Keep the capture lease until they have stopped
            # and detach has finished; otherwise an old finally can detach a
            # new subscriber which already reclaimed the same logical session.
            with anyio.CancelScope(shield=True):
                for task in (reader, writer, detached):
                    if task:
                        task.cancel()
                await asyncio.gather(*(t for t in (reader, writer, detached) if t), return_exceptions=True)
                try:
                    # There is now one writer. The close remains mandatory if
                    # backpressure prevents delivery of this best-effort cancel.
                    if terminal_cancel:
                        with contextlib.suppress(Exception):
                            await asyncio.wait_for(ws.send_json({'type': 'audio_cancel',
                                'data': {'response_id': None}}), _TERMINAL_SEND_TIMEOUT)
                        if session.closed:
                            close_code = 1000
                            # The queued close may have been trapped behind
                            # PCM. Let browser subscribers retire the logical ID
                            # even when that ordinary queue was never drained.
                            with contextlib.suppress(Exception):
                                await asyncio.wait_for(ws.send_json({'type': 'closed',
                                    'data': {}}), _TERMINAL_SEND_TIMEOUT)
                    if error_code:
                        with contextlib.suppress(Exception):
                            await asyncio.wait_for(ws.send_json({'type': 'error',
                                'data': {'code': error_code}}), _TERMINAL_SEND_TIMEOUT)
                    if session and owns_capture:
                        # A dropped transport is not an explicit expert-task cancellation.
                        await session.detach()
                finally:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(ws.close(code=close_code), _TERMINAL_CLOSE_TIMEOUT)
                    if session and owns_capture:
                        async with capture_lock:
                            session._duplex_attached = False
