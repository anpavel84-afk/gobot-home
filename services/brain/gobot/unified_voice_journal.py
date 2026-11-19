"""Content-free view of the existing optional journal for RAM-only B_WS.

Legacy transports retain their existing diagnostic opt-in.  Direct voice may
persist only bounded lifecycle/usage metadata, even when that opt-in is on.
This proxy never passes the original session, turn, provider payload or tool
arguments to a durable recorder. IDs in payloads are consistently hashed.
"""
from __future__ import annotations

import hashlib
import inspect
import math
from types import SimpleNamespace


IDS = {'id', 'session_id', 'conversation_id', 'turn_id', 'job_id', 'response_id',
       'call_id', 'item_id', 'event_id', 'operation_id', 'segment_id', 'wake_id',
       'proposal_id', 'audio_id'}
NUMBERS = {
    'seq', 'chunk_seq', 'segment_sequence', 'transport_epoch', 'frame_id',
    'sample_start', 'sample_count', 'sample_floor', 'sample_rate', 'chunks',
    'max_audio_seconds', 'operation_timeout_seconds', 'audio_seconds', 'seconds',
    'plan_monotonic', 'wake_received_monotonic', 'first_interim_ms', 'final_ms', 'speech_end_to_final_ms',
    'max_seconds', 'jobs_remaining', 'timeout_seconds', 'limit', 'attempt',
    'characters_submitted', 'requests_started', 'reserved_estimate_usd',
    'input_tokens', 'output_tokens', 'total_tokens', 'text_tokens', 'audio_tokens',
    'image_tokens', 'cached_tokens', 'inputTokens', 'outputTokens', 'totalTokens',
    'cachedInputTokens', 'reasoningOutputTokens', 'detector_monotonic_us',
    'callback_monotonic_us', 'detector_sample', 'provider_last_speech_ms', 'provider_audio_end_ms',
    'queued', 'running', 'completed', 'codex_first_answer_delta',
    'first_speakable_chunk', 'narrator_first_audio', 'expert_context_synced',
    'result_notified', 'input_ended', 'response_created', 'answer_transcript',
    'output_buffer_started', 'client_playback', 'client_playback_stopped',
    'followup_requested', 'followup_acknowledged', 'call_created',
    'sideband_connected', 'settings_acknowledged', 'lifetime_ms',
    'captured_samples', 'buffered_samples',
}
BOOLEANS = {
    'enabled', 'active', 'ready', 'input_open', 'muted', 'accepted', 'executed',
    'configuration_confirmed', 'generation_allowed', 'heard', 'incomplete',
    'truncated', 'not_acoustic_proof', 'physical_playback_pending', 'whole_response',
    'playback_complete', 'narration_complete', 'speech_cancelled', 'remember',
    'automatic_retry', 'generated', 'expert_job_preserved', 'paid_start_consumed',
    'reservation_is_invoice', 'provider_invoice', 'usage_reported', 'complete',
    'stable', 'recovered', 'lost_input_replayed', 'narrated', 'voice_deferred',
    'final', 'result_available', 'microphone', 'private_access', 'audio_available',
    'resume_pending', 'resume_capture',
}
CONTAINERS = {'timings', 'timings_ms', 'usage', 'input_token_details',
              'output_token_details', 'cached_tokens_details', 'narrator_usage',
              'responses', 'job', 'availability'}
