"""New joint review is a separate disabled scope; old approval is never enlarged."""
import asyncio
import importlib.util
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from gobot.board_unified import (
    BoardSpeechLedger, UnifiedBoardBudget, UnifiedPublicExpertBudget,
    authorize_proposal, create_service_cue, digest, prepare_proposal, proposal_summary,
)
from gobot.expert_stream import EXPERT_CUE_ID, EXPERT_CUE_TEXT, expert_service_cache
from gobot.realtime_contract import RealtimePolicy
from test_unified_voice_budget import SpeechFixture


def prepare(root):
    return prepare_proposal(root, 'board', expert_profile='ARGON_DEEP', acceptance_preset='joint_review')


def activate_fixture(root):
    """Synthetic owner approval only inside pytest's fresh temporary directory."""
    proposal = prepare(root)
    cache = root/'fixture-public-cue'
    expert_service_cache(cache).put('marin', EXPERT_CUE_ID, bytes(4800), 24000, EXPERT_CUE_TEXT)
    authorize_proposal(root, proposal['proposal_sha256'], cache_root=cache)
    return UnifiedBoardBudget(root)


def test_original_serialization_hash_and_summary_are_unchanged(tmp_path, monkeypatch):
    import gobot.board_unified as module
    ids = iter(['1'*32, '2'*32, '3'*32])
    monkeypatch.setattr(module, 'uuid4', lambda: SimpleNamespace(hex=next(ids)))
    proposal = prepare_proposal(tmp_path/'old', 'board', expert_profile='ARGON_DEEP')
    # Captured from the pre-preset v1 implementation with these fixed IDs.
    assert proposal['proposal_sha256'] == 'd31d4f947ae023e8268991a416c39ff20d34cfc6e98bbd20bcd0c0771744f86f'
    assert proposal['summary'] == proposal_summary('ARGON_DEEP')
    assert 'acceptance_preset' not in proposal and 'acceptance_preset' not in proposal['summary']
    assert proposal['summary']['total_api_estimate_usd'] == 2
    assert proposal['summary']['speech']['cue_generations'] == 1
    assert 'observed_token_limit' not in proposal['summary']['realtime']
    voice = RealtimePolicy.model_validate_json((tmp_path/'old/policy.json').read_text())
    assert voice.observed_token_limit == 12000


def test_joint_preparation_disabled_exact_and_never_rewrites_old_accounting(tmp_path):
    old, new = tmp_path/'old', tmp_path/'new'
    original = prepare_proposal(old, 'board', expert_profile='ARGON_DEEP')
    authorize_proposal(old, original['proposal_sha256'])
    old_budget = UnifiedBoardBudget(old)
    old_budget.reserve_session('used-start', True, 'board')
    before = {p.relative_to(old): p.read_bytes() for p in old.rglob('*') if p.is_file()}
    proposal = prepare(new)
    assert proposal['acceptance_preset'] == 'joint_review'
    assert proposal['summary']['realtime'] == {
        'sessions': 3, 'seconds_each': 180, 'responses_each': 12,
        'output_tokens_each': 1024, 'observed_token_limit': 100000,
        'model': 'gpt-realtime-2.1-mini', 'estimated_usd': 2}
    assert proposal['summary']['expert'] == proposal_summary('ARGON_DEEP')['expert']
    assert proposal['summary']['speech']['cue_generations'] == 0
    assert proposal['summary']['speech']['existing_ready_cue_required']
    assert proposal['summary']['speech']['estimated_usd'] == 1
    assert proposal['summary']['total_api_estimate_usd'] == 3
    assert proposal['summary']['validity_after_approval_seconds'] == 7200
    assert not proposal['summary']['provider_invoice_cap_guaranteed']
    policies = [json.loads((new/name).read_text()) for name in (
        'policy.json', 'experts/policy.json', 'speech-policy.json')]
    assert all(not p['enabled'] and p['expires_at'] == 0 for p in policies)
    assert not (new/'activation.json').exists() and not list(new.rglob('usage.sqlite'))
    assert prepare(new) == proposal
    with pytest.raises(PermissionError, match='preset_mismatch_new_epoch'):
        prepare_proposal(old, 'board', expert_profile='ARGON_DEEP', acceptance_preset='joint_review')
    with pytest.raises(PermissionError, match='exact_disabled_owner_proposal'):
        authorize_proposal(new, original['proposal_sha256'])
    assert before == {p.relative_to(old): p.read_bytes() for p in old.rglob('*') if p.is_file()}


