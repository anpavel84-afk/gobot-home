"""Admission and measured accounting for unified expert speech.

The existing OwnerTesting ledger is the authority.  A board grant is never
translated into a phone grant, and opening an empty socket never calls this
module.  The .50 USD provisional hold and web_stt/web_tts origins are the
established hybrid_api admissions.  Each narrator Response gets its own hold
and existing realtime counter; it is not an unlimited answer-wide allowance.
"""
from __future__ import annotations

import asyncio
import json
import math
import time
from uuid import uuid4

from .audio import TTS_MODEL
from .processes import AgentError
from .realtime_budget import estimate_usd


WEB_OPERATION_RESERVE_USD = .5  # Existing hybrid_api web-STT and web-TTS hold.
LIVE_TRANSCRIBE_USD_PER_MINUTE = .017  # Existing HOST-A grant/audited STT rate.


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def narrator_cost(record):
    """Price complete modality counts; total_tokens alone is not a zero bill."""
    if (not isinstance(record, dict) or record.get('model') != TTS_MODEL or
            record.get('usage_reported') is not True):
        return None
    usage = record.get('usage')
    if not isinstance(usage, dict):
        return None
    for lane in ('input', 'output'):
        details = usage.get(lane+'_token_details')
        if not isinstance(details, dict):
            return None
        if any(not _number(details.get(k)) for k in ('text_tokens', 'audio_tokens')):
            return None
        # Image/unknown modality costs must not be silently counted as free.
        images = details.get('image_tokens', 0)
        if not _number(images) or images != 0:
            return None
        total = usage.get(lane+'_tokens')
        if total is not None and (not _number(total) or total != details['text_tokens']+details['audio_tokens']):
            return None
    incoming = usage['input_token_details']
    cached = incoming.get('cached_tokens_details', {})
    if not isinstance(cached, dict):
        return None
    for modality in ('text', 'audio'):
        value = cached.get(modality+'_tokens', 0)
        if not _number(value) or value > incoming[modality+'_tokens']:
            return None
    cached_count = incoming.get('cached_tokens', 0)
    if not _number(cached_count) or cached_count != sum(cached.get(k, 0) for k in ('text_tokens', 'audio_tokens')):
        return None
    cost = estimate_usd({**usage, '_model': TTS_MODEL})
    return cost if _number(cost) else None


def _record(ledger, key, operation, method, measured, cost=None):
    """Content-free evidence beside the authoritative existing attempts table."""
    with ledger.connect() as db:
        db.execute('''CREATE TABLE IF NOT EXISTS unified_voice_usage(
            attempt_id TEXT PRIMARY KEY, operation TEXT NOT NULL,
            method TEXT NOT NULL, measurement TEXT NOT NULL,
            estimated_usd REAL, updated REAL NOT NULL)''')
        db.execute('''INSERT INTO unified_voice_usage VALUES(?,?,?,?,?,?)
            ON CONFLICT(attempt_id) DO UPDATE SET method=excluded.method,
            measurement=excluded.measurement,estimated_usd=excluded.estimated_usd,
            updated=excluded.updated''',
            (key, operation, method, json.dumps(measured, allow_nan=False), cost, time.time()))


async def _settle(ledger, key, operation, method, measured, cost):
    # Record verifiable evidence before releasing the provisional hold. A crash
    # between writes conservatively retains the hold and is safe to reconcile.
    await asyncio.to_thread(_record, ledger, key, operation, method, measured, cost)
    await asyncio.to_thread(ledger.settle, key, cost)


