"""Accelerated deadlines with synthetic CLI/speech, never paid providers."""
import asyncio
import base64
import json
import time
from contextlib import asynccontextmanager

import pytest

from gobot.audio import Speech
from gobot.expert_stream import AnswerDelta
from gobot.processes import AgentError
from test_realtime_ws import cleanup
from test_unified_board_admission import setup
from test_unified_voice_budget import SpeechFixture, TurnFixture, usage


class ClosingSpeech(SpeechFixture):
    def turn(self):
        class Turn(TurnFixture):
            closed = False
            async def __aexit__(self, *args): self.closed = True
        turn = Turn(True)
        self.turns.append(turn)
        return turn


def metadata(monkeypatch):
    import gobot.expert_jobs as jobs
    import gobot.expert_stream as stream
    from gobot.expert_profiles import resolve_profile
    rows = [{'slug': 'gpt-6.1-sol', 'supported_reasoning_levels': [{'effort': 'high'}]}]
    monkeypatch.setattr(jobs, 'resolve_profile', lambda name: resolve_profile(name, codex_metadata=rows))
    monkeypatch.setattr(stream, 'load_expert_service_cue', lambda: {'status': 'missing'})
    return jobs


async def start(session, *, seconds=.04):
    session.experts.admission = lambda profile: {'available': True}
    await session.wake('manual')
    turn = await session.new_turn(query='София, спроси у Codex, сравни два публичных метода')
    job = await session.experts.start_local(turn.query, 'SOL_HIGH', turn)
    # Compress the duration of this already-admitted synthetic job; production
    # still gets its unchanged 90 seconds from the exact existing grant.
    job.timeout_seconds = seconds
    return job


