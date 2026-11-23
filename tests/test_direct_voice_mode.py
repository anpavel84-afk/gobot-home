"""Explicit mode controls through real Direct handlers, with fake speech only.

All text is synthetic. These checks use temporary ledgers and in-memory provider
sockets; no CLI, model API, microphone or physical acceptance is involved.
"""
import asyncio
import json
import threading

import pytest

from gobot.direct_mode_control import direct_mode_intent
from test_direct_admission_status import ledger_snapshot
from test_owner_terminal_direct import setup_terminal
from test_realtime_ws import cleanup, complete_input


@pytest.mark.parametrize('text,mode', [
    ('переведи меня в экспертный режим', 'expert'),
    ('Переключи меня в экспертный режим!', 'expert'),
    ('Давай перейдём в экспертный режим.', 'expert'),
    ('София, переведи меня в экспертный режим, пожалуйста.', 'expert'),
    ('Софья, пожалуйста, включи экспертный режим.', 'expert'),
    ('София, ты можешь, пожалуйста, перевести меня в экспертный режим?', 'expert'),
    ('Слушай, а ты можешь сейчас перейти в экспертный режим, пожалуйста?', 'expert'),
    ('Можете переключиться в экспертный режим?', 'expert'),
    ('Гобот, подскажите, пожалуйста, вы можете переключить нас в режим эксперта?', 'expert'),
    ('Гобот, подскажите, пожалуйста, можете перевести нас в режим эксперт?', 'expert'),
    ('Можешь ли ты перевести меня, пожалуйста, в экспертный режим?', 'expert'),
    ('Ты могла бы переключить меня в экспертный режим?', 'expert'),
    ('Прошу включить экспертный режим.', 'expert'),
    ('Я хочу перейти в экспертный режим.', 'expert'),
    ('Хочу экспертный режим.', 'expert'),
    ('Экспертный режим А.', 'expert'),
    ('София, включи эксперта.', 'expert'),
    ('Можешь включить эксперта?', 'expert'),
    ('София, переключи меня в быстрый режим.', 'fast'),
    ('Вернись в обычный режим.', 'fast'),
    ('Живой разговор.', 'fast'),
    ('София, можешь перейти в обычный режим, пожалуйста?', 'fast'),
    ('Вернись к обычному разговору.', 'fast'),
])
def test_complete_direct_mode_commands(text, mode):
    assert direct_mode_intent(text) == mode


@pytest.mark.parametrize('text', [
    'Что такое экспертный режим?',
    'София, объясни, что такое экспертный режим.',
    'Ты можешь объяснить экспертный режим?',
    'Гобот, подскажите, что такое режим эксперт?',
    'Подскажи экспертный режим.',
    'Режим эксперт.',
    'Не переходи в экспертный режим.',
    'София, пожалуйста, не включай эксперта.',
    'Отмени экспертный режим.',
    'Он сказал: включи экспертный режим.',
    '«Включи экспертный режим»',
    'София, "включи эксперта".',
    'Если я скажу включи экспертный режим, что будет?',
    'Переведи меня в экспертный режим и сравни два решения.',
    'Переведи меня в экспертный режим. Почему небо синее?',
    'Спроси у эксперта, почему небо синее.',
    'Включи экспертный режим ' + 'пожалуйста ' * 30,
])
def test_mode_mentions_negations_quotes_and_tasks_are_not_controls(text):
    assert direct_mode_intent(text) is None


def mode_events(session):
    return [e['data']['mode'] for e in session.events if e['type'] == 'mode_selected']


def responses(provider):
    return [event for socket in provider.sockets for event in socket.sent
            if event['type'] == 'response.create']


async def final_fast_input(session, text, *, item='mode-input'):
    await session.handle({'type': 'input_audio_buffer.committed', 'item_id': item})
    turn = session.current
    await complete_input(session, item, text)
    return turn


