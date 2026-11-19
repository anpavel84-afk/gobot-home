"""Explicit, disabled-by-default Sophia acceptance on existing board ledgers.

This reuses the finite B and public ExpertBudget admission types and stores
speech reservations in the SAME board usage.sqlite. Historical B, hardware A,
phone and Live grants do not authorize this separate acceptance epoch.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .board_trial import TrialBudget, TrialRealtime, TrialSession
from .expert_jobs import ExpertJobs
from .expert_store import ExpertBudget, ExpertPolicy
from .realtime_contract import RealtimePolicy


UNIFIED_EXPERT_PROFILES = ('SOL_HIGH', 'ARGON_DEEP')
UNIFIED_ACCEPTANCE_PRESETS = ('initial', 'joint_review')
ACCEPTANCE_PRESETS = {
    'initial': {'limits': (3, 60, 8, 512), 'observed_tokens': 12000, 'realtime_estimate': 1,
                'cue_generations': 1},
    'joint_review': {'limits': (3, 180, 12, 1024), 'observed_tokens': 100000,
                     'realtime_estimate': 2, 'cue_generations': 0},
}


def acceptance_preset_config(name):
    if not isinstance(name, str) or name not in ACCEPTANCE_PRESETS:
        raise PermissionError('unified_board_acceptance_preset_outside_allowance')
    return ACCEPTANCE_PRESETS[name]


def acceptance_preset_for_policy(policy):
    limits = (policy.max_sessions, policy.max_session_seconds,
              policy.max_responses_per_session, policy.max_output_tokens)
    for name, preset in ACCEPTANCE_PRESETS.items():
        if limits == preset['limits'] and policy.observed_token_limit == preset['observed_tokens']:
            return name
    raise PermissionError('unified_board_policy_outside_allowance')


class UnifiedBoardBudget(TrialBudget):
    # Exact epoch presets only; the original board/phone budget classes stay unchanged.
    EXPERTS = True

    @property
    def LIMITS(self):
        return ACCEPTANCE_PRESETS[acceptance_preset_for_policy(self.policy())]['limits']

    @property
    def ESTIMATED_LIMIT(self):
        return ACCEPTANCE_PRESETS[acceptance_preset_for_policy(self.policy())]['realtime_estimate']

    @property
    def RESERVATION(self):
        preset = ACCEPTANCE_PRESETS[acceptance_preset_for_policy(self.policy())]
        return preset['realtime_estimate']/preset['limits'][0]

    @staticmethod
    def validate_policy(p):
        acceptance_preset_for_policy(p)
        if (p.owner_full_test or p.expires_at is None or not p.allowed_client_id or
                p.voice != 'marin' or p.model != 'gpt-realtime-2.1-mini' or
                p.allowed_models != ['gpt-realtime-2.1-mini'] or not p.input_transcription or
                not p.expert_jobs_allowed or p.image_generation_allowed or p.device_settings_allowed):
            raise PermissionError('unified_board_policy_outside_allowance')
        return p

    def policy(self):
        p = self.validate_policy(super().policy())
        # A larger tuple in an old policy is not a new approval. The new preset
        # must retain its reviewed disabled-policy SHA and one activation record.
        if acceptance_preset_for_policy(p) == 'joint_review':
            _validate_joint_runtime_binding(self.root)
        return p

    def board_status(self):
        result = super().board_status()
        result['estimated_allowance_usd'] = self.ESTIMATED_LIMIT
        return result


class UnifiedPublicExpertBudget(ExpertBudget):
    @staticmethod
    def validate_policy(p):
        if (p.owner_full_test or not p.allowed_client_id or p.expires_at is None or
                (p.max_sessions, p.job_timeout_seconds, p.max_context_tokens,
                 p.max_result_characters) != (2, 90, 3000, 6000) or
                len(p.allowed_profiles) != 1 or p.allowed_profiles[0] not in UNIFIED_EXPERT_PROFILES):
            raise PermissionError('unified_board_expert_policy_outside_allowance')
        return p

    def policy(self):
        return self.validate_policy(super().policy())


class UnifiedBoardSession(TrialSession):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.experts = ExpertJobs(self, budget=UnifiedPublicExpertBudget(self.manager.budget.root/'experts'))


class UnifiedBoardRealtime(TrialRealtime):
    budget_type = UnifiedBoardBudget
    session_type = UnifiedBoardSession
    public_expert_budget_type = UnifiedPublicExpertBudget


class BoardSpeechPolicy(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    authorization: str = Field(min_length=1, max_length=200)
    allowed_client_id: str = Field(pattern=r'^[A-Za-z0-9_.:-]{1,100}$')
    parent_authorization_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    expert_authorization_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    expires_at: float = Field(default=0, ge=0, allow_inf_nan=False)
    max_stt_attempts: Literal[2] = 2
    max_stt_audio_seconds: Literal[180] = 180
    max_narrator_responses: Literal[12] = 12
    max_narrator_characters: Literal[6000] = 6000
    max_characters_per_job: Literal[3000] = 3000
    max_cue_generations: Literal[0, 1] = 1
    estimate_usd_limit: Literal[1.0] = 1.0
    model: Literal['gpt-realtime-2.1-mini'] = 'gpt-realtime-2.1-mini'
    voice: Literal['marin'] = 'marin'
    stt_model: Literal['gpt-live-transcribe'] = 'gpt-live-transcribe'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class BoardSpeechLedger:
    """Atomic per-attempt accounting beside existing B sessions and usage.

    The pre-existing hardware A JSON batch counted finite attempts but had no
    concurrent measured settlement. Its two-attempt / 6000-character pattern
    is reused, while 180s STT is an explicit NEW proposal for long dictation.
    The old 26s hardware A grant remains untouched and cannot authorize this.
    """
    def __init__(self, budget, expert_budget):
        if not isinstance(budget, TrialBudget):
            raise PermissionError('board_public_expert_budget_required')
        self.budget, self.expert_budget = budget, expert_budget
        self.root, self.path = budget.root, budget.path
        self.policy_path = self.root/'speech-policy.json'
        with self.connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS unified_speech_attempts(
                id TEXT PRIMARY KEY, authorization TEXT NOT NULL, kind TEXT NOT NULL,
                cost REAL NOT NULL, pending INTEGER NOT NULL, characters INTEGER NOT NULL,
                job TEXT, audio_seconds REAL NOT NULL, created REAL NOT NULL)''')

    def connect(self):
        return self.budget.connect()

    def policy(self):
        if not self.policy_path.exists():
            raise PermissionError('board_speech_grant_required')
        return BoardSpeechPolicy.model_validate_json(self.policy_path.read_text(encoding='utf-8'))

    def require(self, binding):
        p, voice, expert = self.policy(), self.budget.policy(), self.expert_budget.policy()
        if (not p.enabled or not p.authorization or p.expires_at <= time.time() or
                not self.budget.active(voice) or not self.expert_budget.active(expert) or
                binding != p.allowed_client_id or binding != voice.allowed_client_id or
                binding != expert.allowed_client_id or voice.owner_full_test or expert.owner_full_test or
                digest(voice.authorization) != p.parent_authorization_sha256 or
                digest(expert.authorization) != p.expert_authorization_sha256 or
                voice.expires_at is None or expert.expires_at is None or
                p.expires_at > min(voice.expires_at, expert.expires_at)):
            raise PermissionError('board_speech_grant_inactive_or_scope_mismatch')
        return p

    def authorized(self, binding):
        try:
            self.require(binding)
            return True
        except (PermissionError, ValueError, OSError):
            return False

    def reserve(self, binding, kind, ident, *, estimate=.5, characters=0,
                job_id=None, audio_seconds=0):
        p = self.require(binding)
        if kind not in {'stt', 'tts', 'cue'} or estimate != .5:
            raise PermissionError('invalid_board_speech_operation')
        if type(characters) is not int or characters < 0 or characters > 1200:
            raise ValueError('invalid_board_speech_characters')
        if kind == 'stt' and (type(audio_seconds) is not int or not 1 <= audio_seconds <= p.max_stt_audio_seconds):
            raise PermissionError('board_stt_duration_limit')
        if (kind == 'stt' and (characters or job_id) or
                kind != 'stt' and audio_seconds or
                kind == 'tts' and (not isinstance(job_id, str) or not 1 <= len(job_id) <= 128)):
            raise PermissionError('invalid_board_speech_operation')
        if kind == 'cue':
            from .expert_stream import EXPERT_CUE_ID, EXPERT_CUE_TEXT
            if ident != EXPERT_CUE_ID or characters != len(EXPERT_CUE_TEXT) or job_id:
                raise PermissionError('exact_expert_service_cue_required')
        key = digest('unified-speech:'+p.authorization+':'+kind+':'+ident)
        grant = digest(p.authorization)
        job = digest(job_id) if job_id else None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM unified_speech_attempts WHERE authorization<>?', (grant,)).fetchone():
                raise PermissionError('board_speech_grant_identity_changed')
            if db.execute('SELECT 1 FROM unified_speech_attempts WHERE id=?', (key,)).fetchone():
                raise PermissionError('board_speech_attempt_already_reserved')
            count = db.execute('SELECT count(*) FROM unified_speech_attempts WHERE kind=?', (kind,)).fetchone()[0]
            cap = {'stt': p.max_stt_attempts, 'tts': p.max_narrator_responses, 'cue': p.max_cue_generations}[kind]
            if count >= cap:
                raise PermissionError('board_'+kind+'_attempts_exhausted')
            spent = db.execute('SELECT coalesce(sum(cost),0) FROM unified_speech_attempts').fetchone()[0]
            if spent+estimate > p.estimate_usd_limit+1e-9:
                raise PermissionError('board_speech_estimate_limit')
            if kind == 'tts':
                self._characters(db, p, job, characters)
            db.execute('INSERT INTO unified_speech_attempts VALUES(?,?,?,?,?,?,?,?,?)',
                (key, grant, kind, estimate, 1, characters, job, audio_seconds, time.time()))
        return key

    @staticmethod
    def _characters(db, policy, job, characters):
        total = db.execute("SELECT coalesce(sum(characters),0) FROM unified_speech_attempts WHERE kind='tts'").fetchone()[0]
        per_job = db.execute("SELECT coalesce(sum(characters),0) FROM unified_speech_attempts WHERE kind='tts' AND job=?", (job,)).fetchone()[0]
        if (not job or total+characters > policy.max_narrator_characters or
                per_job+characters > policy.max_characters_per_job):
            raise PermissionError('board_narrator_character_limit')

    def claim_characters(self, key, characters, job_id):
        p = self.require(self.policy().allowed_client_id)
        if type(characters) is not int or not 1 <= characters <= 1200:
            raise ValueError('invalid_board_speech_characters')
        job = digest(job_id)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT kind,characters,job FROM unified_speech_attempts WHERE id=?', (key,)).fetchone()
            if row != ('tts', 0, job):
                raise PermissionError('board_speech_reservation_already_used')
            self._characters(db, p, job, characters)
            db.execute('UPDATE unified_speech_attempts SET characters=? WHERE id=?', (characters, key))

    def settle(self, key, cost):
        if type(cost) not in (int, float) or not math.isfinite(cost) or cost < 0:
            raise ValueError('invalid_estimated_cost')
        with self.connect() as db:
            db.execute('UPDATE unified_speech_attempts SET cost=?,pending=0 WHERE id=? AND pending=1', (cost, key))

    def status(self):
        with self.connect() as db:
            rows = db.execute('SELECT kind,count(*),coalesce(sum(cost),0),sum(pending),sum(characters) FROM unified_speech_attempts GROUP BY kind').fetchall()
        return {'operations': {row[0]: {'attempts': row[1], 'estimated_usd_including_pending': row[2],
                    'pending_usage': row[3], 'characters_reserved': row[4]} for row in rows},
                'provider_invoice': False, 'historical_grants_reused': False}


def epoch_root(run_root, epoch):
    if not isinstance(epoch, str) or not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,63}', epoch):
        raise ValueError('invalid_sophia_grant_epoch')
    return Path(run_root)/'voice-sophia-acceptance'/epoch


def proposal_summary(expert_profile='SOL_HIGH', *, acceptance_preset='initial'):
    from .expert_stream import EXPERT_CUE_TEXT
    preset = acceptance_preset_config(acceptance_preset)
    if expert_profile not in UNIFIED_EXPERT_PROFILES:
        raise PermissionError('unified_board_expert_profile_outside_allowance')
    if acceptance_preset == 'joint_review' and expert_profile != 'ARGON_DEEP':
        raise PermissionError('joint_review_requires_argon_profile')
    sessions, seconds, responses, tokens = preset['limits']
    result = {'enabled': False, 'expires_at': 0, 'validity_after_approval_seconds': 7200,
        'realtime': {'sessions': sessions, 'seconds_each': seconds, 'responses_each': responses,
                     'output_tokens_each': tokens, 'model': 'gpt-realtime-2.1-mini',
                     'estimated_usd': preset['realtime_estimate']},
        'expert': {'jobs': 2, 'profile': expert_profile, 'seconds_each': 90,
                   'context_tokens': 3000, 'result_characters': 6000, 'private_memory': False},
        'speech': {'stt_attempts': 2, 'stt_seconds_each': 180, 'model': 'gpt-live-transcribe',
                   'narrator_responses': 12, 'narrator_characters_total': 6000,
                   'narrator_characters_per_job': 3000, 'estimated_usd': 1,
                   'cue_generations': preset['cue_generations'], 'cue_text': EXPERT_CUE_TEXT,
                   'cue_model': 'gpt-realtime-2.1-mini', 'cue_voice': 'marin',
                   'cue_characters': len(EXPERT_CUE_TEXT)},
        'total_api_estimate_usd': preset['realtime_estimate']+1, 'provider_invoice_cap_guaranteed': False,
        'paid_requests_made': 0, 'automatic_paid_retries': False}
    if acceptance_preset == 'joint_review':
        result['acceptance_preset'] = acceptance_preset
        result['realtime']['observed_token_limit'] = preset['observed_tokens']
        result['speech']['existing_ready_cue_required'] = True
    return result


def prepare_proposal(root, board_id, *, expert_profile='SOL_HIGH', acceptance_preset='initial'):
    summary = proposal_summary(expert_profile, acceptance_preset=acceptance_preset)
    preset = acceptance_preset_config(acceptance_preset)
    root = Path(root)
    manifest = root/'proposal.json'
    if manifest.exists():
        data = json.loads(manifest.read_text(encoding='utf-8'))
        if data.get('device_id') != board_id:
            raise PermissionError('proposal_device_mismatch')
        if data.get('acceptance_preset', 'initial') != acceptance_preset:
            raise PermissionError('proposal_acceptance_preset_mismatch_new_epoch_required')
        if data.get('summary', {}).get('expert', {}).get('profile') != expert_profile:
            raise PermissionError('proposal_expert_profile_mismatch_new_epoch_required')
        expert = UnifiedPublicExpertBudget.validate_policy(ExpertPolicy.model_validate_json(
            (root/'experts/policy.json').read_text(encoding='utf-8')))
        if expert.allowed_profiles != [expert_profile]:
            raise PermissionError('proposal_expert_profile_mismatch_new_epoch_required')
        if acceptance_preset == 'joint_review':
            _validate_joint_runtime_binding(root)
        return data
    if root.exists() and any(root.iterdir()):
        raise PermissionError('fresh_proposal_directory_required')
    sessions, seconds, responses, tokens = preset['limits']
    voice = RealtimePolicy(enabled=False, authorization=uuid4().hex, expires_at=0,
        audience='owner_interactive', allowed_client_id=board_id,
        max_sessions=sessions, max_session_seconds=seconds, max_responses_per_session=responses,
        max_output_tokens=tokens, observed_token_limit=preset['observed_tokens'],
        input_transcription=True, voice='marin', expert_jobs_allowed=True)
    expert = ExpertPolicy(enabled=False, authorization=uuid4().hex, expires_at=0,
        audience='owner_interactive', allowed_client_id=board_id,
        max_sessions=2, allowed_profiles=[expert_profile], job_timeout_seconds=90,
        max_context_tokens=3000, max_result_characters=6000)
    speech = BoardSpeechPolicy(authorization=uuid4().hex, allowed_client_id=board_id,
        parent_authorization_sha256=digest(voice.authorization),
        expert_authorization_sha256=digest(expert.authorization),
        max_cue_generations=preset['cue_generations'])
    policies = {'policy.json': voice.model_dump(), 'experts/policy.json': expert.model_dump(),
                'speech-policy.json': speech.model_dump()}
    fingerprint = digest(json.dumps(policies, sort_keys=True, separators=(',', ':')))
    data = {'schema': 'sophia-unified-finite-proposal-v1', 'device_id': board_id,
            'proposal_sha256': fingerprint, 'summary': summary}
    if acceptance_preset == 'joint_review':
        data['acceptance_preset'] = acceptance_preset
    for relative, policy in policies.items():
        path = root/relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('x', encoding='utf-8') as out:
            json.dump(policy, out, indent=2)
    with manifest.open('x', encoding='utf-8') as out:
        json.dump(data, out, ensure_ascii=False, indent=2)
    return data


def _validate_proposal_bundle(data, policies):
    """Validate either exact reviewed scope without changing its serialized hash."""
    voice = UnifiedBoardBudget.validate_policy(RealtimePolicy.model_validate(policies['policy.json']))
    expert = UnifiedPublicExpertBudget.validate_policy(ExpertPolicy.model_validate(policies['experts/policy.json']))
    speech = BoardSpeechPolicy.model_validate(policies['speech-policy.json'])
    preset_name = data.get('acceptance_preset', 'initial')
    preset = acceptance_preset_config(preset_name)
    # Preserve v1's exact JSON fingerprint: RealtimePolicy serializes the
    # explicitly provided zero as 0.0; BoardSpeechPolicy's default is integer 0.
    disabled = {path: policy if not policy['enabled'] and policy['expires_at'] == 0 else
                {**policy, 'enabled': False, 'expires_at': 0 if path == 'speech-policy.json' else 0.0}
                for path, policy in policies.items()}
    fingerprint = digest(json.dumps(disabled, sort_keys=True, separators=(',', ':')))
    if (data.get('schema') != 'sophia-unified-finite-proposal-v1' or
            acceptance_preset_for_policy(voice) != preset_name or
            data.get('summary') != proposal_summary(expert.allowed_profiles[0], acceptance_preset=preset_name) or
            data.get('proposal_sha256') != fingerprint or
            speech.max_cue_generations != preset['cue_generations'] or
            data.get('device_id') != voice.allowed_client_id or
            voice.allowed_client_id != expert.allowed_client_id or
            voice.allowed_client_id != speech.allowed_client_id or
            speech.parent_authorization_sha256 != digest(voice.authorization) or
            speech.expert_authorization_sha256 != digest(expert.authorization)):
        raise PermissionError('exact_disabled_owner_proposal_required')
    return voice, expert, speech


def _validate_joint_runtime_binding(root):
    """A new larger policy cannot borrow the old epoch's approval or accounting."""
    root = Path(root)
    try:
        data = json.loads((root/'proposal.json').read_text(encoding='utf-8'))
        if data.get('acceptance_preset') != 'joint_review':
            raise PermissionError('joint_review_proposal_required')
        policies = {path: json.loads((root/path).read_text(encoding='utf-8'))
                    for path in ('policy.json', 'experts/policy.json', 'speech-policy.json')}
        _validate_proposal_bundle(data, policies)
        if any(policy['enabled'] or policy['expires_at'] != 0 for policy in policies.values()):
            activation = json.loads((root/'activation.json').read_text(encoding='utf-8'))
            if (activation.get('approved_proposal_sha256') != data['proposal_sha256'] or
                    type(activation.get('expires_at')) not in (int, float) or
                    any(policy['expires_at'] != activation['expires_at'] for policy in policies.values())):
                raise PermissionError('joint_review_activation_mismatch')
    except (PermissionError, ValueError, OSError, KeyError, TypeError):
        raise PermissionError('joint_review_exact_proposal_binding_required') from None


