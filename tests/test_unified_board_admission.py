"""Finite board admission with real ledgers and synthetic providers only."""
import asyncio
import importlib.util
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from gobot.board_unified import (
    BoardSpeechLedger, UnifiedBoardBudget, UnifiedBoardRealtime, UnifiedPublicExpertBudget,
    authorize_proposal, create_service_cue, digest, epoch_root, prepare_proposal, proposal_summary,
)
from gobot.expert_stream import AnswerDelta, EXPERT_CUE_TEXT, EXPERT_CUE_ID, load_expert_service_cue
from gobot.realtime_ws import DirectRealtimeManager
from gobot.unified_voice_budget import UnifiedVoiceBudget
from test_realtime_native import configured
from test_realtime_ws import Provider, offer, cleanup
from test_unified_voice_budget import SpeechFixture


@pytest.fixture(autouse=True)
def offline_expert_registry(monkeypatch):
    """The existing SOL fixture has explicit model metadata before paid STT."""
    import gobot.expert_profiles as profiles
    original = profiles.resolve_profile
    rows = [{'slug': 'gpt-6.1-sol', 'supported_reasoning_levels': [{'effort': 'high'}]}]
    def resolve(name, *, codex_metadata=None):
        return original(name, codex_metadata=rows if codex_metadata is None else codex_metadata)
    monkeypatch.setattr(profiles, 'resolve_profile', resolve)


def finite(root, *, enabled=True):
    prepared = prepare_proposal(root, 'board')
    if enabled:
        # Synthetic owner authorization in this test's isolated temporary tree.
        authorize_proposal(root, prepared['proposal_sha256'])
    voice = UnifiedBoardBudget(root)
    expert = UnifiedPublicExpertBudget(root/'experts')
    return voice, expert, BoardSpeechLedger(voice, expert)


async def setup(tmp_path, settings, *, enabled=True, recognition=None):
    original, _, _ = configured(tmp_path, settings)
    root = tmp_path/'unified-board'
    finite(root, enabled=enabled)
    board = UnifiedBoardRealtime(original, root)
    authorization = UnifiedVoiceBudget(max_expert_audio_seconds=180, expert_operation_timeout_seconds=240)
    manager = DirectRealtimeManager(board, provider=Provider(), speech=SpeechFixture(), recognition=recognition,
        narrator_authorizer=authorization.narrator, transcription_authorizer=authorization.transcription)
    session = await manager.accept(offer(expert_quota_consent=True))
    return original, board, manager, session, authorization


@pytest.mark.parametrize('expert_profile', ['SOL_HIGH', 'ARGON_DEEP'])
def test_proposal_is_disabled_has_no_running_expiry_and_cannot_renew(tmp_path, expert_profile):
    root = epoch_root(tmp_path, 'acceptance-fixture')
    first = prepare_proposal(root, 'board', expert_profile=expert_profile)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*.json')}
    assert first['summary'] == proposal_summary(expert_profile)
    assert first['summary']['speech']['cue_text'] == EXPERT_CUE_TEXT
    assert json.loads(before[Path('experts/policy.json')])['allowed_profiles'] == [expert_profile]
    assert all(json.loads(before[p])['expires_at'] == 0 for p in before if p.name == 'policy.json' or p.name == 'speech-policy.json')
    assert prepare_proposal(root, 'board', expert_profile=expert_profile) == first
    other_profile = 'SOL_HIGH' if expert_profile == 'ARGON_DEEP' else 'ARGON_DEEP'
    with pytest.raises(PermissionError, match='proposal_expert_profile_mismatch_new_epoch_required'):
        prepare_proposal(root, 'board', expert_profile=other_profile)
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob('*.json')}
    with pytest.raises(PermissionError, match='device_mismatch'):
        prepare_proposal(root, 'phone', expert_profile=expert_profile)
    with pytest.raises(PermissionError, match='exact_disabled_owner_proposal'):
        authorize_proposal(root, '0'*64)
    approved_at = time.time()
    result = authorize_proposal(root, first['proposal_sha256'])
    assert approved_at+7200 <= result['expires_at'] <= time.time()+7200
    assert result['paid_requests_made'] == 0 and result['mounted'] is False
    assert prepare_proposal(root, 'board', expert_profile=expert_profile) == first
    with pytest.raises((PermissionError, FileExistsError)):
        authorize_proposal(root, first['proposal_sha256'])
    assert not list(root.rglob('usage.sqlite'))


