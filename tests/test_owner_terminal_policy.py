"""Permanent board authorization and durable accounting; no real providers."""
import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from gobot.board_unified import (
    BoardSpeechLedger, UnifiedBoardBudget, UnifiedPublicExpertBudget,
    authorize_proposal, prepare_proposal,
)
from gobot.expert_store import ExpertPolicy
from gobot.expert_stream import EXPERT_CUE_ID, EXPERT_CUE_TEXT, expert_service_cache
from gobot.owner_terminal import (
    OwnerTerminalBoardBudget, OwnerTerminalExpertBudget, OwnerTerminalRealtimePolicy,
    authorize_owner_terminal_proposal, prepare_owner_terminal_proposal,
    validate_owner_terminal_binding,
)
from gobot.realtime_contract import RealtimePolicy, session_config, settings_applied


OWNER_DIRECT = 'Fixture owner: постоянный тестовый терминал, без окон, лимитов расходов и общих квот.'


def terminal_fixture(root):
    proposal = prepare_owner_terminal_proposal(root, 'board')
    cache = root/'fixture-public-cue'
    expert_service_cache(cache).put('marin', EXPERT_CUE_ID, bytes(4800), 24000, EXPERT_CUE_TEXT)
    authorize_owner_terminal_proposal(root, proposal['proposal_sha256'],
                                      owner_direct=OWNER_DIRECT, cache_root=cache)
    voice = OwnerTerminalBoardBudget(root)
    expert = OwnerTerminalExpertBudget(root/'experts')
    return voice, expert, BoardSpeechLedger(voice, expert)


