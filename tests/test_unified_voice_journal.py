"""B_WS stays RAM-only even when the older encrypted debug opt-in is enabled."""
import asyncio
import json
from types import SimpleNamespace

from gobot.debug_journal import DebugJournal
from gobot.unified_voice_journal import ContentFreeJournal, metadata


PRIVATE = 'Личная фраза семьи: код сиреневой комнаты семьдесят один.'


def test_device_timer_visual_diagnostics_preserve_correlations_once_without_content():
    import hashlib
    from gobot.unified_voice_journal import device_observation
    source = {'type':'telemetry', 'event':'visual_delivery', 'frame_id':'frame-1',
        'visual_type':'image_card','image_count':1, 'status':'unsupported',
        'reason':'device_visual_protocol_missing', 'url':PRIVATE,'text':PRIVATE,
        'audio':PRIVATE,'accepted':False}
    safe = metadata(device_observation(source))
    assert safe['frame_id'] == hashlib.sha256(b'frame-1').hexdigest()
    assert safe['status'] == 'unsupported' and safe['image_count'] == 1
    assert safe['device_reported'] and safe['not_acoustic_proof']
    assert PRIVATE not in json.dumps(safe, ensure_ascii=False)
    assert device_observation({'type':'telemetry','event':'timer_alarm_ack'}) is None
    receipt = metadata({'receipt_type':'timer_alarm_ack','alarm_id':'alarm-1',
        'claim_id':'claim-1','state':'finished','accepted':True,'audio':PRIVATE})
    assert receipt['state'] == 'finished' and receipt['accepted']
    assert receipt['alarm_id'] == hashlib.sha256(b'alarm-1').hexdigest()
    timers=metadata({'timers':[{'timer_id':'t','deadline':100.,'state':'expired'}]*100})
    assert len(timers['timers']) == 16


def test_metadata_allowlist_drops_text_arguments_payloads_and_untrusted_error_strings():
    raw = {'response_id': 'response-1', 'job_id': 'job-1', 'state': 'completed',
           'question': PRIVATE, 'text': PRIVATE, 'task': PRIVATE, 'result': {'answer': PRIVATE},
           'arguments': {'query': PRIVATE}, 'reason': PRIVATE, 'code': PRIVATE,
           'event': {'type': 'conversation.item.create', 'item': {'input_text': PRIVATE}},
           'usage': {'input_tokens': 12, 'input_token_details': {'text_tokens': 12, 'audio_tokens': 0},
                     'transcript': PRIVATE, 'total_tokens': float('nan')},
           'job': {'task': PRIVATE, 'result': PRIVATE, 'response_id': 'response-1',
                   'speech_text': PRIVATE, 'played_text': PRIVATE,
                   'timings': {'running': 1.5, PRIVATE: 5}},
           'narrator_usage': {'requests_started': 1, 'responses': [
               {'response_id': 'response-1', 'usage': {'output_tokens': 3}, 'transcript': PRIVATE}]}}
    safe = metadata(raw)
    assert PRIVATE not in json.dumps(safe, ensure_ascii=False)
    assert safe['state'] == 'completed' and safe['usage']['input_tokens'] == 12
    assert safe['job']['timings'] == {'running': 1.5}
    assert safe['code'] == safe['reason'] == 'other'
    assert len(safe['response_id']) == 64
    assert safe['response_id'] == safe['job']['response_id']
    assert 'event' not in safe and 'total_tokens' not in safe['usage']


def test_proxy_never_passes_live_session_or_turn_content_to_recorder():
    records = []
    class Recorder:
        code_commit = 'synthetic'
        def session_event(self, session, engine, kind, data):
            assert not hasattr(session, 'config')
            assert not hasattr(session.current, 'query')
            records.append((engine, kind, data))
            return True
    original = Recorder()
    proxy = ContentFreeJournal(original)
    session = SimpleNamespace(owner_test_binding='client', id='session',
        offer=SimpleNamespace(device_id='device', client_id='client', profile_epoch=None),
        current=SimpleNamespace(id='turn', query=PRIVATE), config={'instructions': PRIVATE})
    assert proxy.session_event(session, 'B', 'dialogue_turn', {'question': PRIVATE, 'heard': True})
    assert PRIVATE not in json.dumps(records, ensure_ascii=False)
    assert session.current.query == PRIVATE  # The original RAM objects are intact.
    assert not proxy.session_event(session, 'B', 'audio_chunk', {'pcm': PRIVATE})


def test_name_fragment_diagnostics_do_not_store_question_or_held_pcm():
    safe = metadata({'event': 'wake_fragment_pending', 'captured_samples': 32000,
                     'buffered_samples': 1440, 'resume_pending': True,
                     'text': PRIVATE, 'pcm': PRIVATE, 'transcripts': {'item': PRIVATE}})
    assert safe == {'event': 'wake_fragment_pending', 'captured_samples': 32000,
                    'buffered_samples': 1440, 'resume_pending': True}
    assert metadata({'reason': 'wake_fragment_transcription_timeout'}) == {
        'reason': 'wake_fragment_transcription_timeout'}