def test_joint_limits_reservations_status_and_one_window_match_preview(tmp_path):
    approved_at = time.time()
    budget = activate_fixture(tmp_path)
    assert approved_at+7200 <= budget.policy().expires_at <= time.time()+7200
    assert budget.board_status()['estimated_allowance_usd'] == 2
    assert budget.board_status()['reserved_estimate_usd'] == 0
    for index in range(3):
        policy = budget.reserve_session('start-'+str(index), True, 'board')
        assert (policy.max_session_seconds, policy.max_responses_per_session,
                policy.max_output_tokens, policy.observed_token_limit) == (180, 12, 1024, 100000)
        for _ in range(12):
            budget.reserve_response('start-'+str(index), policy)
        with pytest.raises(PermissionError, match='response_budget_exhausted'):
            budget.reserve_response('start-'+str(index), policy)
    status = budget.board_status()
    assert status['sessions_remaining'] == 0 and status['reserved_estimate_usd'] == 2
    assert status['session_seconds'] == 180 and status['output_tokens_per_response'] == 1024
    assert status['reported_response_estimate_usd'] == 0
    with pytest.raises(PermissionError):
        budget.reserve_session('fourth', True, 'board')
    proposal = json.loads((tmp_path/'proposal.json').read_text())
    with pytest.raises((PermissionError, FileExistsError)):
        authorize_proposal(tmp_path, proposal['proposal_sha256'])
    expert = UnifiedPublicExpertBudget(tmp_path/'experts')
    assert expert.policy().allowed_profiles == ['ARGON_DEEP']
    assert expert.policy().max_sessions == 2
    ledger = BoardSpeechLedger(budget, expert)
    speech = ledger.require('board')
    assert (speech.max_stt_attempts, speech.max_stt_audio_seconds,
            speech.max_narrator_responses, speech.max_narrator_characters) == (2, 180, 12, 6000)
    assert speech.max_cue_generations == 0 and speech.estimate_usd_limit == 1


@pytest.mark.parametrize('patch', [
    {'max_session_seconds': 180}, {'max_output_tokens': 1024},
    {'max_sessions': 4}, {'max_responses_per_session': 13},
    {'observed_token_limit': 100000}, {'observed_token_limit': None},
])
def test_hybrid_or_larger_limits_cannot_authorize_even_with_rehashed_files(tmp_path, patch):
    proposal = prepare_proposal(tmp_path, 'board', expert_profile='ARGON_DEEP')
    paths = ('policy.json', 'experts/policy.json', 'speech-policy.json')
    policies = {name: json.loads((tmp_path/name).read_text()) for name in paths}
    policies['policy.json'].update(patch)
    (tmp_path/'policy.json').write_text(json.dumps(policies['policy.json']))
    proposal['proposal_sha256'] = digest(json.dumps(policies, sort_keys=True, separators=(',', ':')))
    (tmp_path/'proposal.json').write_text(json.dumps(proposal))
    with pytest.raises(PermissionError, match='exact_disabled_owner_proposal'):
        authorize_proposal(tmp_path, proposal['proposal_sha256'])
    assert not (tmp_path/'activation.json').exists()


def test_old_activation_cannot_admit_joint_tuple_or_rewritten_joint_expiry(tmp_path):
    original = prepare_proposal(tmp_path/'old', 'board', expert_profile='ARGON_DEEP')
    authorize_proposal(tmp_path/'old', original['proposal_sha256'])
    path = tmp_path/'old/policy.json'
    policy = json.loads(path.read_text())
    policy.update(max_session_seconds=180, max_responses_per_session=12,
                  max_output_tokens=1024, observed_token_limit=100000)
    path.write_text(json.dumps(policy))
    with pytest.raises(PermissionError, match='joint_review_exact_proposal_binding'):
        UnifiedBoardBudget(path.parent).reserve_session('borrowed', True, 'board')
    budget = activate_fixture(tmp_path/'joint')
    policy = budget.policy()
    budget.policy_path.write_text(policy.model_copy(update={'expires_at': policy.expires_at+3600}).model_dump_json())
    with pytest.raises(PermissionError, match='joint_review_exact_proposal_binding'):
        budget.reserve_session('renewal', True, 'board')