def test_preparation_and_activation_exact_persistent_and_no_provider_requests(tmp_path):
    proposal = prepare_proposal(tmp_path, 'board', expert_profile='ARGON_DEEP', acceptance_preset='owner_terminal')
    original = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    assert prepare_owner_terminal_proposal(tmp_path, 'board') == proposal
    assert original == {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    assert proposal['summary']['total_api_estimate_usd'] is None
    assert proposal['summary']['validity_after_approval_seconds'] is None
    assert all(not value.enabled and value.expires_at is None for value in validate_owner_terminal_binding(tmp_path))
    with pytest.raises(PermissionError, match='exact_disabled_owner_proposal'):
        authorize_proposal(tmp_path, proposal['proposal_sha256'])
    with pytest.raises(PermissionError, match='existing_ready_cue'):
        authorize_proposal(tmp_path, proposal['proposal_sha256'], owner_direct=OWNER_DIRECT, cache_root=tmp_path/'empty')
    assert not (tmp_path/'activation.json').exists()
    cache = tmp_path/'fixture-public-cue'
    expert_service_cache(cache).put('marin', EXPERT_CUE_ID, bytes(4800), 24000, EXPERT_CUE_TEXT)
    result = authorize_proposal(tmp_path, proposal['proposal_sha256'], owner_direct=OWNER_DIRECT, cache_root=cache)
    assert result['expires_at'] is None and result['paid_requests_made'] == 0 and not result['mounted']
    approval_bytes = (tmp_path/'owner-authorization.json').read_bytes()
    approval = json.loads(approval_bytes)
    activation = json.loads((tmp_path/'activation.json').read_bytes())
    assert approval['statement'] == OWNER_DIRECT and approval['source'] == 'owner_direct'
    assert activation['owner_authorization_sha256'] == hashlib.sha256(approval_bytes).hexdigest()
    assert activation['approved_proposal_sha256'] == proposal['proposal_sha256']
    assert all(value.enabled and value.expires_at is None for value in validate_owner_terminal_binding(tmp_path))
    assert not list(tmp_path.rglob('usage.sqlite'))
    with pytest.raises(PermissionError, match='exact_disabled_owner_proposal'):
        authorize_proposal(tmp_path, proposal['proposal_sha256'], owner_direct=OWNER_DIRECT, cache_root=cache)


def test_permanent_scope_does_not_modify_or_borrow_existing_finite_grant(tmp_path):
    old, new = tmp_path/'finite', tmp_path/'terminal'
    proposal = prepare_proposal(old, 'board', expert_profile='ARGON_DEEP')
    authorize_proposal(old, proposal['proposal_sha256'])
    old_budget = UnifiedBoardBudget(old)
    old_budget.reserve_session('old-attempt', True, 'board')
    before = {path.relative_to(old): path.read_bytes() for path in old.rglob('*') if path.is_file()}
    voice, _, _ = terminal_fixture(new)
    voice.reserve_session('terminal-attempt', True, 'board')
    assert before == {path.relative_to(old): path.read_bytes() for path in old.rglob('*') if path.is_file()}
    assert voice.policy().authorization != old_budget.policy().authorization
    # Existing generic and finite policy parsers do not gain the new authority.
    with pytest.raises(ValueError):
        RealtimePolicy.model_validate_json(voice.policy_path.read_text())
    with pytest.raises((PermissionError, ValueError)):
        UnifiedBoardBudget(new).policy()
    with pytest.raises((PermissionError, ValueError)):
        UnifiedPublicExpertBudget(new/'experts').policy()
    with pytest.raises(ValueError):
        ExpertPolicy(enabled=True, authorization='old-unbounded', allowed_client_id='board',
                     audience='owner_interactive', expires_at=None, max_sessions=None,
                     allowed_profiles=['ARGON_DEEP'])


def test_starts_responses_cost_tokens_and_age_do_not_exhaust_terminal(tmp_path):
    voice, expert, _ = terminal_fixture(tmp_path)
    for index in range(5):
        ident = 'start-'+str(index)
        policy = voice.reserve_session(ident, True, 'board')
        for _ in range(16):
            voice.reserve_response(ident, policy)
    with voice.connect() as db:
        db.execute('UPDATE sessions SET started=?', (time.time()-10*365*86400,))
    voice.record('start-0', 'large-measured-response', {
        'input_tokens': 1_000_000, 'output_tokens': 1_000_000, 'total_tokens': 2_000_000,
        'input_token_details': {'text_tokens': 0, 'audio_tokens': 1_000_000},
        'output_token_details': {'text_tokens': 0, 'audio_tokens': 1_000_000},
    })
    voice.reserve_response('start-0', policy)
    assert voice.reserve_session('sixth-start', True, 'board').expires_at is None
    status = voice.board_status()
    assert status['reported_response_estimate_usd'] > 2
    assert status['sessions_remaining'] is None and status['estimated_allowance_usd'] is None
    assert status['reserved_estimate_usd'] is None
    assert status['response_attempts'] == 81 and status['measured_usage_rows'] == 1
    assert status['unknown_or_pending_response_usage'] == 80
    assert voice.total_tokens('start-0') == 2_000_000
    for index in range(4):
        expert.reserve_session('job-'+str(index), True, 'board')
    expert.record_cli_usage('job-0', {'inputTokens': 25, 'outputTokens': 15, 'private_text': 'discard'})
    assert expert.status()['sessions_remaining'] is None
    assert expert.status()['cli_usage_unknown_or_pending'] == 3
    assert expert.status()['cli_usage_rows'] == 1


def test_duplicate_unknown_attempt_remains_spent_after_reopen_and_race(tmp_path):
    voice, expert, _ = terminal_fixture(tmp_path)
    def attempt(_):
        try:
            voice.reserve_session('same-operation', True, 'board')
            return True
        except ValueError:
            return False
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert sum(pool.map(attempt, range(8))) == 1
    reopened = OwnerTerminalBoardBudget(tmp_path)
    with pytest.raises(ValueError, match='already_attempted'):
        reopened.reserve_session('same-operation', True, 'board')
    expert.reserve_session('unknown-cli-attempt', True, 'board')
    with pytest.raises(ValueError, match='already_attempted'):
        OwnerTerminalExpertBudget(tmp_path/'experts').reserve_session('unknown-cli-attempt', True, 'board')
    reopened.reserve_response('same-operation', reopened.policy())
    reopened.record('same-operation', 'missing-modalities', {'total_tokens': 100})
    assert reopened.board_status()['unknown_or_pending_response_usage'] == 1
    assert reopened.board_status()['measured_usage_rows'] == 0


def test_terminal_does_not_borrow_client_consent_phone_or_previous_ledger(tmp_path):
    voice, expert, speech = terminal_fixture(tmp_path)
    for budget in (voice, expert):
        for kwargs in ({'consent': False, 'client_id': 'board'},
                       {'consent': True, 'client_id': 'phone'},
                       {'consent': True, 'client_id': 'board', 'owner_test_binding': 'board'}):
            with pytest.raises(PermissionError):
                budget.reserve_session('denied', **kwargs)
        with budget.connect() as db:
            assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
            db.execute('INSERT INTO sessions(id,authorization,started) VALUES(?,?,?)',
                       ('old-attempt', 'previous-authorization', time.time()))
        with pytest.raises(PermissionError, match='fresh_accounting_scope'):
            budget.reserve_session('new-attempt', True, 'board')
    with pytest.raises(PermissionError):
        speech.reserve('phone', 'stt', 'wrong-board', audio_seconds=10)


def test_speech_no_total_caps_preserves_pending_measured_and_single_use(tmp_path):
    voice, expert, speech = terminal_fixture(tmp_path)
    keys = [speech.reserve('board', 'stt', 'stt-'+str(index), audio_seconds=180) for index in range(4)]
    tts = [speech.reserve('board', 'tts', 'tts-'+str(index), job_id='same-job', characters=1200)
           for index in range(14)]
    speech.settle(keys[0], .04)
    speech.settle(tts[0], .02)
    reopened = BoardSpeechLedger(OwnerTerminalBoardBudget(tmp_path), OwnerTerminalExpertBudget(tmp_path/'experts'))
    operations = reopened.status()['operations']
    assert operations['stt']['attempts'] == 4 and operations['stt']['pending_usage'] == 3
    assert operations['tts']['attempts'] == 14 and operations['tts']['pending_usage'] == 13
    assert operations['tts']['characters_reserved'] == 16800
    assert operations['tts']['estimated_usd_including_pending'] > 1
    with pytest.raises(PermissionError, match='already_reserved'):
        reopened.reserve('board', 'stt', 'stt-0', audio_seconds=180)
    key = reopened.reserve('board', 'tts', 'unclaimed', job_id='same-job')
    reopened.claim_characters(key, 1200, 'same-job')
    with pytest.raises(PermissionError, match='already_used'):
        reopened.claim_characters(key, 1200, 'same-job')
    # Single-operation transport/resource bounds are still exact.
    with pytest.raises(PermissionError, match='duration_limit'):
        reopened.reserve('board', 'stt', 'too-long', audio_seconds=181)
    with pytest.raises(ValueError, match='characters'):
        reopened.reserve('board', 'tts', 'too-large', job_id='same-job', characters=1201)


@pytest.mark.parametrize('path,key,value', [
    ('policy.json', 'expires_at', 0),
    ('policy.json', 'max_sessions', 100),
    ('policy.json', 'max_output_tokens', 4096),
    ('policy.json', 'owner_full_test', True),
    ('policy.json', 'enabled', 'true'),
    ('experts/policy.json', 'allowed_profiles', ['SOL_HIGH']),
    ('speech-policy.json', 'estimate_usd_limit', 100),
    ('speech-policy.json', 'max_stt_attempts', 100),
    ('speech-policy.json', 'allowed_client_id', 'phone'),
    ('activation.json', 'expires_at', 9999999999),
    ('activation.json', 'approved_proposal_sha256', '0'*64),
    ('owner-authorization.json', 'statement', 'Another authorization'),
])
def test_runtime_rejects_policy_activation_or_owner_record_tampering(tmp_path, path, key, value):
    voice, expert, speech = terminal_fixture(tmp_path)
    file = tmp_path/path
    data = json.loads(file.read_text())
    data[key] = value
    file.write_text(json.dumps(data))
    for read in (voice.policy, expert.policy, speech.policy):
        with pytest.raises(PermissionError, match='approval_binding'):
            read()


def test_partial_activation_or_revocation_cannot_admit_and_records_survive(tmp_path):
    voice, expert, speech = terminal_fixture(tmp_path)
    voice.reserve_session('persist', True, 'board')
    key = speech.reserve('board', 'stt', 'pending', audio_seconds=30)
    paths = ('policy.json', 'experts/policy.json', 'speech-policy.json')
    for index, relative in enumerate(paths):
        path = tmp_path/relative
        policy = json.loads(path.read_text())
        policy['enabled'] = False
        path.write_text(json.dumps(policy))
        if index < 2:
            with pytest.raises(PermissionError, match='approval_binding'):
                voice.policy()
    assert not voice.active(voice.policy())
    with pytest.raises(PermissionError):
        voice.reserve_session('revoked', True, 'board')
    with pytest.raises(PermissionError):
        speech.reserve('board', 'stt', 'revoked', audio_seconds=30)
    speech.settle(key, .017)
    assert speech.status()['operations']['stt']['pending_usage'] == 0
    with voice.connect() as db:
        assert db.execute('SELECT count(*) FROM sessions').fetchone()[0] == 1


def test_provider_output_sentinel_stays_confined_to_explicit_terminal_policy():
    policy = OwnerTerminalRealtimePolicy(authorization='fixture', allowed_client_id='board',
                                        input_transcription=True, expert_jobs_allowed=True)
    config = session_config(policy, 'fixture instructions', [])
    assert config['max_output_tokens'] == 'inf' and settings_applied(config, config)
    with pytest.raises(ValueError):
        RealtimePolicy(max_output_tokens='inf')