def test_argon_proposal_has_its_own_approval_and_preserves_the_sol_proposal(tmp_path):
    old = epoch_root(tmp_path, 'previous-sol')
    previous = prepare_proposal(old, 'board')
    before = {p.relative_to(old): p.read_bytes() for p in old.rglob('*.json')}
    root = epoch_root(tmp_path, 'new-argon')
    prepared = prepare_proposal(root, 'board', expert_profile='ARGON_DEEP')
    expected = proposal_summary()
    expected['expert']['profile'] = 'ARGON_DEEP'
    assert prepared['summary'] == expected
    with pytest.raises(PermissionError, match='exact_disabled_owner_proposal'):
        authorize_proposal(root, previous['proposal_sha256'])
    assert not (root/'activation.json').exists()
    authorize_proposal(root, prepared['proposal_sha256'])
    expert = UnifiedPublicExpertBudget(root/'experts')
    policy = expert.policy()
    assert policy.allowed_profiles == ['ARGON_DEEP']
    assert (policy.max_sessions, policy.job_timeout_seconds, policy.max_context_tokens,
            policy.max_result_characters) == (2, 90, 3000, 6000)
    expert.reserve_session('first', True, 'board')
    expert.reserve_session('second', True, 'board')
    with pytest.raises(PermissionError, match='session_budget_exhausted'):
        expert.reserve_session('third', True, 'board')
    ledger = BoardSpeechLedger(UnifiedBoardBudget(root), expert)
    speech = ledger.require('board')
    assert speech.estimate_usd_limit == 1 and speech.max_stt_attempts == 2
    assert ledger.status()['operations'] == {}
    assert before == {p.relative_to(old): p.read_bytes() for p in old.rglob('*.json')}


@pytest.mark.parametrize('profiles', [[], ['ASTRA_HIGH'], ['SOL_HIGH', 'ARGON_DEEP'],
                                     ['ARGON_DEEP', 'ARGON_DEEP']])
def test_profile_scope_is_rejected_even_with_a_rehashed_proposal(tmp_path, profiles):
    data = prepare_proposal(tmp_path, 'board', expert_profile='ARGON_DEEP')
    paths = ('policy.json', 'experts/policy.json', 'speech-policy.json')
    policies = {path: json.loads((tmp_path/path).read_text()) for path in paths}
    policies['experts/policy.json']['allowed_profiles'] = profiles
    (tmp_path/'experts/policy.json').write_text(json.dumps(policies['experts/policy.json']))
    data['proposal_sha256'] = digest(json.dumps(policies, sort_keys=True, separators=(',', ':')))
    (tmp_path/'proposal.json').write_text(json.dumps(data))
    with pytest.raises(PermissionError, match='expert_policy_outside_allowance'):
        prepare_proposal(tmp_path, 'board', expert_profile='ARGON_DEEP')
    with pytest.raises(PermissionError, match='exact_disabled_owner_proposal'):
        authorize_proposal(tmp_path, data['proposal_sha256'])
    assert not (tmp_path/'activation.json').exists()
    expert = UnifiedPublicExpertBudget(tmp_path/'experts')
    with pytest.raises(PermissionError, match='expert_policy_outside_allowance'):
        expert.policy()
    with expert.connect() as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0


def test_profile_change_is_bound_to_both_policy_hash_and_reviewed_summary(tmp_path):
    data = prepare_proposal(tmp_path, 'board')
    paths = ('policy.json', 'experts/policy.json', 'speech-policy.json')
    policies = {path: json.loads((tmp_path/path).read_text()) for path in paths}
    policies['experts/policy.json']['allowed_profiles'] = ['ARGON_DEEP']
    (tmp_path/'experts/policy.json').write_text(json.dumps(policies['experts/policy.json']))
    with pytest.raises(PermissionError, match='exact_disabled_owner_proposal'):
        authorize_proposal(tmp_path, data['proposal_sha256'])
    # Even a new matching SHA cannot approve a policy whose displayed profile disagrees.
    data['proposal_sha256'] = digest(json.dumps(policies, sort_keys=True, separators=(',', ':')))
    (tmp_path/'proposal.json').write_text(json.dumps(data))
    with pytest.raises(PermissionError, match='exact_disabled_owner_proposal'):
        authorize_proposal(tmp_path, data['proposal_sha256'])
    assert not (tmp_path/'activation.json').exists()


