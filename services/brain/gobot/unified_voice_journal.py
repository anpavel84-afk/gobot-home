"""Scoped views of the existing optional, encrypted diagnostic journal.

The default direct-voice view persists only bounded lifecycle/usage metadata.
The exact permanent physical-board adapter may additionally record final text
under the already separate, enabled diagnostic device opt-in. It does not turn
that opt-in on or authorize semantic memory, audio or provider request archives.
This proxy never passes the original session, turn, provider payload or tool
arguments to a durable recorder. IDs in payloads are consistently hashed.
"""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import inspect
import math
import re
from types import SimpleNamespace


PLAYBACK_SUMMARY_COUNTS = {
    'packets_sent', 'progress_receipts', 'duplicate_progress_receipts',
    'invalid_progress_receipts', 'min_decode_pending', 'max_decode_pending',
    'min_output_pending', 'max_output_pending', 'empty_software_queue_samples',
    'empty_queue_and_idle_writer_samples', 'encode_drops_observed_delta',
    'dropped_frames_observed_delta',
}
PLAYBACK_SUMMARY_GAPS = {'max_packet_send_gap_ms', 'max_progress_receipt_gap_ms'}
CAPTURE_BOUNDARY_COUNTS = {'physical_sample_floor', 'guard_samples', 'ring_end',
                           'sample_floor', 'selected_start', 'source_sample_start',
                           'source_sample_end'}
CAPTURE_BOUNDARY_STAGES = {'playback_finished', 'followup_opened', 'first_uplink'}


def capture_boundary(value):
    """Device-reported capture cursor evidence; it grants no input authority."""
    if (not isinstance(value, dict) or value.get('event') != 'capture_boundary' or
            not isinstance(value.get('stage'), str) or
            value['stage'] not in CAPTURE_BOUNDARY_STAGES):
        return None
    required = {'stream_epoch', 'ring_end', 'sample_floor', 'plan_monotonic'}
    if value['stage'] == 'playback_finished':
        required |= {'response_id', 'physical_sample_floor', 'guard_samples'}
    elif value['stage'] == 'followup_opened':
        required |= {'wake_id', 'selected_start'}
        if any(key in value for key in ('response_id', 'physical_sample_floor', 'guard_samples')):
            required |= {'response_id', 'physical_sample_floor', 'guard_samples'}
    else:
        required |= {'wake_id', 'selected_start', 'source_sample_start', 'source_sample_end'}
    if not required <= value.keys():
        return None
    result = {'event': 'capture_boundary', 'stage': value['stage']}
    for key in required:
        item = value[key]
        if key in {'stream_epoch', 'response_id', 'wake_id'}:
            if not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', item):
                return None
        elif (type(item) not in ((int, float) if key == 'plan_monotonic' else (int,)) or
              not 0 <= item <= 1e15 or not math.isfinite(item)):
            return None
        result[key] = item
    # Keep mismatched floors: detecting a capture guard violation is the point
    # of this evidence. Never convert this observation into a playback ACK.
    result.update(device_reported=True, not_acoustic_proof=True)
    return result


def playback_buffer_summary(value):
    """Untrusted device diagnostics only; never a playback or admission receipt."""
    if (not isinstance(value, dict) or value.get('event') != 'playback_buffer_summary' or
            not isinstance(value.get('response_id'), str) or
            not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', value['response_id']) or
            not isinstance(value.get('audio_role'), str) or
            value.get('audio_role') not in {'fast_answer', 'expert_answer', 'service_cue'} or
            not isinstance(value.get('reason'), str) or
            value.get('reason') not in {'finished', 'interrupted'}):
        return None
    result = {key: value[key] for key in ('event', 'response_id', 'audio_role', 'reason')}
    for key in PLAYBACK_SUMMARY_COUNTS | PLAYBACK_SUMMARY_GAPS:
        if key not in value:
            continue
        item = value[key]
        if (type(item) not in ((int,) if key in PLAYBACK_SUMMARY_COUNTS else (int, float)) or
                not 0 <= item <= 1e15 or not math.isfinite(item)):
            return None
        result[key] = item
    result.update(underrun_measurement='not_instrumented', device_reported=True,
                  not_acoustic_proof=True)
    return result


