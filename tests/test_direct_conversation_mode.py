"""Real Direct protocol and scoped expert jobs; synthetic providers/PCM only."""
import asyncio
import base64
import json

import pytest

from gobot.realtime import TOOLS
from gobot.direct_mode_control import direct_mode_intent
from gobot.expert_stream import AnswerDelta
from test_owner_terminal_direct import setup_terminal
from test_realtime_ws import cleanup, complete_input


async def question(session, text, ident='input'):
    await session.wake('wake-'+ident)
    await session.handle({'type': 'input_audio_buffer.committed', 'item_id': ident})
    await complete_input(session, ident, text)
    async with asyncio.timeout(2):
        while not session.live_response:
            await asyncio.sleep(.001)
    return session.current, session.live_response


async def call(session, response, args, ident='mode-call'):
    before = set(session.tasks)
    await session.handle({'type': 'response.function_call_arguments.done',
        'response_id': response, 'call_id': ident, 'name': 'conversation_mode',
        'arguments': json.dumps(args, ensure_ascii=False)})
    created = [task for task in session.tasks-before if task.get_coro().__name__ == 'tool']
    if created:
        await asyncio.wait_for(asyncio.gather(*created), 3)


def outputs(provider):
    return [json.loads(e['item']['output']) for socket in provider.sockets for e in socket.sent
            if e.get('item', {}).get('type') == 'function_call_output']


def requests(provider):
    return [e for socket in provider.sockets for e in socket.sent if e['type'] == 'response.create']


def fake_expert(monkeypatch, session, observed, gate=None):
    from gobot import expert_jobs, expert_stream
    async def source(settings, req, packet, *, expert_profile):
        observed.append((req.text, packet, expert_profile))
        if gate is not None:
            await gate.wait()
        yield AnswerDelta('Синтетический экспертный ответ.', item_id='answer',
            phase='final_answer', job_id=req.turn_id, verified=True)
    monkeypatch.setattr(expert_jobs, 'bridge_stream', source)
    monkeypatch.setattr(expert_stream, 'load_expert_service_cue', lambda: {'status': 'missing'})
    session.experts.admission = lambda profile: {'available': True}