@pytest.mark.parametrize('profile', ['ASTRA_HIGH', ['SOL_HIGH', 'ARGON_DEEP'], None])
def test_prepare_rejects_nonapproved_profiles_without_creating_an_epoch(tmp_path, profile):
    root = tmp_path/'not-created'
    with pytest.raises(PermissionError, match='expert_profile_outside_allowance'):
        prepare_proposal(root, 'board', expert_profile=profile)
    assert not root.exists()


def test_expiry_or_limit_tampering_is_not_authorization(tmp_path):
    data = prepare_proposal(tmp_path, 'board')
    manifest = tmp_path/'proposal.json'
    changed = json.loads(manifest.read_text())
    changed['summary']['validity_after_approval_seconds'] = 999999
    manifest.write_text(json.dumps(changed))
    with pytest.raises(PermissionError, match='exact_disabled_owner_proposal'):
        authorize_proposal(tmp_path, data['proposal_sha256'])
    assert not (tmp_path/'activation.json').exists()
    with pytest.raises(ValueError):
        epoch_root(tmp_path, '../old-grant')


@pytest.mark.parametrize('expert_profile', ['SOL_HIGH', 'ARGON_DEEP'])
def test_operator_preview_and_cue_preview_are_read_only(tmp_path, capsys, expert_profile):
    path = Path(__file__).resolve().parents[1]/'scripts/sophia_voice_grant.py'
    spec = importlib.util.spec_from_file_location('sophia_grant_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = tmp_path/'new-run'
    base = ['--run-root', str(run), '--epoch', 'new', '--device-id', 'board',
            '--gateway-config', str(tmp_path/'not-installed.json')]
    result = module.main(['preview', *base, '--expert-profile', expert_profile])
    assert result['dry_run'] and result['paid_requests_made'] == 0 and not run.exists()
    assert result['summary']['expert']['profile'] == expert_profile
    result = module.main(['cue', *base, '--cache-root', str(tmp_path/'missing-cache')])
    assert result['requires_explicit_execute'] and result['paid_requests_made'] == 0
    assert not run.exists() and not (tmp_path/'missing-cache').exists()
    capsys.readouterr()


def test_operator_prepares_only_the_explicit_argon_profile(tmp_path, capsys):
    path = Path(__file__).resolve().parents[1]/'scripts/sophia_voice_grant.py'
    spec = importlib.util.spec_from_file_location('sophia_grant_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    result = module.main(['prepare', '--run-root', str(tmp_path), '--epoch', 'argon',
                          '--device-id', 'board', '--gateway-config', str(tmp_path/'absent.json'),
                          '--expert-profile', 'ARGON_DEEP'])
    root = epoch_root(tmp_path, 'argon')
    policy = json.loads((root/'experts/policy.json').read_text())
    assert result['summary']['expert']['profile'] == 'ARGON_DEEP'
    assert policy['allowed_profiles'] == ['ARGON_DEEP'] and not policy['enabled']
    assert policy['expires_at'] == 0 and not (root/'activation.json').exists()
    assert not list(root.rglob('usage.sqlite'))
    capsys.readouterr()