ENUMS = {
    'model': {'gpt-realtime-2.1-mini', 'gpt-realtime-2.1', 'gpt-live-transcribe',
              'gpt-6.1-sol', 'gpt-6-astra', 'gemini-4-argon-medium'},
    'voice': {'marin'}, 'source': {'device', 'browser'},
    'mode': {'fast', 'expert', 'followup', 'idle'},
    'input_mode': {'fast', 'expert', 'followup', 'idle'},
    'audio_role': {'fast_answer', 'expert_answer', 'service_cue'},
    'endpoint_owner': {'gateway_local', 'provider'},
    'state': {'ready', 'listening', 'speaking', 'thinking', 'blocked', 'muted',
              'disconnected', 'detached', 'queued', 'running', 'completed',
              'failed', 'cancelled', 'timed_out', 'awaiting_confirmation'},
    'status': {'ready', 'missing', 'queued', 'running', 'completed', 'failed',
               'cancelled', 'incomplete', 'finished', 'interrupted',
               'character_limit_reached', 'preparing'},
    'provider': {'openai', 'codex', 'antigravity'},
    'format': {'pcm16', 'pcm_s16le'},
    'playback': {'client_playback_reported', 'unconfirmed_or_interrupted'},
    'name': {'gobot_tool', 'expert_propose', 'expert_start', 'expert_cancel',
             'expert_status', 'expert_list_profiles', 'visual_query'},
}
CODES = {
    'closed', 'user_stop', 'client_disconnected', 'output_backpressure',
    'client_detached', 'setup_failed', 'server_shutdown', 'detached_expired',
    'finished', 'interrupted', 'no_audio', 'tts_error', 'silence', 'max_output_tokens',
    'expert_local_endpoint', 'transport_rotation_deadline',
    'replacement_unavailable', 'transport_unavailable',
    'response_cancel_not_active', 'input_audio_buffer_commit_empty',
    'input_audio_buffer_commit_too_small', 'conversation_already_has_active_response',
    'rate_limit_exceeded', 'insufficient_quota', 'invalid_api_key', 'server_error',
    'invalid_request_error', 'narrator_budget_unavailable', 'narrator_preparation_failed',
    'existing_owner_speech_admission_required', 'existing_owner_speech_context_required',
    'developer_acceptance_limit', 'developer_acceptance_expired', 'developer_estimate_limit',
    'owner_api_estimate_limit', 'owner_realtime_daily_limit', 'owner_transcription_daily_limit',
    'speech_grant_expiring', 'expert_narration_budget_denied',
    'expert_transcription_budget_unavailable', 'realtime_budget_or_consent_required',
    'realtime_budget_expired', 'realtime_session_budget_exhausted',
    'realtime_response_budget_exhausted', 'board_estimated_budget_exhausted',
    'board_policy_outside_owner_allowance', 'warm_transport_scope_changed',
    'paid_operation_expired_new_wake_required', 'profile_authorization_revoked',
    'expert_transcription_failed', 'expert_tts_failed', 'voice_maintenance_failed',
    'realtime_transport_disconnected',
    'realtime_background_failed', 'openai_tts_unavailable', 'openai_tts_incomplete',
    'expert_budget_missing_or_expired', 'expert_budget_exhausted',
    'native_experts_disabled', 'expert_quota_consent_required', 'other',
    'wake_fragment_buffer_limit', 'wake_fragment_transcription_failed',
    'wake_fragment_transcription_timeout', 'wake_fragment_overlap', 'wake_fragment_failed',
}
EVENTS = {
    'cloud_ready', 'first_audio_packet', 'expert_job_accepted', 'cached_cue_queued',
    'cached_cue_started', 'expert_context_synced', 'pre_roll_flushed',
    'playback_started', 'playback_finished', 'speaker_sound_started', 'last_speech_sample',
    'end_of_speech', 'endpoint_decided',
    'local_endpoint_decision', 'session.update', 'session.updated', 'session.created',
    'wake_fragment_pending', 'wake_fragment_rejected', 'wake_word_only_skipped',
    'wake_fragment_question_ready', 'playback_receipt_received', 'heard_context_committed',
    'response.create', 'response.created', 'response.done', 'response.cancel',
    'response.output_audio.delta', 'response.output_audio.done',
    'response.output_audio_transcript.delta', 'response.output_audio_transcript.done',
    'response.output_text.delta', 'response.output_text.done',
    'response.function_call_arguments.done', 'response.output_item.done',
    'conversation.item.create', 'conversation.item.added', 'conversation.item.created',
    'conversation.item.truncate', 'conversation.item.input_audio_transcription.completed',
    'conversation.item.input_audio_transcription.failed', 'input_audio_buffer.clear',
    'input_audio_buffer.commit', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_started', 'input_audio_buffer.speech_stopped', 'error',
}
KINDS = {
    'ready', 'closed', 'error', 'telemetry', 'provider_command', 'provider_event',
    'tool_request', 'tool_result', 'dialogue_turn', 'client_command', 'turn_complete',
    'input_transcript', 'transcript', 'answer_transcript', 'text_delta',
    'audio_start', 'audio_stop', 'audio_cancel', 'audio_segment_done', 'playback_finished',
    'expert_job', 'expert_result', 'expert_result_ready', 'expert_result_pending',
    'expert_context_pending', 'expert_blocked', 'expert_sentence', 'expert_text_delta',
    'narrator_usage', 'narration_unavailable', 'tts_status', 'tts_error',
    'stt_ready', 'stt_interim', 'stt_final', 'stt_error', 'stt_status',
    'cue_missing', 'cue_failed', 'wake_accepted', 'mode_selected',
    'operation_admitted', 'admission_denied', 'listening', 'followup',
    'input_closed', 'followup_closed', 'muted', 'stopped', 'transport_detached',
    'transport_disconnected', 'transport_rotated', 'rotation_pending', 'reconnect_pending',
    'speaking', 'thinking', 'response_created', 'response_done', 'speaker_readiness',
    'response_incomplete', 'turn_incomplete', 'generation_done',
}