@pytest.mark.parametrize('text', [
    'переведи меня в экспертный режим',
    'София, ты можешь, пожалуйста, перевести меня в экспертный режим?',
    'София, можешь перейти в экспертный режим, пожалуйста?',
    'София, включи эксперта.',
])
def test_final_physical_asr_switches_without_model_reply_memory_lookup_or_expert_job(
        tmp_path, settings, monkeypatch, text):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        async def unexpected_lookup(_):
            raise AssertionError('A mode command is not a memory question')
        monkeypatch.setattr(session.memory_flow, 'on_input', unexpected_lookup)
        try:
            await session.wake('synthetic-mode-wake')
            before = ledger_snapshot(manager)
            turn = await final_fast_input(session, text)
            await session.response()  # Even a late queued request stays retired.
            assert turn.local_control and turn.input_ready.is_set() and turn.consent_ready.is_set()
            assert session.selected_mode == 'expert' and mode_events(session) == ['expert']
            assert not session.input_open and session.input_mode == 'idle'
            assert session.state == 'ready' and session.ready and session.attached
            assert not responses(provider) and not session.experts.jobs
            assert ledger_snapshot(manager) == before
            assert manager.board_speech_ledger.status()['operations'] == {}
            assert any(e['type'] == 'conversation.item.delete' and e['item_id'] == turn.input_id
                       for e in provider.sockets[0].sent)
            assert not any(e['type'] == 'error' for e in session.events)
            assert session.admission_status()['mode'] == 'expert'
            assert session.admission_status()['input_allowed']
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_revoked_expert_admission_keeps_fast_and_does_not_claim_switch(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        try:
            await session.wake('synthetic-denied-mode')
            path = manager.public_expert_budget.policy_path
            policy = json.loads(path.read_text())
            path.write_text(json.dumps({**policy, 'enabled': False}))
            before = ledger_snapshot(manager)
            turn = await final_fast_input(session, 'Включи экспертный режим.')
            assert turn.local_control and session.selected_mode == 'fast'
            assert mode_events(session) == [] and not session.input_open
            denied = [e['data'] for e in session.events if e['type'] == 'admission_denied']
            assert denied[-1]['requested_mode'] == 'expert'
            assert denied[-1]['automatic_retry'] is False
            assert not responses(provider) and not session.experts.jobs
            assert ledger_snapshot(manager) == before
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('boundary', ['stop', 'mute', 'new_turn', 'same_mode_selection'])
def test_interruption_during_mode_preview_cannot_apply_a_stale_command(
        tmp_path, settings, monkeypatch, boundary):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        entered, release = asyncio.Event(), threading.Event()
        loop = asyncio.get_running_loop()
        preview = session.expert_input_availability
        def delayed_preview():
            loop.call_soon_threadsafe(entered.set)
            assert release.wait(3), 'Synthetic mode admission was not released'
            return preview()
        monkeypatch.setattr(session, 'expert_input_availability', delayed_preview)
        pending = None
        try:
            await session.wake('synthetic-racing-mode')
            pending = asyncio.create_task(final_fast_input(session, 'Включи экспертный режим.'))
            await asyncio.wait_for(entered.wait(), 1)
            if boundary == 'stop':
                await session.stop()
            elif boundary == 'mute':
                await session.mute(True)
            elif boundary == 'same_mode_selection':
                await session.select_mode('fast')
            else:
                await session.new_turn('synthetic-new-question')
            release.set()
            await asyncio.wait_for(pending, 2)
            assert session.selected_mode == 'fast'
            assert mode_events(session) == (['fast'] if boundary == 'same_mode_selection' else [])
            assert not session.input_open and not responses(provider) and not session.experts.jobs
            assert not any(e['type'] == 'error' for e in session.events)
        finally:
            release.set()
            if pending:
                await asyncio.gather(pending, return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())


class SyntheticRecognition:
    def __init__(self, text):
        self.text, self.calls = text, 0

    async def live(self, chunks, **options):
        self.calls += 1
        async for _ in chunks:
            pass
        yield {'type': 'stt_final', 'data': {
            'text': self.text, 'stable': True, 'item_id': 'synthetic-stt-'+str(self.calls),
            'audio_seconds': .1, 'usage_reported': True, 'usage': {'duration': .1}}}


@pytest.mark.parametrize('text', [
    'София, можешь перейти в обычный режим, пожалуйста?', 'Стоп.',
])
def test_expert_stt_mode_command_returns_to_fast_before_start_local(tmp_path, settings, text):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        recognition = SyntheticRecognition(text)
        manager.recognition = recognition
        async def never_start(*_):
            raise AssertionError('A mode command must not become a CLI task')
        session.experts.start_local = never_start
        try:
            await session.select_mode('expert')
            await session.wake('synthetic-expert-return')
            assert await session.append_pcm(bytes(4800))
            await session.finish_input()
            await session._stt_task
            assert recognition.calls == 1
            assert session.current.local_control and session.selected_mode == 'fast'
            assert mode_events(session) == ['expert', 'fast']
            assert not responses(provider) and not session.experts.jobs
            assert not session.input_open and session._stt_queue is None
            assert not any(e['type'] == 'error' for e in session.events)
            assert not any(e['type'] == 'conversation.item.delete' for e in provider.sockets[0].sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_explicit_mode_persists_without_automatic_stt_and_next_wake_uses_expert(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        recognition = SyntheticRecognition('Сравни два синтетических решения.')
        manager.recognition = recognition
        accepted = []
        async def start_local(text, profile, turn):
            assert session.expert_input_authorized(turn)
            accepted.append((text, profile))
        session.experts.start_local = start_local
        try:
            await session.wake('synthetic-select-expert')
            await final_fast_input(session, 'Включи эксперта.')
            for index in range(2):
                before = ledger_snapshot(manager)
                await session.open_followup_after_guard()
                assert session.selected_mode == 'expert' and not session.input_open
                assert recognition.calls == index and ledger_snapshot(manager) == before
                await session.wake('synthetic-expert-question-'+str(index))
                assert session.input_open and session.input_mode == 'expert'
                await session.append_pcm(bytes(4800))
                await session.finish_input()
                await session._stt_task
                assert recognition.calls == index+1 and len(accepted) == index+1
            assert accepted == [(recognition.text, 'ARGON_DEEP')] * 2
            assert not responses(provider)
            await session.stop()
            assert session.selected_mode == 'fast' and mode_events(session)[-1] == 'fast'
            await session.wake('synthetic-after-stop')
            assert session.input_mode != 'expert' and recognition.calls == 2
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_fast_mode_keeps_existing_followup_and_ordinary_question_response(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        try:
            await session.wake('synthetic-ordinary-question')
            turn = await final_fast_input(session, 'Что такое экспертный режим?')
            assert not turn.local_control and session.selected_mode == 'fast'
            assert len(responses(provider)) == 1 and not session.experts.jobs
            await session.stop()
            before = ledger_snapshot(manager)
            await session.open_followup_after_guard()
            assert session.selected_mode == 'fast' and session.input_open
            assert session.input_mode == 'followup' and ledger_snapshot(manager) == before
            assert manager.board_speech_ledger.status()['operations'] == {}
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_conflicting_late_asr_cannot_replace_a_committed_question_with_a_mode_command(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        try:
            await session.wake('synthetic-conflicting-asr')
            turn = await final_fast_input(session, 'Объясни закон Архимеда.')
            before = ledger_snapshot(manager)
            epoch = session._input_gate_epoch
            await session.handle({'type': 'conversation.item.input_audio_transcription.completed',
                                  'item_id': turn.input_id, 'transcript': 'Включи экспертный режим.'})
            assert turn.query == 'Объясни закон Архимеда.' and not turn.local_control
            assert session.selected_mode == 'fast' and session._input_gate_epoch == epoch
            assert mode_events(session) == [] and len(responses(provider)) == 1
            assert ledger_snapshot(manager) == before
            assert not any(e['type'] == 'stopped' for e in session.events)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('mode', ['fast', 'expert'])
@pytest.mark.parametrize('new_question', [False, True])
def test_real_expert_playback_preserves_explicit_mode_and_binds_followup_to_its_turn(
        tmp_path, settings, monkeypatch, mode, new_question):
    from gobot import expert_jobs, expert_stream
    from gobot.expert_stream import AnswerDelta
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        recognition = SyntheticRecognition('Сравни два публичных синтетических варианта.')
        manager.recognition = recognition
        calls = []
        async def source(settings, req, packet, *, expert_profile):
            calls.append(req.turn_id)
            yield AnswerDelta('Синтетический ответ эксперта.', item_id='answer',
                              phase='final_answer', job_id=req.turn_id, verified=True)
        monkeypatch.setattr(expert_jobs, 'bridge_stream', source)
        monkeypatch.setattr(expert_stream, 'load_expert_service_cue', lambda: {'status': 'missing'})
        session.experts.admission = lambda profile: {'available': True}
        try:
            await session.wake('synthetic-real-expert', mode=mode)
            if mode == 'fast':
                turn = await session.new_turn(query='София, спроси у эксперта, сравни два варианта.')
                job = await session.experts.start_local(turn.query, 'ARGON_DEEP', turn)
            else:
                await session.append_pcm(bytes(4800))
                await session.finish_input()
                await session._stt_task
                job = next(iter(session.experts.jobs.values()))
            await job.worker
            assert job.state == 'completed' and job.narration_complete
            assert not job.playback_complete and len(calls) == 1
            assert session.offer.owner_test_binding is None and session.owner_test_binding == 'board'
            assert manager.public_expert_budget.status()['sessions_reserved'] == 1
            with original.owner_testing.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
            if new_question:
                await session.new_turn('newer-question', query='Объясни другую синтетическую тему.')
            speech_before = manager.board_speech_ledger.status()['operations']
            await session.playback_started(job.response_id)
            await session.playback_finished(job.response_id)
            await asyncio.wait_for(asyncio.shield(session._guard_task), 3)
            assert job.playback_complete and session.selected_mode == mode
            assert session.input_open == (mode == 'fast' and not new_question)
            assert recognition.calls == (1 if mode == 'expert' else 0)
            assert manager.board_speech_ledger.status()['operations'] == speech_before
            assert len(calls) == 1 and not responses(provider)
            assert not session._expert_followup_jobs
            if mode == 'expert' and not new_question:
                await session.wake('next-manual-expert-question')
                assert session.input_open and session.input_mode == 'expert'
                await asyncio.sleep(0)
                assert recognition.calls == 2 and len(calls) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_permanent_expert_rejects_an_explicit_foreign_binding_without_any_attempt(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        session.experts.admission = lambda profile: {'available': True}
        try:
            await session.wake('synthetic-foreign-binding')
            turn = await session.new_turn(query='София, спроси у эксперта, сравни два варианта.')
            # Defense in depth: even if a forged value reached this already
            # bound session, it cannot become public-device expense authority.
            session.offer = session.offer.model_copy(update={'owner_test_binding': 'other-phone'})
            before = ledger_snapshot(manager)
            with pytest.raises(PermissionError):
                await session.experts.start_local(turn.query, 'ARGON_DEEP', turn)
            assert ledger_snapshot(manager) == before
            assert manager.public_expert_budget.status()['sessions_reserved'] == 0
            assert not any(job.worker for job in session.experts.jobs.values())
            assert not responses(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