def test_physical_receipt_and_clock_events_retain_only_fixed_numeric_metadata():
    records = []
    class Recorder:
        def session_event(self, session, engine, kind, data):
            records.append((kind, data))
            return True
    proxy = ContentFreeJournal(Recorder())
    session = SimpleNamespace(owner_test_binding='client', id='session',
        offer=SimpleNamespace(device_id='device', client_id='client', profile_epoch=None),
        current=SimpleNamespace(id='turn'))
    assert proxy.session_event(session, 'B', 'playback_finished', {
        'response_id': 'response-1', 'audio_role': 'expert_answer', 'sample_floor': 24000,
        'text': PRIVATE, 'audio': PRIVATE, 'evidence': PRIVATE})
    for event in ('speaker_sound_started', 'end_of_speech', 'endpoint_decided'):
        assert proxy.session_event(session, 'B', 'telemetry', {
            'event': event, 'response_id': 'response-1', 'plan_monotonic': 12.5,
            'provider_audio_end_ms': 1350, 'clock_domain': PRIVATE, 'text': PRIVATE})
    assert records[0][0] == 'playback_finished'
    assert records[0][1]['audio_role'] == 'expert_answer'
    assert records[0][1]['sample_floor'] == 24000
    assert [row[1]['event'] for row in records[1:]] == [
        'speaker_sound_started', 'end_of_speech', 'endpoint_decided']
    assert all(row[1]['response_id'] == records[0][1]['response_id'] for row in records[1:])
    assert all(row[1]['provider_audio_end_ms'] == 1350 for row in records[1:])
    assert all(row[1]['plan_monotonic'] == 12.5 for row in records[1:])
    assert PRIVATE not in json.dumps(records, ensure_ascii=False)
    assert metadata({'event': PRIVATE}) == {'event': 'other'}
    assert metadata({'provider_audio_end_ms': float('nan')}) == {}


def test_truncated_voice_response_retains_safe_completion_evidence_only():
    records = []
    class Recorder:
        def session_event(self, session, engine, kind, data):
            records.append((kind, data))
            return True
    proxy = ContentFreeJournal(Recorder())
    session = SimpleNamespace(owner_test_binding='client', id='session',
        offer=SimpleNamespace(device_id='device', client_id='client', profile_epoch=None),
        current=SimpleNamespace(id='turn'))
    for kind in ('response_incomplete', 'turn_incomplete'):
        assert proxy.session_event(session, 'B', kind, {
            'reason': 'max_output_tokens', 'audio_available': True,
            'transcript': PRIVATE, 'text': PRIVATE,
            'provider_payload': {'output': PRIVATE}})
    assert proxy.session_event(session, 'B', 'generation_done', {
        'response_id': 'response-1', 'status': 'incomplete', 'result': PRIVATE})
    assert [data['reason'] for kind, data in records[:2]] == ['max_output_tokens']*2
    assert all(data['audio_available'] is True for kind, data in records[:2])
    assert records[-1][1]['status'] == 'incomplete'
    assert len(records[-1][1]['response_id']) == 64
    assert PRIVATE not in json.dumps(records, ensure_ascii=False)


def test_full_expert_path_enabled_durable_journal_keeps_private_phrase_only_in_ram(tmp_path, settings, monkeypatch):
    import test_realtime_native as native_fixture
    import test_owner_testing as owner_fixture
    import test_unified_expert_stream as integration

    configured = native_fixture.configured
    activate = owner_fixture.activate
    delta = integration.AnswerDelta
    journals = []
    durable_calls = []
    generated = []

    def with_journal(path, configuration):
        manager, provider, budget = configured(path, configuration)
        # Identity protection is deliberately a fixture so the test can inspect
        # all persisted bytes. Production continues using the original DPAPI.
        journal = DebugJournal(path/'enabled-test-journal', manager.owner_testing,
                               protect=lambda raw: raw, unprotect=lambda raw: raw)
        recorder = journal.session_event
        def observed(session, engine, kind, data=None):
            assert not hasattr(session, 'config')
            if session.current:
                assert not hasattr(session.current, 'query')
            durable_calls.append((kind, data))
            return recorder(session, engine, kind, data)
        journal.session_event = observed
        manager.journal = journal
        manager.owns_journal = True
        manager.brain.debug_journal = journal
        journals.append(journal)
        return manager, provider, budget

    def opt_in(*args, **kwargs):
        owner, expert = activate(*args, **kwargs)
        owner.update('client-1', {'debug_journal_enabled': True})
        return owner, expert

    def private_delta(text, **kwargs):
        value = delta(PRIVATE+' '+text, **kwargs)
        generated.append(str(value))
        return value

    monkeypatch.setattr(native_fixture, 'configured', with_journal)
    monkeypatch.setattr(owner_fixture, 'activate', opt_in)
    monkeypatch.setattr(integration, 'AnswerDelta', private_delta)
    integration.test_direct_expert_cue_early_answer_rotation_and_physical_followup(
        tmp_path, settings, monkeypatch)
    assert generated and all(PRIVATE in text for text in generated)
    assert durable_calls and any(kind == 'expert_text_delta' for kind, _ in durable_calls)
    assert any(kind == 'playback_finished' and data.get('audio_role') == 'expert_answer'
               for kind, data in durable_calls)
    assert any(kind == 'telemetry' and data.get('event') == 'speaker_sound_started'
               for kind, data in durable_calls)
    assert PRIVATE not in json.dumps(durable_calls, ensure_ascii=False)
    journal = journals[0]
    assert journal.enabled('client-1') and journal.written > 0
    with journal.connect() as db:
        rows = db.execute('SELECT sealed FROM events').fetchall()
    assert rows and all(PRIVATE.encode() not in row[0] for row in rows)
    assert all(json.loads(row[0])['data']['content_free'] is True for row in rows)
    # No expert result entered the ordinary durable conversation database.
    for path in tmp_path.glob('memory.sqlite*'):
        assert PRIVATE.encode() not in path.read_bytes()