def _identifier(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 200:
        return None
    return hashlib.sha256(value.encode()).hexdigest()


def metadata(value, depth=0):
    if not isinstance(value, dict) or depth > 4:
        return {}
    result = {}
    for key, item in list(value.items())[:64]:
        if key in IDS:
            if (digest := _identifier(item)) is not None:
                result[key] = digest
        elif key in NUMBERS and type(item) in (int, float) and math.isfinite(item) and 0 <= item <= 1e15:
            result[key] = item
        elif key in BOOLEANS and type(item) is bool:
            result[key] = item
        elif key in ENUMS and isinstance(item, str):
            result[key] = item if item in ENUMS[key] else 'other'
        elif key in {'code', 'error_code', 'reason'} and isinstance(item, str):
            result[key] = item if item in CODES else 'other'
        elif key in {'event_type', 'event'} and isinstance(item, str):
            result[key] = item if item in EVENTS else 'other'
        elif key in CONTAINERS:
            if isinstance(item, dict):
                result[key] = metadata(item, depth+1)
            elif key == 'responses' and isinstance(item, list):
                result[key] = [metadata(row, depth+1) for row in item[:64] if isinstance(row, dict)]
    return result


class ContentFreeJournal:
    def __init__(self, journal):
        self.journal = journal
        self.code_commit = getattr(journal, 'code_commit', None)

    def session_event(self, session, engine, kind, data=None):
        if kind not in KINDS:
            return False
        safe = metadata(data or {})
        safe['content_free'] = True
        safe['ids_hashed'] = True
        # Even the recorder's session argument contains only authorized scope
        # identifiers. It cannot accidentally inspect current.query or config.
        view = SimpleNamespace(owner_test_binding=session.owner_test_binding,
            offer=SimpleNamespace(device_id=session.offer.device_id,
                client_id=session.offer.client_id, profile_epoch=session.offer.profile_epoch),
            id=session.id, current=SimpleNamespace(id=session.current.id) if session.current else None)
        return self.journal.session_event(view, 'B', kind, safe)

    def enabled(self, binding):
        return self.journal.enabled(binding)

    def status(self, binding):
        return {**self.journal.status(binding), 'content_free': True,
                'text_recording': False, 'raw_audio': False}

    async def flush(self, *args, **kwargs):
        result = self.journal.flush(*args, **kwargs)
        return await result if inspect.isawaitable(result) else result

    async def close(self):
        # The underlying opt-in journal is shared by older transports.
        return await self.flush()