def test_completed_cli_survives_slower_narration_and_playback_keeps_real_ack(tmp_path, settings, monkeypatch):
    jobs = metadata(monkeypatch)
    calls = []
    async def source(settings, req, packet, *, expert_profile):
        calls.append(req.turn_id)
        yield AnswerDelta('Первый метод надёжен. ', phase='partial_answer', verified=True, job_id=req.turn_id)
        await asyncio.sleep(.002)
        yield AnswerDelta('Второй метод быстрее.', phase='final_answer', verified=True, job_id=req.turn_id)
    monkeypatch.setattr(jobs, 'bridge_stream', source)
    async def run():
        original, board, manager, session, _ = await setup(tmp_path, settings)
        manager.speech = ClosingSpeech()
        deliver = session.expert_stream_event
        async def slow(job, event):
            if event['type'] == 'audio_chunk': await asyncio.sleep(.07)
            await deliver(job, event)
        session.expert_stream_event = slow
        try:
            job = await start(session)
            before = time.monotonic()
            async with asyncio.timeout(2): await job.worker
            assert time.monotonic()-before > job.timeout_seconds*2
            assert job.state == 'completed' and job.narration_complete
            assert not job.playback_complete and not job.played_text
            assert job.result['display_text'] == 'Первый метод надёжен. Второй метод быстрее.'
            assert job.timings['codex_result_complete'] < job.timings['completed']
            assert len(calls) == 1 and manager.speech.turns[0].requests_started == 2
            assert manager.speech.turns[0].closed
            await session.playback_started(job.response_id)
            await session.playback_finished(job.response_id)
            assert job.playback_complete and 'Второй метод' in job.played_text
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def test_cli_deadline_still_cancels_a_slow_producer_while_narration_waits(tmp_path, settings, monkeypatch):
    jobs = metadata(monkeypatch)
    async def run():
        closed, delivery_closed = asyncio.Event(), asyncio.Event()
        async def source(settings, req, packet, *, expert_profile):
            try:
                yield AnswerDelta('Первая готовая часть. ', phase='partial_answer', verified=True, job_id=req.turn_id)
                await asyncio.Event().wait()
            finally: closed.set()
        monkeypatch.setattr(jobs, 'bridge_stream', source)
        original, board, manager, session, _ = await setup(tmp_path, settings)
        manager.speech = ClosingSpeech()
        deliver = session.expert_stream_event
        async def blocked(job, event):
            if event['type'] == 'audio_chunk':
                try: await asyncio.Event().wait()
                finally: delivery_closed.set()
            await deliver(job, event)
        session.expert_stream_event = blocked
        try:
            job = await start(session, seconds=.08)
            async with asyncio.timeout(1): await job.worker
            assert job.state == 'timed_out' and job.error == 'expert_timeout'
            assert closed.is_set() and delivery_closed.is_set()
            assert manager.speech.turns[0].closed
            assert 'codex_result_complete' not in job.timings
            assert manager.public_expert_budget.status()['sessions_reserved'] == 1
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def test_stalled_delivery_is_bounded_without_losing_completed_cli_text_or_retry(tmp_path, settings, monkeypatch):
    jobs = metadata(monkeypatch)
    monkeypatch.setattr(jobs, 'EXPERT_DELIVERY_STALL_SECONDS', .04)
    calls = []
    async def source(settings, req, packet, *, expert_profile):
        calls.append(req.turn_id)
        yield AnswerDelta('Полный оплаченный текст. Следующее пояснение.', phase='final_answer', verified=True, job_id=req.turn_id)
    monkeypatch.setattr(jobs, 'bridge_stream', source)
    async def run():
        original, board, manager, session, _ = await setup(tmp_path, settings)
        manager.speech = ClosingSpeech()
        closed = asyncio.Event()
        async def stalled(job, event):
            if event['type'] == 'audio_chunk':
                try: await asyncio.Event().wait()
                finally: closed.set()
        session.expert_stream_event = stalled
        try:
            job = await start(session)
            async with asyncio.timeout(1): await job.worker
            assert job.state == 'completed' and closed.is_set() and job.speech_cancelled
            assert session.experts.detached and not job.playback_complete
            assert job.result['display_text'] == 'Полный оплаченный текст. Следующее пояснение.'
            assert len(calls) == 1 and all(t.closed for t in manager.speech.turns)
            assert not any(t.get_name() in {'expert-source:'+job.id, 'expert-narrator:'+job.id}
                           for t in asyncio.all_tasks() if not t.done())
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def test_stop_cancels_both_independent_producer_and_waiting_narrator(tmp_path, settings, monkeypatch):
    jobs = metadata(monkeypatch)
    async def run():
        producer_closed, delivering, delivery_closed = asyncio.Event(), asyncio.Event(), asyncio.Event()
        async def source(settings, req, packet, *, expert_profile):
            try:
                yield AnswerDelta('Содержательная часть ответа. ', phase='partial_answer', verified=True, job_id=req.turn_id)
                await asyncio.Event().wait()
            finally: producer_closed.set()
        monkeypatch.setattr(jobs, 'bridge_stream', source)
        original, board, manager, session, _ = await setup(tmp_path, settings)
        manager.speech = ClosingSpeech()
        async def stalled(job, event):
            if event['type'] == 'audio_chunk':
                delivering.set()
                try: await asyncio.Event().wait()
                finally: delivery_closed.set()
        session.expert_stream_event = stalled
        try:
            job = await start(session, seconds=5)
            async with asyncio.timeout(1):
                await delivering.wait()
                await session.stop()
            assert job.state == 'cancelled' and producer_closed.is_set() and delivery_closed.is_set()
            assert all(t.closed for t in manager.speech.turns)
            assert not session.input_open and not job.playback_complete
            assert manager.public_expert_budget.status()['sessions_reserved'] == 1
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def test_independent_text_spool_rejects_oversized_output_before_storing_it(tmp_path, settings, monkeypatch):
    jobs = metadata(monkeypatch)
    async def source(settings, req, packet, *, expert_profile):
        for _ in range(1000):
            yield AnswerDelta('', phase='partial_answer', verified=True, job_id=req.turn_id)
        yield AnswerDelta('Краткая часть. ', phase='partial_answer', verified=True, job_id=req.turn_id)
        yield AnswerDelta('А'*6001, phase='final_answer', verified=True, job_id=req.turn_id)
    monkeypatch.setattr(jobs, 'bridge_stream', source)
    async def run():
        original, board, manager, session, _ = await setup(tmp_path, settings)
        manager.narrator_authorizer = None
        try:
            job = await start(session, seconds=1)
            async with asyncio.timeout(2): await job.worker
            assert job.state == 'failed' and job.answer_text == 'Краткая часть. '
            assert len(job.answer_text) < job.max_result_characters
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def test_stalled_context_delivery_keeps_result_pending_until_successful_attach(tmp_path, settings, monkeypatch):
    jobs = metadata(monkeypatch)
    monkeypatch.setattr(jobs, 'EXPERT_DELIVERY_STALL_SECONDS', .04)
    calls = []
    async def source(settings, req, packet, *, expert_profile):
        calls.append(req.turn_id)
        yield AnswerDelta('Полный текст сохранён в памяти.', phase='final_answer', verified=True, job_id=req.turn_id)
    monkeypatch.setattr(jobs, 'bridge_stream', source)
    async def run():
        original, board, manager, session, _ = await setup(tmp_path, settings)
        manager.speech = ClosingSpeech()
        send = session.send
        stalled, closed = asyncio.Event(), asyncio.Event()
        async def blocked(event):
            if event['type'] == 'conversation.item.create':
                stalled.set()
                try: await asyncio.Event().wait()
                finally: closed.set()
            return await send(event)
        session.send = blocked
        try:
            job = await start(session, seconds=.15)
            async with asyncio.timeout(1): await job.worker
            assert stalled.is_set() and closed.is_set()
            assert job.state == 'completed' and job.result['display_text'] == 'Полный текст сохранён в памяти.'
            assert session.experts.detached and job.speech_cancelled
            assert not session._context_synced and job.id not in session.experts.context_versions
            assert not any(t.get_name() in {'expert-source:'+job.id, 'expert-narrator:'+job.id}
                           for t in asyncio.all_tasks() if not t.done())
            session.send = send
            await session.experts.attach(session)
            assert not session.experts.detached
            assert session._context_synced and job.id in session.experts.context_versions
            assert len(calls) == 1 and job.returned
            assert not job.playback_complete and not job.played_text
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def test_fallback_packet_preparation_keeps_original_cli_deadline(tmp_path, settings, monkeypatch):
    jobs = metadata(monkeypatch)
    calls = []
    async def source(settings, req, packet, *, expert_profile):
        calls.append(req.turn_id)
        yield AnswerDelta('Never started', phase='final_answer', verified=True, job_id=req.turn_id)
    monkeypatch.setattr(jobs, 'bridge_stream', source)
    async def run():
        original, board, manager, session, _ = await setup(tmp_path, settings)
        closed = asyncio.Event()
        async def blocked(job):
            try: await asyncio.Event().wait()
            finally: closed.set()
        try:
            job = await start(session)
            job.packet = {}
            session.experts.prepare_packet = blocked
            async with asyncio.timeout(1): await job.worker
            assert job.state == 'timed_out' and job.error == 'expert_timeout'
            assert closed.is_set() and not calls and not manager.speech.turns
            assert manager.public_expert_budget.status()['sessions_reserved'] == 1
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def provider_fixture(*, reads_delay=.003, chunks=2):
    sent, contexts = [], []
    class Socket:
        def __init__(self): self.queue = asyncio.Queue()
        async def send(self, raw):
            event = json.loads(raw); sent.append(event)
            if event['type'] == 'session.update': await self.queue.put({'type': 'session.updated'})
            if event['type'] == 'response.create':
                for _ in range(chunks):
                    await self.queue.put({'type': 'response.output_audio.delta', 'delta': base64.b64encode(bytes(480)).decode()})
                await self.queue.put({'type': 'response.done', 'response': {
                    'id': 'one-response', 'status': 'completed', 'usage': usage()['usage']}})
        async def recv(self):
            await asyncio.sleep(reads_delay)
            return json.dumps(await self.queue.get())
    @asynccontextmanager
    async def connector(*args, **kwargs):
        marker = {'closed': False}; contexts.append(marker)
        try: yield Socket()
        finally: marker['closed'] = True
    return Speech(api_key='synthetic', connector=connector), sent, contexts