IDS = {'id', 'session_id', 'conversation_id', 'turn_id', 'job_id', 'response_id',
       'call_id', 'item_id', 'event_id', 'operation_id', 'segment_id', 'wake_id',
       'proposal_id', 'audio_id', 'stream_epoch'}
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
NUMBERS |= PLAYBACK_SUMMARY_COUNTS | PLAYBACK_SUMMARY_GAPS
NUMBERS |= CAPTURE_BOUNDARY_COUNTS
BOOLEANS = {
    'enabled', 'active', 'ready', 'input_open', 'muted', 'accepted', 'executed',
    'configuration_confirmed', 'generation_allowed', 'input_allowed', 'heard', 'incomplete',
    'truncated', 'not_acoustic_proof', 'physical_playback_pending', 'whole_response',
    'playback_complete', 'narration_complete', 'speech_cancelled', 'remember',
    'automatic_retry', 'generated', 'expert_job_preserved', 'paid_start_consumed',
    'reservation_is_invoice', 'provider_invoice', 'usage_reported', 'complete',
    'stable', 'recovered', 'lost_input_replayed', 'narrated', 'voice_deferred',
    'final', 'result_available', 'microphone', 'private_access', 'audio_available',
    'resume_pending', 'resume_capture',
    'device_reported',
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
    'underrun_measurement': {'not_instrumented'},
    'stage': CAPTURE_BOUNDARY_STAGES,
    'trigger': {'wake_word', 'touch', 'manual', 'followup', 'unknown'},
}
CODES = {
    'available', 'scope_expired', 'starts_exhausted', 'consent_required', 'unavailable',
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
    'realtime_budget_expired', 'realtime_consent_required', 'realtime_session_budget_exhausted',
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
    'input_final_transcript', 'input_audio_commit', 'tool_result',
    'pending_continuation', 'native_continuation',
    'input_transcription_failed_or_empty', 'input_transcription_timeout', 'input_wake_word_only',
    'response_acknowledgement_timeout',
    'stale_or_unknown_request',
}
EVENTS = {
    'cloud_ready', 'first_audio_packet', 'expert_job_accepted', 'cached_cue_queued',
    'cached_cue_started', 'expert_context_synced', 'pre_roll_flushed',
    'playback_started', 'playback_finished', 'speaker_sound_started', 'last_speech_sample',
    'end_of_speech', 'endpoint_decided',
    'local_endpoint_decision', 'session.update', 'session.updated', 'session.created',
    'playback_buffer_summary', 'capture_boundary',
    'input_transcript_pending', 'input_transcript_ready', 'input_transcript_rejected',
    'local_voice_stop',
    'response_correlation_rejected',
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
    'operation_admitted', 'admission_denied', 'admission_status', 'listening', 'followup',
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


INPUT_TEXT_LIMIT = 8000
OUTPUT_TEXT_LIMIT = 16000
TEXT_DEDUP_LIMIT = 256


class OwnerTerminalDiagnosticJournal(ContentFreeJournal):
    """Final-text exception for one approved physical board and existing opt-in.

    The exact adapter factory pins the budget object, authorization and device.
    Every text event rechecks the separate diagnostic device opt-in. The journal
    worker repeats its own opt-in check before DPAPI encryption/write and keeps
    the existing 1..7-day retention, bounded queue and authenticated read scope.
    Neither an expense grant nor a phone's diagnostic consent is sufficient.
    """

    def __init__(self, journal, budget, policy):
        super().__init__(journal)
        self.budget = budget
        self.board_id = policy.allowed_client_id
        self.authorization = policy.authorization
        # Native finish is authoritative once per turn. This bounded duplicate
        # window additionally suppresses repeated final-ASR/current-turn hooks;
        # it retains hashes and flags only, never transcript strings.
        self._text_events = OrderedDict()

    def _recording_enabled(self):
        try:
            policy = self.journal.owner.policy()
            return bool(policy.debug_journal_enabled and
                        self.board_id in policy.debug_journal_device_bindings and
                        self.journal.enabled(self.board_id))
        except Exception:
            return False

    def _same_scope(self, session):
        try:
            offer = session.offer
            policy = session.policy
            return bool(session.manager.budget is self.budget and
                session.source == 'device' and offer.client_kind == 'device' and
                offer.device_id == offer.client_id == session.owner_test_binding == self.board_id and
                offer.owner_test_binding is None and offer.profile_epoch is None and
                offer.confirmed_profile_epoch is None and
                offer.personalization_mode == 'guest' and offer.remember is False and
                offer.speaker_consent is False and offer.developer_acceptance is False and
                offer.consent is True and session.access.confirmed_profile_id is None and
                policy.authorization == self.authorization and
                getattr(policy, 'owner_terminal', False) is True and
                policy.allowed_client_id == self.board_id)
        except (AttributeError, TypeError):
            return False

    def session_event(self, session, engine, kind, data=None):
        final_input = kind == 'input_transcript' and isinstance(data, dict) and data.get('final') is True
        final_output = kind == 'direct_dialogue_turn' and isinstance(data, dict)
        if not (final_input or final_output):
            return super().session_event(session, engine, kind, data)
        if engine != 'B' or not self._same_scope(session) or not self._recording_enabled():
            # This also deliberately drops the private-only output hook when
            # recording is disabled; the legacy lifecycle metadata still exists.
            return super().session_event(session, engine, kind, data)
        try:
            return self._final_text(session, data, final_input)
        except Exception:
            # Diagnostics must not break voice input, playback or provider work.
            return False

    def _final_text(self, session, data, final_input):
        from .debug_journal import clean

        if final_input:
            if session.current is None:
                return False
            turn_id = session.current.id
            item_id = getattr(session.current, 'input_id', '')
            field, limit, kind = 'text', INPUT_TEXT_LIMIT, 'input_transcript'
            source = 'input_asr_hypothesis'
        else:
            # Explicit final hook, not session.current: an interrupted old turn
            # may finish after a newer turn has become current.
            turn_id, item_id = data.get('turn_id'), data.get('item_id')
            field, limit, kind = 'answer_transcript', OUTPUT_TEXT_LIMIT, 'direct_dialogue_turn'
            source = 'assistant_output_transcript'
            if (data.get('playback') not in ENUMS['playback'] or
                    type(data.get('truncated')) is not bool):
                return False
        raw = data.get(field)
        if (not isinstance(turn_id, str) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,200}', turn_id) or
                not isinstance(raw, str) or not raw[:limit].strip()):
            return False
        key = (_identifier(session.id), _identifier(turn_id), kind)
        if key[0] is None or key in self._text_events:
            return False
        # Clean only a bounded string, never arbitrary caller keys/nesting.
        text = clean(raw[:limit])
        text = re.sub(r'[\x00-\x08\x0b-\x1f\x7f]', '', text)
        safe = metadata({'turn_id': turn_id, 'item_id': item_id,
                         'response_id': data.get('response_id')})
        safe.update({field: text[:limit], 'final': True, 'content_free': False,
            'ids_hashed': True, 'diagnostic_only': True, 'untrusted_text': True,
            'text_source': source, 'text_recording_scope': 'owner_terminal_board',
            'diagnostic_text_truncated': len(raw) > limit or len(text) > limit,
            'not_acoustic_proof': True})
        if not final_input:
            safe.update(playback=data['playback'], truncated=data['truncated'])
        view = SimpleNamespace(owner_test_binding=self.board_id,
            offer=SimpleNamespace(device_id=self.board_id, client_id=self.board_id, profile_epoch=None),
            id=session.id, current=SimpleNamespace(id=turn_id))
        accepted = self.journal.session_event(view, 'B', kind, safe)
        if accepted:
            self._text_events[key] = True
            while len(self._text_events) > TEXT_DEDUP_LIMIT:
                self._text_events.popitem(last=False)
        return accepted

    def status(self, binding):
        recording = binding == self.board_id and self._recording_enabled()
        return {**self.journal.status(binding), 'content_free': not recording,
                'text_recording': recording, 'text_recording_scope': 'owner_terminal_board',
                'final_transcripts_only': True, 'raw_audio': False}


def direct_journal(original):
    """No opt-in or policy mutation; every other direct transport stays metadata-only."""
    from .debug_journal import DebugJournal
    from .owner_terminal import OwnerTerminalBoardBudget, OwnerTerminalBoardRealtime

    journal = original.journal
    if (type(original) is OwnerTerminalBoardRealtime and
            type(original.budget) is OwnerTerminalBoardBudget and
            type(journal) is DebugJournal and journal.owner is original.owner_testing):
        try:
            policy = original.budget.policy()
            if policy.enabled:
                return OwnerTerminalDiagnosticJournal(journal, original.budget, policy)
        except Exception:
            pass
    return ContentFreeJournal(journal)
