"""Semantic expert admission with real temporary grants and mocked providers.

These are server/protocol tests, not claims about a model's natural-language
accuracy or physical speech. No CLI, transcription or paid speech call is made.
"""
import asyncio
import copy
import threading
from dataclasses import replace

import pytest

from gobot import expert_jobs, expert_stream
from gobot.context_manager import serialize_context, tokens
from gobot.direct_conversation_mode import ModeActionAuthority
from gobot.expert_jobs import require_requested_expert_profile
from gobot.expert_profiles import resolve_profile
from gobot.expert_stream import AnswerDelta, conversation_binding
from test_direct_admission_status import ledger_snapshot
from test_owner_terminal_direct import setup_terminal
from test_realtime_ws import cleanup


@pytest.fixture
def expert_calls(monkeypatch):
    calls = []

    async def stream(settings, req, packet, *, expert_profile):
        calls.append({'request': req, 'packet': copy.deepcopy(packet), 'profile': expert_profile})
        yield AnswerDelta('Синтетический результат: 42.', item_id='answer',
                          phase='final_answer', job_id=req.turn_id, verified=True)

    monkeypatch.setattr(expert_jobs, 'bridge_stream', stream)
    load_cue = expert_stream.load_expert_service_cue
    monkeypatch.setattr(expert_stream, 'load_expert_service_cue',
        lambda root=None: load_cue(root) if root is not None else {'status': 'missing'})
    return calls


async def terminal(tmp_path, settings):
    original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
    session.experts.admission = lambda profile: {'available': True}
    await session.wake('synthetic-mode-action')
    return original, board, manager, session, provider


def bind_action(session, *, source=None, requested_provider='configured'):
    """Mint the same server-only proof after the controller chose its source."""
    turn = session.current
    source = source or turn
    profile = session.selected_expert()
    authority = ModeActionAuthority(source.query, profile['profile'], source.id,
        turn.query, turn.id, turn.input_revision, session._input_gate_epoch,
        session.transport_epoch, session._mode_selection_revision,
        conversation_binding(session), session.selected_mode,
        tuple(profile[key] for key in ('profile', 'provider', 'model', 'effort')),
        requested_provider=requested_provider)
    session.mode_actions.authority = authority
    return authority


async def start_action(session, authority):
    return await session.experts.start_mode_action(authority.task, authority.profile,
        session.current, authority=authority, source_turn_id=authority.source_turn_id)


@pytest.mark.parametrize('source_kind', ['current', 'previous'])
@pytest.mark.parametrize('selected_mode', ['fast', 'expert'])
def test_exact_task_and_current_instruction_reach_real_job_and_current_playback(
        tmp_path, settings, monkeypatch, expert_calls, source_kind, selected_mode):
    async def run():
        original, board, manager, session, provider = await terminal(tmp_path, settings)
        try:
            if source_kind == 'previous':
                source = await session.new_turn(query='Сравни синтетические варианты при значениях 17 и 25.')
                source.answer = 'UNHEARD_SYNTHETIC_FRAGMENT_MUST_NOT_BE_ALREADY_EXPLAINED'
                turn = await session.new_turn(query='Хочу, чтобы эксперт перепроверил этот ответ и разобрал возможную ошибку.')
            else:
                turn = await session.new_turn(query='Давай тщательно проверим у выбранного эксперта, сколько будет 17 плюс 25.')
                source = turn
                source.answer = 'UNHEARD_SYNTHETIC_FRAGMENT_MUST_NOT_BE_ALREADY_EXPLAINED'
            await session.interrupt(_preserve_turn=True)
            await session.select_mode(selected_mode)
            authority = bind_action(session, source=source, requested_provider='antigravity')
            job = await start_action(session, authority)
            session.mode_actions.authority = None  # Consumed proof cannot kill the accepted worker.
            await job.worker
            assert job.state == 'completed' and job.narration_complete
            assert len(expert_calls) == 1 and job.confirmed
            assert job.task == source.query and job.task_source_turn_id == source.id
            assert job.turn_id == turn.id and job.confirmation_turn_id == turn.id
            assert job.mode_action_instruction == turn.query and job.already_explained == ''
            assert job.operation_id == 'local:'+job.id and job.call_id is None
            assert job.mode_action_authority is None
            assert job.profile['model'] == 'gemini-4-argon-medium' and job.profile['effort'] == 'medium'
            assert job.profile['provider'] == authority.requested_provider
            packet = expert_calls[0]['packet']
            action = packet['dialogue_state']['mode_action_request']
            assert action == {'current_user_instruction': turn.query,
                'instruction_turn_id': turn.id, 'source_question_turn_id': source.id,
                'origin': 'current_user_request', 'trusted_as_instructions': False}
            assert packet['dialogue_state']['already_explained_by_gobot'] == ''
            assert 'server has already accepted the requested expert handoff' in packet['dialogue_state']['expert_deliverable']
            assert 'UNHEARD_SYNTHETIC_FRAGMENT' not in serialize_context(job.task, packet)
            assert tokens(serialize_context(job.task, packet)) <= job.context_token_limit
            assert packet['_context_meta']['packet_tokens'] == tokens(serialize_context(job.task, packet))
            assert expert_calls[0]['request'].device_id == session.access.effective_scope
            assert not expert_calls[0]['request'].remember and not job.remember
            assert session.offer.owner_test_binding is None and session.owner_test_binding == 'board'
            assert manager.public_expert_budget.status()['sessions_reserved'] == 1
            with original.owner_testing.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
            assert not job.playback_complete
            await session.playback_started(job.response_id)
            await session.playback_finished(job.response_id)
            await asyncio.wait_for(asyncio.shield(session._guard_task), 3)
            assert job.playback_complete and session.selected_mode == selected_mode
            assert session.input_open == (selected_mode == 'fast')
            assert len(expert_calls) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('bad_proof', ['absent', 'copy', 'wrong_profile_snapshot'])
