"""Owner boundary for the existing loopback application behind Tailscale Serve.

Serve strips caller-supplied identity headers and inserts the authenticated
tailnet login. The web server MUST stay loopback-only with proxy_headers=False.
Local access is the explicitly enabled signed-in PLAN owner's interface; a
browser guest cookie is deliberately irrelevant here. No provider secret is
used as an administrator credential or returned to the browser.
"""
from email.header import decode_header
import hashlib
import hmac
import ipaddress
import json
import math
from pathlib import Path
import re

from fastapi import HTTPException


TAILNET_HOST = 'plan.tailffc57c.ts.net'
LOCAL_HOSTS = {'127.0.0.1:18811', 'localhost:18811'}
ADMIN_HEADERS = {
    'Cache-Control': 'no-store, private',
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Frame-Options': 'SAMEORIGIN',
    'Content-Security-Policy': (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
    ),
}


ARCHIVE_ERROR_CODES = frozenset({
    'archive_unavailable', 'archive_policy_fields', 'archive_policy_boolean',
    'archive_retention_range', 'archive_timezone_invalid', 'archive_binding_invalid',
    'archive_revision_conflict', 'archive_operation_conflict',
    'archive_operation_id_required', 'archive_owner_required', 'archive_context_changed',
    'archive_disabled', 'archive_clear_confirmation_required',
    'archive_exact_device_required', 'archive_change_requires_idle',
    'invalid_archive_control', 'archive_record_failed', 'archive_lookup_failed',
    'archive_context_reset_required',
    'archive_binding_unavailable', 'archive_write_queue_full', 'archive_source_context_changed',
    'archive_write_timeout', 'archive_write_unavailable',
})


def safe_archive_status(value):
    """Owner-facing counts/settings only; never archive text or scope keys."""
    value = value if isinstance(value, dict) else {}
    result = {}
    for key in ('available', 'read_effective', 'lookup_blocked_by_skill'):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    if value.get('private_archive') is False:
        result['private_archive'] = False
    if value.get('historical_import') is False:
        result['historical_import'] = False
    for key in ('revision', 'generation'):
        if type(value.get(key)) is int and 0 <= value[key] <= 2**53-1:
            result[key] = value[key]
    try:
        from .native_archive import validate_policy
        result['policy'] = validate_policy(value.get('policy'))
    except (ValueError, TypeError):
        result['policy'] = {}
    result['counts'] = {key: number for key in ('turns', 'messages', 'topics', 'blocks', 'backlog')
                        if type(number := (value.get('counts') or {}).get(key)) is int
                        and 0 <= number <= 2**53-1} if isinstance(value.get('counts'), dict) else {}
    for key in ('oldest_at', 'newest_at', 'last_write_at'):
        number = value.get(key)
        if number is None:
            result[key] = None
        elif type(number) in (int, float) and 0 <= number <= 1e12 and math.isfinite(number):
            result[key] = number
    for key, allowed in (
        ('storage', {'sqlite_plaintext_windows_acl'}),
        ('coverage', {'since_enabled'}),
        ('scope', {'device_archive'}),
    ):
        if isinstance(value.get(key), str) and value[key] in allowed:
            result[key] = value[key]
    error = value.get('last_error')
    result['last_error'] = error if error is None or isinstance(error, str) and error in ARCHIVE_ERROR_CODES else 'archive_unavailable'
    if 'operation' in value:
        operation = value['operation']
        result['operation'] = None
        if (isinstance(operation, dict)
                and isinstance(operation.get('id'), str)
                and re.fullmatch(r'[A-Za-z0-9_-]{16,80}', operation['id'])
                and type(operation.get('applied_revision')) is int
                and 0 < operation['applied_revision'] <= result.get('revision', -1)
                and type(operation.get('replayed')) is bool):
            result['operation'] = {key: operation[key] for key in ('id', 'applied_revision', 'replayed')}
    return result


