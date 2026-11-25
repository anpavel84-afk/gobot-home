"""Bounded physical timer delivery, independent of paid speech or input.

Brain owns durable scope and claims. This transport owns one audible attempt
for each received claim; it never retries an uncertain attempt. Native display
receipts prove a framebuffer callback, not panel DMA or human observation.
"""
from __future__ import annotations

import asyncio
import math
import struct
import time
from uuid import UUID, uuid4


MAX_TIMERS = 16
MAX_SEEN_ALARMS = 256
MAX_DURATION_MS = 86400000
ALARM_FINISH_TIMEOUT = 4.
EXPIRED_DISPLAY_SECONDS = 8.
TERMINAL = {'finished', 'cancelled', 'suppressed', 'unknown'}


def identifier(value):
    if not isinstance(value, str) or len(value) != 36:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


def number(value, low, high):
    return type(value) in (int, float) and math.isfinite(value) and low <= value <= high


def alarm_pcm():
    """A fixed 360 ms, low-level 660 Hz signal with fades, at user volume."""
    samples = 1440*6
    pcm = bytearray(samples*2)
    for index in range(samples):
        envelope = min(1., index/960., (samples-1-index)/960.)
        value = int(2200*envelope*math.sin(2*math.pi*660*index/24000))
        struct.pack_into('<h', pcm, index*2, value)
    return bytes(pcm)


