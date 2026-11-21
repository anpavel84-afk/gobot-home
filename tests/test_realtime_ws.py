"""Mock-provider checks for the direct transport; no network or paid calls."""
import asyncio
import base64
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from gobot.realtime_ws import DirectOffer, DirectRealtimeManager
from gobot.realtime_contract import RealtimePolicy
from test_board_realtime import prepared, enable


class Socket:
    def __init__(self, *, bad_ack=False):
        self.sent = []
        self.queue = asyncio.Queue()
        self.config = {}
        self.closed = False
        self.bad_ack = bad_ack
        self.serial = 0

    async def send(self, raw):
        event = json.loads(raw)
        self.sent.append(event)
        if event['type'] == 'session.update':
            if 'model' in event['session']:
                self.config = json.loads(json.dumps(event['session']))
            else:
                self.config['audio']['input'].update(event['session'].get('audio', {}).get('input', {}))
            ack = json.loads(json.dumps(self.config))
            if self.bad_ack:
                ack['audio']['output']['voice'] = 'cedar'
            await self.queue.put({'type': 'session.updated', 'session': ack})
        elif event['type'] == 'response.create':
            self.serial += 1
            await self.queue.put({'type': 'response.created',
                                  'response': {'id': 'response-'+str(self.serial),
                                               'metadata': event['response'].get('metadata')}})

    async def recv(self):
        value = await self.queue.get()
        if value is None:
            raise ConnectionError('fixture_closed')
        return json.dumps(value)

    async def close(self):
        self.closed = True
        await self.queue.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        value = await self.queue.get()
        if value is None:
            raise StopAsyncIteration
        return json.dumps(value)


class Provider:
    def __init__(self, *, bad_ack=False):
        self.sockets = []
        self.bad_ack = bad_ack

    @asynccontextmanager
    async def open(self, model):
        assert model == 'gpt-realtime-2.1-mini'
        socket = Socket(bad_ack=self.bad_ack)
        self.sockets.append(socket)
        try:
            yield socket
        finally:
            await socket.close()


class CredentialGateProvider(Provider):
    def __init__(self):
        super().__init__()
        self.available = False
        self.attempts = 0

    @asynccontextmanager
    async def open(self, model):
        self.attempts += 1
        if not self.available:
            raise RuntimeError('realtime_key_missing')
        async with super().open(model) as socket:
            yield socket


def offer(**changes):
    return DirectOffer(session_id='direct-1', conversation_id='conversation-1',
                       device_id='board', client_id='board', consent=True,
                       requested_model='gpt-realtime-2.1-mini', client_kind='device', **changes)


def setup(tmp_path, settings, *, enabled=True, bad_ack=False):
    original, board, _, path = prepared(tmp_path, settings)
    if enabled:
        enable(path)
    provider = Provider(bad_ack=bad_ack)
    manager = DirectRealtimeManager(board, provider=provider)
    return original, board, manager, provider


async def cleanup(original, board, manager):
    await manager.shutdown()
    await board.shutdown()
    await original.shutdown()


async def complete_input(session, item_id='input-1', text='Сколько будет два плюс три?'):
    """Deliver the existing provider ASR final, required by physical input."""
    gate = session._wake_fragment
    await session.handle({'type': 'conversation.item.input_audio_transcription.completed',
                          'item_id': item_id, 'transcript': text})
    if gate is not None:
        await gate['task']