def test_model_arguments_or_copied_proof_do_not_create_server_authority(
        tmp_path, settings, expert_calls, bad_proof):
    async def run():
        original, board, manager, session, provider = await terminal(tmp_path, settings)
        try:
            await session.new_turn(query='Мне нужен более обстоятельный экспертный разбор этого расчёта.')
            original_proof = bind_action(session)
            proof = None if bad_proof == 'absent' else replace(original_proof)
            if bad_proof == 'wrong_profile_snapshot':
                proof = replace(original_proof, profile_snapshot=('ARGON_DEEP', 'codex', 'gpt-6-astra', 'high'))
                session.mode_actions.authority = proof
            before = ledger_snapshot(manager)
            with pytest.raises(PermissionError):
                await session.experts.start_mode_action(original_proof.task, original_proof.profile,
                    session.current, authority=proof)
            assert not session.experts.jobs and not expert_calls
            assert ledger_snapshot(manager) == before
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('changed', ['task', 'profile', 'source_turn', 'instruction', 'source_scope', 'source_epoch'])
def test_valid_proof_cannot_authorize_another_task_profile_or_source(
        tmp_path, settings, expert_calls, changed):
    async def run():
        original, board, manager, session, provider = await terminal(tmp_path, settings)
        try:
            source = await session.new_turn(query='Сравни два синтетических варианта.')
            await session.new_turn(query='Хочу обсудить тот же вопрос с выбранным экспертом подробнее.')
            proof = bind_action(session, source=source)
            task, profile, source_id = proof.task, proof.profile, proof.source_turn_id
            if changed == 'task': task = 'Другой вопрос, сочинённый моделью.'
            elif changed == 'profile': profile = 'SOL_HIGH'
            elif changed == 'source_turn': source_id = session.current.id
            elif changed == 'instruction': session.current.query = 'Теперь другая задача.'
            elif changed == 'source_scope': source.req = source.req.model_copy(update={'device_id': 'other-person'})
            elif changed == 'source_epoch': source.req = source.req.model_copy(update={'profile_epoch': 'other-epoch'})
            before = ledger_snapshot(manager)
            with pytest.raises((PermissionError, ValueError)):
                await session.experts.start_mode_action(task, profile, session.current,
                    authority=proof, source_turn_id=source_id)
            assert not session.experts.jobs and not expert_calls
            assert ledger_snapshot(manager) == before
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('invalidation', ['input_epoch', 'mode_revision', 'transport_epoch',
    'input_revision', 'muted', 'cancelled', 'source_changed', 'proof_consumed'])