def test_tool_is_direct_only_and_instructions_use_user_meaning_not_phrase_list(tmp_path, settings):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        try:
            assert 'conversation_mode' not in {tool['name'] for tool in TOOLS}
            tool = next(t for t in s.config['tools'] if t['name'] == 'conversation_mode')
            assert not tool['parameters']['additionalProperties']
            assert 'task' not in tool['parameters']['properties'] and 'profile' not in tool['parameters']['properties']
            assert 'фиксированную фразу' in s.config['instructions']
            assert 'цитаты' in s.config['instructions'] and 'настоящего согласия' in s.config['instructions']
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_semantic_selection_has_one_bounded_native_ack_and_no_expert_or_stt(tmp_path, settings):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        text = 'Дальше хочу обсуждать всё с более вдумчивым собеседником.'
        try:
            assert direct_mode_intent(text) is None
            turn, response = await question(s, text)
            await call(s, response, {'mode': 'expert', 'task_source': 'none'})
            assert s.selected_mode == 'expert' and not turn.cancelled
            result = outputs(provider)[0]
            assert result['executed'] and result['mode_selected'] and result['mode_changed']
            assert not result['accepted'] and result['selected_expert']['provider'] == 'antigravity'
            assert len(requests(provider)) == 2
            ack = requests(provider)[-1]['response']
            assert ack['tool_choice'] == 'none' and ack['max_output_tokens'] == 384
            assert not s.experts.jobs and manager.board_speech_ledger.status()['operations'] == {}
            await asyncio.gather(*(s.response() for _ in range(4)))
            assert len(requests(provider)) == 2 and not s.pending_response
            await s.handle({'type': 'response.done', 'response': {'id': response, 'status': 'cancelled'}})
            assert not turn.cancelled
            await call(s, response, {'mode': 'fast', 'task_source': 'none'}, 'replayed-old-response')
            assert s.selected_mode == 'expert' and len(outputs(provider)) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_concurrent_ack_requests_claim_the_live_pending_ack_under_response_lock(tmp_path, settings):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        pending, extras = None, []
        try:
            _, response = await question(s, 'Теперь хочу более вдумчивого собеседника.')
            await s.response_lock.acquire()
            pending = asyncio.create_task(call(s, response, {'mode': 'expert', 'task_source': 'none'}))
            async with asyncio.timeout(2):
                while not outputs(provider): await asyncio.sleep(.001)
            assert s.current.mode_action_ack is not None
            extras = [asyncio.create_task(s.response()) for _ in range(3)]
            await asyncio.sleep(0)  # All contenders now wait behind the same writer.
            s.response_lock.release()
            await asyncio.gather(pending, *extras)
            assert len(requests(provider)) == 2 and not s.pending_response
            assert s.current.mode_action_ack is None
        finally:
            if s.response_lock.locked(): s.response_lock.release()
            if pending: await asyncio.gather(pending, *extras, return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('scope', ['conversation', 'one_question'])
def test_current_question_handoff_preserves_turn_and_ignores_late_cancelled_response(
        tmp_path, settings, monkeypatch, scope):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        observed, gate = [], asyncio.Event()
        fake_expert(monkeypatch, s, observed, gate)
        text = 'Нужен обстоятельный разбор двух синтетических вариантов, поручим это специалисту.'
        try:
            turn, response = await question(s, text)
            await s.handle({'type': 'response.output_audio.delta', 'response_id': response,
                            'delta': base64.b64encode(bytes(4800)).decode()})
            await s.playback_started(response)
            await call(s, response, {'mode': 'expert', 'task_source': 'current', 'scope': scope})
            job = next(iter(s.experts.jobs.values()))
            assert job.task == text and job.turn_id == turn.id and not turn.cancelled
            assert outputs(provider)[0]['accepted'] and outputs(provider)[0]['job_id'] == job.id
            assert s.selected_mode == ('expert' if scope == 'conversation' else 'fast')
            assert len(requests(provider)) == 1
            assert any(e['type'] == 'audio_cancel' and e['data'].get('response_id') == response for e in s.events)
            await s.handle({'type': 'response.done', 'response': {'id': response,
                'status': 'cancelled', 'usage': {'total_tokens': 10, 'input_tokens': 5, 'output_tokens': 5}}})
            assert not turn.cancelled and job.state in {'queued', 'running'}
            gate.set()
            await job.worker
            assert job.state == 'completed' and len(observed) == 1 and observed[0][0] == text
            assert manager.public_expert_budget.status()['sessions_reserved'] == 1
            assert 'stt' not in manager.board_speech_ledger.status()['operations']
            await s.playback_started(job.response_id)
            await s.playback_finished(job.response_id)
            await asyncio.wait_for(asyncio.shield(s._guard_task), 3)
            assert s.input_open == (scope == 'one_question')
            assert not s.mode_actions.authority
        finally:
            gate.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_previous_handoff_uses_original_question_and_new_decision_turn(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        observed = []
        fake_expert(monkeypatch, s, observed)
        try:
            previous, _ = await question(s, 'Сравни синтетические варианты А и Б.', 'first')
            await s.stop()
            decision, response = await question(s, 'Пусть специалист перепроверит этот вопрос.', 'decision')
            await call(s, response, {'mode': 'expert', 'task_source': 'previous', 'scope': 'one_question'})
            job = next(iter(s.experts.jobs.values()))
            await job.worker
            assert job.task == previous.query and job.task_source_turn_id == previous.id
            assert job.mode_action_instruction == decision.query and job.turn_id == decision.id
            assert job.already_explained == '' and len(observed) == 1
            await s.playback_started(job.response_id)
            await s.playback_finished(job.response_id)
            await asyncio.wait_for(asyncio.shield(s._guard_task), 3)
            assert s.selected_mode == 'fast' and s.input_open
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('boundary', ['stop', 'mute', 'new_question', 'same_mode', 'rotation'])
def test_event_time_claim_cannot_execute_after_a_newer_boundary(tmp_path, settings, boundary):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        entered, release = asyncio.Event(), asyncio.Event()
        actual = s.tool
        async def held(*args):
            entered.set()
            await release.wait()
            return await actual(*args)
        s.tool = held
        pending = None
        try:
            turn, response = await question(s, 'Мне нужен более вдумчивый собеседник.')
            # capture() runs in the reader before the held tool coroutine starts.
            await s.handle({'type': 'response.function_call_arguments.done',
                'response_id': response, 'call_id': 'held-mode', 'name': 'conversation_mode',
                'arguments': json.dumps({'mode': 'expert', 'task_source': 'none'})})
            await asyncio.wait_for(entered.wait(), 1)
            pending = next(task for task in s.tasks if task.get_coro().__name__ == 'held')
            if boundary == 'stop': await s.stop()
            elif boundary == 'mute': await s.mute(True)
            elif boundary == 'new_question': await s.new_turn('new', query='Другой синтетический вопрос.')
            elif boundary == 'same_mode':
                # No active output is needed to invalidate even a same-value selection.
                s.generating = s.response_requested = s.speaking = False
                await s.select_mode('fast')
            else: await s.rotate(force=True)
            release.set()
            await pending
            assert s.selected_mode == 'fast' and not outputs(provider) and not s.experts.jobs
        finally:
            release.set()
            if pending: await asyncio.gather(pending, return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('args', [
    {'mode': 'expert', 'task_source': 'none', 'task': 'Invented task'},
    {'mode': 'expert', 'task_source': 'none', 'profile': 'SOL_HIGH'},
    {'mode': 'expert', 'task_source': 'none', 'confirmed': True},
    {'mode': 'expert', 'task_source': 'none', 'requested_provider': 'other'},
    {'mode': 'fast', 'task_source': 'current'},
    {'mode': 'expert', 'task_source': 'none', 'scope': 'one_question'},
])
def test_tool_arguments_cannot_supply_task_profile_or_approval(tmp_path, settings, args):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        try:
            _, response = await question(s, 'Обсудим настройку нашего разговора.')
            await call(s, response, args)
            assert s.selected_mode == 'fast' and not s.experts.jobs
            assert outputs(provider)[0]['error'] == 'invalid_conversation_mode_arguments'
            assert manager.public_expert_budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_unknown_function_event_and_direct_method_call_have_no_authority(tmp_path, settings):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        try:
            turn, _ = await question(s, 'Обсудим наш следующий вопрос.')
            args = {'mode': 'expert', 'task_source': 'current'}
            await call(s, 'unknown-response', args)
            await s.tool('fabricated-call', 'conversation_mode', json.dumps(args), turn)
            assert s.selected_mode == 'fast' and not s.experts.jobs and not outputs(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('missing', ['no_previous', 'ambiguous_confirmation', 'wrong_scope'])
def test_previous_source_must_be_a_bound_question_not_a_guessed_older_topic(tmp_path, settings, missing):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        try:
            if missing != 'no_previous':
                turn, _ = await question(s, 'Объясни первую синтетическую тему.', 'prior')
                await s.stop()
                if missing == 'ambiguous_confirmation':
                    await question(s, 'Да.', 'confirmation')
                    await s.stop()
                else:
                    turn.req.profile_epoch = 'foreign-profile-epoch'
            _, response = await question(s, 'Специалист пусть разберёт предыдущий вопрос.', 'decision')
            await call(s, response, {'mode': 'expert', 'task_source': 'previous'})
            assert not s.experts.jobs and outputs(provider)[0]['error'] == 'previous_question_unavailable'
            assert s.selected_mode == 'fast'
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_completed_current_handoff_remains_the_previous_question_after_new_activation(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        observed = []
        fake_expert(monkeypatch, s, observed)
        async def consume():
            while True: await s.next_event()
        listener = asyncio.create_task(consume())
        try:
            await question(s, 'Заведомо более старая синтетическая тема.', 'older')
            await s.stop()
            original_turn, response = await question(s, 'Переходим к вдумчивому разбору: сравни реальные варианты А и Б.', 'question')
            await call(s, response, {'mode': 'expert', 'task_source': 'current'}, 'first-action')
            first = next(iter(s.experts.jobs.values()))
            await first.worker
            await s.playback_started(first.response_id)
            await s.playback_finished(first.response_id)
            await asyncio.wait_for(asyncio.shield(s._guard_task), 3)
            await s.stop()  # The same barrier used before an interrupted/new wake.
            decision, response = await question(s, 'Попроси его ещё раз проверить именно этот вопрос.', 'repeat')
            await call(s, response, {'mode': 'expert', 'task_source': 'previous',
                                    'scope': 'one_question'}, 'second-action')
            second = next(job for job in s.experts.jobs.values() if job.id != first.id)
            await second.worker
            assert second.task == first.task == original_turn.query
            assert second.task_source_turn_id == original_turn.id and second.turn_id == decision.id
            assert len(observed) == 2 and observed[1][0] == original_turn.query
        finally:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('requested,accepted', [('codex', False), ('configured', True)])
def test_provider_constraint_never_substitutes_the_registered_expert(tmp_path, settings, monkeypatch, requested, accepted):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        observed = []
        fake_expert(monkeypatch, s, observed)
        try:
            text = ('Хочу привлечь именно Codex для этого вопроса.' if requested == 'codex' else
                    'Привлечём специалиста, чтобы сравнить Codex и Gemini как продукты.')
            _, response = await question(s, text)
            await call(s, response, {'mode': 'expert', 'task_source': 'current',
                                    'requested_provider': requested})
            result = outputs(provider)[0]
            assert result['accepted'] == accepted
            if accepted:
                job = next(iter(s.experts.jobs.values()))
                await job.worker
                assert job.profile['provider'] == 'antigravity'
                assert result['selected_expert']['profile'] == 'ARGON_DEEP'
            else:
                assert result['error'] == 'explicit_expert_profile_mismatch'
                assert not s.experts.jobs and s.selected_mode == 'fast' and not observed
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_job_admission_failure_reports_successful_selection_separately(tmp_path, settings):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        s.experts.admission = lambda profile: {'available': False, 'reason': 'isolation_not_verified'}
        try:
            _, response = await question(s, 'Переходим к обстоятельному разбору двух способов.')
            await call(s, response, {'mode': 'expert', 'task_source': 'current'})
            result = outputs(provider)[0]
            assert result['executed'] and result['mode_selected'] and result['mode_changed']
            assert result['selected_mode'] == 'expert' and not result['accepted']
            assert result['error'] == 'isolation_not_verified'
            assert result['selected_expert']['provider'] == 'antigravity'
            assert not any(job.worker for job in s.experts.jobs.values())
            assert manager.public_expert_budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('malformed', [False, True])
def test_denied_or_unresolved_handoff_cannot_fall_back_to_an_unrelated_older_question(tmp_path, settings, monkeypatch, malformed):
    async def run():
        original, board, manager, s, provider = await setup_terminal(tmp_path, settings)
        observed = []
        fake_expert(monkeypatch, s, observed)
        async def consume():
            while True: await s.next_event()
        listener = asyncio.create_task(consume())
        try:
            await question(s, 'Какие размеры у синтетического стола?', 'old-topic')
            await s.stop()
            source, response = await question(s, 'Пусть Codex сравнит виды топлива А и Б.', 'denied-topic')
            args = {'mode': 'expert', 'task_source': 'current', 'requested_provider': 'codex'}
            if malformed: args['task'] = 'Model-supplied text is forbidden'
            await call(s, response, args, 'denied-action')
            assert not outputs(provider)[0]['accepted']
            await s.stop()
            _, response = await question(s, 'Тогда пусть настроенный эксперт проверит тот же вопрос.', 'new-decision')
            await call(s, response, {'mode': 'expert', 'task_source': 'previous',
                                    'scope': 'one_question'}, 'retry-from-new-turn')
            result = outputs(provider)[-1]
            if malformed:
                assert not result['accepted'] and result['error'] == 'previous_question_unavailable'
                assert not s.experts.jobs and not observed
            else:
                assert result['accepted']
                job = next(iter(s.experts.jobs.values()))
                await job.worker
                assert job.task == source.query and job.task_source_turn_id == source.id
                assert 'топлива' in observed[0][0] and 'стола' not in observed[0][0]
        finally:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())