def test_disabled_expired_and_foreign_grants_deny_before_pcm_or_phone_spend(tmp_path, settings):
    async def run():
        original, board, manager, session, auth = await setup(tmp_path, settings, enabled=False)
        try:
            assert session.ready and not session.scoped_public_expert_allowed()
            with pytest.raises(PermissionError):
                await session.wake('disabled', mode='expert')
            with pytest.raises(PermissionError):
                await auth.transcription(session)
            with pytest.raises(PermissionError):
                await auth.narrator(session, SimpleNamespace(id='job', max_result_characters=6000))
            assert await session.append_pcm(bytes(4800)) is False
            assert not manager.speech.turns
            with board.budget.connect() as db:
                assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
                assert db.execute('SELECT count(*) FROM unified_speech_attempts').fetchone()[0] == 0
            with original.owner_testing.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
            assert not any(e['type'] in {'response.create', 'input_audio_buffer.append'}
                           for sock in manager.provider.sockets for e in sock.sent)
            root = board.budget.root
            proposal = json.loads((root/'proposal.json').read_text())
            authorize_proposal(root, proposal['proposal_sha256'])
            speech = manager.board_speech_ledger
            p = speech.policy()
            speech.policy_path.write_text(p.model_copy(update={'expires_at': time.time()-1}).model_dump_json())
            with pytest.raises(PermissionError):
                await auth.transcription(session)
            speech.policy_path.write_text(p.model_copy(update={'allowed_client_id': 'phone'}).model_dump_json())
            with pytest.raises(PermissionError):
                await auth.transcription(session)
            assert speech.status()['operations'] == {}
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_original_public_trial_scope_is_preserved_without_new_speech_grant(tmp_path, settings):
    from test_board_trial import trial
    async def run():
        original, old, board, _, _, _ = trial(tmp_path, settings)
        manager = DirectRealtimeManager(board, provider=Provider(), speech=SpeechFixture())
        try:
            session = await manager.accept(offer(expert_quota_consent=True))
            assert session.scoped_public_expert_allowed()
            assert session.experts.budget.root == board.budget.root/'experts'
            assert session.experts.budget.policy().max_sessions == 1
            assert not session.owner_test_authorized and not session.expert_authorized
            assert session.access.confirmed_profile_id is None and not session.offer.remember
            with pytest.raises(PermissionError):
                await UnifiedVoiceBudget().transcription(session)
            assert not old.budget.board_status()['reserved_estimate_usd']
        finally:
            await cleanup(original, board, manager)
            await old.shutdown()
    asyncio.run(run())


def test_new_explicit_180s_stt_reuses_board_database_and_settles_actual_duration(tmp_path, settings):
    async def run():
        original, board, manager, session, auth = await setup(tmp_path, settings)
        try:
            assert session.scoped_public_expert_allowed() and not session.owner_test_authorized
            admission = await auth.transcription(session)
            assert admission['max_audio_seconds'] == 180 and board.budget.policy().max_session_seconds == 60
            assert manager.board_speech_ledger.path == board.budget.path
            with board.budget.connect() as db:
                assert db.execute('SELECT kind,pending,audio_seconds FROM unified_speech_attempts').fetchone() == ('stt', 1, 180)
            await admission['settle'](audio_seconds=61, provider_usage={'seconds': 61.1}, usage_reported=True)
            second = await auth.transcription(session)
            await second['settle'](audio_seconds=180)
            with pytest.raises(PermissionError, match='stt_attempts_exhausted'):
                await auth.transcription(session)
            with board.budget.connect() as db:
                costs = db.execute('SELECT cost,pending FROM unified_speech_attempts ORDER BY created').fetchall()
            assert costs == [(pytest.approx(61.1/60*.017), 0), (pytest.approx(180/60*.017), 0)]
            assert board.budget.status()['sessions_reserved'] == 0
            with original.owner_testing.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_atomic_speech_holds_cannot_overspend_or_move_to_new_authorization(tmp_path):
    voice, expert, ledger = finite(tmp_path)
    def attempt(index):
        try:
            return ledger.reserve('board', 'stt', 'stt-'+str(index), audio_seconds=180)
        except PermissionError:
            return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        keys = list(pool.map(attempt, range(4)))
    assert len([k for k in keys if k]) == 2
    assert ledger.status()['operations']['stt']['estimated_usd_including_pending'] == 1
    with pytest.raises(PermissionError, match='estimate_limit'):
        ledger.reserve('board', 'tts', 'first-narrator', job_id='job')
    p = ledger.policy()
    ledger.policy_path.write_text(p.model_copy(update={'authorization': 'new-unapproved-identity'}).model_dump_json())
    with pytest.raises(PermissionError, match='identity_changed'):
        ledger.reserve('board', 'tts', 'second-narrator', job_id='job')