def authorize_proposal(root, approved_sha256, *, cache_root=None):
    """Explicit operator action ONLY after the owner approves this exact proposal.

    Does not mount the profile, restart services, or open any provider. An
    activation record is created first and permanently prevents renewal/retry.
    """
    root = Path(root)
    data = json.loads((root/'proposal.json').read_text(encoding='utf-8'))
    policies = {path: json.loads((root/path).read_text(encoding='utf-8'))
                for path in ('policy.json', 'experts/policy.json', 'speech-policy.json')}
    fingerprint = digest(json.dumps(policies, sort_keys=True, separators=(',', ':')))
    try:
        _validate_proposal_bundle(data, policies)
    except (PermissionError, ValueError, KeyError, TypeError):
        raise PermissionError('exact_disabled_owner_proposal_required') from None
    if (approved_sha256 != data['proposal_sha256'] or fingerprint != approved_sha256 or
            any(p['enabled'] or p['expires_at'] != 0 for p in policies.values())):
        raise PermissionError('exact_disabled_owner_proposal_required')
    if data.get('acceptance_preset') == 'joint_review':
        from .expert_stream import load_expert_service_cue
        if load_expert_service_cue(cache_root)['status'] != 'ready':
            raise PermissionError('joint_review_existing_ready_cue_required')
    expires = time.time()+7200
    with (root/'activation.json').open('x', encoding='utf-8') as out:
        json.dump({'approved_proposal_sha256': approved_sha256, 'expires_at': expires,
                   'paid_requests_made': 0}, out, indent=2)
    for relative, policy in policies.items():
        path = root/relative
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps({**policy, 'enabled': True, 'expires_at': expires}, indent=2), encoding='utf-8')
        temporary.replace(path)
    return {'authorized': True, 'expires_at': expires, 'mounted': False, 'paid_requests_made': 0}