class UnifiedVoiceBudget:
    """Pass .narrator and .transcription to DirectRealtimeManager.

    Audio limits are local resource bounds, not an extension of any money,
    developer count, grant expiry, or provider entitlement. Defaults retain the
    existing Live Transcribe bounds. An operator may explicitly configure a
    longer input within the adapter's supported 300/360 second bounds.
    """

    def __init__(self, *, max_expert_audio_seconds=60, expert_operation_timeout_seconds=100):
        if type(max_expert_audio_seconds) is not int or not 1 <= max_expert_audio_seconds <= 300:
            raise ValueError('invalid_live_stt_audio_limit')
        if (type(expert_operation_timeout_seconds) is not int or
                not max(5, max_expert_audio_seconds) <= expert_operation_timeout_seconds <= 360):
            raise ValueError('invalid_live_stt_operation_limit')
        self.max_audio_seconds = max_expert_audio_seconds
        self.operation_timeout_seconds = expert_operation_timeout_seconds

    @staticmethod
    def _authority(session):
        ledger = session.manager.owner_testing
        binding = getattr(session, 'owner_test_binding', None)
        current = session.manager.budget.policy()
        if (getattr(session, 'closed', False) or not session.offer.consent or
                not getattr(session, 'owner_test_authorized', False) or
                not binding or binding != session.offer.client_id or
                not current.owner_full_test or current.allowed_client_id != binding or
                current.authorization != session.policy.authorization or
                not session.manager.budget.active(current) or
                not ledger.authorized(binding)):
            raise PermissionError('existing_owner_speech_admission_required')
        # NativeSession.request supplies this context through the established
        # owner path. Do not synthesize it from a device ID or user JSON.
        request = session.request('Проверка допуска речи', session.id)
        origin = 'developer' if session.offer.developer_acceptance else 'owner'
        if (getattr(request, '_owner_test_budget', None) is not ledger or
                getattr(request, '_owner_test_binding', None) != binding or
                getattr(request, '_owner_test_origin', None) != origin):
            raise PermissionError('existing_owner_speech_context_required')
        return ledger, binding, origin

    async def _reserve(self, session, operation, ident):
        ledger, binding, origin = await asyncio.to_thread(self._authority, session)
        origin = 'developer' if origin == 'developer' else 'web_'+operation
        # Developer STT has a separately authorized finite allowance. Existing
        # realtime developer credits cannot substitute for a zero/expired STT
        # allowance; the ordinary owner web_stt path retains its original kind.
        kind = 'transcription' if operation == 'stt' and origin == 'developer' else 'realtime'
        key = await asyncio.to_thread(ledger.reserve, binding, kind, ident,
                                      estimate=WEB_OPERATION_RESERVE_USD, origin=origin)
        await asyncio.to_thread(_record, ledger, key, operation, 'pending_provider_usage',
                                {'reserved_estimate_usd': WEB_OPERATION_RESERVE_USD})
        return ledger, key

    async def transcription(self, session):
        await asyncio.to_thread(self._authority, session)
        policy = await asyncio.to_thread(session.manager.budget.policy)
        maximum = self.max_audio_seconds
        timeout = self.operation_timeout_seconds
        if policy.max_session_seconds is not None:
            maximum = min(maximum, policy.max_session_seconds)
        if policy.expires_at is not None:
            remaining = int(policy.expires_at-time.time())
            # Leave a bounded completion interval before an expiring grant;
            # local resource configuration cannot extend its expiry.
            maximum = min(maximum, remaining-10)
            timeout = min(timeout, remaining)
        if maximum < 1 or timeout < 5:
            raise PermissionError('speech_grant_expiring')
        ledger, key = await self._reserve(session, 'stt', 'unified-web-stt:'+uuid4().hex)
        settled = False

        async def validate():
            await asyncio.to_thread(self._authority, session)

        async def settle(*, audio_seconds, provider_usage=None, usage_reported=False):
            nonlocal settled
            if settled:
                return
            if not _number(audio_seconds) or not 0 < audio_seconds <= maximum:
                return  # Unknown/malformed completion keeps the full hold.
            provider_usage = provider_usage if isinstance(provider_usage, dict) else {}
            durations = [provider_usage[k] for k in ('seconds', 'audio_seconds', 'input_audio_seconds')
                         if k in provider_usage and _number(provider_usage[k])]
            # A complete stable transcript plus the exact transmitted PCM count
            # is sufficient measured duration, even if the endpoint omits usage.
            # Prefer the larger valid provider duration to avoid undercounting.
            duration = max([audio_seconds, *durations]) if usage_reported else audio_seconds
            if duration > 360:
                return
            cost = duration / 60 * LIVE_TRANSCRIBE_USD_PER_MINUTE
            measured = {'model': 'gpt-live-transcribe', 'input_pcm_audio_seconds': audio_seconds,
                        'billed_duration_seconds': duration, 'provider_duration_reported': bool(durations and usage_reported),
                        'provider_invoice': False}
            await _settle(ledger, key, 'stt', 'measured_duration_x_existing_rate', measured, cost)
            settled = True

        return {'paid_consent': True, 'max_audio_seconds': maximum,
                'operation_timeout_seconds': timeout,
                'reservation_id': key, 'settle': settle, 'validate': validate}

    async def narrator(self, session, job):
        existing = getattr(session, '_narrator_reservations', {}).get(job.id)
        if existing is not None:
            return existing
        if getattr(session.manager, 'speech', None) is None:
            raise PermissionError('narrator_unavailable')
        limit = getattr(job, 'max_result_characters', 24000)
        if type(limit) is not int or not 1 <= limit <= 32000:
            raise PermissionError('expert_narration_limit_invalid')
        ledger, key = await self._reserve(session, 'tts', 'unified-web-tts:'+job.id+':0')
        admission = _NarratorAdmission(self, session, job.id, ledger, key)
        return {'paid_tts_consent': True, 'tts_character_limit': limit,
                'speech': _BudgetSpeech(session.manager.speech, admission),
                'reservation_id': key, 'settle': admission.finish}


