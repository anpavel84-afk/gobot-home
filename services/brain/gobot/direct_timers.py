"""Native timer actions and local terminal delivery, independent of paid answers.

The provider may select an operation, never an owner, duration invented outside
the current utterance, or a delivery receipt. Only the authenticated physical
subscriber can acknowledge its own durably claimed alarm.
"""
import asyncio
from dataclasses import dataclass, replace
import json
import sqlite3
import time

from .expert_stream import conversation_binding
from .timer_service import ALARM_LATE_SECONDS


TOOL = {
    'type': 'function', 'name': 'timer_action',
    'description': ('Исполнить настоящую текущую просьбу пользователя поставить таймер, '
                    'узнать оставшееся время или отменить таймер. Выбери действие по смыслу '
                    'реплики, в том числе в середине обычной беседы. Цитата, условие, отрицание '
                    'или твоя собственная идея не дают команды. Передавай всю длительность '
                    'из текущей реплики; допустима равнозначная запись цифрами или в секундах. Не угадывай.'),
    'parameters': {'type': 'object', 'properties': {
        'operation': {'type': 'string', 'enum': ['start', 'status', 'cancel']},
        'duration_text': {'type': 'string', 'maxLength': 120},
        'target': {'type': 'string', 'enum': ['only', 'all', 'ordinal']},
        'ordinal': {'type': 'integer', 'minimum': 1, 'maximum': 5}},
        'required': ['operation'], 'additionalProperties': False}}

INSTRUCTIONS = '''
Таймер во время разговора: вызывай timer_action сразу по настоящей просьбе, без эксперта.
operation=start и duration_text — вся названная пользователем длительность, например
«пять минут», «300 секунд», «полторы минуты» или «1 минута 30 секунд». Сервер сверяет
равнозначность с оригиналом. Не добавляй отсутствующую единицу и не выбирай из альтернатив.
Если аргумент не указан, сервер сам проверит полную реплику. При настоящей неоднозначности
или отсутствии длительности задай одно уточнение. Не требуй специального формата речи.
При ошибке не говори «попробую» и не утверждай, что таймер поставлен. При однозначной
длительности сообщи подтверждённый результат сразу; при конфликте уточни длительность.
timer_duration_source_mismatch означает несогласованность распознавания и аргумента,
а не неправильный формат речи пользователя. Не проси говорить в специальном формате.
До вызова не произноси «сейчас попробую»: сначала инструмент, затем его результат.
operation=status получает текущие таймеры и оставшееся время. Для cancel target=only
допустим один таймер; all — только настоящая просьба отменить все. ordinal означает
номер из недавно показанного сервером списка, а не придуманную нумерацию.
Сначала дождись результата. Только executed=true подтверждает действие. replayed=true
означает прежнее действие этой же реплики, а не новый таймер. Ответ «таймер запущен»
не означает подтверждённый экран или сигнал: состояние доставки приходит отдельно.
Повторный вызов инструмента по одной пользовательской реплике не создаёт новый таймер.
'''


@dataclass(frozen=True)
class TimerCall:
    call_id: str
    response_id: str
    turn: object
    instruction: str
    input_revision: int
    input_epoch: int
    transport_epoch: int
    binding: tuple
    arguments: str
    selected_mode: str = 'fast'