def test_stale_action_during_context_pack_never_reserves_or_executes(
        tmp_path, settings, monkeypatch, expert_calls, invalidation):
    async def run():
        original, board, manager, session, provider = await terminal(tmp_path, settings)
        entered, proceed = asyncio.Event(), asyncio.Event()
        try:
            source = await session.new_turn(query='Сравни два синтетических варианта.')
            await session.new_turn(query='Хотел бы получить экспертную перепроверку этого вопроса.')
            proof = bind_action(session, source=source)
            prepare = session.experts.prepare_packet

            async def held_packet(job):
                packet = await prepare(job)
                entered.set()
                await proceed.wait()
                return packet

            monkeypatch.setattr(session.experts, 'prepare_packet', held_packet)
            before = ledger_snapshot(manager)
            pending = asyncio.create_task(start_action(session, proof))
            await asyncio.wait_for(entered.wait(), 3)
            if invalidation == 'input_epoch': session._input_gate_epoch += 1
            elif invalidation == 'mode_revision': session._mode_selection_revision += 1
            elif invalidation == 'transport_epoch': session.transport_epoch += 1
            elif invalidation == 'input_revision': session.current.input_revision += 1
            elif invalidation == 'muted': session.muted = True
            elif invalidation == 'cancelled': session.current.cancelled = True
            elif invalidation == 'source_changed': source.query = 'Иной вопрос.'
            elif invalidation == 'proof_consumed': session.mode_actions.authority = None
            proceed.set()
            with pytest.raises(PermissionError, match='expert_context_changed'):
                await pending
            assert ledger_snapshot(manager) == before and not expert_calls
            assert all(job.state == 'cancelled' and job.worker is None for job in session.experts.jobs.values())
        finally:
            proceed.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_invalidation_after_reservation_keeps_accounting_without_launch_or_retry(
        tmp_path, settings, monkeypatch, expert_calls):
    async def run():
        original, board, manager, session, provider = await terminal(tmp_path, settings)
        entered, proceed = threading.Event(), threading.Event()
        try:
            await session.new_turn(query='Давай разберём этот расчёт с экспертом подробно.')
            proof = bind_action(session)
            reserve = session.experts.budget.reserve_session

            def held_reservation(*args, **kwargs):
                result = reserve(*args, **kwargs)
                entered.set()
                assert proceed.wait(3)
                return result

            monkeypatch.setattr(session.experts.budget, 'reserve_session', held_reservation)
            pending = asyncio.create_task(start_action(session, proof))
            assert await asyncio.to_thread(entered.wait, 3)
            session.mode_actions.authority = None
            proceed.set()
            with pytest.raises(PermissionError, match='expert_context_changed'):
                await pending
            assert not expert_calls and session.experts.budget.status()['sessions_reserved'] == 1
            job = session.experts.pending
            assert job.state == 'cancelled' and job.worker is None and not job.confirmed
            with pytest.raises(PermissionError):
                await session.experts.start(job.proposal_id, None)
            assert session.experts.budget.status()['sessions_reserved'] == 1
        finally:
            proceed.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('denial', ['isolation', 'quota_consent', 'foreign_phone_binding', 'context_limit'])
