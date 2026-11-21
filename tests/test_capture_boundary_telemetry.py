"""Numeric capture-boundary evidence cannot change voice or privacy authority."""
import asyncio
import hashlib
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from gobot.debug_journal import DebugJournal
from gobot.unified_voice_journal import ContentFreeJournal, capture_boundary, metadata
from test_unified_voice_api import TOKEN, hello, setup


def boundary(stage='first_uplink', epoch='capture-1', **extra):
    data = {'type': 'telemetry', 'event': 'capture_boundary', 'stage': stage,
        'stream_epoch': epoch, 'ring_end': 14400, 'sample_floor': 8000,
        'plan_monotonic': 12.25}
    if stage == 'playback_finished':
        data.update(response_id='response-1', physical_sample_floor=4800, guard_samples=3200)
    elif stage == 'followup_opened':
        data.update(wake_id='wake-1', selected_start=8000, response_id='response-1',
                    physical_sample_floor=4800, guard_samples=3200)
    else:
        data.update(wake_id='wake-1', selected_start=8000, source_sample_start=8000, source_sample_end=9440)
    return {**data, **extra}


def test_capture_validator_keeps_only_typed_fields_and_hashable_opaque_ids():
    forbidden = 'private transcript, PCM, prompt or exception text'
    for stage in ('playback_finished', 'followup_opened', 'first_uplink'):
        safe = capture_boundary(boundary(stage, text=forbidden, pcm=forbidden,
            input_allowed=True, generation_allowed=True, evidence=forbidden))
        assert safe['stage'] == stage and safe['device_reported'] and safe['not_acoustic_proof']
        stored = metadata(safe)
        assert stored['stream_epoch'] == hashlib.sha256(b'capture-1').hexdigest()
        assert forbidden not in json.dumps(stored)
        assert 'input_allowed' not in stored and 'generation_allowed' not in stored
    for change in ({'stage': []}, {'stage': 'input_authorized'}, {'stream_epoch': ''},
                   {'stream_epoch': 'unsafe '+forbidden}, {'stream_epoch': 'x'*129},
                   {'wake_id': []}, {'ring_end': True}, {'ring_end': 1.5},
                   {'sample_floor': -1}, {'sample_floor': 10**1000},
                   {'plan_monotonic': float('inf')}, {'plan_monotonic': float('nan')},
                   {'plan_monotonic': True}, {'source_sample_start': -1}):
        assert capture_boundary(boundary(**change)) is None
    for key in ('stream_epoch', 'sample_floor', 'ring_end', 'plan_monotonic',
                'selected_start', 'source_sample_start', 'source_sample_end'):
        missing = boundary()
        del missing[key]
        assert capture_boundary(missing) is None
    assert capture_boundary(boundary('playback_finished', guard_samples=False)) is None
    partial = boundary('followup_opened')
    del partial['guard_samples']
    assert capture_boundary(partial) is None
    # Mismatched source/floor is diagnostic evidence, not a value to conceal or
    # an input gate. It must remain visible if a future regression occurs.
    assert capture_boundary(boundary(source_sample_start=4800))['source_sample_start'] == 4800


def test_authenticated_capture_evidence_uses_existing_opt_in_and_has_no_voice_side_effects(tmp_path):
    class Owner:
        enabled = False
        def bound(self, binding):
            return False
        def policy(self):
            return SimpleNamespace(debug_journal_enabled=self.enabled,
                debug_journal_device_bindings=['board'], debug_journal_retention_days=7)

    owner = Owner()
    journal = DebugJournal(tmp_path/'journal', owner, protect=lambda raw: raw, unprotect=lambda raw: raw)
    app, board, browser = setup()
    board.journal = ContentFreeJournal(journal)
    browser.journal = ContentFreeJournal(journal)
    try:
        with TestClient(app) as client:
            with client.websocket_connect('/api/v1/voice-ws/stream', headers={'Authorization': 'Bearer '+TOKEN}) as ws:
                ws.send_json(hello())
                assert ws.receive_json()['type'] == 'transport_attached'
                session = board.sessions['session']
                session.owner_test_binding, session.current = 'board', None
                before = (session.state, session.ready, session.selected_mode,
                          session.received_pcm, session.detach_count)
                ws.send_json(boundary(epoch='opted-out'))
                ws.send_json({'type': 'ping'})
                assert ws.receive_json()['type'] == 'pong'
                assert not journal.path.exists()
                owner.enabled = True
                for stage in ('playback_finished', 'followup_opened', 'first_uplink'):
                    ws.send_json(boundary(stage, text='FORBIDDEN', raw_audio='FORBIDDEN'))
                    ws.send_json(boundary(stage))
                ws.send_json(boundary(epoch='invalid', source_sample_end=True))
                ws.send_json({'type': 'ping'})
                assert ws.receive_json()['type'] == 'pong'
                assert (session.state, session.ready, session.selected_mode,
                        session.received_pcm, session.detach_count) == before
                assert asyncio.run(journal.flush())
                rows = journal.read(journal.scope('board', 'board'), 'session')['events']
                assert len(rows) == 3
                assert [row['data']['stage'] for row in rows] == [
                    'playback_finished', 'followup_opened', 'first_uplink']
                assert all(row['data']['event'] == 'capture_boundary' for row in rows)
                assert all(row['data']['stream_epoch'] == hashlib.sha256(b'capture-1').hexdigest() for row in rows)
                assert 'FORBIDDEN' not in json.dumps(rows) and 'capture-1' not in json.dumps(rows)
            with client.websocket_connect('/api/v1/voice-ws/stream', headers={'Authorization': 'Bearer '+TOKEN}) as ws:
                message = hello('browser')
                message['offer']['client_kind'] = 'panel'
                ws.send_json(message)
                assert ws.receive_json()['type'] == 'transport_attached'
                ws.send_json(boundary(epoch='forged-browser'))
                assert ws.receive_json()['data']['code'] == 'unsupported_voice_control'
            assert asyncio.run(journal.flush())
            assert len(journal.read(journal.scope('board', 'board'), 'session')['events']) == 3
    finally:
        asyncio.run(journal.close())