def test_joint_estimate_gate_uses_two_dollars_and_preserves_measured_usage(tmp_path):
    budget = activate_fixture(tmp_path)
    policy = budget.reserve_session('manual', True, 'board')
    budget.record('manual', 'first', {'output_token_details': {'audio_tokens': 60000}})
    assert budget.board_status()['reported_response_estimate_usd'] == pytest.approx(1.2)
    budget.reserve_response('manual', policy) # Above the old $1 gate, within this exact new $2 scope.
    budget.record('manual', 'second', {'output_token_details': {'audio_tokens': 50000}})
    with pytest.raises(PermissionError, match='estimated_budget_exhausted'):
        budget.reserve_response('manual', policy)
    status = budget.board_status()
    assert status['reported_response_estimate_usd'] == pytest.approx(2.2)
    assert status['reserved_estimate_usd'] == pytest.approx(2/3)
    assert not status['hard_dollar_cap_guaranteed']
    with budget.connect() as db:
        assert db.execute('SELECT count(*) FROM usage').fetchone()[0] == 2


def test_joint_does_not_regenerate_missing_cue_and_reuses_valid_cache(tmp_path):
    async def run():
        root, cache = tmp_path/'joint', tmp_path/'cache'
        budget = activate_fixture(root)
        speech = SpeechFixture()
        with pytest.raises(PermissionError, match='cue_attempts_exhausted'):
            await create_service_cue(root, cache_root=cache, speech=speech)
        assert not speech.turns
        expert_service_cache(cache).put('marin', EXPERT_CUE_ID, bytes(4800), 24000, EXPERT_CUE_TEXT)
        result = await create_service_cue(root, cache_root=cache, speech=speech)
        assert result['cached'] and result['paid_requests_made'] == 0 and not speech.turns
        ledger = BoardSpeechLedger(budget, UnifiedPublicExpertBudget(root/'experts'))
        assert ledger.status()['operations'] == {}
    asyncio.run(run())


def test_joint_authorization_requires_existing_validated_cue_without_generating_it(tmp_path):
    root, cache = tmp_path/'joint', tmp_path/'absent-cache'
    proposal = prepare(root)
    before = {p.relative_to(root): p.read_bytes() for p in root.rglob('*.json')}
    with pytest.raises(PermissionError, match='existing_ready_cue_required'):
        authorize_proposal(root, proposal['proposal_sha256'], cache_root=cache)
    assert not (root/'activation.json').exists() and not cache.exists()
    assert before == {p.relative_to(root): p.read_bytes() for p in root.rglob('*.json')}


def test_cli_preset_is_preview_prepare_only_and_binds_exact_argon(tmp_path, capsys):
    path = Path(__file__).resolve().parents[1]/'scripts/sophia_voice_grant.py'
    spec = importlib.util.spec_from_file_location('sophia_joint_grant_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = tmp_path/'run'
    base = ['--run-root', str(run), '--epoch', 'joint', '--device-id', 'board',
            '--gateway-config', str(tmp_path/'absent.json')]
    result = module.main(['preview', *base, '--acceptance-preset', 'joint_review'])
    assert result['summary']['total_api_estimate_usd'] == 3 and not run.exists()
    result = module.main(['prepare', *base, '--acceptance-preset', 'joint_review'])
    assert result['summary']['expert']['profile'] == 'ARGON_DEEP'
    root = run/'voice-sophia-acceptance/joint'
    assert not (root/'activation.json').exists() and not list(root.rglob('usage.sqlite'))
    with pytest.raises(SystemExit):
        module.main(['authorize', *base, '--acceptance-preset', 'joint_review'])
    with pytest.raises(PermissionError, match='joint_review_requires_argon'):
        proposal_summary('SOL_HIGH', acceptance_preset='joint_review')
    capsys.readouterr()