def test_tts_provider_budget_excludes_slow_consumer_without_extra_response(monkeypatch):
    import gobot.audio as audio
    monkeypatch.setattr(audio, 'TTS_PROVIDER_TIMEOUT_SECONDS', .05)
    async def run():
        speech, sent, contexts = provider_fixture()
        result = []
        async with speech.turn() as turn:
            async for chunk in turn.synthesize('Точный публичный текст.', paid_consent=True):
                result.append(chunk)
                await asyncio.sleep(.07)
            assert turn.requests_started == 1 and len(turn.usage_records) == 1
        assert len(result) == 2 and all(c['closed'] for c in contexts)
        assert sum(e['type'] == 'response.create' for e in sent) == 1
        assert not any(e['type'] == 'response.cancel' for e in sent)
    asyncio.run(run())


def test_tts_timeout_remains_cumulative_across_provider_reads(monkeypatch):
    import gobot.audio as audio
    monkeypatch.setattr(audio, 'TTS_PROVIDER_TIMEOUT_SECONDS', .07)
    async def run():
        speech, sent, contexts = provider_fixture(reads_delay=.025, chunks=4)
        async with speech.turn() as turn:
            with pytest.raises(AgentError, match='openai_tts_timeout'):
                async for _ in turn.synthesize('Одна попытка.', paid_consent=True): await asyncio.sleep(.01)
            assert turn.requests_started == 1 and turn.usage_records == []
        assert sum(e['type'] == 'response.create' for e in sent) == 1
        assert sum(e['type'] == 'response.cancel' for e in sent) == 1
        assert all(c['closed'] for c in contexts)
    asyncio.run(run())


def test_tts_close_during_paused_yield_cancels_once_and_leaves_no_timeout(monkeypatch):
    import gobot.audio as audio
    monkeypatch.setattr(audio, 'TTS_PROVIDER_TIMEOUT_SECONDS', .04)
    async def run():
        speech, sent, contexts = provider_fixture()
        async with speech.turn() as turn:
            stream = turn.synthesize('Отмена ответа.', paid_consent=True)
            await anext(stream)
            await asyncio.sleep(.06)
            async with asyncio.timeout(.2): await stream.aclose()
            assert turn.requests_started == 1 and turn.usage_records == []
        await asyncio.sleep(.05)
        assert sum(e['type'] == 'response.create' for e in sent) == 1
        assert sum(e['type'] == 'response.cancel' for e in sent) == 1
        assert all(c['closed'] for c in contexts)
    asyncio.run(run())