def test_existing_admission_and_native_board_binding_still_apply(
        tmp_path, settings, monkeypatch, expert_calls, denial):
    async def run():
        original, board, manager, session, provider = await terminal(tmp_path, settings)
        try:
            await session.new_turn(query='Хочу обстоятельный экспертный разбор синтетической задачи.')
            proof = bind_action(session)
            if denial == 'isolation': session.experts.admission = lambda profile: {'available': False, 'reason': 'isolation_not_verified'}
            elif denial == 'quota_consent': session.offer = session.offer.model_copy(update={'expert_quota_consent': False})
            elif denial == 'foreign_phone_binding': session.offer = session.offer.model_copy(update={'owner_test_binding': 'other-phone'})
            elif denial == 'context_limit':
                policy = session.experts.budget.policy
                monkeypatch.setattr(session.experts.budget, 'policy', lambda: policy().model_copy(update={'max_context_tokens': 1}))
            before = ledger_snapshot(manager)
            with pytest.raises((PermissionError, ValueError)):
                await start_action(session, proof)
            assert ledger_snapshot(manager) == before and not expert_calls
            assert all(job.state == 'cancelled' and job.worker is None for job in session.experts.jobs.values())
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_one_user_decision_cannot_launch_a_second_job_even_with_new_server_proof(
        tmp_path, settings, expert_calls):
    async def run():
        original, board, manager, session, provider = await terminal(tmp_path, settings)
        try:
            await session.new_turn(query='Пусть эксперт обстоятельно проверит синтетическую задачу.')
            first = await start_action(session, bind_action(session))
            await first.worker
            second_proof = bind_action(session)
            with pytest.raises(PermissionError, match='expert_confirmation_already_used'):
                await start_action(session, second_proof)
            assert len(expert_calls) == 1 and session.experts.budget.status()['sessions_reserved'] == 1
            assert session.experts.pending.state == 'cancelled'
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_model_proposal_still_waits_for_real_yes_and_plays_on_that_decision_turn(
        tmp_path, settings, expert_calls):
    async def run():
        original, board, manager, session, provider = await terminal(tmp_path, settings)
        try:
            source = await session.new_turn(query='Сравни два синтетических варианта.')
            proposal = session.experts.propose(source.query, 'ARGON_DEEP', source)
            assert not proposal['confirmed']
            with pytest.raises(PermissionError):
                await session.experts.start(proposal['proposal_id'], 'synthetic-proposal-without-yes')
            assert not expert_calls and session.experts.budget.status()['sessions_reserved'] == 0
            decision = await session.new_turn(query='Да')
            job = await session.experts.start(proposal['proposal_id'], 'synthetic-real-confirmation')
            await job.worker
            assert job.state == 'completed' and len(expert_calls) == 1
            assert job.task == source.query and job.task_source_turn_id == source.id
            assert job.turn_id == decision.id and job.confirmation_turn_id == decision.id
            await session.playback_started(job.response_id)
            await session.playback_finished(job.response_id)
            await asyncio.wait_for(asyncio.shield(session._guard_task), 3)
            assert job.playback_complete and session.input_open and session.selected_mode == 'fast'
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('utterance', ['Спроси Codex, как устроен этот расчёт.',
    'София, передай этот вопрос кодексу.', 'Давай перейдём на Codex.'])
def test_named_codex_cannot_be_silently_substituted_in_existing_proposals(
        tmp_path, settings, expert_calls, utterance):
    async def run():
        original, board, manager, session, provider = await terminal(tmp_path, settings)
        try:
            turn = await session.new_turn(query=utterance)
            with pytest.raises(ValueError, match='explicit_expert_profile_mismatch'):
                session.experts.propose(turn.query, 'ARGON_DEEP', turn)
            assert not session.experts.jobs and not expert_calls
            assert session.experts.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('utterance', [
    'Подключи эксперта и сравни Codex с Gemini.',
    'Пусть Argon объяснит, как использовать Codex для анализа кода.',
    'Спроси у эксперта, как использовать Codex для анализа кода.',
    'Пусть эксперт оценит, стоит ли использовать Codex вместо Gemini.',
    'Не подключай Codex, пусть выбранный эксперт разберёт этот вопрос.'])
def test_provider_names_inside_the_subject_do_not_change_executor(utterance):
    require_requested_expert_profile(utterance, resolve_profile('ARGON_DEEP'))


@pytest.mark.parametrize('provider,utterance', [
    ('codex', 'Реши этот вопрос через Codex.'),
    ('codex', 'Для этого вопроса мне нужен именно Codex.'),
    ('codex', 'Пожалуйста, выбери старшую модель Codex для этой задачи.')])
def test_semantic_provider_constraint_rejects_mismatch_without_intent_regex(provider, utterance):
    with pytest.raises(ValueError, match='explicit_expert_profile_mismatch'):
        require_requested_expert_profile(utterance, resolve_profile('ARGON_DEEP'), requested_provider=provider)


@pytest.mark.parametrize('provider', ['gemini', 'arbitrary/model', '', None, {}])
def test_provider_constraint_is_a_closed_enum_not_an_arbitrary_model_selector(provider):
    with pytest.raises(ValueError, match='invalid_conversation_mode_arguments'):
        require_requested_expert_profile('Разбери этот вопрос.', resolve_profile('ARGON_DEEP'), requested_provider=provider)


def test_semantic_constraint_cannot_route_to_codex_under_argon_grant(
        tmp_path, settings, expert_calls):
    async def run():
        original, board, manager, session, provider = await terminal(tmp_path, settings)
        try:
            await session.new_turn(query='Реши этот вопрос через Codex.')
            proof = bind_action(session, requested_provider='codex')
            before = ledger_snapshot(manager)
            with pytest.raises(ValueError, match='explicit_expert_profile_mismatch'):
                await start_action(session, proof)
            assert ledger_snapshot(manager) == before and not expert_calls and not session.experts.jobs
            assert session.selected_expert()['profile'] == 'ARGON_DEEP'
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