class SophiaTimerOutput:
    def __init__(self, connection, *, clock=time.time):
        self.connection, self.clock = connection, clock
        self.display_supported = False
        self.packets = ()
        self.snapshot_revision = -1
        self.snapshot_content = None
        self.wire_revision = 0
        self.display_pending = None
        self.pending = []
        self.seen = {}
        self.preempting = 0
        self.fenced = False
        self.changed = asyncio.Event()
        self.stats = {'display_supported': False, 'signal_supported': False,
                      'display': 'unavailable', 'signal': 'unavailable',
                      'invalid_events': 0, 'stale_events': 0, 'queued': 0,
                      'active': False, 'receipts_dropped': 0, 'display_receipt': None,
                      'alarm_last_state': None, 'delivery_state': 'idle',
                      'delay_reason': None, 'last_outcome_reason': None,
                      'postponed_count': 0, 'started_count': 0, 'finished_count': 0,
                      'cancelled_count': 0, 'suppressed_count': 0, 'unknown_count': 0}
        connection.stats['timer_output'] = self.stats

    def configure(self, hello):
        caps = hello.get('host_stream', {})
        self.display_supported = type(caps.get('timer_display')) is int and caps['timer_display'] == 1
        try:
            encoder = self.connection.encoder_factory()
            packets = tuple([*encoder.feed(alarm_pcm(), 24000), *encoder.finish()])
            if not 1 <= len(packets) <= 8 or any(not isinstance(p, bytes) or not 0 < len(p) <= 4096 for p in packets):
                raise ValueError('invalid_local_timer_packetization')
            self.packets = packets
        except Exception:
            # A missing local codec must not take down ordinary voice.
            self.packets = ()
        self.stats.update(display_supported=self.display_supported, signal_supported=bool(self.packets),
                          display='unconfirmed' if self.display_supported else 'unavailable',
                          signal='unconfirmed' if self.packets else 'unavailable')

    async def announce(self):
        await self.connection.to_brain({'type': 'timer_capabilities',
            'display_supported': self.display_supported,
            'signal_supported': bool(self.packets)})
        samples=[sample[0] for sample in struct.iter_unpack('<h',alarm_pcm())]
        await self.notify({'type':'telemetry','event':'timer_signal_metrics',
            'signal_samples':len(samples),'sample_rate':24000,'signal_hz':660,
            'signal_peak':max(map(abs,samples)),
            'signal_rms':round(math.sqrt(sum(x*x for x in samples)/len(samples)),2),
            'encoded_packets':len(self.packets),'not_acoustic_proof':True})

    def owns(self, state=None):
        state = self.connection.output if state is None else state
        if state is None or state.get('role') != 'timer_alarm':
            return False
        record = state.get('timer')
        return isinstance(record, dict) and self.seen.get(record.get('alarm_id')) is record

    def idle(self):
        c = self.connection
        return (not self.fenced and not self.preempting and not c.closed and not c.transport_ending
                and not c.muted and c.brain is not None and c.cloud_ready.is_set()
                and c.stats.get('device_protocol_confirmed') is True and c.output is None
                and not c.forward and not c.stats.get('input_open') and c.ring.cursor is None
                and c.pending_interrupt is None and c.stats.get('voice_phase') == 'ready')

    async def notify(self, event):
        try:
            await self.connection.to_brain(event)
        except Exception:
            self.stats['receipts_dropped'] += 1

    def queue_status(self):
        c = self.connection
        self.stats['queued'] = len(self.pending)
        self.stats['delay_reason'] = None
        if self.owns() and self.stats['active']:
            self.stats['delivery_state'] = 'playing'
        elif self.pending:
            delayed = not self.idle()
            reason = ('playback' if c.output is not None else 'input_open' if
                      c.forward or c.stats.get('input_open') or c.ring.cursor is not None else 'conversation_busy')
            self.stats['delivery_state'] = 'postponed' if delayed else 'queued'
            if delayed:
                self.stats['delay_reason'] = reason
                for record in self.pending:
                    if not record.get('postponed_recorded'):
                        record['postponed_recorded'] = True
                        self.stats['postponed_count'] += 1
        else:
            self.stats['delivery_state'] = self.stats['alarm_last_state'] or 'idle'

    def cancelled_by_snapshot(self, record):
        if self.snapshot_revision < record['revision']:
            return False
        item = next((item for item in self.snapshot_content or () if item['timer_id'] == record['timer_id']), None)
        return item is None or item['state'] == 'cancelled'

    async def ack(self, record, state, *, reason=None):
        if record.get('state') in TERMINAL or record.get('state') == state:
            return
        record['state'] = state
        self.stats['alarm_last_state'] = state
        self.stats[state+'_count'] += 1
        self.stats['last_outcome_reason'] = reason
        self.queue_status()
        await self.notify({'type': 'timer_alarm_ack', 'alarm_id': record['alarm_id'],
                           'claim_id': record['claim_id'], 'state': state})

    async def snapshot(self, data):
        if not isinstance(data, dict):
            self.stats['invalid_events'] += 1
            return
        revision, timers = data.get('revision'), data.get('timers')
        if type(revision) is not int or not 0 <= revision <= 2**53-1 or not isinstance(timers, list) or len(timers) > MAX_TIMERS:
            self.stats['invalid_events'] += 1
            return
        clean, ids = [], set()
        for item in timers:
            if (not isinstance(item, dict) or not identifier(item.get('timer_id'))
                    or item['timer_id'] in ids or type(item.get('revision')) is not int
                    or not 0 <= item['revision'] <= revision or item.get('state') not in {'running', 'expired', 'cancelled'}
                    or not number(item.get('deadline'), 0, 10**12)
                    or type(item.get('remaining_ms')) is not int or not 0 <= item['remaining_ms'] <= MAX_DURATION_MS):
                self.stats['invalid_events'] += 1
                return
            ids.add(item['timer_id'])
            clean.append({key: item[key] for key in ('timer_id', 'revision', 'state', 'deadline')})
        content = sorted(clean, key=lambda item: item['timer_id'])
        if revision < self.snapshot_revision or (revision == self.snapshot_revision and content != self.snapshot_content):
            self.stats['stale_events'] += 1
            return
        if revision == self.snapshot_revision:
            return  # Local monotonic countdown must not restart on each poll.
        self.snapshot_revision, self.snapshot_content = revision, content
        suppress = [record for record in self.pending if self.cancelled_by_snapshot(record)]
        self.pending = [record for record in self.pending if not self.cancelled_by_snapshot(record)]
        self.queue_status()
        for record in suppress:
            await self.ack(record, 'suppressed', reason='timer_cancelled')
        if self.owns() and self.cancelled_by_snapshot(self.connection.output['timer']):
            self.connection.output['timer_cancel_reason'] = 'timer_cancelled'
            await self.connection.clear_output()
        await self.render_snapshot()

    async def render_snapshot(self):
        """Presentation expires; durable timer history and alarm claims do not."""
        if not self.display_supported or self.snapshot_content is None:
            return
        clean, revision = self.snapshot_content, self.snapshot_revision
        now = self.clock()
        running = sorted((item for item in clean if item['state'] == 'running' and item['deadline'] > now),
                         key=lambda item: (item['deadline'], item['timer_id']))
        expired = sorted((item for item in clean if item['state'] in {'running','expired'}
                          and now-EXPIRED_DISPLAY_SECONDS < item['deadline'] <= now),
                         key=lambda item: (-item['deadline'], item['timer_id']))
        selected = (running or expired or [None])[0]
        state = 'running' if running else 'expired' if expired else 'clear'
        ident = selected['timer_id'] if selected else ''
        pending = self.display_pending
        if pending and (pending['snapshot_revision'],pending['timer_id'],pending['state']) == (revision,ident,state):
            return  # Do not restart countdown or resend an unchanged scene.
        remaining_ms = min(MAX_DURATION_MS, max(0, math.ceil((selected['deadline']-now)*1000))) if running else 0
        if self.wire_revision >= 0xffffffff:
            raise ValueError('timer_display_revision_exhausted')
        self.wire_revision += 1
        self.display_pending = {'revision': self.wire_revision, 'snapshot_revision': revision,
                                'timer_id': ident, 'state': state}
        self.stats['display_receipt'] = None
        await self.connection.send({'type': 'gobot_host_timer',
            **{key: self.display_pending[key] for key in ('revision', 'timer_id', 'state')},
            'remaining_ms': remaining_ms})

    async def display_receipt(self, obj):
        pending = self.display_pending
        if (not self.display_supported or not pending or any(obj.get(key) != pending[key] for key in ('revision', 'timer_id', 'state'))
                or type(obj.get('revision')) is not int or type(obj.get('rendered')) is not bool
                or obj.get('evidence') not in {'native_framebuffer_invalidated', 'native_framebuffer_unchanged'}
                or (pending['state'] == 'clear' and obj['rendered'])):
            self.stats['stale_events'] += 1
            return
        receipt = {'snapshot_revision': pending['snapshot_revision'], 'state': pending['state'],
                   'evidence': obj['evidence'], 'rendered': obj['rendered']}
        if self.stats['display_receipt'] == receipt:
            return
        self.stats['display_receipt'] = receipt
        if obj['rendered']:
            self.stats['display'] = 'confirmed'
        await self.notify({'type': 'timer_display_ack', **receipt})

    async def alarm(self, data):
        now = self.clock()
        if (not isinstance(data, dict) or any(not identifier(data.get(key)) for key in ('alarm_id', 'claim_id', 'timer_id'))
                or type(data.get('revision')) is not int or not 0 <= data['revision'] <= 2**53-1
                or not number(data.get('expires_at'), 0, now+125)):
            self.stats['invalid_events'] += 1
            return
        for key, record in list(self.seen.items()):
            if record['expires_at'] <= now and record.get('state') in TERMINAL:
                del self.seen[key]
        if data['alarm_id'] in self.seen:
            self.stats['stale_events'] += 1
            return
        if len(self.seen) >= MAX_SEEN_ALARMS:
            # Reject an overflow without evicting an audible attempt's fence.
            await self.notify({'type': 'timer_alarm_ack', 'alarm_id': data['alarm_id'],
                               'claim_id': data['claim_id'], 'state': 'suppressed'})
            return
        record = {key: data[key] for key in ('alarm_id', 'claim_id', 'timer_id', 'revision', 'expires_at')}
        record['state'] = 'queued'
        self.seen[data['alarm_id']] = record
        c = self.connection
        cancelled = self.cancelled_by_snapshot(record)
        if (not self.packets or self.fenced or c.muted or c.transport_ending or c.closed or c.pending_interrupt is not None
                or cancelled or record['expires_at'] <= now or len(self.pending) >= MAX_TIMERS):
            reason = ('signal_unavailable' if not self.packets else 'muted' if c.muted else
                      'timer_cancelled' if cancelled else 'expired' if record['expires_at'] <= now else
                      'queue_full' if len(self.pending) >= MAX_TIMERS else 'control_fence')
            await self.ack(record, 'suppressed', reason=reason)
            return
        self.pending.append(record)
        self.queue_status()
        self.changed.set()

    def fence(self, reason):
        self.fenced = True
        pending, self.pending = self.pending, []
        self.queue_status()
        for record in pending:
            self.connection.spawn(self.ack(record, 'suppressed', reason='control_fence'))
        if self.owns():
            self.connection.output['timer_cancel_reason'] = 'transport_closed' if reason == 'transport_closed' else 'control_fence'
        if reason == 'transport_closed' and self.owns():
            # The durable Brain claim prevents retry even if this ACK is lost.
            self.connection.spawn(self.ack(self.connection.output['timer'], 'unknown', reason='transport_closed'))
        self.changed.set()

    def ready(self):
        c = self.connection
        if not c.muted and not c.transport_ending and c.pending_interrupt is None:
            self.fenced = False
            self.queue_status()
            self.changed.set()

    async def preempt(self):
        if not self.owns():
            return
        self.preempting += 1
        try:
            self.connection.output['timer_cancel_reason'] = 'conversation_priority'
            await self.connection.clear_output()
        finally:
            self.preempting -= 1

    async def started(self, state):
        await self.ack(state['timer'], 'started')

    async def finished(self, state, outcome):
        if state.get('timer_finished'):
            return
        state['timer_finished'] = True
        state['timer_done'].set()
        self.stats['active'] = False
        if outcome == 'finished':
            self.stats['signal'] = 'confirmed'
        if self.idle():
            # The installed cue handler deliberately retains response_busy for
            # an expert's following answer. This independent cue has no such
            # answer: restore idle only after its real DMA/Stop barrier. A new
            # input or output can supersede this write while the lock is held.
            self.connection.ring.set_blocked(False, reason='timer_physical_quiet')
            await self.connection.send({'type': 'gobot_host_state', 'state': 'ready'}, timer_idle=True)
        if not self.connection.transport_ending:
            await self.notify({'type': 'timer_output_activity', 'alarm_id': state['timer']['alarm_id'],
                               'claim_id': state['timer']['claim_id'], 'active': False})
        await self.ack(state['timer'], outcome, reason=state.get('timer_cancel_reason') if outcome != 'finished' else None)
        self.queue_status()
        self.changed.set()

    async def play(self, record):
        c = self.connection
        if not self.idle():
            return False
        # Ownership is reserved synchronously before any lock/network await.
        response_id = 'timer_'+uuid4().hex
        state = {'response_id': response_id, 'playback_id': uuid4().hex, 'output_epoch': c.output_epoch,
                 'seq': 0, 'started_at': None, 'role': 'timer_alarm', 'done': False, 'start_sent': False,
                 'consumed': 0, 'progress_seen': False, 'pcm_samples': 8640,
                 'cancel_signal': asyncio.Event(), 'timer': record, 'timer_done': asyncio.Event(),
                 'metrics': c.new_output_metrics(response_id, 'timer_alarm')}
        c.output = state
        c.ring.set_blocked(True, reason='timer_alarm')
        self.stats['active'] = True
        self.queue_status()
        try:
            # This is output observation only, never a wake or input allowance.
            await c.to_brain({'type': 'timer_output_activity', 'alarm_id': record['alarm_id'],
                              'claim_id': record['claim_id'], 'active': True})
            fields = {key: state[key] for key in ('response_id', 'playback_id', 'output_epoch')}
            sent = await c.send({'type': 'gobot_host_output_start', **fields, 'kind': 'cue',
                                'streaming': True, 'packet_count': 0, 'codec': 'opus',
                                'sample_rate': 24000, 'frame_samples': 1440}, output_state=state)
            if not sent:
                if c.output is state:
                    await c.clear_output()
                return True
            for packet in self.packets:
                if c.output is not state or state.get('cancel_pending'):
                    break
                await c.output_packet(packet)
            if c.output is state and not state.get('cancel_pending'):
                state['done'] = True
                await c.send({'type': 'gobot_host_output_end', **fields,
                              'packet_count': state['seq'], 'whole_response': False}, output_state=state)
            waiters = [asyncio.create_task(state['timer_done'].wait()),
                       asyncio.create_task(state['cancel_signal'].wait())]
            try:
                await asyncio.wait(waiters, timeout=ALARM_FINISH_TIMEOUT,
                                   return_when=asyncio.FIRST_COMPLETED)
                if c.output is state:
                    if not state['cancel_signal'].is_set():
                        state['timer_cancel_reason'] = 'completion_timeout'
                    await c.clear_output()
            finally:
                for task in waiters:
                    task.cancel()
                await asyncio.gather(*waiters, return_exceptions=True)
            return True
        except Exception:
            await self.ack(record, 'unknown' if state['start_sent'] else 'suppressed', reason='transport_failure')
            raise  # Existing run() transport cleanup must prove physical quiet.

    async def tick(self):
        await self.render_snapshot()
        now = self.clock()
        expired = [record for record in self.pending if record['expires_at'] <= now]
        self.pending = [record for record in self.pending if record['expires_at'] > now]
        self.queue_status()
        for record in expired:
            await self.ack(record, 'suppressed', reason='expired')
        if self.pending and self.idle():
            record = self.pending.pop(0)
            self.queue_status()
            await self.play(record)

    async def run(self):
        while not self.connection.transport_ending:
            await self.tick()
            self.changed.clear()
            try:
                await asyncio.wait_for(self.changed.wait(), .25)
            except TimeoutError:
                pass