class DirectTimers:
    def __init__(self, session):
        self.session = session
        self.pending = {}
        self.claims = {}
        self.snapshot_revision = None
        self.attachment_epoch = None
        self.next_check = 0.
        self.display_supported = False
        self.signal_supported = False
        self.capabilities_seen = False
        self.display_confirmed = False
        self.signal_confirmed = False
        self.display_state = None
        self.output_active = set()
        self.error = None
        self.last_checked_at = None
        self.refresh_lock = asyncio.Lock()
        self.stop_floor = 0.

    @property
    def service(self):
        return self.session.manager.brain.tools.timers

    def request(self, text='Таймеры устройства', turn=None):
        s = self.session
        return s.timer_request(text, turn or s.id)

    def current(self, call, *, final=True):
        s, turn = self.session, call.turn
        return bool(turn is s.current and turn and not turn.cancelled and not turn.local_control
            and s.ready and s.attached and not s.closed and not s._closing and not s.muted
            and not s._stop_count and s.selected_mode == call.selected_mode
            and s._input_gate_epoch == call.input_epoch and s.transport_epoch == call.transport_epoch
            and conversation_binding(s) == call.binding
            and (not final or turn.query == call.instruction and turn.input_revision == call.input_revision))

    def capture(self, event):
        s = self.session
        call_id, response_id = event.get('call_id'), event.get('response_id')
        if (not isinstance(call_id, str) or not 1 <= len(call_id) <= 128 or call_id in s.calls
                or not s.response_event_current(response_id)):
            return None
        turn = s.response_turn.get(response_id)
        if turn is not s.current or not turn:
            return None
        call = TimerCall(call_id, response_id, turn, turn.query, turn.input_revision,
            s._input_gate_epoch, s.transport_epoch, conversation_binding(s), event.get('arguments', '{}'), s.selected_mode)
        if not self.current(call, final=False):
            return None
        s.calls.add(call_id)
        self.pending[call_id] = call
        while len(self.pending) > 32:
            self.pending.pop(next(iter(self.pending)))
        return call

    async def local_input(self, turn):
        """A completed expert-input transcript may request a local timer, not CLI.

        This application action has no invented provider function call. Preserve
        the persistent expert selection; use its existing native voice for ACK.
        """
        from .quick_intents import resolve_quick
        s = self.session
        call = TimerCall('', '', turn, turn.query, turn.input_revision,
            s._input_gate_epoch, s.transport_epoch, conversation_binding(s), '{}', s.selected_mode)
        if not self.current(call):return False
        req = self.request(turn.query, turn.id)
        context = await asyncio.to_thread(s.manager.brain.memory.context, req)
        quick = resolve_quick(turn.query, context)
        if not quick or not (quick.executor in {'timer', 'timer_status'} or
                quick.executor == 'quick_clarify' and quick.intent.startswith('timer_')):return False
        if not self.current(call):return True
        try:
            permission = await s.require_capability('timer')
            def authorized():
                if not self.current(call):return False
                try:return s.timer_scope_authorized() and s.capabilities.settings()['revision'] == permission['settings_revision']
                except (ValueError, OSError):return False
            slots = {**quick.slots, 'intent':quick.intent, 'status':quick.status, 'reason':quick.reason}
            result = await asyncio.to_thread(s.manager.brain.tools.execute, quick.executor, req, slots,
                action_id='native-timer:'+turn.id, is_current=authorized)
            if not await asyncio.to_thread(authorized):return True
            if result.widget:
                frame = s.manager.brain.visual.timer(req, result.widget)
                s.emit('visual_response', presentation=frame.model_dump())
            await self.refresh(force=True)
            output = {'text':result.text, 'evidence':result.evidence,
                'executed':(result.evidence or {}).get('executed') is True}
        except (ValueError, PermissionError) as error:
            if not self.current(call):return True
            allowed = {'capability_disabled_by_owner', 'conversation_settings_unavailable',
                'capability_unavailable', 'invalid_timer_duration', 'action_payload_conflict',
                'timer_action_context_changed'}
            output = {'executed':False, 'error':str(error) if str(error) in allowed else 'timer_action_not_executed'}
        if not self.current(call):return True
        s.manager.journal.session_event(s, 'B', 'tool_result',
            {'name':'timer_action', 'result':output})
        turn.mode_action_handled = True
        turn.mode_action_ack = output
        # This completed, explicitly activated input may reserve its ordinary
        # acknowledgement under the existing B allowance. No CLI or retry.
        await s.admission(explicit_wake=True)
        if not self.current(call):return True
        await s.response()
        return True

    async def execute(self, call_id, arguments, turn):
        call = self.pending.pop(call_id, None)
        if not call or call.turn is not turn or call.arguments != arguments:
            return
        s = self.session
        try:
            if not self.current(call, final=False):return
            await asyncio.wait_for(turn.consent_ready.wait(), 5)
            if not self.current(call, final=False):return
            if not call.instruction and not call.input_revision:
                call = replace(call, instruction=turn.query, input_revision=turn.input_revision)
            if not self.current(call) or not call.instruction:return
            if not isinstance(arguments, str) or len(arguments) > 1500:
                raise ValueError('invalid_timer_arguments')
            args = json.loads(arguments)
            if (not isinstance(args, dict) or 'operation' not in args or
                    set(args)-{'operation','duration_text','target','ordinal'} or
                    not isinstance(args['operation'], str) or
                    args['operation'] not in {'start','status','cancel'}):
                raise ValueError('invalid_timer_arguments')
            permission = await s.require_capability('timer')
            if not self.current(call):return
            def authorized():
                if not self.current(call):return False
                try:return (s.timer_scope_authorized() and
                    s.capabilities.settings()['revision'] == permission['settings_revision'])
                except (ValueError, OSError):return False
            req = self.request(call.instruction, turn.id)
            s.manager.journal.session_event(s, 'B', 'tool_request', {
                'call_id': call_id, 'name': 'timer_action', 'arguments': args})
            result = await asyncio.to_thread(s.manager.brain.tools.execute_timer_action, req,
                **args, action_id='native-timer:'+turn.id, is_current=authorized)
            if not await asyncio.to_thread(authorized) or not self.current(call):return
            output = {'text': result.text, 'evidence': result.evidence, 'executed_by': 'gobot_server',
                      'executed': (result.evidence or {}).get('executed') is True,
                      'ordinary_conversation_available': True}
            if self.current(call) and result.widget:
                frame = s.manager.brain.visual.timer(req, result.widget)
                s.emit('visual_response', presentation=frame.model_dump())
            await self.refresh(force=True)
            if args['operation'] == 'start' and output['executed']:
                output['delivery'] = {
                    'scope': 'this_timer', 'display': 'pending' if self.display_supported else 'unavailable'
                        if self.capabilities_seen else 'unconfirmed',
                    'signal': 'scheduled' if self.signal_supported else 'unavailable'
                        if self.capabilities_seen else 'unconfirmed',
                    'display_rendered': False, 'signal_played': False,
                    'display_supported': self.display_supported, 'signal_supported': self.signal_supported}
            else:
                output['delivery'] = {'scope': 'device_capability', **self.delivery_status()}
        except asyncio.CancelledError:
            raise
        except (ValueError, PermissionError, TimeoutError, OSError) as error:
            allowed = {'invalid_timer_arguments','invalid_timer_duration','timer_duration_source_required',
                'timer_action_context_changed','action_payload_conflict','timer_selection_required',
                'capability_disabled_by_owner','conversation_settings_unavailable','capability_unavailable',
                'timer_current_user_command_required','timer_duration_ambiguous','invalid_timer_action',
                'current_user_command_required','timer_target_source_mismatch','timer_duration_source_mismatch'}
            reason = str(error) if str(error) in allowed else 'timer_action_not_executed'
            output = {'executed': False, 'error': reason, 'ordinary_conversation_available': True}
            if reason == 'timer_duration_source_mismatch':
                output['text'] = 'Таймер не установлен: я неточно расслышал просьбу. Повторите её, пожалуйста.'
        if not self.current(call):return
        sent = await s.send({'type': 'conversation.item.create', 'item': {
            'type': 'function_call_output', 'call_id': call_id,
            'output': json.dumps(output, ensure_ascii=False)}}, _conversation_mode_gate=lambda: self.current(call))
        if sent and self.current(call):
            s.manager.journal.session_event(s, 'B', 'tool_result', {
                'call_id': call_id, 'name': 'timer_action', 'result': output})
            await s.response()

    def capabilities(self, obj):
        if (set(obj) != {'type','display_supported','signal_supported'} or
                any(type(obj.get(key)) is not bool for key in ('display_supported','signal_supported'))):
            raise ValueError('invalid_timer_capabilities')
        self.display_supported = obj['display_supported']
        self.signal_supported = obj['signal_supported']
        self.capabilities_seen = True
        if not self.display_supported:self.display_confirmed = False
        if not self.signal_supported:self.signal_confirmed = False
        self.snapshot_revision = None

    def delivery_status(self):
        def state(supported, confirmed):
            return 'confirmed' if supported and confirmed else 'unconfirmed' if supported or not self.capabilities_seen else 'unavailable'
        return {'display': state(self.display_supported, self.display_confirmed),
                'signal': state(self.signal_supported, self.signal_confirmed),
                'display_supported': self.display_supported, 'signal_supported': self.signal_supported}

    def connected(self):
        s = self.session
        return s.source == 'device' and s.attached and not s.closed and not s._closing and self.capabilities_seen

    async def refresh(self, *, force=False, now=None):
        if self.refresh_lock.locked():return False
        async with self.refresh_lock:
            return await self._refresh(force=force, now=now)

    async def _refresh(self, *, force=False, now=None):
        now = time.monotonic() if now is None else now
        if not self.connected() or not force and now < self.next_check:return False
        self.next_check = now+1.
        s = self.session
        epoch, input_epoch = s._attachment_epoch, s._input_gate_epoch
        try:
            await s.require_transport_scope()
            if not await asyncio.to_thread(s.timer_scope_authorized):
                raise PermissionError('timer_scope_unavailable')
            req = self.request()
            snapshot = await asyncio.to_thread(self.service.snapshot, req)
            if not await asyncio.to_thread(s.timer_scope_authorized):
                raise PermissionError('timer_scope_unavailable')
            if not self.connected() or epoch != s._attachment_epoch:return False
            if force or snapshot['revision'] != self.snapshot_revision or epoch != self.attachment_epoch:
                if snapshot['revision'] != self.snapshot_revision or epoch != self.attachment_epoch:
                    self.display_confirmed = False
                s.emit('timer_snapshot', **snapshot)
                self.snapshot_revision = snapshot['revision']
                self.attachment_epoch = epoch
            # A disabled skill suppresses future expiry output, but never deletes
            # the already-owned persistent timer or changes its user's settings.
            self.claims = {key: value for key, value in self.claims.items() if value['expires_at']+30 > time.time()}
            self.output_active.intersection_update(self.claims)
            if self.signal_supported and len(self.claims) < 16:
                alarms = await asyncio.to_thread(self.service.claim_due, req, s.id, limit=16-len(self.claims))
                for alarm in alarms:
                    allowed, still_authorized = await asyncio.gather(
                        asyncio.to_thread(s.capabilities.enabled_now, 'timer'),
                        asyncio.to_thread(s.timer_scope_authorized))
                    if (not self.connected() or epoch != s._attachment_epoch
                            or input_epoch != s._input_gate_epoch or s.muted or s._stop_count
                            or not allowed or not still_authorized
                            or alarm['expires_at']-ALARM_LATE_SECONDS <= self.stop_floor):
                        await asyncio.to_thread(self.service.ack, req, alarm['alarm_id'], alarm['claim_id'], 'suppressed')
                        continue
                    self.claims[alarm['alarm_id']] = alarm
                    self.signal_confirmed = False
                    s.emit('timer_alarm', **alarm)
            self.last_checked_at = time.time()
            self.error = None
            return True
        except asyncio.CancelledError:
            raise
        except (ValueError, PermissionError, OSError, RuntimeError, sqlite3.Error):
            self.error = 'timer_delivery_unavailable'
            return False

    async def command(self, obj):
        try:
            accepted = await self._command(obj)
        except ValueError:
            self.session.manager.journal.session_event(self.session,'B','timer_receipt',
                {'receipt_type':obj.get('type'), 'accepted':False})
            raise
        self.session.manager.journal.session_event(self.session,'B','timer_receipt',
            {**obj,'receipt_type':obj.get('type'),'render_evidence':obj.get('evidence'),
             'accepted':accepted is True, 'not_acoustic_proof':True})
        return accepted

    async def _command(self, obj):
        if not self.connected():
            raise ValueError('timer_device_not_attached')
        kind = obj['type']
        if kind == 'timer_display_ack':
            if (set(obj) != {'type','snapshot_revision','state','evidence','rendered'} or
                    type(obj.get('snapshot_revision')) is not int or
                    obj['snapshot_revision'] != self.snapshot_revision or
                    obj.get('state') not in {'running','expired','clear'} or
                    obj.get('evidence') not in {'native_framebuffer_invalidated','native_framebuffer_unchanged'} or
                    type(obj.get('rendered')) is not bool):
                return False
            self.display_state = obj['state']
            # Empty-screen ACK is not evidence that a countdown was rendered.
            if self.display_supported and obj['state'] in {'running','expired'} and obj['rendered']:
                self.display_confirmed = True
            return True
        expected = {'type','alarm_id','claim_id','active' if kind == 'timer_output_activity' else 'state'}
        if set(obj) != expected:
            raise ValueError('invalid_timer_alarm_receipt')
        alarm = self.claims.get(obj.get('alarm_id'))
        if not alarm or obj.get('claim_id') != alarm['claim_id']:
            return False
        if kind == 'timer_output_activity':
            if type(obj.get('active')) is not bool:raise ValueError('invalid_timer_alarm_receipt')
            if obj['active']:self.output_active.add(alarm['alarm_id'])
            else:self.output_active.discard(alarm['alarm_id'])
            return True
        state = obj.get('state')
        if state not in {'started','finished','cancelled','suppressed','unknown'}:
            raise ValueError('invalid_timer_alarm_receipt')
        s = self.session
        epoch, req = s._attachment_epoch, self.request()
        def current():
            return bool(self.connected() and s._attachment_epoch == epoch and
                        self.claims.get(alarm['alarm_id']) is alarm and s.timer_scope_authorized())
        try:
            accepted = await asyncio.to_thread(self.service.ack, req, alarm['alarm_id'], alarm['claim_id'], state,
                                              is_current=current)
        except (PermissionError, sqlite3.Error, OSError):
            return False
        if not current():return False
        if accepted and state == 'finished':self.signal_confirmed = True
        if state != 'started':
            # Cancellation may already be durable before this physical terminal
            # receipt. Release its local owner, without relabelling it as played.
            self.output_active.discard(alarm['alarm_id'])
            self.claims.pop(alarm['alarm_id'], None)
        return accepted

    def detach(self):
        self.capabilities_seen = False
        self.display_supported = self.signal_supported = False
        self.display_confirmed = self.signal_confirmed = False
        self.snapshot_revision = self.attachment_epoch = None
        self.claims.clear()
        self.output_active.clear()

    def stop(self):
        # A late SQL claim cannot reintroduce an already-due alarm after Stop.
        # Future running deadlines remain active; Stop is not "cancel all".
        self.stop_floor = time.time()

    def status(self):
        return {**self.delivery_status(), 'capabilities_received': self.capabilities_seen,
                'snapshot_revision': self.snapshot_revision, 'display_state': self.display_state,
                'pending_claims': len(self.claims), 'output_active': bool(self.output_active),
                'checked_at': self.last_checked_at, 'error': self.error}


async def expire_timers(service, stop):
    """One Brain lifespan worker. No session, response, speech or model creation."""
    state = service.timer_expiry_status = {'running': True, 'expired': 0, 'error': None, 'checked_at': None}
    try:
        while not stop.is_set():
            try:
                state['expired'] += await asyncio.to_thread(service.tools.timers.expire_due)
                state.update(error=None, checked_at=time.time())
            except asyncio.CancelledError:
                raise
            except Exception:
                state['error'] = 'timer_expiry_unavailable'
            try:await asyncio.wait_for(stop.wait(), 1.)
            except TimeoutError:pass
    finally:
        state['running'] = False