def test_narrator_per_job_total_and_response_caps_apply_before_provider(tmp_path, settings):
    from gobot.processes import AgentError
    async def run():
        original, board, manager, session, auth = await setup(tmp_path, settings)
        try:
            for job_id in ('first', 'second'):
                options = await auth.narrator(session, SimpleNamespace(id=job_id, max_result_characters=6000))
                assert options['tts_character_limit'] == 3000
                async with options['speech'].turn() as turn:
                    for _ in range(6):
                        assert [item async for item in turn.synthesize('А'*500, 'openai', 'marin', paid_consent=True)]
                    with pytest.raises(AgentError, match='budget_denied'):
                        [item async for item in turn.synthesize('Ещё', 'openai', 'marin', paid_consent=True)]
            stats = manager.board_speech_ledger.status()['operations']['tts']
            assert stats['attempts'] == 12 and stats['characters_reserved'] == 6000 and stats['pending_usage'] == 0
            assert sum(turn.requests_started for turn in manager.speech.turns) == 12
            with original.owner_testing.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_revocation_blocks_next_stt_pcm_and_retains_unknown_reserve(tmp_path, settings):
    class Recognition:
        def __init__(self): self.bytes = 0
        async def live(self, chunks, **kwargs):
            async for chunk in chunks:
                self.bytes += len(chunk)
            if False: yield None
    async def run():
        recognition = Recognition()
        original, board, manager, session, auth = await setup(tmp_path, settings, recognition=recognition)
        try:
            await session.wake('manual', mode='expert')
            assert session.input_open
            p = manager.board_speech_ledger.policy()
            manager.board_speech_ledger.policy_path.write_text(p.model_copy(update={'enabled': False}).model_dump_json())
            assert await session.append_pcm(bytes(4800)) is False
            assert not session.input_open and recognition.bytes == 0
            assert manager.board_speech_ledger.status()['operations']['stt']['pending_usage'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_fixed_cue_is_one_explicit_paid_attempt_and_cache_reuse_is_free(tmp_path):
    async def run():
        root, cache = tmp_path/'grant', tmp_path/'cache'
        voice, expert, ledger = finite(root)
        speech = SpeechFixture()
        result = await create_service_cue(root, cache_root=cache, speech=speech)
        assert result['paid_requests_made'] == 1 and len(speech.turns) == 1
        ready = load_expert_service_cue(cache)
        assert ready['status'] == 'ready' and ready['text'] == EXPERT_CUE_TEXT
        assert ready['voice'] == 'marin' and ready['model'] == 'gpt-realtime-2.1-mini'
        assert ready['sha256'] == result['sha256'] and ready['runtime_generation'] is False
        result = await create_service_cue(root, cache_root=cache, speech=speech)
        assert result['paid_requests_made'] == 0 and len(speech.turns) == 1
        for path in cache.iterdir(): path.unlink()
        with pytest.raises(PermissionError, match='already_reserved'):
            await create_service_cue(root, cache_root=cache, speech=speech)
        assert len(speech.turns) == 1
        assert ledger.status()['operations']['cue']['attempts'] == 1
    asyncio.run(run())


def test_read_only_admission_preview_requires_exact_source_and_preserves_all_counters(tmp_path, settings):
    async def run():
        original, board, manager, session, auth = await setup(tmp_path, settings)
        try:
            denied = manager.admission_preview(client_id='phone', device_id='phone')
            assert not denied['allowed'] and denied['code'] == 'exact_authorized_client_required'
            denied = manager.admission_preview(client_id='board', device_id='board', owner_test_binding='board')
            assert not denied['allowed']
            ready = manager.admission_preview(client_id='board', device_id='board')
            assert ready['allowed'] and ready['expert_available'] and not ready['private_memory_allowed']
            assert not ready['reserves_paid_start']
            assert board.budget.status()['sessions_reserved'] == 0
            assert manager.public_expert_budget.status()['sessions_reserved'] == 0
            assert manager.board_speech_ledger.status()['operations'] == {}
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_exhausted_fast_starts_do_not_hide_separate_expert_preview(tmp_path, settings):
    async def run():
        original, board, manager, session, _ = await setup(tmp_path, settings)
        try:
            for index in range(3):
                board.budget.reserve_session('manual-'+str(index), True, 'board')
            before = board.budget.status()
            preview = manager.admission_preview(client_id='board', device_id='board')
            assert preview['allowed'] is False and preview['generation_allowed'] is False
            assert preview['code'] == 'realtime_session_budget_exhausted'
            assert preview['expert_available'] is True
            assert before == board.budget.status()
            assert manager.public_expert_budget.status()['sessions_remaining'] == 2
            assert manager.admission_preview(client_id='other', device_id='other')['expert_available'] is False
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_board_expert_routes_narrate_once_and_preserve_selected_followup_mode(tmp_path, settings, monkeypatch):
    """Public guest, real Direct/ExpertJobs/pipeline; no phone budget or provider."""
    import gobot.expert_jobs as jobs
    import gobot.expert_stream as stream
    from gobot.expert_profiles import resolve_profile
    rows = [{'slug': 'gpt-6.1-sol', 'supported_reasoning_levels': [{'effort': 'high'}]}]
    monkeypatch.setattr(jobs, 'resolve_profile', lambda name: resolve_profile(name, codex_metadata=rows))
    monkeypatch.setattr(stream, 'load_expert_service_cue', lambda: {'status': 'missing'})
    calls = []
    async def source(settings, req, packet, *, expert_profile):
        calls.append(req.turn_id)
        yield AnswerDelta('Проверенный публичный ответ.', item_id='answer', phase='final_answer',
                          job_id=req.turn_id, verified=True)
    monkeypatch.setattr(jobs, 'bridge_stream', source)
    class Recognition:
        async def live(self, chunks, **kwargs):
            assert kwargs['max_audio_seconds'] == 180
            samples = 0
            async for chunk in chunks: samples += len(chunk)//2
            yield {'type': 'stt_final', 'data': {'text': 'Сравни два публичных метода.',
                'item_id': 'dictation', 'stable': True, 'audio_seconds': samples/24000,
                'usage_reported': True, 'usage': {'seconds': samples/24000}}}
    async def finish_response(session, job, *, mode='fast'):
        await job.worker
        assert job.state == 'completed' and job.narration_complete and not job.playback_complete
        await session.playback_started(job.response_id)
        await session.playback_finished(job.response_id)
        # The real guard includes 200ms plus async policy/SQLite admission.
        # Waiting only 250ms races normal Windows file/thread scheduling.
        # Await its actual completion; still fail if it hangs or rejects input.
        await asyncio.wait_for(asyncio.shield(session._guard_task), 3)
        assert job.playback_complete and session.selected_mode == mode
        assert session.input_open == (mode == 'fast')
    async def run():
        original, board, manager, session, auth = await setup(tmp_path, settings, recognition=Recognition())
        async def consume_output():
            # Model the attached listener across both responses; an unconsumed
            # bounded wire queue correctly detaches even in a synthetic test.
            while True:
                await session.next_event()
        listener = asyncio.create_task(consume_output())
        try:
            session.experts.admission = lambda profile: {'available': True}
            await session.wake('fast-route')
            turn = await session.new_turn(query='София, спроси у Codex, сравни публичные методы')
            first = await session.experts.start_local(turn.query, 'SOL_HIGH', turn)
            # A 90s expert may outlive the original 60s B operation. Its result
            # continues with one new paid B reservation, never a clock extension.
            session.operation_started -= 61
            await finish_response(session, first)
            assert board.budget.status()['sessions_reserved'] == 2
            await session.stop()
            await session.wake('dictation-route', mode='expert')
            for _ in range(61):
                assert await session.append_pcm(bytes(48000))
            await session.finish_input()
            await session._stt_task
            second = next(job for job in session.experts.jobs.values() if job.id != first.id)
            # Explicit expert mode remains selected, awaiting a new manual wake;
            # its answer must not reserve an unwanted fast or STT followup.
            session.operation_started -= 61
            await finish_response(session, second, mode='expert')
            assert len(calls) == 2 and manager.public_expert_budget.status()['sessions_reserved'] == 2
            assert board.budget.status()['sessions_reserved'] == 2
            assert manager.board_speech_ledger.status()['operations']['stt']['attempts'] == 1
            assert manager.board_speech_ledger.status()['operations']['stt']['pending_usage'] == 0
            assert manager.board_speech_ledger.status()['operations']['tts']['attempts'] == 2
            assert not session.owner_test_authorized and session.access.confirmed_profile_id is None
            assert not any(e['type'] == 'response.create' or e.get('item', {}).get('type') == 'function_call_output'
                           for sock in manager.provider.sockets for e in sock.sent)
            await session.stop()
            with pytest.raises(PermissionError, match='expert_unavailable'):
                await session.wake('third-job-denied', mode='expert')
            with original.owner_testing.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
            with original.brain.memory.connect() as db:
                assert db.execute('SELECT count(*) FROM expert_results').fetchone()[0] == 0
        finally:
            listener.cancel()
            await asyncio.gather(listener, return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('boundary', ['stop', 'expiry', 'exhausted'])
def test_physical_ack_cannot_reopen_after_stop_expiry_or_count_exhaustion(tmp_path, settings, monkeypatch, boundary):
    import gobot.expert_jobs as jobs
    import gobot.expert_stream as stream
    from gobot.expert_profiles import resolve_profile
    rows = [{'slug': 'gpt-6.1-sol', 'supported_reasoning_levels': [{'effort': 'high'}]}]
    monkeypatch.setattr(jobs, 'resolve_profile', lambda name: resolve_profile(name, codex_metadata=rows))
    monkeypatch.setattr(stream, 'load_expert_service_cue', lambda: {'status': 'missing'})
    async def source(settings, req, packet, *, expert_profile):
        yield AnswerDelta('Ответ эксперта.', item_id='a', phase='final_answer', job_id=req.turn_id, verified=True)
    monkeypatch.setattr(jobs, 'bridge_stream', source)
    async def run():
        original, board, manager, session, auth = await setup(tmp_path, settings)
        try:
            session.experts.admission = lambda profile: {'available': True}
            await session.wake('manual')
            turn = await session.new_turn(query='София, спроси у Codex, как это устроено')
            job = await session.experts.start_local(turn.query, 'SOL_HIGH', turn)
            await job.worker
            assert job.state == 'completed' and job.narration_complete
            session.operation_started -= 61
            if boundary == 'stop':
                await session.stop()
            elif boundary == 'expiry':
                policy = board.budget.policy()
                board.budget.policy_path.write_text(policy.model_copy(update={'expires_at': time.time()-1}).model_dump_json())
            else:
                board.budget.reserve_session('separate-manual-2', True, 'board')
                board.budget.reserve_session('separate-manual-3', True, 'board')
            expected = board.budget.status()['sessions_reserved']
            await session.playback_started(job.response_id)
            await session.playback_finished(job.response_id)
            # A duplicate late receipt cannot retry the consumed continuation.
            assert not (await session.playback_finished(job.response_id))['accepted']
            if session._guard_task and not session._guard_task.cancelled():
                await asyncio.wait_for(asyncio.shield(session._guard_task), 3)
            assert not session.input_open and board.budget.status()['sessions_reserved'] == expected
            assert not session._expert_followup_jobs
            assert await session.append_pcm(bytes(4800)) is False
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_browser_preview_respects_existing_owner_daily_counter_without_spending(tmp_path, settings):
    from test_unified_voice_budget import owner_setup, close
    async def run():
        original, manager, session, owner, auth = await owner_setup(tmp_path, settings)
        try:
            preview = manager.admission_preview(client_id='client-1', device_id='browser-1')
            assert preview['allowed'] and not preview['private_memory_allowed']
            with owner.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
            owner.update('client-1', {'realtime_responses_per_day': 10})
            for index in range(10):
                owner.reserve('client-1', 'realtime', 'previous-manual-fixture-'+str(index), estimate=.01)
            denied = manager.admission_preview(client_id='client-1', device_id='browser-1')
            assert not denied['allowed'] and denied['code'] == 'owner_realtime_daily_limit'
            with owner.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 10
        finally:
            await close(original, manager)
    asyncio.run(run())