def test_empty_ready_and_rotation_consume_no_starts_or_pcm(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            assert s.ready and not s.input_open
            assert board.budget.status()['sessions_reserved'] == 0
            assert await s.append_pcm(bytes(4800)) is False
            s.started -= 4000  # A 60 second paid trial does not kill an empty pipe.
            await s.rotate()
            assert len(provider.sockets) == 2 and provider.sockets[0].closed
            assert board.budget.status()['sessions_reserved'] == 0
            assert not any(e['type'] in {'response.create', 'input_audio_buffer.append'}
                           for sock in provider.sockets for e in sock.sent)
            assert s.ready and s.transport_epoch == 2
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_stop_prunes_cancelled_pcm_and_overtakes_backlog_without_losing_other_response(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            while not s.outgoing.empty():
                s.outgoing.get_nowait()
            await s.publish_audio(bytes(4800), 'cancel-me')
            for i in range(50):
                await s.publish_audio(bytes(4800), 'cancel-me', chunk_seq=i+1)
            other = {'type': 'audio_chunk', 'data': {'response_id': 'other', 'pcm': 'fixture'}}
            s.outgoing.put_nowait(other)
            await s.interrupt()
            first = await s.next_event()
            assert first['type'] == 'audio_cancel' and first['data']['response_id'] == 'cancel-me'
            assert (await s.next_event())['type'] == 'telemetry'
            assert await s.next_event() == other
            assert not any(item and item.get('type', '').startswith('audio_') and
                           item.get('data', {}).get('response_id') == 'cancel-me'
                           for item in list(s.outgoing._queue))
            # A producer released from backpressure after cancellation is gated
            # again at dequeue, not played as a stale late packet.
            s.outgoing.put_nowait({'type': 'audio_chunk', 'data': {'response_id': 'cancel-me'}})
            s.emit('telemetry', event='still_alive')
            assert (await s.next_event())['type'] == 'telemetry'
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_local_audio_cancel_does_not_wait_for_stalled_provider_send(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            while not s.outgoing.empty():
                s.outgoing.get_nowait()
            await s.publish_audio(bytes(4800), 'cancel-now')
            gate = asyncio.Event()
            async def blocked(_):
                await gate.wait()
            s.send = blocked
            s.generating = True
            task = asyncio.create_task(s.interrupt())
            first = await asyncio.wait_for(s.next_event(), .1)
            # The first packet may already have been dequeued before the task
            # runs; allow that one in-flight packet, never the queued backlog.
            while first['type'] != 'audio_cancel':
                first = await asyncio.wait_for(s.next_event(), .1)
            assert first['data']['response_id'] == 'cancel-now'
            assert not task.done()
            gate.set()
            await task
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_mismatched_effective_configuration_is_never_ready(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings, bad_ack=True)
        try:
            with pytest.raises(RuntimeError, match='not_acknowledged'):
                await manager.accept(offer())
            assert board.budget.status()['sessions_reserved'] == 0
            assert provider.sockets[0].closed
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_rotation_rechecks_scope_before_reading_context_or_opening_provider(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            p = board.budget.policy().model_copy(update={'allowed_client_id': 'other-device'})
            board.budget.policy_path.write_text(p.model_dump_json())
            def context_forbidden(_):
                raise AssertionError('Changed scope must be rejected before context access')
            monkeypatch.setattr(manager.brain.memory, 'context', context_forbidden)
            with pytest.raises(PermissionError, match='warm_transport_scope_changed'):
                await s.rotate()
            assert len(provider.sockets) == 1
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_inactive_budget_still_allows_empty_ready_but_no_paid_input(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings, enabled=False)
        try:
            s = await manager.accept(offer())
            assert s.ready and not s.generation_allowed()
            with pytest.raises(PermissionError):
                await s.wake('wake-1')
            assert not s.input_open
            assert not await s.append_pcm(bytes(4800))
            assert board.budget.status()['sessions_reserved'] == 0
            assert not any(e['type'] == 'input_audio_buffer.append' for e in s.ws.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_wake_once_admits_before_burst_and_never_commits_preroll(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            assert (await s.wake('wake-1'))['accepted']
            assert (await s.wake('wake-1'))['duplicate']
            for _ in range(8):
                assert await s.append_pcm(bytes(2880))
            assert board.budget.status()['sessions_reserved'] == 1
            messages = [e['type'] for e in s.ws.sent]
            assert messages.count('input_audio_buffer.append') == 8
            assert 'input_audio_buffer.commit' not in messages
            assert 'response.create' not in messages
            vad = s.ws.config['audio']['input']['turn_detection']
            assert vad['create_response'] is False and vad['interrupt_response'] is False
            assert vad['silence_duration_ms'] == 450 and vad['idle_timeout_ms'] is None
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_paid_usage_is_recorded_against_operation_not_empty_socket(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            await s.wake('wake-1')
            await s.handle({'type': 'input_audio_buffer.committed', 'item_id': 'input-1'})
            await complete_input(s)
            await asyncio.sleep(.02)
            ident = s.live_response
            assert ident and not s.input_open
            await s.handle({'type': 'response.done', 'response': {
                'id': ident, 'status': 'completed', 'usage': {'total_tokens': 23}}})
            assert board.budget.total_tokens(s.operation_id) == 23
            assert board.budget.total_tokens(s.id) == 0
            with board.budget.connect() as db:
                assert db.execute('SELECT responses FROM sessions').fetchone()[0] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_generation_and_segment_end_never_open_followup(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            await s.wake('wake-1')
            await s.handle({'type': 'input_audio_buffer.committed', 'item_id': 'input-1'})
            await complete_input(s)
            await asyncio.sleep(.02)
            ident = s.live_response
            await s.handle({'type': 'response.output_audio.delta', 'response_id': ident,
                            'delta': base64.b64encode(bytes(2880)).decode()})
            await s.handle({'type': 'response.done', 'response': {'id': ident, 'status': 'completed'}})
            await asyncio.sleep(.25)
            assert s.speaking and not s.input_open
            with pytest.raises(ValueError, match='not_confirmed'):
                await s.playback_finished(ident)
            await s.playback_started(ident)
            await s.playback_finished(ident, segment_id='sentence-1')
            assert not s.input_open
            assert not (await s.playback_finished('stale-response'))['accepted']
            await s.playback_finished(ident, sample_floor=42000)
            assert not s.input_open  # Guard is real.
            await asyncio.sleep(.25)
            assert s.input_open and s.input_mode == 'followup'
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('has_pcm', [False, True])
def test_token_limited_direct_audio_waits_for_actual_playback_receipt(tmp_path, settings, has_pcm):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            await s.wake('wake-1')
            await s.handle({'type': 'input_audio_buffer.committed', 'item_id': 'input-1'})
            await complete_input(s)
            await asyncio.sleep(.02)
            ident, turn = s.live_response, s.current
            assert ident
            await s.handle({'type': 'response.output_audio.delta', 'response_id': ident,
                            'delta': base64.b64encode(bytes(2880) if has_pcm else b'').decode()})
            await s.handle({'type': 'response.done', 'response': {
                'id': ident, 'status': 'incomplete',
                'status_details': {'reason': 'max_output_tokens'}}})
            assert turn.truncated and 'output_buffer_started' not in turn.timings
            assert not any(e['type'] == 'turn_complete' for e in s.events)
            assert not s.input_open
            if has_pcm:
                assert not turn.stored and not turn.cancelled
                assert s.response_audio_available(turn)
                assert not any(e['type'] == 'turn_incomplete' for e in s.events)
                await s.playback_started(ident)
                assert not turn.stored
                await s.playback_finished(ident, sample_floor=42000)
                assert turn.stored and not turn.cancelled
                assert any(e['type'] == 'turn_complete' and e['data'].get('heard') is True
                           and e['data'].get('incomplete') is True for e in s.events)
            else:
                assert turn.stored and turn.cancelled
                assert not s.response_audio_available(turn)
                assert s.output_owner is None
                assert not any(e['type'] == 'audio_start' for e in s.events)
                assert any(e['type'] == 'turn_incomplete' for e in s.events)
            # There is no automatic retry or budget extension for truncation.
            assert sum(e['type'] == 'response.create' for e in s.ws.sent) == 1
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_followup_speech_start_disarms_silence_deadline(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            await s.wake('wake-1')
            await s.handle({'type': 'input_audio_buffer.speech_started'})
            assert s.followup_deadline is None
            await asyncio.sleep(.15)
            assert s.input_open
            # A no-speech window closes input but keeps the warm socket.
            s._input_started = False
            s.followup_deadline = time.monotonic()-1
            await asyncio.sleep(.2)
            assert not s.input_open and s.ready and not s.closed
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_expired_operation_never_auto_renews_and_rotation_keeps_job(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            await s.wake('wake-1')
            await s.stop()
            s.operation_started -= 61
            with pytest.raises(PermissionError, match='new_wake'):
                await s.admission(explicit_wake=False)
            assert board.budget.status()['sessions_reserved'] == 1
            # A logical worker is owned by ExpertJobs, not the socket reader.
            gate = asyncio.Event()
            worker = asyncio.create_task(gate.wait())
            s.experts.active = lambda: not worker.done()
            await s.rotate()
            assert not worker.done() and not worker.cancelled()
            assert board.budget.status()['sessions_reserved'] == 1
            gate.set()
            await worker
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_mute_and_stop_reject_late_audio_and_input(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            await s.wake('wake-1')
            await s.handle({'type': 'input_audio_buffer.committed', 'item_id': 'input-1'})
            await complete_input(s)
            await asyncio.sleep(.02)
            ident = s.live_response
            await s.publish_audio(bytes(2880), ident)
            await s.mute(True)
            size = s.outgoing.qsize()
            assert not await s.publish_audio(bytes(2880), ident)
            assert not await s.append_pcm(bytes(2880))
            assert size == s.outgoing.qsize()
            with pytest.raises(PermissionError, match='muted'):
                await s.wake('wake-2')
            await s.mute(False)
            assert not s.input_open
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_source_binding_and_expert_grant_cannot_be_borrowed(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            with pytest.raises(PermissionError):
                await manager.accept(offer(owner_test_binding='phone'))
            with pytest.raises(PermissionError):
                await manager.accept(offer(expert_quota_consent=True))
            assert not provider.sockets
            s = await manager.accept(offer())
            with pytest.raises(PermissionError, match='source'):
                await s.wake('wake-1', source='browser')
            await s.select_mode('expert')
            with pytest.raises(PermissionError, match='expert_unavailable'):
                await s.wake('wake-expert')
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_detach_reattach_preserves_identity_and_does_not_repeat_reservation(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            await s.wake('wake-1')
            experts = s.experts
            operation = s.operation_id
            await s.detach()
            assert not s.closed and s.experts.detached
            restored = await manager.accept(offer())
            assert restored is s and not s.experts.detached
            assert s.experts is experts and s.operation_id == operation
            assert not s.input_open and len(provider.sockets) == 1
            assert not await s.append_pcm(bytes(4800))
            assert board.budget.status()['sessions_reserved'] == 1
            with pytest.raises(ValueError, match='already_attached'):
                await manager.accept(offer())
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_stable_identity_reopens_only_empty_failed_setup_when_credentials_return(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        provider = manager.provider = CredentialGateProvider()
        try:
            with pytest.raises(RuntimeError, match='realtime_key_missing'):
                await manager.accept(offer())
            failed = manager.sessions['direct-1']
            assert failed.closed and failed.close_reason == 'setup_failed'
            assert failed._empty_setup_failed and not failed.setup_done
            assert board.budget.status()['sessions_reserved'] == 0
            provider.available = True
            session = await manager.accept(offer())
            assert session is not failed and session.ready and not session.input_open
            assert provider.attempts == 2 and len(manager.sessions) == 1
            assert board.budget.status()['sessions_reserved'] == 0
            assert not any(e['type'] in {'response.create', 'input_audio_buffer.append'}
                           for socket in provider.sockets for e in socket.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_empty_setup_retry_is_scoped_and_rate_bounded_without_changing_paid_ledger(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        provider = manager.provider = CredentialGateProvider()
        try:
            for _ in range(3):
                with pytest.raises(RuntimeError, match='realtime_key_missing'):
                    await manager.accept(offer())
            with pytest.raises(ValueError, match='empty_setup_retry_rate_limited'):
                await manager.accept(offer())
            assert provider.attempts == 3
            with pytest.raises(PermissionError, match='identity_mismatch'):
                await manager.accept(offer().model_copy(update={'conversation_id': 'another-conversation'}))
            assert provider.attempts == 3
            # This advances only the empty-transport rate window; grants and
            # monetary counters are untouched and no microphone byte is replayed.
            attempts = manager._empty_setup_attempts['direct-1']
            for index in range(len(attempts)):
                attempts[index] -= 61
            provider.available = True
            session = await manager.accept(offer())
            assert session.ready and not session.input_open and provider.attempts == 4
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_used_or_explicitly_closed_stable_conversation_cannot_use_setup_retry(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('paid-wake')
            operation = session.operation_id
            await manager.close(session.id, 'board', 'board', None, 'setup_failed')
            assert not session._empty_setup_failed
            with pytest.raises(ValueError, match='logical_conversation_closed'):
                await manager.accept(offer())
            assert board.budget.status()['sessions_reserved'] == 1
            assert session.operation_id == operation and len(provider.sockets) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_failed_empty_reattach_releases_subscriber_without_cancelling_logical_jobs(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        provider = manager.provider = CredentialGateProvider()
        provider.available = True
        try:
            session = await manager.accept(offer())
            experts = session.experts
            gate = asyncio.Event()
            worker = asyncio.create_task(gate.wait())
            session.experts.active = lambda: not worker.done()
            await session.detach()
            session.ready = False
            provider.available = False
            with pytest.raises(RuntimeError, match='realtime_key_missing'):
                await manager.accept(offer())
            assert not session.attached and session.experts.detached and not session.closed
            assert not worker.done() and session.experts is experts
            provider.available = True
            restored = await manager.accept(offer())
            assert restored is session and session.attached and not session.experts.detached
            assert not worker.done() and board.budget.status()['sessions_reserved'] == 0
            gate.set()
            await worker
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_service_cue_physical_end_gates_expert_audio_and_never_followup(tmp_path, settings, monkeypatch):
    import gobot.expert_stream
    monkeypatch.setattr(gobot.expert_stream, 'load_expert_service_cue', lambda: {
        'status': 'ready', 'pcm': bytes(4800), 'sample_rate': 24000, 'sha256': 'a'*64})
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            manager.speech = object()
            manager.narrator_authorizer = lambda session, job: {'paid_tts_consent': True, 'tts_character_limit': 1000}
            s = await manager.accept(offer())
            s.experts.active = lambda: True
            job = SimpleNamespace(id='job-1', response_id='expert-1')
            options = await s.expert_stream_started(job)
            assert options['voice'] == 'marin'
            await asyncio.sleep(.01)
            cue_id = s.output_response
            assert s.output_owner == 'service_cue'
            task = asyncio.create_task(s.expert_stream_event(job, {
                'type': 'audio_chunk', 'response_id': 'expert-1',
                'data': {'pcm': base64.b64encode(bytes(2880)).decode(), 'segment_id': 'segment-1'}}))
            await asyncio.sleep(.01)
            assert not task.done()
            await s.playback_started(cue_id)
            await s.playback_finished(cue_id)
            await task
            assert s.output_owner == 'expert_answer' and s.output_response == 'expert-1'
            assert not s.input_open and s._guard_task is None
            assert not any(event['type'] == 'response.create' for event in s.ws.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_partial_expert_context_updates_without_second_reply(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            job = SimpleNamespace(id='job-1')
            item = {'state': 'running', 'speech_text': 'Первый.', 'played_text': '',
                    'result': {'display_text': 'Первый.'}, 'job_id': job.id}
            await s.expert_context_synced(job, item)
            await s.expert_context_synced(job, item)
            await s.expert_context_synced(job, {**item, 'speech_text': 'Первый. Второй.'})
            notices = [e for e in s.ws.sent if e['type'] == 'conversation.item.create']
            assert len(notices) == 2
            assert all(e['item']['type'] == 'message' for e in notices)
            assert not any(e['type'] == 'response.create' for e in s.ws.sent)
            s.ready = False
            assert await s.expert_context_synced(job, item) is False
            s.ready = True
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_selected_expert_transcription_keeps_explicit_duration_and_usage(tmp_path, settings, monkeypatch):
    from gobot.expert_store import ExpertPolicy
    import gobot.expert_profiles as profiles
    resolve = profiles.resolve_profile
    monkeypatch.setattr(profiles, 'resolve_profile', lambda name: resolve(name, codex_metadata=[{
        'slug': 'gpt-6.1-sol', 'supported_reasoning_levels': [{'effort': 'high'}]}]))
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        observed = {}
        class Recognition:
            async def live(self, chunks, **options):
                observed['options'] = options
                count = 0
                async for part in chunks:
                    count += len(part)
                yield {'type': 'stt_final', 'data': {
                    'text': 'Сравни два решения', 'stable': True, 'item_id': 'stable-item',
                    'audio_seconds': count/48000, 'usage': {'type': 'duration', 'seconds': count/48000},
                    'usage_reported': True}}
        async def settle(**usage):
            observed['usage'] = usage
        manager.recognition = Recognition()
        manager.transcription_authorizer = lambda s: {
            'paid_consent': True, 'max_audio_seconds': 180,
            'operation_timeout_seconds': 240, 'settle': settle}
        try:
            s = await manager.accept(offer())
            s.experts.budget.policy_path.write_text(ExpertPolicy(allowed_profiles=['SOL_HIGH']).model_dump_json())
            s.experts.status = lambda **kw: {'enabled': True, 'blocked_reasons': []}
            async def start_local(text, profile, turn):
                assert s.expert_input_authorized(turn)
                observed['task'] = (text, profile, turn.input_id)
            s.experts.start_local = start_local
            await s.select_mode('expert')
            await s.wake('expert-wake')
            assert await s.append_pcm(bytes(4800))
            await s.finish_input()
            await s._stt_task
            assert observed['options']['max_audio_seconds'] == 180
            assert observed['task'] == ('Сравни два решения', 'SOL_HIGH', 'stable-item')
            assert observed['usage']['provider_usage'] == {'type': 'duration', 'seconds': .1}
            assert board.budget.status()['sessions_reserved'] == 0
            assert not any(e['type'] == 'input_audio_buffer.append' for e in s.ws.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