class _NarratorAdmission:
    def __init__(self, budget, session, job_id, ledger, first_key):
        self.budget, self.session, self.job_id, self.ledger = budget, session, job_id, ledger
        self.keys = [first_key]
        self.used = 0
        self.settled = set()
        self.records = {}

    async def next(self):
        # Revocation/expiry is checked for every sentence, including the first.
        await asyncio.to_thread(self.budget._authority, self.session)
        index = self.used
        if index:
            ledger, key = await self.budget._reserve(
                self.session, 'tts', 'unified-web-tts:'+self.job_id+':'+str(index))
            if ledger is not self.ledger:
                raise PermissionError('narrator_ledger_changed')
            self.keys.append(key)
        self.used += 1
        return index

    async def measured(self, index, record):
        self.records[index] = record
        cost = narrator_cost(record)
        if cost is None or index in self.settled:
            return
        usage = record['usage']
        clean = {}
        for lane in ('input', 'output'):
            details = usage[lane+'_token_details']
            clean[lane+'_token_details'] = {key: details[key] for key in ('text_tokens', 'audio_tokens')}
            if lane == 'input':
                cached = details.get('cached_tokens_details', {})
                clean[lane+'_token_details']['cached_tokens_details'] = {
                    key: cached.get(key, 0) for key in ('text_tokens', 'audio_tokens')}
        status = record.get('status')
        measured = {'model': TTS_MODEL, 'usage': clean, 'provider_invoice': False,
                    'response_final_status': status if status in {'completed', 'failed', 'cancelled', 'incomplete'} else 'unknown'}
        await _settle(self.ledger, self.keys[index], 'tts',
                      'provider_response_usage_x_existing_rates', measured, cost)
        self.settled.add(index)

    async def finish(self, job):
        if job.id != self.job_id:
            raise PermissionError('narrator_settlement_job_mismatch')
        # The normal proxy settles each completed request immediately. The job
        # aggregate is a recovery path only when every started request is known.
        report = getattr(job, 'narrator_usage', {})
        if (not isinstance(report, dict) or report.get('complete') is not True or
                report.get('requests_started') != self.used):
            return
        rows = report.get('responses')
        if not isinstance(rows, list) or len(rows) != self.used:
            return
        ids = [row.get('response_id') for row in rows if isinstance(row, dict)]
        if len(ids) != self.used or any(not value for value in ids) or len(set(ids)) != self.used:
            return
        for index, record in enumerate(rows):
            await self.measured(index, record)


class _BudgetSpeech:
    def __init__(self, speech, admission):
        self.speech, self.admission = speech, admission

    def turn(self):
        return _BudgetSpeechTurn(self.speech.turn(), self.admission)


class _BudgetSpeechTurn:
    def __init__(self, turn, admission):
        self.turn, self.admission = turn, admission

    @property
    def requests_started(self):
        return self.turn.requests_started

    @property
    def usage_records(self):
        return self.turn.usage_records

    async def __aenter__(self):
        await self.turn.__aenter__()
        return self

    async def __aexit__(self, *args):
        return await self.turn.__aexit__(*args)

    async def prepare(self, provider, voice, *, paid_consent=False):
        if not paid_consent:
            raise AgentError('openai_tts_consent_required')
        await asyncio.to_thread(self.admission.budget._authority, self.admission.session)
        await self.turn.prepare(provider, voice, paid_consent=True)

    async def synthesize(self, text, provider, voice, *, paid_consent=False):
        if not paid_consent or provider != 'openai' or voice != 'marin':
            raise AgentError('unified_narrator_admission_required')
        try:
            index = await self.admission.next()
        except PermissionError:
            raise AgentError('expert_narration_budget_denied') from None
        before_count = self.turn.requests_started
        before_usage = len(self.turn.usage_records)
        iterator = self.turn.synthesize(text, provider, voice, paid_consent=True)
        try:
            async for item in iterator:
                yield item
        finally:
            await iterator.aclose()
            records = self.turn.usage_records[before_usage:]
            if self.turn.requests_started == before_count+1 and len(records) == 1:
                await self.admission.measured(index, records[0])