def owner_boundary(root):
    """Return a request check with a stable, non-secret pseudonymous actor."""
    config_path = Path(root)/'data/sophia-admin-owner.json'

    def authenticate(request, write=False):
        try:
            local = ipaddress.ip_address(request.client.host).is_loopback
        except (ValueError, AttributeError):
            local = False
        host = request.headers.get('host')
        origin = request.headers.get('origin')
        expected_origin = ('https://'+TAILNET_HOST if host == TAILNET_HOST
                           else 'http://'+host if host in LOCAL_HOSTS else None)
        if (not local or expected_origin is None
                or len(request.headers.getlist('host')) != 1
                or len(request.headers.getlist('origin')) > 1
                or request.headers.get('sec-fetch-site') == 'cross-site'
                or (origin != expected_origin if write else origin not in {None, expected_origin})):
            raise HTTPException(403, 'sophia_admin_private_owner_only')
        try:
            if (config_path.is_symlink() or config_path.parent.is_symlink()
                    or not config_path.is_file() or config_path.stat().st_size > 4096):
                raise ValueError()
            config = json.loads(config_path.read_text(encoding='utf-8'))
            if (not isinstance(config, dict)
                    or set(config) != {'version', 'owner_login_sha256', 'local_owner_enabled'}
                    or type(config['version']) is not int or config['version'] != 1
                    or type(config['local_owner_enabled']) is not bool
                    or not isinstance(config['owner_login_sha256'], str)
                    or not re.fullmatch(r'[a-f0-9]{64}', config['owner_login_sha256'])):
                raise ValueError()
        except (OSError, ValueError, TypeError, KeyError):
            raise HTTPException(503, 'sophia_admin_owner_binding_unavailable') from None
        owner = config['owner_login_sha256']
        if host in LOCAL_HOSTS:
            # A proxied request cannot take the local-owner branch merely by
            # adding an identity header or a Forwarded/X-Forwarded-Host value.
            if (not config['local_owner_enabled'] or any(
                    key.lower().startswith(('tailscale-', 'x-forwarded-')) or key.lower() == 'forwarded'
                    for key in request.headers)):
                raise HTTPException(403, 'sophia_admin_private_owner_only')
        else:
            identities = request.headers.getlist('tailscale-user-login')
            try:
                if len(identities) != 1 or len(identities[0]) > 512:
                    raise ValueError()
                login = ''.join(part.decode(charset or 'ascii') if isinstance(part, bytes) else part
                                for part, charset in decode_header(identities[0]))
                if not login or any(ord(char) < 32 for char in login):
                    raise ValueError()
                matched = hmac.compare_digest(hashlib.sha256(login.encode('utf-8')).hexdigest(), owner)
            except (ValueError, UnicodeError, LookupError):
                matched = False
            if not matched:
                raise HTTPException(403, 'sophia_admin_owner_required')
        return 'owner:'+owner

    return authenticate