async def create_service_cue(root, *, cache_root=None, speech=None):
    """One explicit cache build; runtime lookup never calls this function."""
    from .audio import Speech
    from .expert_stream import expert_service_cache, load_expert_service_cue, EXPERT_CUE_ID, EXPERT_CUE_TEXT
    from .unified_voice_budget import narrator_cost, _settle
    current = load_expert_service_cue(cache_root)
    if current['status'] == 'ready':
        return {'cached': True, 'paid_requests_made': 0, 'sha256': current['sha256']}
    voice = UnifiedBoardBudget(root)
    ledger = BoardSpeechLedger(voice, UnifiedPublicExpertBudget(Path(root)/'experts'))
    key = ledger.reserve(voice.policy().allowed_client_id, 'cue', EXPERT_CUE_ID,
                         characters=len(EXPERT_CUE_TEXT))
    chunks, size = [], 0
    async with (speech or Speech()).turn() as turn:
        async for pcm, rate in turn.synthesize(EXPERT_CUE_TEXT, 'openai', 'marin', paid_consent=True):
            size += len(pcm)
            if rate != 24000 or size > 480000:
                raise ValueError('expert_cue_audio_limit')
            chunks.append(pcm)
        records = list(turn.usage_records)
        if turn.requests_started == 1 and len(records) == 1 and (cost := narrator_cost(records[0])) is not None:
            await _settle(ledger, key, 'cue', 'provider_response_usage_x_existing_rates',
                          {'model': 'gpt-realtime-2.1-mini', 'provider_invoice': False,
                           'requests_started': 1}, cost)
    if not chunks or turn.requests_started != 1:
        raise ValueError('exact_single_expert_cue_response_required')
    expert_service_cache(cache_root).put('marin', EXPERT_CUE_ID, b''.join(chunks), 24000, EXPERT_CUE_TEXT)
    result = load_expert_service_cue(cache_root)
    if result['status'] != 'ready':
        raise ValueError('expert_cue_cache_validation_failed')
    return {'cached': True, 'paid_requests_made': 1, 'sha256': result['sha256']}
