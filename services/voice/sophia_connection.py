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
        self.tasks = set()
        self.closed = False
        self.endpoint = {'started': None, 'last_voice': None, 'noise': 80., 'samples': 0}
        self.stats = {'protocol': 2, 'mode': 'B_WS', 'pcm_stage': 'pre_afe',
                      'selected_mode': self.mode,
                      'wake_location': 'ESP', 'voice': 'marin', 'received_packets': 0,
                      'downlink_packets': 0, 'cloud_ready': False, 'generation_allowed': False,
                      'raw_audio_saved': False, 'text_saved': False, 'wake_events': 0,
                      'playback_started': 0, 'playback_finished': 0,
                      'last_error': None, 'input_open': False, 'output_metrics': [],
                      'application_keepalives_sent': 0,
                      'last_application_keepalive_monotonic': None,
                      'device_control_messages': 0,
                      'last_device_control_monotonic': None,
                      'device_control_age_seconds': None}

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
            'progress_points': []}
        self.stats['output_metrics'] = [*self.stats['output_metrics'], metrics][-2:]
        return metrics

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

    async def send(self, data, packet=None):
        async with self.device_send_lock:
            await asyncio.wait_for(self.device.send(json.dumps({
                **data, 'session_id': self.transport, 'epoch': self.epoch}, ensure_ascii=False)), 2)
            if packet is not None:
                await asyncio.wait_for(self.device.send(packet), 2)

    async def to_brain(self, obj):
        if self.brain is None:
            raise ValueError('brain_transport_unavailable')
        async with self.brain_send_lock:
            await asyncio.wait_for(self.brain.send(obj if isinstance(obj, bytes)
                                                 else json.dumps(obj, ensure_ascii=False)), 3)

    async def screen(self, phase, text=''):
        self.stats['voice_phase'] = phase
        titles = {'ready': 'София', 'listening': 'Слушаю', 'thinking': 'Обдумываю',
                  'speaking': 'Отвечаю', 'muted': 'Микрофон выключен', 'error': 'Разговор недоступен'}
        await self.send({'type': 'gobot_host_state', 'state': phase})
        await self.send({'type': 'custom', 'payload': {'namespace': 'gobot.ui', 'version': 2,
                         'command': 'presentation.show', 'type': 'status_card',
                         'title': titles[phase], 'text': text[:160],
                         'voice_engine': 'B_WS', 'voice_phase': phase}})

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
            self.stats['device_protocol_confirmed'] = True
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
                if self.muted or self.output or self.ring.cursor:
                    self.stats['suppressed_busy_wakes'] = self.stats.get('suppressed_busy_wakes', 0)+1
                    continue
                if self.ring.begin(obj, pre_roll_seconds=1.0):
                    self.stats['wake_events'] += 1
                    self.resampler = ContinuousPcm24()
                    self.endpoint.update(started=None, last_voice=None, samples=0)
                    self.spawn(self.activate(obj, trigger='wake_word'))
            elif kind == 'gobot_host_touch':
                if obj.get('action') == 'stop':
                    self.forward = False
                    self.ring.stop('physical_stop')
                    self.spawn(self.stop('physical_stop'))
                elif not self.ring.cursor and not self.output and not self.muted:
                    wake = {'wake_id': obj.get('event_id') or uuid4().hex,
                            'stream_epoch': self.ring.epoch, 'detector_sample': self.ring.end}
                    self.ring.begin(wake, pre_roll_seconds=0.)
                    self.resampler = ContinuousPcm24()
                    self.spawn(self.activate(wake, trigger='touch'))
            elif kind == 'gobot_host_mute':
                self.muted = obj.get('muted') is True
                self.forward = False
                self.ring.set_blocked(self.muted, reason='mute')
                if self.brain:
                    await self.to_brain({'type': 'mute', 'muted': self.muted})
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
            elif kind == 'gobot_host_finish':
                # v1 firmware endpointing is not a second controller for B_WS.
                self.stats['ignored_device_endpoints'] = self.stats.get('ignored_device_endpoints', 0) + 1
            elif kind in ('gobot_host_telemetry', 'gobot_host_stats'):
                allowed = ('free_heap', 'min_free_heap', 'free_psram', 'queue_frames',
                           'underrun', 'dropped_frames', 'pcm_samples', 'detector_errors',
                           'encode_pending', 'send_pending', 'decode_pending', 'output_pending',
                           'internal_free', 'psram_free', 'input_blocks', 'encoded_frames', 'encode_drops',
                           'audio_input_stack_hwm_bytes')
                self.stats['device_resources'] = {k: obj[k] for k in allowed
                                                  if type(obj.get(k)) in (int, float)}
                if type(obj.get('audio_input_task_present')) is bool:
                    self.stats['device_resources']['audio_input_task_present'] = obj['audio_input_task_present']
                if 'audio_input_stack_hwm_bytes' in self.stats['device_resources']:
                    # Pinned ESP-IDF reports this high-water mark in bytes.
                    self.stats['device_resources']['audio_input_stack_hwm_units'] = 'bytes'
                self.stats['device_resources']['underrun_measurement'] = obj.get('underrun_measurement', 'not_instrumented')
            else:
                raise ValueError('unsupported_sophia_control')

    async def activate(self, wake, *, trigger='manual'):
        try:
            await asyncio.wait_for(self.cloud_ready.wait(), 10)
            if not self.ring.cursor or self.ring.cursor.wake_id != wake['wake_id']:
                return
            # Firmware wake counters restart at boot. Deduplication belongs to
            # the capture epoch, while Brain's logical conversation survives it.
            ident = uuid5(NAMESPACE_URL, str(wake['stream_epoch'])+':'+wake['wake_id']).hex
            await self.to_brain({'type': 'wake', 'wake_id': 'esp_'+ident,
                                 'mode': self.mode, 'trigger': trigger})
        except Exception:
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
                sample_start, pcm = available[0]
                if self.mode == 'expert':
                    remaining = max(0, int(16000*self.expert_audio_limit)-self.endpoint['samples'])
                    pcm = pcm[:remaining*2]
                out = self.resampler.feed(pcm)
                if out:
                    await self.to_brain(out)
                if self.ring.cursor:
                    sent_end = self.ring.cursor.selected_start+self.resampler.output_samples*16000//24000
                    self.ring.acknowledge_sent(min(sample_start+len(pcm)//2, sent_end))
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
            tail = self.resampler.finish()
            if tail:
                await self.to_brain(tail)
            await self.to_brain({'type': 'input_end'})
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
            async for raw in brain:
                if not isinstance(raw, str):
                    raise ValueError('unexpected_brain_binary')
                event = json.loads(raw)
                await self.cloud_event(event)
        self.brain = None

    async def cloud_event(self, event):
        kind, data = event.get('type'), event.get('data', {})
        if kind == 'ready':
            self.cloud_ready.set()
            self.stats.update(cloud_ready=True, generation_allowed=data.get('generation_allowed') is True)
            await self.screen('ready', 'Скажите «София»' if self.stats['generation_allowed']
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
                self.mode = 'fast'
                wake = {'wake_id': 'followup_'+uuid4().hex, 'stream_epoch': self.ring.epoch,
                        'detector_sample': max(self.ring.end, self.ring.floor)}
                self.ring.begin(wake, pre_roll_seconds=0.)
                self.resampler = ContinuousPcm24()
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
            if self.output is not None:
                raise ValueError('multiple_physical_output_owners')
            self.forward = False
            self.ring.set_blocked(True, reason='playback')
            self.output = {'response_id': data['response_id'], 'playback_id': uuid4().hex,
                           'output_epoch': self.output_epoch, 'encoder': self.encoder_factory(),
                           'seq': 0, 'started_at': None, 'role': data.get('audio_role', 'fast_answer'),
                           'done': False, 'consumed': 0, 'progress_seen': False,
                           'pcm_samples': 0}
            self.output['metrics'] = self.new_output_metrics(data['response_id'], self.output['role'])
            await self.send({'type': 'gobot_host_output_start', **self.output_fields(),
                             'kind': 'cue' if self.output['role'] == 'service_cue' else 'answer',
                             'streaming': True, 'packet_count': 0, 'codec': 'opus',
                             'sample_rate': 24000, 'frame_samples': 1440})
            await self.screen('speaking')
        elif kind == 'audio_chunk':
            if not self.output or data.get('response_id') in self.cancelled:
                return
            if data.get('response_id') != self.output['response_id']:
                raise ValueError('physical_response_mismatch')
            pcm = base64.b64decode(data['pcm'], validate=True)
            self.output['pcm_samples'] += len(pcm)//2
            for packet in self.output['encoder'].feed(pcm, 24000):
                await self.output_packet(packet)
        elif kind in ('expert_segment_generated', 'audio_segment_done'):
            if self.output and data.get('response_id') == self.output['response_id']:
                await self.send({'type': 'gobot_host_output_segment_end', **self.output_fields(),
                                 'segment_id': data.get('segment_id'),
                                 'pcm_sample_end': self.output['pcm_samples']})
        elif kind == 'audio_stop':
            if self.output and data.get('response_id') == self.output['response_id']:
                state = self.output
                for packet in self.output['encoder'].finish():
                    await self.output_packet(packet)
                self.output['done'] = True
                await self.send({'type': 'gobot_host_output_end', **self.output_fields(),
                                 'packet_count': self.output['seq'],
                                 'whole_response': self.output['role'] != 'service_cue'})
                state['metrics']['output_end_sent_monotonic'] = time.monotonic()
                state['metrics']['output_end_sent_wall'] = time.time()
        elif kind in ('audio_cancel', 'stopped'):
            await self.clear_output()
            self.forward = False
            self.stats['input_open'] = False
            self.ring.set_blocked(self.muted, reason='stop')
            await self.screen('muted' if self.muted else 'ready')
        elif kind == 'muted':
            self.muted = data.get('muted') is True
            self.forward = False
            self.stats['input_open'] = False
            self.ring.set_blocked(self.muted, reason='mute')
            await self.send({'type': 'gobot_host_mute', 'muted': self.muted})
            await self.screen('muted' if self.muted else 'ready')
        elif kind == 'mode_selected':
            self.mode = data['mode']
            self.stats['selected_mode'] = self.mode
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
            await asyncio.sleep(delay)
        while self.output is state and state['progress_seen'] and state['seq']-state['consumed'] >= 4:
            self.output_credit.clear()
            await asyncio.wait_for(self.output_credit.wait(), 2)
        if self.output is not state or state['response_id'] in self.cancelled:
            return
        await self.send({'type': 'gobot_host_output_frame', **self.output_fields(),
                         'seq': state['seq'], 'sample_start': state['seq']*1440,
                         'sample_count': 1440}, packet)
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
            if obj.get('stream_epoch') != self.ring.epoch or type(floor) is not int:
                raise ValueError('physical_playback_capture_floor_missing')
            self.output_receipt_metrics(state, obj)
            self.ring.set_blocked(True, sample_floor=max(self.ring.end, floor), reason='playback_guard')
            self.stats['playback_finished'] += 1
            self.output = None
            await self.to_brain({'type': 'playback_finished', 'response_id': state['response_id'],
                                 'sample_floor': floor})

    async def clear_output(self):
        async with self.cancel_lock:
            if self.output:
                self.cancelled.append(self.output['response_id'])
                self.output['cancel_pending'] = True
                self.cancel_finished.clear()
                await self.send({'type': 'gobot_host_output_cancel', **self.output_fields()})
                self.output_credit.set()
                await asyncio.wait_for(self.cancel_finished.wait(), 2)
                self.output_epoch += 1
                self.output = None

    async def stop(self, reason):
        self.forward = False
        self.ring.stop(reason)
        await self.clear_output()
        if self.brain:
            await self.to_brain({'type': 'stop'})