def safe_runtime_status(payload, *, observed_at, gateway_observed_at):
    """Only product status and accounting aggregates; never session identifiers."""
    def fields(value, names):
        if not isinstance(value, dict):
            return {}
        return {key: item for key, item in value.items() if key in names and (
            item is None or type(item) is bool or type(item) is int
            or type(item) is float and math.isfinite(item)
            or isinstance(item, str) and len(item) <= 160)}

    brain = payload.get('brain', {})
    status = brain.get('status', {})
    budget = fields(status.get('budget'), {
        'enabled', 'owner_terminal', 'model', 'voice', 'expires_at', 'sessions_reserved',
        'sessions_remaining', 'session_seconds', 'responses_per_session', 'output_tokens_per_response',
        'response_attempts', 'usage_rows', 'measured_usage_rows', 'unknown_or_pending_response_usage',
        'reported_response_estimate_usd', 'transcription_billed_separately',
        'transcription_final_cost_confirmed', 'hard_dollar_cap_guaranteed', 'automatic_paid_retries',
    })
    sessions = []
    for session in brain.get('sessions', [])[:4]:
        item = fields(session, {'ready', 'state', 'input_mode', 'muted', 'capture_connected',
                               'generation_allowed', 'expert_active'})
        item['selected_expert'] = fields(session.get('selected_expert'),
                                         {'profile', 'provider', 'model', 'effort', 'requested_label'})
        item['lifecycle'] = fields(session.get('lifecycle'), {
            'attached', 'closing', 'transport_age_seconds', 'reader_running', 'maintenance_running',
            'last_transport_failure', 'reconnect_attempts', 'home_context_status',
            'home_context_revision', 'home_context_applied_at', 'home_context_error',
        })
        item['lifecycle']['home_context'] = fields(session.get('lifecycle', {}).get('home_context'), {
            'state', 'desired_revision', 'applied_revision', 'applied_at', 'checked_at',
            'applied_transport_epoch', 'reason',
        })
        item['lifecycle']['conversation_settings'] = fields(
            session.get('lifecycle', {}).get('conversation_settings'), {
                'state', 'settings_revision', 'applied_settings_revision', 'desired_revision',
                'applied_revision', 'applied_at', 'checked_at', 'reason',
            })
        item['lifecycle']['timers'] = fields(session.get('lifecycle', {}).get('timers'), {
            'display','signal','display_supported','signal_supported','capabilities_received',
            'snapshot_revision','display_state','pending_claims','output_active','checked_at','error',
        })
        archive = session.get('lifecycle', {}).get('native_archive')
        if isinstance(archive, dict):
            item['lifecycle']['native_archive'] = safe_archive_status(archive)
        capabilities = session.get('capabilities')
        if isinstance(capabilities, dict):
            public = fields(capabilities, {'version', 'settings_revision', 'revision'})
            public['capabilities'] = {}
            rows = capabilities.get('capabilities', {})
            if isinstance(rows, dict):
                for name in ('clock','timer','weather','utilities','memory','expert','visual','tv','shell','files'):
                    row = rows.get(name)
                    if not isinstance(row, dict):continue
                    safe = fields(row, {'enabled','implemented','state','reason','tool','display','signal'})
                    if isinstance(row.get('actions'), list):
                        safe['actions'] = [action for action in row['actions'][:8]
                            if isinstance(action, str) and re.fullmatch('[a-z_]{1,40}', action)]
                    public['capabilities'][name] = safe
            item['capabilities'] = public
        sessions.append(item)
    device = fields(payload.get('device'), {
        'protocol', 'mode', 'voice', 'wake_location', 'pcm_stage', 'cloud_ready', 'generation_allowed',
        'input_open', 'voice_phase', 'last_error', 'wake_events', 'playback_started', 'playback_finished',
        'last_wake_lvgl_refresh_ready_ms', 'wake_ui_measurement', 'device_protocol_confirmed',
    })
    device['device_resources'] = fields(payload.get('device', {}).get('device_resources'), {
        'encode_pending', 'send_pending', 'decode_pending', 'output_pending', 'encode_drops',
        'aec_ready', 'interrupt_pending', 'barge_wakes', 'barge_taps', 'underrun_measurement',
        'host_wake_mode', 'wake_barge_frames', 'wake_barge_gaps', 'wake_barge_resets',
        'wake_barge_detections', 'wake_barge_accepted', 'aec_clean_zero_frames', 'aec_level_frame',
        'wake_barge_process_max_us', 'wake_barge_processing_overrun_frames',
        'barge_duck_started', 'barge_duck_restored', 'barge_duck_active',
        'aec_mic_avg_abs', 'aec_ref_avg_abs', 'aec_clean_avg_abs',
        'aec_mic_peak', 'aec_ref_peak', 'aec_clean_peak',
    })
    device['timer_output'] = fields(payload.get('device', {}).get('timer_output'), {
        'display_supported','signal_supported','display','signal','invalid_events','stale_events',
        'queued','active','receipts_dropped','alarm_last_state','delivery_state','delay_reason',
        'postponed_count','started_count','finished_count','cancelled_count','suppressed_count',
        'unknown_count','last_outcome_reason',
    })
    age = (round(max(0, observed_at-gateway_observed_at), 2)
           if gateway_observed_at is not None and -1 <= observed_at-gateway_observed_at else None)
    fresh = age is not None and age < 15
    return {
        'observed_at': observed_at, 'source': 'existing_brain_and_spotpear_gateway',
        'gateway_observed_at': gateway_observed_at, 'gateway_age_seconds': age, 'gateway_fresh': fresh,
        'status': ('connected' if payload.get('status') == 'connected' and fresh
                   else 'stale' if payload.get('status') == 'connected' else payload.get('status', 'unavailable')),
        'configured': payload.get('configured') is True,
        'wake_baseline': payload.get('wake_baseline'),
        'brain': {'status': {**fields(status, {'engine', 'transport', 'model', 'voice', 'active_sessions',
                    'ready_transports', 'active_inputs', 'provider_verified', 'hardware_accepted'}), 'budget': budget},
                  'sessions': sessions,
                  'admission': fields(brain.get('admission'), {'allowed', 'generation_allowed', 'code',
                      'expert_available', 'model', 'voice', 'private_memory_allowed', 'requires_explicit_activation'})},
        'device': device,
    }
