"""Explicit permanent owner terminal, isolated from every finite test grant.

This profile removes application expense/count/window limits only for its exact
approved board. It retains public guest scope, provider isolation, measured
accounting, duplicate-attempt protection and the existing per-request resource
bounds. Preparing or authorizing it never mounts a profile or calls a provider.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import Field, model_validator

from .board_trial import TrialBudget, TrialRealtime, TrialSession
from .board_unified import BoardSpeechPolicy, digest
from .expert_jobs import ExpertJobs
from .expert_store import ExpertBudget, ExpertPolicy
from .realtime_budget import RealtimeBudget
from .realtime_contract import RealtimePolicy


OWNER_TERMINAL_PROFILE = 'sophia_owner_terminal'
OWNER_TERMINAL_PRESET = 'owner_terminal'
POLICY_PATHS = ('policy.json', 'experts/policy.json', 'speech-policy.json')


class OwnerTerminalRealtimePolicy(RealtimePolicy):
    owner_terminal: Literal[True] = True
    audience: Literal['owner_interactive'] = 'owner_interactive'
    owner_full_test: Literal[False] = False
    expires_at: None = None
    max_sessions: None = None
    max_responses_per_session: None = None
    max_session_seconds: None = None
    max_output_tokens: Literal['inf'] = 'inf'
    observed_token_limit: None = None

    @model_validator(mode='after')
    def exact_terminal_voice(self):
        _validate_voice(self)
        return self


class OwnerTerminalExpertPolicy(ExpertPolicy):
    owner_terminal: Literal[True] = True
    audience: Literal['owner_interactive'] = 'owner_interactive'
    owner_full_test: Literal[False] = False
    expires_at: None = None
    max_sessions: None = None
    max_responses_per_session: None = None
    max_session_seconds: None = None
    max_output_tokens: Literal['inf'] = 'inf'
    observed_token_limit: None = None
    allowed_profiles: list[Literal['ARGON_DEEP']] = Field(default_factory=lambda: ['ARGON_DEEP'],
                                                       min_length=1, max_length=1)
    # Per-call CLI/streaming resource bounds, never a daily or lifetime grant.
    job_timeout_seconds: Literal[90] = 90
    max_context_tokens: Literal[6000] = 6000
    max_result_characters: Literal[24000] = 24000

    @model_validator(mode='after')
    def bounded_expert_grant(self):
        # Override only this subclass's finite-grant validator. The generic
        # ExpertPolicy still rejects uncapped non-owner-full-test policies.
        _validate_voice(self)
        return self


class OwnerTerminalSpeechPolicy(BoardSpeechPolicy):
    owner_terminal: Literal[True] = True
    expires_at: None = None
    max_stt_attempts: None = None
    max_narrator_responses: None = None
    max_narrator_characters: None = None
    max_characters_per_job: None = None
    max_cue_generations: None = None
    estimate_usd_limit: None = None
    # This is a single recording's RAM/transport bound, not an allowance.
    max_stt_audio_seconds: Literal[180] = 180


def _validate_voice(policy):
    if (not policy.authorization or not policy.allowed_client_id or
            policy.model != 'gpt-realtime-2.1-mini' or
            policy.allowed_models != ['gpt-realtime-2.1-mini'] or
            policy.voice != 'marin' or not policy.input_transcription or
            not policy.expert_jobs_allowed or policy.image_generation_allowed or
            policy.image_generation_daily_limit != 0 or policy.device_settings_allowed or
            policy.owner_assistant_preferences is not None or policy.accepted_as_default):
        raise ValueError('owner_terminal_exact_public_voice_scope_required')


def owner_terminal_summary(expert_profile='ARGON_DEEP'):
    if expert_profile != 'ARGON_DEEP':
        raise PermissionError('owner_terminal_exact_expert_profile_required')
    return {
        'acceptance_preset': OWNER_TERMINAL_PRESET, 'profile': OWNER_TERMINAL_PROFILE,
        'enabled': False, 'expires_at': None, 'validity_after_approval_seconds': None,
        'realtime': {'sessions': None, 'seconds_each': None, 'responses_each': None,
                     'output_tokens_each': 'inf', 'observed_token_limit': None,
                     'model': 'gpt-realtime-2.1-mini', 'voice': 'marin', 'estimated_usd': None},
        'expert': {'jobs': None, 'profile': expert_profile, 'private_memory': False},
        'speech': {'stt_attempts': None, 'model': 'gpt-live-transcribe',
                   'narrator_responses': None, 'narrator_characters_total': None,
                   'narrator_characters_per_job': None, 'estimated_usd': None,
                   'cue_generations': None, 'existing_ready_cue_required': True,
                   'cue_model': 'gpt-realtime-2.1-mini', 'cue_voice': 'marin'},
        'operational_bounds': {'expert_job_timeout_seconds': 90,
                               'expert_context_tokens': 6000, 'expert_result_characters': 24000,
                               'stt_audio_seconds_per_request': 180,
                               'tts_characters_per_chunk': 1200,
                               'provider_model_output_limit_remains': True},
        'total_api_estimate_usd': None, 'provider_invoice_cap_guaranteed': False,
        'paid_requests_made': 0, 'automatic_paid_retries': False,
        'historical_grants_reused': False, 'usage_accounting': 'durable_measured_or_pending',
    }


def _policies(root):
    return {relative: json.loads((Path(root)/relative).read_text(encoding='utf-8'))
            for relative in POLICY_PATHS}


def _fingerprint(policies):
    return digest(json.dumps(policies, sort_keys=True, separators=(',', ':'), allow_nan=False))


def _validate_bundle(data, policies):
    voice = OwnerTerminalRealtimePolicy.model_validate(policies['policy.json'])
    expert = OwnerTerminalExpertPolicy.model_validate(policies['experts/policy.json'])
    speech = OwnerTerminalSpeechPolicy.model_validate(policies['speech-policy.json'])
    for relative, policy in zip(POLICY_PATHS, (voice, expert, speech)):
        raw = policies[relative]
        if (raw != policy.model_dump() or set(raw) != set(policy.model_dump()) or
                type(raw.get('enabled')) is not bool or raw.get('owner_terminal') is not True):
            raise PermissionError('owner_terminal_exact_policy_required')
    disabled = {relative: {**policy, 'enabled': False} for relative, policy in policies.items()}
    if (set(data) != {'schema', 'acceptance_preset', 'profile', 'device_id', 'proposal_sha256', 'summary'} or
            data.get('schema') != 'sophia-owner-terminal-proposal-v1' or
            data.get('acceptance_preset') != OWNER_TERMINAL_PRESET or
            data.get('profile') != OWNER_TERMINAL_PROFILE or
            data.get('summary') != owner_terminal_summary() or
            data.get('proposal_sha256') != _fingerprint(disabled) or
            data.get('device_id') != voice.allowed_client_id or
            voice.allowed_client_id != expert.allowed_client_id or
            voice.allowed_client_id != speech.allowed_client_id or
            speech.parent_authorization_sha256 != digest(voice.authorization) or
            speech.expert_authorization_sha256 != digest(expert.authorization)):
        raise PermissionError('owner_terminal_exact_proposal_required')
    return voice, expert, speech


def validate_owner_terminal_binding(root):
    """Read-only validation of the original policies, owner record and activation.

    All enabled flags are a common revocation switch. Changing any other byte
    that affects the canonical policy bundle requires a different fresh scope.
    """
    root = Path(root)
    try:
        data = json.loads((root/'proposal.json').read_text(encoding='utf-8'))
        policies = _policies(root)
        values = _validate_bundle(data, policies)
        if len({value.enabled for value in values}) != 1:
            raise PermissionError('owner_terminal_partial_activation')
        activation_path, approval_path = root/'activation.json', root/'owner-authorization.json'
        if values[0].enabled or activation_path.exists() or approval_path.exists():
            activation = json.loads(activation_path.read_text(encoding='utf-8'))
            approval_bytes = approval_path.read_bytes()
            approval = json.loads(approval_bytes)
            if (set(activation) != {'schema', 'approved_proposal_sha256', 'owner_authorization_sha256',
                                    'expires_at', 'paid_requests_made'} or
                    activation['schema'] != 'sophia-owner-terminal-activation-v1' or
                    activation['approved_proposal_sha256'] != data['proposal_sha256'] or
                    activation['expires_at'] is not None or type(activation['paid_requests_made']) is not int or
                    activation['paid_requests_made'] != 0 or
                    activation['owner_authorization_sha256'] != digest(approval_bytes.decode('utf-8')) or
                    set(approval) != {'schema', 'source', 'statement', 'recorded_at', 'device_id',
                                      'profile', 'approved_proposal_sha256'} or
                    approval['schema'] != 'sophia-owner-terminal-owner-authorization-v1' or
                    approval['source'] != 'owner_direct' or
                    not isinstance(approval['statement'], str) or not 1 <= len(approval['statement']) <= 8000 or
                    type(approval['recorded_at']) not in (int, float) or
                    not math.isfinite(approval['recorded_at']) or approval['recorded_at'] <= 0 or
                    approval['device_id'] != data['device_id'] or approval['profile'] != OWNER_TERMINAL_PROFILE or
                    approval['approved_proposal_sha256'] != data['proposal_sha256']):
                raise PermissionError('owner_terminal_exact_activation_required')
        return values
    except (ValueError, PermissionError, OSError, KeyError, TypeError):
        raise PermissionError('owner_terminal_exact_approval_binding_required') from None


def prepare_owner_terminal_proposal(root, board_id, *, expert_profile='ARGON_DEEP'):
    summary = owner_terminal_summary(expert_profile)
    root = Path(root)
    manifest = root/'proposal.json'
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('device_id') != board_id:
            raise PermissionError('proposal_device_mismatch')
        validate_owner_terminal_binding(root)
        return data
    if root.exists() and any(root.iterdir()):
        raise PermissionError('fresh_proposal_directory_required')
    common = {'enabled': False, 'allowed_client_id': board_id, 'input_transcription': True,
              'expert_jobs_allowed': True}
    voice = OwnerTerminalRealtimePolicy(authorization=uuid4().hex, **common)
    expert = OwnerTerminalExpertPolicy(authorization=uuid4().hex, **common)
    speech = OwnerTerminalSpeechPolicy(authorization=uuid4().hex, allowed_client_id=board_id,
        parent_authorization_sha256=digest(voice.authorization),
        expert_authorization_sha256=digest(expert.authorization))
    policies = {'policy.json': voice.model_dump(), 'experts/policy.json': expert.model_dump(),
                'speech-policy.json': speech.model_dump()}
    data = {'schema': 'sophia-owner-terminal-proposal-v1', 'acceptance_preset': OWNER_TERMINAL_PRESET,
            'profile': OWNER_TERMINAL_PROFILE, 'device_id': board_id,
            'proposal_sha256': _fingerprint(policies), 'summary': summary}
    _validate_bundle(data, policies)
    for relative, policy in policies.items():
        path = root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as stream:
            json.dump(policy, stream, ensure_ascii=False, indent=2, allow_nan=False)
    with manifest.open('x', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
    return data


def authorize_owner_terminal_proposal(root, approved_sha256, *, owner_direct, cache_root=None):
    """Local operator action using the already received explicit owner statement.

    Both authority files are exclusive-create. Partial activation fails closed
    and cannot be automatically retried. Historical scopes are never opened.
    """
    root = Path(root)
    values = validate_owner_terminal_binding(root)
    data = json.loads((root/'proposal.json').read_text(encoding='utf-8'))
    policies = _policies(root)
    if (any(value.enabled for value in values) or approved_sha256 != data['proposal_sha256'] or
            _fingerprint(policies) != approved_sha256 or
            not isinstance(owner_direct, str) or not owner_direct.strip() or len(owner_direct) > 8000 or
            (root/'activation.json').exists() or (root/'owner-authorization.json').exists()):
        raise PermissionError('owner_terminal_exact_disabled_owner_proposal_required')
    from .expert_stream import load_expert_service_cue
    if load_expert_service_cue(cache_root)['status'] != 'ready':
        raise PermissionError('owner_terminal_existing_ready_cue_required')
    approval = {'schema': 'sophia-owner-terminal-owner-authorization-v1', 'source': 'owner_direct',
                'statement': owner_direct, 'recorded_at': time.time(), 'device_id': data['device_id'],
                'profile': OWNER_TERMINAL_PROFILE, 'approved_proposal_sha256': approved_sha256}
    approval_text = json.dumps(approval, ensure_ascii=False, indent=2, allow_nan=False)
    # Binary write fixes the exact approved bytes on both Windows and POSIX;
    # platform newline conversion must not change the activation's hash.
    with (root/'owner-authorization.json').open('xb') as stream:
        stream.write(approval_text.encode('utf-8'))
    with (root/'activation.json').open('x', encoding='utf-8') as stream:
        json.dump({'schema': 'sophia-owner-terminal-activation-v1',
                   'approved_proposal_sha256': approved_sha256,
                   'owner_authorization_sha256': digest(approval_text), 'expires_at': None,
                   'paid_requests_made': 0}, stream, indent=2)
    for relative, policy in policies.items():
        path = root/relative
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({**policy, 'enabled': True}, indent=2, allow_nan=False), encoding='utf-8')
        temporary.replace(path)
    validate_owner_terminal_binding(root)
    return {'authorized': True, 'expires_at': None, 'mounted': False, 'paid_requests_made': 0,
            'profile': OWNER_TERMINAL_PROFILE, 'owner_authorization_sha256': digest(approval_text)}


class OwnerTerminalBoardBudget(TrialBudget):
    EXPERTS = True
    ESTIMATED_LIMIT = None
    RESERVATION = None
    LIMITS = (None, None, None, 'inf')

    def policy(self):
        return validate_owner_terminal_binding(self.root)[0]

    def reserve_session(self, ident, consent, client_id=None, owner_test_binding=None):
        return _reserve_terminal_session(self, ident, consent, client_id, owner_test_binding)

    def reserve_response(self, ident, policy):
        return RealtimeBudget.reserve_response(self, ident, policy)

    def board_status(self):
        from .unified_voice_budget import narrator_cost
        policy = self.policy()
        with self.connect() as db:
            count, responses = db.execute('SELECT count(*),coalesce(sum(responses),0) FROM sessions').fetchone()
            rows = [json.loads(row[0]) for row in db.execute('SELECT usage FROM usage')]
        costs = [narrator_cost({'model': policy.model, 'usage_reported': True, 'usage': row}) for row in rows]
        measured = [cost for cost in costs if cost is not None]
        return {'enabled': self.active(policy), 'owner_terminal': True, 'model': policy.model,
                'voice': policy.voice, 'expires_at': None, 'sessions_reserved': count,
                'sessions_remaining': None, 'session_seconds': None, 'responses_per_session': None,
                'output_tokens_per_response': 'inf', 'estimated_allowance_usd': None,
                'reserved_estimate_usd': None, 'response_attempts': responses,
                'usage_rows': len(rows), 'measured_usage_rows': len(measured),
                'unknown_or_pending_response_usage': max(0, responses-len(measured)),
                'reported_response_estimate_usd': sum(measured),
                'transcription_billed_separately': True, 'transcription_final_cost_confirmed': False,
                'hard_dollar_cap_guaranteed': False, 'automatic_paid_retries': False,
                'hardware_accepted': False, 'historical_grants_reused': False}


class OwnerTerminalExpertBudget(ExpertBudget):
    def policy(self):
        return validate_owner_terminal_binding(self.root.parent)[1]

    def reserve_session(self, ident, consent, client_id=None, owner_test_binding=None):
        return _reserve_terminal_session(self, ident, consent, client_id, owner_test_binding)

    def status(self):
        result = super().status()
        with self.connect() as db:
            table = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='cli_usage'").fetchone()
            rows = [json.loads(row[0]) for row in db.execute('SELECT usage FROM cli_usage')] if table else []
        result.update(owner_terminal=True, cli_usage_rows=len(rows),
                      cli_usage_unknown_or_pending=max(0, result['sessions_reserved']-sum(bool(row) for row in rows)),
                      cli_subscription_usage=True, automatic_paid_retries=False)
        return result


def _reserve_terminal_session(budget, ident, consent, client_id, owner_test_binding):
    """Same atomic attempt semantics as RealtimeBudget without finite quotas.

    Refuse historical rows with another authorization: an unlimited new scope
    cannot be installed over an earlier grant's accounting directory.
    """
    if owner_test_binding:
        raise PermissionError('board_must_not_borrow_phone_binding')
    policy = budget.policy()
    if not budget.active(policy) or consent is not True:
        raise PermissionError('realtime_budget_or_consent_required')
    if client_id != policy.allowed_client_id:
        raise PermissionError('realtime_trial_client_not_allowed')
    with budget.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM sessions WHERE authorization IS NULL OR authorization<>?',
                      (policy.authorization,)).fetchone():
            raise PermissionError('owner_terminal_fresh_accounting_scope_required')
        if db.execute('SELECT 1 FROM cancelled WHERE id=?', (budget.key(ident),)).fetchone():
            raise ValueError('realtime_session_cancelled')
        if db.execute('SELECT 1 FROM sessions WHERE id=?', (budget.key(ident),)).fetchone():
            raise ValueError('realtime_session_already_attempted')
        db.execute('INSERT INTO sessions(id,authorization,started) VALUES(?,?,?)',
                   (budget.key(ident), policy.authorization, time.time()))
    return policy


class OwnerTerminalBoardSession(TrialSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.experts = ExpertJobs(self, budget=OwnerTerminalExpertBudget(self.manager.budget.root/'experts'))


class OwnerTerminalBoardRealtime(TrialRealtime):
    budget_type = OwnerTerminalBoardBudget
    session_type = OwnerTerminalBoardSession
    public_expert_budget_type = OwnerTerminalExpertBudget
