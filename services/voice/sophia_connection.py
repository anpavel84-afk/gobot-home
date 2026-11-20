"""Negotiated Sophia V4 capture -> existing Brain B_WS -> one physical output.

Only the admitted input cursor reaches Brain. Idle/muted/playback PCM stays in
bounded local RAM or is discarded. Neither recordings nor text enter stats.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
from collections import deque
from contextlib import suppress
import json
import time
from urllib.parse import urlparse
from uuid import uuid4, uuid5, NAMESPACE_URL

from websockets.asyncio.client import connect

from sophia_audio import PcmRing, OrderedOpus, ContinuousPcm24


# The Brain's existing 200 ms wall-clock guard does not discard microphone
# packets that arrive late. Keep its equivalent in the device's 16 kHz capture
# coordinate too. This is read-progress evidence, never an acoustic DMA clock.
POST_PLAYBACK_CAPTURE_GUARD_SAMPLES = 3200
INTERRUPT_STOP_ACK_SECONDS = 6.


class PrefetchedSocket:
    """Preserve the original legacy receive contract after capability routing."""
    def __init__(self, socket, first):
        self.socket, self.first = socket, first

    def __getattr__(self, key):
        return getattr(self.socket, key)

    async def recv(self):
        if self.first is not None:
            result, self.first = self.first, None
            return result
        return await self.socket.recv()

    def __aiter__(self):
        return self

    async def __anext__(self):
        from websockets.exceptions import ConnectionClosedOK
        try:
            return await self.recv()
        except ConnectionClosedOK:
            raise StopAsyncIteration


def supports_sophia_v2(hello):
    caps = hello.get('host_stream', {}) if isinstance(hello, dict) else {}
    return (caps.get('version') == 2 and caps.get('local_wake_enabled') is True
            and caps.get('capture') == 'continuous' and caps.get('pcm_stage') == 'pre_afe')


class SophiaConnection:
    def __init__(self, config, token, *, session_id, conversation_id, encoder_factory,
                 connector=connect, decoder_factory=None, on_status=None):
        self.config, self.token = config, token
        self.options = config.get('unified_voice', {})
        self.logical_session = session_id
        self.conversation = conversation_id
        self.encoder_factory, self.connector = encoder_factory, connector
        self.on_status = on_status
        self.events = deque(maxlen=256)
        self.ring = PcmRing(seconds=self.options.get('ring_seconds', 10), on_event=self.trace)
        self.decoder = OrderedOpus(self.ring, decoder_factory)
        self.resampler = None
        self.device = self.brain = None
        self.transport = str(uuid4())
        self.epoch = uuid4().hex
        self.device_send_lock = asyncio.Lock()
        self.brain_send_lock = asyncio.Lock()
        self.cloud_ready = asyncio.Event()
        self.input_changed = asyncio.Event()
        self.forward = False
        self.muted = False
        self.mode = self.options.get('input_mode', 'fast')
        self.expert_audio_limit = self.options.get('expert_max_seconds', 180)
        self.output = None
        self.output_epoch = 0
        self.output_credit = asyncio.Event()
        self.cancel_finished = asyncio.Event()
        self.cancel_lock = asyncio.Lock()
        self.cancelled = deque(maxlen=128)
        self.pending_interrupt = None
        self.completed_stop_requests = deque(maxlen=128)
        self.activation_events = deque(maxlen=128)
        self.physical_mute_requests = {}
        self.latest_physical_mute_request = None
        self.device_mute_revision = None
        self.mute_control_epoch = 0
        self.tasks = set()
        self.closed = False
        self.capture_completion = None
        self.first_uplink_cursor = None
        self.endpoint = {'started': None, 'last_voice': None, 'noise': 80., 'samples': 0}
        self.stats = {'protocol': 2, 'mode': 'B_WS', 'pcm_stage': 'pre_afe',
                      'selected_mode': self.mode,
                      'wake_location': 'ESP', 'voice': 'marin', 'received_packets': 0,
                      'downlink_packets': 0, 'cloud_ready': False, 'generation_allowed': False,
                      'raw_audio_saved': False, 'text_saved': False, 'wake_events': 0,
                      'playback_started': 0, 'playback_finished': 0,
                      'last_error': None, 'input_open': False, 'output_metrics': [],
                      'output_summaries_sent': 0, 'output_summaries_dropped': 0,
                      'capture_boundaries': {}, 'capture_boundaries_sent': 0,
                      'capture_boundaries_dropped': 0,
                      'application_keepalives_sent': 0,
                      'last_application_keepalive_monotonic': None,
                      'device_control_messages': 0,
                      'last_device_control_monotonic': None,
                      'device_control_age_seconds': None,
                      'admission_status': {'known': False, 'mode': self.mode},
                      'invalid_admission_status': 0, 'stale_admission_status': 0,
                      'admission_receipt': None, 'discarded_admission_receipts': 0}

    def queue_capture_boundary(self, stage, **fields):
        data = {'type': 'telemetry', 'event': 'capture_boundary', 'stage': stage,
                'stream_epoch': self.ring.epoch, 'ring_end': self.ring.end,
                'sample_floor': self.ring.floor, 'plan_monotonic': time.monotonic(), **fields}
        # Exactly one bounded snapshot per stage. Persistent stats contain no
        # raw identifiers; the journal separately hashes the wire identifiers.
        snapshot = {key: value for key, value in data.items()
                    if key not in ('type', 'stream_epoch', 'response_id', 'wake_id')}
        for key in ('stream_epoch', 'response_id', 'wake_id'):
            if isinstance(data.get(key), str):
                snapshot[key+'_sha256'] = hashlib.sha256(data[key].encode()).hexdigest()
        self.stats['capture_boundaries'][stage] = snapshot
        self.spawn(self.send_capture_boundary(data))

    async def send_capture_boundary(self, data):
        try:
            await self.to_brain(data)
            self.stats['capture_boundaries_sent'] += 1
        except Exception:
            # Diagnostic failure must never change input, playback or admission.
            self.stats['capture_boundaries_dropped'] += 1

    def new_output_metrics(self, response_id, role):
        metrics = {'response_sha256': hashlib.sha256(response_id.encode()).hexdigest(),
            'audio_role': role if role in {'fast_answer', 'expert_answer', 'service_cue'} else 'other',
            'created_wall': time.time(), 'created_monotonic': time.monotonic(),
            'packets_sent': 0, 'progress_receipts': 0, 'duplicate_progress_receipts': 0,
            'invalid_progress_receipts': 0, 'last_packets_consumed': 0,
            'max_packet_send_gap_ms': 0., 'max_progress_receipt_gap_ms': 0.,
            'min_decode_pending': None, 'min_output_pending': None,
            'max_decode_pending': None, 'max_output_pending': None,
            'empty_software_queue_samples': 0, 'empty_queue_and_idle_writer_samples': 0,
            'underrun_count': None, 'underrun_measurement': 'not_instrumented',
            'drop_counters_start': {key: value for key in ('encode_drops', 'dropped_frames')
                if type(value := self.stats.get('device_resources', {}).get(key)) is int and value >= 0},
            'progress_points': []}
        self.stats['output_metrics'] = [*self.stats['output_metrics'], metrics][-2:]
        return metrics

    def queue_output_summary(self, state, reason):
        metrics = state['metrics']
        if metrics.get('summary_queued'):
            return
        metrics['summary_queued'] = True
        fields = ('packets_sent', 'progress_receipts', 'duplicate_progress_receipts',
            'invalid_progress_receipts', 'min_decode_pending', 'max_decode_pending',
            'min_output_pending', 'max_output_pending', 'empty_software_queue_samples',
            'empty_queue_and_idle_writer_samples', 'max_packet_send_gap_ms',
            'max_progress_receipt_gap_ms')
        summary = {'type': 'telemetry', 'event': 'playback_buffer_summary',
            'response_id': state['response_id'], 'audio_role': metrics['audio_role'], 'reason': reason,
            **{key: metrics[key] for key in fields if metrics.get(key) is not None}}
        # These are sampled counter differences, not proof of DMA underruns.
        for key, before in metrics['drop_counters_start'].items():
            after = self.stats.get('device_resources', {}).get(key)
            if type(after) is int and after >= before:
                summary[key+'_observed_delta'] = after-before
        self.spawn(self.send_output_summary(summary))

    async def send_output_summary(self, summary):
        try:
            await self.to_brain(summary)
            self.stats['output_summaries_sent'] += 1
        except Exception:
            # A diagnostic write failure must never disturb audio/control.
            self.stats['output_summaries_dropped'] += 1

    def output_receipt_metrics(self, state, obj):
        metrics = state['metrics']
        kind, now, wall = obj.get('state'), time.monotonic(), time.time()
        if kind == 'progress':
            consumed = obj.get('packets_consumed')
            if type(consumed) is not int or not state['consumed'] <= consumed <= state['seq']:
                metrics['invalid_progress_receipts'] += 1
                return
            if consumed == metrics['last_packets_consumed']:
                metrics['duplicate_progress_receipts'] += 1
                return
            previous = metrics.get('last_progress_monotonic')
            if previous is not None:
                metrics['max_progress_receipt_gap_ms'] = max(
                    metrics['max_progress_receipt_gap_ms'], (now-previous)*1000)
            metrics['last_progress_monotonic'] = now
            metrics['last_progress_wall'] = wall
            metrics['last_packets_consumed'] = consumed
            metrics['progress_receipts'] += 1
            point = {'wall': wall, 'plan_monotonic': now, 'packets_consumed': consumed}
            for key in ('decode_pending', 'output_pending'):
                value = obj.get(key)
                if type(value) is int and 0 <= value <= 1024:
                    point[key] = value
                    for prefix, choose in (('min_', min), ('max_', max)):
                        previous_value = metrics[prefix+key]
                        metrics[prefix+key] = value if previous_value is None else choose(previous_value, value)
            for key in ('decode_in_flight', 'output_in_flight'):
                if type(obj.get(key)) is bool:
                    point[key] = obj[key]
            if point.get('decode_pending') == point.get('output_pending') == 0:
                metrics['empty_software_queue_samples'] += 1
                if point.get('output_in_flight') is False:
                    metrics['empty_queue_and_idle_writer_samples'] += 1
            metrics['progress_points'] = [*metrics['progress_points'], point][-64:]
        elif kind in {'playback_started', 'playback_finished', 'segment_finished', 'stopped'}:
            # Arrival on PLAN is a transport receipt, not acoustic onset.
            prefix = {'playback_started': 'driver_submit_receipt', 'playback_finished': 'whole_finish_receipt',
                      'segment_finished': 'segment_finish_receipt', 'stopped': 'stop_receipt'}[kind]
            metrics[prefix+'_wall'] = wall
            metrics[prefix+'_monotonic'] = now
            if (kind == 'playback_finished' and type(obj.get('sample_floor')) is int
                    and 0 <= obj['sample_floor'] <= 1e15):
                metrics['completion_capture_sample_floor'] = obj['sample_floor']

    def trace(self, event):
        self.events.append(event)
        if event.get('event') == 'pre_roll_flushed':
            self.stats['pre_roll_flushed'] = self.stats.get('pre_roll_flushed', 0) + 1

    def spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    @staticmethod
    def parse(raw):
        if not isinstance(raw, str) or len(raw.encode()) > 8192:
            raise ValueError('invalid_sophia_control')
        obj = json.loads(raw)
        if not isinstance(obj, dict):
            raise ValueError('invalid_sophia_control')
        return obj

    async def send(self, data, packet=None, *, output_state=None, mute_epoch=None):
        async with self.device_send_lock:
            # A physical hold can win while an earlier unmute/state update
            # waits for this lock. Its already captured device revision also
            # lets ESP reject a stale command which is already on the wire.
            if mute_epoch is not None and mute_epoch != self.mute_control_epoch:
                return False
            # Cancellation may win while a previous metadata+Opus pair holds
            # the lock. Recheck ownership before starting another pair.
            if output_state is not None and (self.output is not output_state or
                    self.muted or output_state.get('cancel_pending') or
                    output_state['response_id'] in self.cancelled):
                return False
            if output_state is not None and data.get('type') == 'gobot_host_output_start':
                output_state['start_sent'] = True
            await asyncio.wait_for(self.device.send(json.dumps({
                **data, 'session_id': self.transport, 'epoch': self.epoch}, ensure_ascii=False)), 2)
            if packet is not None:
                await asyncio.wait_for(self.device.send(packet), 2)
            return True

    async def to_brain(self, obj, *, activation_cursor=None, input_cursor=None, mute_epoch=None):
        if self.brain is None:
            raise ValueError('brain_transport_unavailable')
        async with self.brain_send_lock:
            if mute_epoch is not None and mute_epoch != self.mute_control_epoch:
                return False
            if activation_cursor is not None and not self.activation_current(activation_cursor):
                return False
            if input_cursor is not None and not self.activation_current(input_cursor):
                return False
            await asyncio.wait_for(self.brain.send(obj if isinstance(obj, bytes)
                                                 else json.dumps(obj, ensure_ascii=False)), 3)
            return True

    def activation_current(self, cursor):
        return (not self.closed and not self.muted and self.pending_interrupt is None and
                self.ring.cursor is cursor and not self.ring.blocked)

    def device_mute_snapshot(self, obj, *, initial=False):
        """Adopt the physical intent from authenticated ACK/control frames.

        Legacy 0.4.18 has no revision. Negotiated 0.4.19 controls must always
        carry one; the per-boot counter never wraps. No network state update
        can invent a newer physical intent.
        """
        revision = obj.get('mute_revision')
        if 'mute_revision' not in obj and self.device_mute_revision is None:
            if initial:
                return False
        else:
            if (type(revision) is not int or not 0 <= revision <= 0xffffffff or
                    type(obj.get('muted')) is not bool):
                raise ValueError('invalid_physical_mute_revision')
            if not initial and self.device_mute_revision is not None and revision <= self.device_mute_revision:
                self.stats['stale_physical_mute_controls'] = self.stats.get('stale_physical_mute_controls', 0)+1
                return False
            self.device_mute_revision = revision
            self.stats['device_mute_revision'] = revision
        if type(obj.get('muted')) is not bool:
            raise ValueError('invalid_physical_mute')
        self.mute_control_epoch += 1
        self.muted = obj['muted']
        if self.pending_interrupt is not None:
            self.pending_interrupt['wake'] = None
        if self.muted:
            self.fence_interruption('physical_mute')
        else:
            self.forward = False
            self.stats['input_open'] = False
            self.ring.set_blocked(False, reason='physical_unmute')
        return True

    async def notify_physical_mute(self):
        request_id, muted, epoch = uuid4().hex, self.muted, self.mute_control_epoch
        self.physical_mute_requests[request_id] = muted
        self.latest_physical_mute_request = request_id
        while len(self.physical_mute_requests) > 128:
            del self.physical_mute_requests[next(iter(self.physical_mute_requests))]
        return await self.to_brain({'type': 'mute', 'muted': muted, 'request_id': request_id},
                                   mute_epoch=epoch)

    def selected_input_mode(self, mode):
        if mode not in ('fast', 'expert'):
            raise ValueError('invalid_selected_input_mode')
        if mode != self.mode:
            # A permit for the previous mode must not describe the new one.
            # Only Brain's following typed status can make it known again.
            self.stats['admission_status'] = {'known': False, 'mode': mode}
            self.stats['admission_receipt'] = None
        self.mode = mode
        self.stats['selected_mode'] = mode

    async def admission_status(self, data):
        codes = {'available', 'scope_expired', 'starts_exhausted', 'consent_required', 'unavailable'}
        if (not isinstance(data, dict) or data.get('mode') not in ('fast', 'expert')
                or type(data.get('input_allowed')) is not bool
                or type(data.get('generation_allowed')) is not bool
                or type(data.get('code')) is not str or data['code'] not in codes
                or (data['code'] == 'available') != data['input_allowed']):
            self.stats['invalid_admission_status'] += 1
            return
        if data['mode'] != self.mode:
            self.stats['stale_admission_status'] += 1
            return
        state = {key: data[key] for key in ('mode', 'input_allowed', 'generation_allowed', 'code')}
        current = {'known': True, **state}
        if self.stats['admission_status'] != current:
            self.stats['admission_receipt'] = None
        self.stats['admission_status'] = current
        self.stats['generation_allowed'] = state['generation_allowed']
        # UI information only. Never reset ready/busy, capture, output, or the
        # actual server admission. Older host-v2 firmware safely ignores this
        # scoped no-op; newer native UI can explain a closed allowance.
        await self.send({'type': 'gobot_host_admission',
                         **{key: state[key] for key in ('input_allowed', 'code', 'mode')}})

    def admission_receipt(self, obj):
        state = self.stats['admission_status']
        revision = obj.get('render_revision')
        evidence = obj.get('render_evidence')
        previous = self.stats['admission_receipt']
        valid = (state.get('known') is True and obj.get('admission_known') is True
                 and type(obj.get('input_allowed')) is bool
                 and obj['input_allowed'] == state['input_allowed']
                 and obj.get('mode') == state['mode'] and obj.get('code') == state['code']
                 and type(obj.get('notice_rendered')) is bool
                 and not (obj['input_allowed'] and obj['notice_rendered'])
                 and type(revision) is int and 0 <= revision <= 10**15
                 and type(evidence) is str
                 and evidence in {'native_framebuffer_invalidated', 'native_framebuffer_unchanged'}
                 and (previous is None or revision >= previous['render_revision']))
        if not valid:
            self.stats['discarded_admission_receipts'] += 1
            return
        # At most one receipt, matching the current typed status. This is a
        # native framebuffer callback, never panel DMA or human-visible proof.
        self.stats['admission_receipt'] = {key: obj[key] for key in (
            'admission_known', 'input_allowed', 'mode', 'code', 'notice_rendered',
            'render_revision', 'render_evidence')}
        self.stats['admission_receipt']['receipt_plan_monotonic'] = time.monotonic()

    async def screen(self, phase, text=''):
        mute_epoch = self.mute_control_epoch
        if self.muted:
            phase, text = 'muted', ''
        self.stats['voice_phase'] = phase
        titles = {'ready': 'София', 'listening': 'Слушаю', 'thinking': 'Обдумываю',
                  'speaking': 'Отвечаю', 'muted': 'Микрофон выключен', 'error': 'Разговор недоступен'}
        if not await self.send({'type': 'gobot_host_state', 'state': phase}, mute_epoch=mute_epoch):
            return
        await self.send({'type': 'custom', 'payload': {'namespace': 'gobot.ui', 'version': 2,
                         'command': 'presentation.show', 'type': 'status_card',
                         'title': titles[phase], 'text': text[:160],
                         'voice_engine': 'B_WS', 'voice_phase': phase}}, mute_epoch=mute_epoch)

    async def run(self, ws, hello, validator):
        self.device = ws
        if not validator(hello) or not supports_sophia_v2(hello):
            raise ValueError('sophia_v2_capabilities_required')
        if self.options.get('lan_stream_consent') is not True:
            raise PermissionError('local_stream_consent_required')
        try:
            await self.send({'type': 'hello', 'version': 1, 'transport': 'websocket',
                             'audio_params': {'format': 'opus', 'sample_rate': 24000,
                                              'channels': 1, 'frame_duration': 60}})
            await self.send({'type': 'gobot_host_ready', 'protocol': 2,
                             'wake_location': 'ESP', 'pcm_stage': 'pre_afe',
                             'frame_samples': 960, 'preroll_ms': 1000,
                             'paid_session_opened': False, 'continuous': True})
            ack = self.parse(await asyncio.wait_for(ws.recv(), 8))
            if (ack.get('type') != 'gobot_host_ready_ack' or ack.get('protocol') != 2
                    or ack.get('session_id') != self.transport or ack.get('epoch') != self.epoch
                    or ack.get('frame_samples') != 960 or ack.get('pcm_stage') != 'pre_afe'):
                raise ValueError('sophia_v2_handshake_not_confirmed')
            self.decoder.reset(ack['stream_epoch'], sample_start=ack.get('sample_start', 0))
            self.device_mute_snapshot(ack, initial=True)
            self.stats['device_protocol_confirmed'] = True
            self.stats['interruption_protocol'] = (
                'wake_touch_v1' if ack.get('interruption') == 'wake_touch_v1' else None)
            core = [self.spawn(self.receive()), self.spawn(self.uplink()),
                    self.spawn(self.cloud()), self.spawn(self.status_tick())]
            done, _ = await asyncio.wait(core, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        finally:
            self.stats['input_open_before_cleanup'] = self.stats.get('input_open') is True
            self.stats['output_active_before_cleanup'] = self.output is not None
            self.closed = True
            self.forward = False
            self.decoder.close()
            self.resampler = None
            for task in list(self.tasks):
                task.cancel()
            await asyncio.gather(*list(self.tasks), return_exceptions=True)
            self.stats['cloud_ready'] = False
            self.stats['input_open'] = False
            self.stats['device_protocol_confirmed'] = False

    async def status_tick(self):
        while True:
            next_tick = time.monotonic()+5
            # Installed V4 uses application-data age in IsAudioChannelOpened.
            # WebSocket Ping/Pong does not refresh that clock: after a quiet
            # interval HostControl silently stops, although PCM still flows.
            # This scoped, no-op frame keeps the control path live without
            # changing the board phase, admitting input, or calling Brain.
            # Use the same lock as metadata+Opus so that pair stays atomic.
            await self.send({'type': 'gobot_host_keepalive'})
            now = time.monotonic()
            self.stats['application_keepalives_sent'] += 1
            self.stats['last_application_keepalive_monotonic'] = now
            last_control = self.stats['last_device_control_monotonic']
            self.stats['device_control_age_seconds'] = (
                max(0., now-last_control) if last_control is not None else None)
            if self.on_status:
                self.on_status()
            await asyncio.sleep(max(0., next_tick-time.monotonic()))

    async def receive(self):
        pending = None
        while True:
            raw = await asyncio.wait_for(self.device.recv(), 15)
            if isinstance(raw, bytes):
                if pending is None or not 0 < len(raw) <= 4096:
                    raise ValueError('sophia_binary_without_frame')
                if self.decoder.feed(pending, raw):
                    self.stats['received_packets'] += 1
                    self.input_changed.set()
                pending = None
                continue
            obj = self.parse(raw)
            if obj.get('session_id') != self.transport or obj.get('epoch') != self.epoch:
                raise ValueError('stale_sophia_transport')
            if pending is not None:
                raise ValueError('sophia_missing_opus_frame')
            kind = obj.get('type')
            if kind in {'gobot_host_wake', 'gobot_host_touch', 'gobot_host_mute',
                        'gobot_host_playback', 'gobot_host_ack', 'gobot_host_finish',
                        'gobot_host_telemetry', 'gobot_host_stats'}:
                self.stats['device_control_messages'] += 1
                self.stats['last_device_control_monotonic'] = time.monotonic()
                self.stats['device_control_age_seconds'] = 0.
            if kind == 'gobot_host_frame':
                pending = obj
            elif kind == 'gobot_host_wake':
                self.device_activation(obj, trigger='wake_word', control=obj)
            elif kind == 'gobot_host_touch':
                if obj.get('action') == 'stop':
                    if obj.get('interrupt_requested') is True and isinstance(obj.get('event_id'), str):
                        if (self.pending_interrupt is not None and
                                self.pending_interrupt['event_id'] == obj['event_id']):
                            # A second short tap changes the already-visible
                            # listening intent to standby without restarting
                            # either the physical or provider stop barrier.
                            self.pending_interrupt['wake'] = None
                            self.forward = False
                            self.stats['input_open'] = False
                            self.ring.set_blocked(True, reason='physical_stop')
                        else:
                            self.begin_interruption(None, trigger='touch', control=obj)
                    else:
                        self.fence_interruption('physical_stop')
                        self.spawn(self.stop('physical_stop'))
                elif obj.get('action') in {'activate', 'interrupt'}:
                    wake = {'wake_id': obj.get('event_id') or uuid4().hex,
                            'stream_epoch': obj.get('stream_epoch', self.ring.epoch),
                            'detector_sample': obj.get('detector_sample', self.ring.end)}
                    self.device_activation(wake, trigger='touch', control=obj)
            elif kind == 'gobot_host_mute':
                if not self.device_mute_snapshot(obj):
                    continue
                self.stats['last_physical_control'] = 'mute' if self.muted else 'unmute'
                if self.brain:
                    await self.notify_physical_mute()
                await self.screen('muted' if self.muted else 'ready')
            elif kind == 'gobot_host_playback':
                await self.receipt(obj)
            elif kind == 'gobot_host_ack':
                if obj.get('event') == 'ui_visible':
                    callback = obj.get('callback_monotonic_us')
                    visible = obj.get('device_monotonic_us', obj.get('device_mono_us'))
                    if type(callback) is int and type(visible) is int and visible >= callback:
                        # The installed V4-derived callback is LV_EVENT_REFR_READY.
                        # Its legacy wire name does not prove final panel DMA or
                        # first visible pixels. Both timestamps are ESP-local.
                        self.stats['last_wake_lvgl_refresh_ready_ms'] = (visible-callback)/1000
                        self.stats['wake_ui_measurement'] = 'lvgl_refr_ready_not_panel_dma'
                    self.trace({'event': 'ui_visible', 'wake_id': obj.get('wake_id'),
                                'device_mono_us': visible, 'callback_monotonic_us': callback,
                                'clock_domain': 'esp32_monotonic'})
                elif obj.get('event') == 'admission_rendered':
                    self.admission_receipt(obj)
                elif obj.get('event') == 'interrupt_quiet':
                    self.interrupt_quiet_receipt(obj)
            elif kind == 'gobot_host_finish':
                # v1 firmware endpointing is not a second controller for B_WS.
                self.stats['ignored_device_endpoints'] = self.stats.get('ignored_device_endpoints', 0) + 1
            elif kind in ('gobot_host_telemetry', 'gobot_host_stats'):
                allowed = ('free_heap', 'min_free_heap', 'free_psram', 'queue_frames',
                           'underrun', 'dropped_frames', 'pcm_samples', 'detector_errors',
                           'encode_pending', 'send_pending', 'decode_pending', 'output_pending',
                           'internal_free', 'psram_free', 'input_blocks', 'encoded_frames', 'encode_drops',
                           'audio_input_stack_hwm_bytes', 'aec_frames', 'aec_process_max_us',
                           'aec_reference_frames', 'barge_wakes', 'barge_taps')
                self.stats['device_resources'] = {k: obj[k] for k in allowed
                                                  if type(obj.get(k)) in (int, float)}
                for key in ('audio_input_task_present', 'aec_ready', 'interrupt_pending'):
                    if type(obj.get(key)) is bool:
                        self.stats['device_resources'][key] = obj[key]
                if 'audio_input_stack_hwm_bytes' in self.stats['device_resources']:
                    # Pinned ESP-IDF reports this high-water mark in bytes.
                    self.stats['device_resources']['audio_input_stack_hwm_units'] = 'bytes'
                self.stats['device_resources']['underrun_measurement'] = obj.get('underrun_measurement', 'not_instrumented')
            else:
                raise ValueError('unsupported_sophia_control')

    def fence_interruption(self, reason):
        """Run in the receive task before yielding to a queued finish receipt."""
        self.forward = False
        self.stats['input_open'] = False
        self.ring.set_blocked(True, reason=reason)
        if self.output is not None:
            self.output['cancel_pending'] = True
            self.output['cancel_signal'].set()
            if self.output['response_id'] not in self.cancelled:
                self.cancelled.append(self.output['response_id'])
            self.output_credit.set()

    def device_activation(self, wake, *, trigger, control):
        if self.muted:
            return False
        ident, sample = wake.get('wake_id'), wake.get('detector_sample')
        if (wake.get('stream_epoch') != self.ring.epoch or not isinstance(ident, str)
                or not 1 <= len(ident) <= 128 or type(sample) is not int
                or not 0 <= sample <= 10**15 or sample > self.ring.end+32000):
            raise ValueError('invalid_device_activation')
        key = (self.ring.epoch, ident)
        if key in self.activation_events or ident in self.ring.seen_wakes:
            self.stats['duplicate_device_activations'] = self.stats.get('duplicate_device_activations', 0)+1
            return False
        self.activation_events.append(key)
        if self.pending_interrupt is not None:
            self.stats['coalesced_device_activations'] = self.stats.get('coalesced_device_activations', 0)+1
            return False
        if control.get('interrupt_requested') is True:
            return self.begin_interruption(wake, trigger=trigger, control=control)
        if self.output or self.ring.cursor or self.stats.get('voice_phase') in {'speaking', 'thinking'}:
            self.stats['suppressed_busy_wakes'] = self.stats.get('suppressed_busy_wakes', 0)+1
            return False
        if self.ring.begin(wake, pre_roll_seconds=1. if trigger == 'wake_word' else 0.):
            self.stats['wake_events'] += 1
            self.resampler = ContinuousPcm24()
            self.endpoint.update(started=None, last_voice=None, samples=0)
            self.spawn(self.activate(wake, trigger=trigger))
            return True
        return False

    def begin_interruption(self, wake, *, trigger, control):
        if self.muted or self.pending_interrupt is not None:
            return False
        event_id = wake['wake_id'] if wake is not None else control.get('event_id')
        if not isinstance(event_id, str) or not 1 <= len(event_id) <= 128:
            raise ValueError('invalid_interrupt_event_id')
        owner_fields = ('interrupted_response_id', 'interrupted_playback_id', 'interrupted_output_epoch')
        if self.output and any(key in control for key in owner_fields):
            expected = tuple(self.output[key] for key in ('response_id', 'playback_id', 'output_epoch'))
            if (type(control.get('interrupted_output_epoch')) is not int or
                    tuple(control.get(key) for key in owner_fields) != expected):
                self.stats['stale_interrupt_owners'] = self.stats.get('stale_interrupt_owners', 0)+1
                return False
        intent = {'event_id': event_id, 'request_id': uuid4().hex, 'wake': wake,
                  'trigger': trigger, 'ack': asyncio.Event(), 'quiet': asyncio.Event(),
                  'quiet_floor': None, 'output_state': self.output if self.output is not None and
                    self.output.get('start_sent') is not False else None}
        self.pending_interrupt = intent
        self.fence_interruption('device_interrupt')
        self.stats['device_interrupts'] = self.stats.get('device_interrupts', 0)+1
        self.spawn(self.interrupt_then_activate(intent))
        return True

    def interrupt_quiet_receipt(self, obj, *, output_state=None):
        intent = self.pending_interrupt
        if (intent is None or intent['quiet'].is_set() or
                (output_state is None and (intent['output_state'] is not None or
                                          obj.get('event_id') != intent['event_id'])) or
                (output_state is not None and intent['output_state'] is not output_state)):
            return
        physical_floor = obj.get('sample_floor')
        if (obj.get('stream_epoch') != self.ring.epoch or type(physical_floor) is not int
                or not 0 <= physical_floor <= 10**15):
            raise ValueError('physical_cancel_capture_floor_missing')
        floor = max(self.ring.floor, self.ring.end, physical_floor)
        if intent['wake'] is not None and not self.muted:
            # Preserve the question after physical quiet while remote Stop is
            # still pending. No input authority follows from this receipt.
            self.ring.set_blocked(False, sample_floor=floor, reason='interrupt_physical_quiet')
        intent['quiet_floor'] = floor
        intent['quiet'].set()
        fields = {'wake_id': intent['event_id'], 'physical_sample_floor': physical_floor,
                  'guard_samples': 0, 'selected_start': floor}
        if output_state is not None:
            fields['response_id'] = output_state['response_id']
        self.queue_capture_boundary('interrupt_quiet', **fields)

    async def interrupt_then_activate(self, intent):
        """Physical quiet and an exact server Stop ACK precede the next wake.

        Post-quiet PCM stays in the existing bounded ring while provider/expert
        cancellation finishes. It is forwarded only after a fresh admission.
        """
        stop_send = asyncio.create_task(self.to_brain({'type': 'stop', 'request_id': intent['request_id']}))
        try:
            async def physical_barrier():
                await self.clear_output()
                await intent['quiet'].wait()
            await asyncio.wait_for(physical_barrier(), 2)
            if intent['wake'] is not None and not self.muted:
                original = intent['wake']
                wake = {**original, 'detector_sample': max(original['detector_sample'], intent['quiet_floor']),
                        'capture_detector_sample': original['detector_sample'], 'capture_interrupt': True}
                self.ring.begin(wake, pre_roll_seconds=0.)
                self.resampler = ContinuousPcm24()
                self.endpoint.update(started=None, last_voice=None, samples=0)
            else:
                wake = None
            await stop_send
            await asyncio.wait_for(intent['ack'].wait(), INTERRUPT_STOP_ACK_SECONDS)
            if self.pending_interrupt is not intent:
                return
            reopen = wake is not None and intent['wake'] is not None and not self.muted
            await self.send({'type': 'gobot_host_interrupt_complete', 'event_id': intent['event_id'],
                             'outcome': 'listening' if reopen else 'ready'})
            self.pending_interrupt = None
            if reopen:
                self.stats['wake_events'] += 1
                await self.activate(wake, trigger=intent['trigger'])
            else:
                self.ring.set_blocked(self.muted, reason='device_stop_complete')
                await self.screen('muted' if self.muted else 'ready')
        except Exception:
            # A missing physical/Stop barrier is not permission to admit the
            # next question. Reconnect the empty transport, never retry a turn.
            self.forward = False
            self.stats['input_open'] = False
            self.ring.set_blocked(True, reason='interrupt_barrier_failed')
            self.stats['last_error'] = 'interrupt_barrier_failed'
            with suppress(Exception):
                await self.screen('error', 'Не удалось остановить ответ. Восстанавливаю связь.')
            if self.brain is not None:
                with suppress(Exception):
                    await self.brain.close(code=1011, reason='interrupt_barrier_failed')
        finally:
            if intent['request_id'] not in self.completed_stop_requests:
                self.completed_stop_requests.append(intent['request_id'])
            if not stop_send.done():
                stop_send.cancel()
            await asyncio.gather(stop_send, return_exceptions=True)

    async def activate(self, wake, *, trigger='manual'):
        cursor = self.ring.cursor
        if cursor is None or cursor.wake_id != wake['wake_id']:
            return
        try:
            await asyncio.wait_for(self.cloud_ready.wait(), 10)
            if not self.activation_current(cursor):
                return
            # Firmware wake counters restart at boot. Deduplication belongs to
            # the capture epoch, while Brain's logical conversation survives it.
            ident = uuid5(NAMESPACE_URL, str(wake['stream_epoch'])+':'+wake['wake_id']).hex
            event = {'type': 'wake', 'wake_id': 'esp_'+ident,
                     'mode': self.mode, 'trigger': trigger}
            if type(wake.get('detector_sample')) is int and hasattr(cursor, 'selected_start'):
                event['capture'] = {'stream_epoch': wake['stream_epoch'],
                    'selected_start': cursor.selected_start,
                    'detector_sample': wake.get('capture_detector_sample', wake['detector_sample']),
                    'sample_rate': 16000, 'interrupt': wake.get('capture_interrupt') is True}
            await self.to_brain(event, activation_cursor=cursor)
        except Exception:
            if not self.activation_current(cursor):
                return
            self.ring.stop('activation_failed')
            self.stats['last_error'] = 'cloud_not_ready'
            await self.screen('error', 'Нет связи с разговором. София продолжает ждать обращения.')

    async def uplink(self):
        while True:
            await self.input_changed.wait()
            self.input_changed.clear()
            if not self.forward or self.muted or not self.resampler:
                continue
            while self.forward:
                available = self.ring.read_available(max_chunks=1)
                if not available:
                    break
                cursor, resampler = self.ring.cursor, self.resampler
                sample_start, pcm = available[0]
                if self.mode == 'expert':
                    remaining = max(0, int(16000*self.expert_audio_limit)-self.endpoint['samples'])
                    pcm = pcm[:remaining*2]
                out = resampler.feed(pcm)
                if out:
                    if not await self.to_brain(out, input_cursor=cursor):
                        continue
                if self.ring.cursor is not cursor or self.resampler is not resampler:
                    continue  # Stop/new input also supersedes the old local expert endpoint.
                sent_end = cursor.selected_start+resampler.output_samples*16000//24000
                self.ring.acknowledge_sent(min(sample_start+len(pcm)//2, sent_end))
                if out and self.first_uplink_cursor is not cursor:
                    self.first_uplink_cursor = cursor
                    self.queue_capture_boundary('first_uplink', wake_id=cursor.wake_id,
                        selected_start=cursor.selected_start, source_sample_start=sample_start,
                        source_sample_end=sample_start+len(pcm)//2)
                if self.mode == 'expert':
                    await self.expert_endpoint(pcm, sample_start)

    async def expert_endpoint(self, pcm, position):
        import numpy as np
        values = np.frombuffer(pcm, '<i2').astype(np.float32)
        rms = float(np.sqrt(np.mean(values*values))) if len(values) else 0.
        state = self.endpoint
        now = (position+len(values))/16000
        state['samples'] += len(values)
        if rms > max(240., state['noise']*2.8):
            if state['started'] is None:
                state['started'] = now
            state['last_voice'] = now
        elif state['started'] is None:
            state['noise'] = .97*state['noise']+.03*min(rms, 300.)
        complete = (state['last_voice'] is not None and now-state['last_voice'] >= 1.4)
        limit = state['samples'] >= 16000*self.expert_audio_limit
        empty = state['started'] is None and state['samples'] >= 16000*12
        if complete or limit or empty:
            cursor = self.ring.cursor
            tail = self.resampler.finish()
            if tail:
                if not await self.to_brain(tail, input_cursor=cursor):
                    return
            if not await self.to_brain({'type': 'input_end'}, input_cursor=cursor):
                return
            self.forward = False
            self.ring.stop('expert_local_endpoint')
            self.trace({'event': 'end_of_speech', 'last_speech_sample':
                        int(state['last_voice']*16000) if state['last_voice'] else None,
                        'clock_domain': 'capture_16k', 'evidence': 'local_energy_endpoint'})

    async def cloud(self):
        url = urlparse(self.config['brain_url'])
        if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.path not in ('', '/'):
            raise ValueError('brain_loopback_required')
        endpoint = 'ws://'+url.netloc+'/api/v1/voice-ws/stream'
        async with self.connector(endpoint, additional_headers={'Authorization': 'Bearer '+self.token},
                                  proxy=None, open_timeout=10, close_timeout=2,
                                  max_size=1048576, max_queue=16) as brain:
            self.brain = brain
            offer = {'session_id': self.logical_session, 'conversation_id': self.conversation,
                     'device_id': self.config['device_id'], 'client_id': self.config['device_id'],
                     'consent': self.config.get('hardware_realtime_consent') is True,
                     'expert_quota_consent': self.config.get('hardware_expert_consent') is True,
                     'remember': False, 'speak': True, 'client_kind': 'device',
                     'personalization_mode': 'guest', 'requested_voice': 'marin',
                     'requested_model': self.options.get('model', 'gpt-realtime-2.1-mini'),
                     'input_mode': self.mode, 'endpointing': self.options.get('endpointing', 'server_450')}
            await self.to_brain({'type': 'hello', 'source': 'device', 'offer': offer})
            if self.device_mute_revision is not None:
                # Reconnection uses the device's actual state. Register the
                # correlated command before consuming old server state events.
                await self.notify_physical_mute()
            async for raw in brain:
                if not isinstance(raw, str):
                    raise ValueError('unexpected_brain_binary')
                event = json.loads(raw)
                await self.cloud_event(event)
        self.brain = None

    async def cloud_event(self, event):
        kind, data = event.get('type'), event.get('data', {})
        if self.muted and kind in {'audio_start', 'audio_chunk', 'audio_stop',
                'audio_segment_done', 'expert_segment_generated', 'input_transcript',
                'stt_partial', 'stt_final'}:
            # Provider cancellation can cross media already in flight. Keep
            # stop/cancel receipts live, but never restore output after a hold.
            if kind == 'audio_start' and isinstance(data.get('response_id'), str):
                self.cancelled.append(data['response_id'])
            self.stats['muted_events_dropped'] = self.stats.get('muted_events_dropped', 0)+1
            return
        if kind == 'stopped' and data.get('request_id') in self.completed_stop_requests:
            return
        intent = self.pending_interrupt
        if intent is not None:
            if kind == 'stopped':
                if data.get('request_id') == intent['request_id']:
                    self.completed_stop_requests.append(intent['request_id'])
                    intent['ack'].set()
                return
            if kind in {'audio_start', 'audio_chunk', 'audio_stop', 'audio_cancel',
                        'audio_segment_done', 'expert_segment_generated', 'listening', 'followup',
                        'input_closed', 'followup_closed', 'ready', 'input_transcript',
                        'stt_partial', 'stt_final', 'admission_denied', 'transport_disconnected',
                        'error', 'narration_unavailable'}:
                # Do not play queued old audio or let an old listening/closed
                # event steal the new capture cursor before the Stop barrier.
                if kind == 'audio_start' and isinstance(data.get('response_id'), str):
                    self.cancelled.append(data['response_id'])
                self.stats['interrupted_events_dropped'] = self.stats.get('interrupted_events_dropped', 0)+1
                return
        if kind == 'admission_status':
            await self.admission_status(data)
        elif kind == 'ready':
            if data.get('input_mode') in ('fast', 'expert'):
                self.selected_input_mode(data['input_mode'])
            self.cloud_ready.set()
            self.stats.update(cloud_ready=True, generation_allowed=data.get('generation_allowed') is True)
            if data.get('recovered') is True and self.stats.get('last_error') == 'transport_unavailable':
                self.stats['last_error'] = None
            await self.screen('muted' if self.muted else 'ready', 'Скажите «София»' if self.stats['generation_allowed']
                              else 'Для разговора нужен действующий допуск к расходам.')
        elif kind in ('listening', 'followup'):
            if self.muted:
                return
            if data.get('resume_capture') is True and (not self.ring.cursor or not self.resampler):
                raise ValueError('wake_fragment_capture_cursor_missing')
            if type(data.get('max_audio_seconds')) in (int, float):
                self.expert_audio_limit = min(self.options.get('expert_max_seconds', 180),
                                              max(1, data['max_audio_seconds']))
            if kind == 'followup':
                self.ring.set_blocked(False, reason='playback_guard_finished')
                self.selected_input_mode('fast')
                wake = {'wake_id': 'followup_'+uuid4().hex, 'stream_epoch': self.ring.epoch,
                        'detector_sample': max(self.ring.end, self.ring.floor)}
                self.ring.begin(wake, pre_roll_seconds=0.)
                self.resampler = ContinuousPcm24()
                fields = {'wake_id': wake['wake_id'], 'selected_start': self.ring.cursor.selected_start}
                if self.capture_completion and self.capture_completion['stream_epoch'] == self.ring.epoch:
                    fields.update(response_id=self.capture_completion['response_id'],
                        physical_sample_floor=self.capture_completion['physical_sample_floor'],
                        guard_samples=POST_PLAYBACK_CAPTURE_GUARD_SAMPLES)
                self.queue_capture_boundary('followup_opened', **fields)
            self.forward = True
            self.stats['input_open'] = True
            self.stats['last_error'] = None
            self.input_changed.set()
            await self.screen('listening', 'Говорите')
        elif kind in ('input_closed', 'followup_closed', 'admission_denied', 'transport_disconnected'):
            self.forward = False
            self.stats['input_open'] = False
            if not (kind == 'input_closed' and data.get('resume_pending') is True):
                self.ring.stop(kind)
            if type(data.get('generation_allowed')) is bool:
                self.stats['generation_allowed'] = data['generation_allowed']
            reason = data.get('reason', kind)
            terminal = kind in ('followup_closed', 'admission_denied') or (
                kind == 'input_closed' and reason not in ('provider_endpoint', 'expert_local_endpoint'))
            if terminal:
                # A finite input window can end without an answer. In that
                # case neither the host busy state nor the post-playback RAM
                # gate may keep suppressing the owner's next local wake.
                if self.output is None:
                    self.ring.set_blocked(self.muted, reason=kind)
                if kind == 'admission_denied' and 'generation_allowed' not in data:
                    self.stats['generation_allowed'] = False
                if reason != 'silence':
                    self.stats['last_error'] = str(reason)[:160]
                allowed = self.stats['generation_allowed']
                text = ('Время этой беседы истекло. Скажите «София» ещё раз.'
                        if allowed and reason == 'paid_operation_expired_new_wake_required' else
                        'Скажите «София»' if allowed else
                        'Допуск к быстрому разговору закрыт. Проверьте доступ к эксперту в панели Софии.')
                if str(reason).startswith('wake_fragment_'):
                    text = 'Не удалось разобрать начало вопроса. Скажите «София» и повторите.'
                await self.screen('muted' if self.muted else 'ready', text)
            elif kind == 'input_closed':
                await self.screen('thinking')
        elif kind == 'audio_start':
            if data.get('response_id') in self.cancelled:
                return
            if self.output is not None:
                raise ValueError('multiple_physical_output_owners')
            self.forward = False
            self.ring.set_blocked(True, reason='playback')
            self.output = {'response_id': data['response_id'], 'playback_id': uuid4().hex,
                           'output_epoch': self.output_epoch, 'encoder': self.encoder_factory(),
                           'seq': 0, 'started_at': None, 'role': data.get('audio_role', 'fast_answer'),
                           'done': False, 'start_sent': False, 'consumed': 0, 'progress_seen': False,
                           'pcm_samples': 0, 'cancel_signal': asyncio.Event()}
            self.output['metrics'] = self.new_output_metrics(data['response_id'], self.output['role'])
            state = self.output
            sent = await self.send({'type': 'gobot_host_output_start', **self.output_fields(),
                             'kind': 'cue' if self.output['role'] == 'service_cue' else 'answer',
                             'streaming': True, 'packet_count': 0, 'codec': 'opus',
                             'sample_rate': 24000, 'frame_samples': 1440}, output_state=state)
            if sent and self.output is state and not state.get('cancel_pending'):
                await self.screen('speaking')
        elif kind == 'audio_chunk':
            if not self.output or data.get('response_id') in self.cancelled:
                return
            if data.get('response_id') != self.output['response_id']:
                raise ValueError('physical_response_mismatch')
            pcm = base64.b64decode(data['pcm'], validate=True)
            state = self.output
            state['pcm_samples'] += len(pcm)//2
            for packet in state['encoder'].feed(pcm, 24000):
                if self.output is not state or state.get('cancel_pending'):
                    break
                await self.output_packet(packet)
        elif kind in ('expert_segment_generated', 'audio_segment_done'):
            if self.output and data.get('response_id') == self.output['response_id']:
                state = self.output
                await self.send({'type': 'gobot_host_output_segment_end', **self.output_fields(),
                                 'segment_id': data.get('segment_id'),
                                 'pcm_sample_end': self.output['pcm_samples']}, output_state=state)
        elif kind == 'audio_stop':
            if self.output and data.get('response_id') == self.output['response_id']:
                state = self.output
                for packet in state['encoder'].finish():
                    if self.output is not state or state.get('cancel_pending'):
                        break
                    await self.output_packet(packet)
                if self.output is not state or state.get('cancel_pending'):
                    return
                state['done'] = True
                sent = await self.send({'type': 'gobot_host_output_end', **self.output_fields(),
                                 'packet_count': self.output['seq'],
                                 'whole_response': self.output['role'] != 'service_cue'}, output_state=state)
                if sent:
                    state['metrics']['output_end_sent_monotonic'] = time.monotonic()
                    state['metrics']['output_end_sent_wall'] = time.time()
        elif kind in ('audio_cancel', 'stopped'):
            response = data.get('response_id')
            if kind == 'audio_cancel' and isinstance(response, str) and (
                    response in self.cancelled and self.output is None or
                    self.output is not None and response != self.output['response_id']):
                return
            await self.clear_output()
            if self.pending_interrupt is not None:
                return
            self.forward = False
            self.stats['input_open'] = False
            self.ring.set_blocked(self.muted, reason='stop')
            await self.screen('muted' if self.muted else 'ready')
        elif kind == 'muted':
            if type(data.get('muted')) is not bool:
                raise ValueError('invalid_brain_mute')
            request_id = data.get('request_id')
            physical_ack = False
            if isinstance(request_id, str) and request_id in self.physical_mute_requests:
                expected = self.physical_mute_requests.pop(request_id)
                if (request_id != self.latest_physical_mute_request or
                        data.get('muted') is not expected):
                    self.stats['stale_mute_acks'] = self.stats.get('stale_mute_acks', 0)+1
                    return
                self.latest_physical_mute_request = None
                physical_ack = True
            elif request_id is not None:
                self.stats['stale_mute_acks'] = self.stats.get('stale_mute_acks', 0)+1
                return
            elif self.latest_physical_mute_request is not None:
                # Even a same-state echo cannot supersede the physical intent:
                # its correlated command may still be waiting for the Brain
                # wire lock. Only the exact ACK completes that pending intent.
                self.stats['stale_mute_acks'] = self.stats.get('stale_mute_acks', 0)+1
                return
            if physical_ack:
                # The receive task already applied this physical intent. Its
                # ACK must not clear a newer input cursor/listening transition
                # or cancel a pending tap. Only confirm the matching wire state.
                control = {'type': 'gobot_host_mute', 'muted': data['muted']}
                if self.device_mute_revision is not None:
                    control['mute_revision'] = self.device_mute_revision
                await self.send(control, mute_epoch=self.mute_control_epoch)
                return
            self.mute_control_epoch += 1
            mute_epoch = self.mute_control_epoch
            self.muted = data['muted']
            if self.muted:
                if self.pending_interrupt is not None:
                    self.pending_interrupt['wake'] = None
                self.fence_interruption('mute')
            else:
                self.forward = False
                self.stats['input_open'] = False
                self.ring.set_blocked(False, reason='unmute')
            control = {'type': 'gobot_host_mute', 'muted': self.muted}
            if self.device_mute_revision is not None:
                control['mute_revision'] = self.device_mute_revision
            if not await self.send(control, mute_epoch=mute_epoch):
                return
            await self.screen('muted' if self.muted else 'ready')
        elif kind == 'mode_selected':
            self.selected_input_mode(data['mode'])
        elif kind == 'stt_ready' and type(data.get('max_audio_seconds')) in (int, float):
            self.expert_audio_limit = min(self.options.get('expert_max_seconds', 180),
                                          max(1, data['max_audio_seconds']))
        elif kind in ('input_transcript', 'stt_partial', 'stt_final'):
            text = data.get('text', '')
            if text:
                await self.send({'type': 'stt', 'text': text[:512]})
        elif kind in ('error', 'narration_unavailable'):
            self.stats['last_error'] = data.get('code', data.get('reason', kind))[:160]
            self.forward = False
            self.ring.stop('cloud_error')
            await self.screen('error', 'Откройте панель Софии, чтобы увидеть причину.')
        elif kind == 'telemetry':
            self.trace({k: v for k, v in data.items() if k not in ('text', 'pcm', 'audio')})

    def output_fields(self):
        return {k: self.output[k] for k in ('response_id', 'playback_id', 'output_epoch')}

    async def output_packet(self, packet):
        state = self.output
        if not state or state['response_id'] in self.cancelled:
            return
        # First packet is immediate. Limit look-ahead to four existing 60ms
        # packets; this is output backpressure, never an input pre-roll delay.
        now = time.monotonic()
        if state['started_at'] is None:
            state['started_at'] = now
        delay = state['started_at']+max(0, state['seq']-3)*.06-now
        if delay > 0:
            try:
                await asyncio.wait_for(state['cancel_signal'].wait(), delay)
            except TimeoutError:
                pass
        while (self.output is state and not state.get('cancel_pending') and
               state['progress_seen'] and state['seq']-state['consumed'] >= 4):
            self.output_credit.clear()
            await asyncio.wait_for(self.output_credit.wait(), 2)
        if self.output is not state or state.get('cancel_pending') or state['response_id'] in self.cancelled:
            return
        sent = await self.send({'type': 'gobot_host_output_frame',
                         **{key: state[key] for key in ('response_id', 'playback_id', 'output_epoch')},
                         'seq': state['seq'], 'sample_start': state['seq']*1440,
                         'sample_count': 1440}, packet, output_state=state)
        if not sent:
            return
        state['seq'] += 1
        self.stats['downlink_packets'] += 1
        now, wall = time.monotonic(), time.time()
        metrics = state['metrics']
        previous = metrics.get('last_packet_sent_monotonic')
        if previous is not None:
            metrics['max_packet_send_gap_ms'] = max(metrics['max_packet_send_gap_ms'], (now-previous)*1000)
        else:
            metrics['first_packet_sent_monotonic'] = now
            metrics['first_packet_sent_wall'] = wall
        metrics['last_packet_sent_monotonic'] = now
        metrics['last_packet_sent_wall'] = wall
        metrics['packets_sent'] = state['seq']

    async def receipt(self, obj):
        state = self.output
        if not state or obj.get('response_id') != state['response_id'] or obj.get('playback_id') != state['playback_id']:
            self.stats['stale_playback_receipts'] = self.stats.get('stale_playback_receipts', 0)+1
            return
        kind = obj.get('state')
        if kind == 'stopped' and state.get('cancel_pending'):
            if obj.get('output_epoch') != state['output_epoch']+1:
                raise ValueError('cancel_output_epoch_not_confirmed')
            self.interrupt_quiet_receipt(obj, output_state=state)
            self.output_receipt_metrics(state, obj)
            self.cancel_finished.set()
        elif state.get('cancel_pending'):
            # DMA completion can cross an already-sent cancel. Keep the owner
            # until the next-generation stopped ACK; never open follow-up here.
            return
        elif kind == 'progress':
            self.output_receipt_metrics(state, obj)
            consumed = obj.get('packets_consumed')
            if type(consumed) is int and state['consumed'] <= consumed <= state['seq']:
                state['consumed'] = consumed
                state['progress_seen'] = True
                self.output_credit.set()
        elif kind == 'playback_started':
            self.output_receipt_metrics(state, obj)
            self.stats['playback_started'] += 1
            await self.to_brain({'type': 'playback_started', 'response_id': state['response_id']})
        elif kind == 'segment_finished' and obj.get('segment_id') is not None:
            self.output_receipt_metrics(state, obj)
            await self.to_brain({'type': 'playback_finished', 'response_id': state['response_id'],
                                 'segment_id': obj['segment_id']})
        elif ((kind == 'playback_finished' and obj.get('whole_response') is True)
              or (kind == 'segment_finished' and state['role'] == 'service_cue'
                  and obj.get('whole_response') is False)):
            if not state['done']:
                raise ValueError('playback_finished_before_whole_response_end')
            floor = obj.get('sample_floor')
            if (obj.get('stream_epoch') != self.ring.epoch or type(floor) is not int
                    or not 0 <= floor <= 1e15-POST_PLAYBACK_CAPTURE_GUARD_SAMPLES):
                raise ValueError('physical_playback_capture_floor_missing')
            self.output_receipt_metrics(state, obj)
            self.ring.set_blocked(True, sample_floor=max(
                self.ring.end, self.ring.floor, floor+POST_PLAYBACK_CAPTURE_GUARD_SAMPLES),
                reason='playback_guard')
            self.capture_completion = {'response_id': state['response_id'],
                'stream_epoch': self.ring.epoch, 'physical_sample_floor': floor}
            boundary = {'response_id': state['response_id'], 'physical_sample_floor': floor,
                'guard_samples': POST_PLAYBACK_CAPTURE_GUARD_SAMPLES,
                'stream_epoch': self.ring.epoch, 'ring_end': self.ring.end,
                'sample_floor': self.ring.floor, 'plan_monotonic': time.monotonic()}
            self.stats['playback_finished'] += 1
            self.output = None
            try:
                await self.to_brain({'type': 'playback_finished', 'response_id': state['response_id'],
                                     'sample_floor': floor})
            finally:
                self.queue_output_summary(state, 'finished')
                self.queue_capture_boundary('playback_finished', **boundary)

    async def clear_output(self):
        async with self.cancel_lock:
            if self.output:
                state = self.output
                if state['response_id'] not in self.cancelled:
                    self.cancelled.append(state['response_id'])
                state['cancel_pending'] = True
                state['cancel_signal'].set()
                if state.get('start_sent') is False:
                    # Cancellation won before any owner/audio reached ESP.
                    # There is no physical output owner to cancel or ACK.
                    self.output = None
                    self.queue_output_summary(state, 'interrupted')
                    return
                self.cancel_finished.clear()
                try:
                    await self.send({'type': 'gobot_host_output_cancel', **self.output_fields()})
                    self.output_credit.set()
                    await asyncio.wait_for(self.cancel_finished.wait(), 2)
                    self.output_epoch += 1
                    self.output = None
                finally:
                    self.queue_output_summary(state, 'interrupted')

    async def stop(self, reason):
        self.forward = False
        if self.pending_interrupt is not None:
            self.pending_interrupt['wake'] = None
        self.ring.stop(reason)
        await self.clear_output()
        if self.pending_interrupt is not None:
            return
        if self.brain:
            await self.to_brain({'type': 'stop'})
