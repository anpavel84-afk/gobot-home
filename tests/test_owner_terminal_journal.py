"""Final text stays within the existing, explicitly opted-in board journal."""
import asyncio
import base64
import hashlib
import json
from types import SimpleNamespace

import pytest

from gobot.owner_testing import OwnerTestPolicy
from gobot.realtime import NativeTurn
from gobot.unified_voice_journal import (
    ContentFreeJournal, INPUT_TEXT_LIMIT, OUTPUT_TEXT_LIMIT,
    OwnerTerminalDiagnosticJournal, TEXT_DEDUP_LIMIT, direct_journal, metadata,
)
from test_owner_terminal_direct import setup_terminal
from test_realtime_ws import cleanup


QUESTION = 'Синтетический вопрос о фиолетовом квадрате.'
ANSWER = 'Синтетический ответ о фиолетовом квадрате.'
FORBIDDEN = 'Недопустимое содержимое контекста и полного запроса.'


def opt_in(original, enabled=True, bindings=('board',)):
    owner = original.owner_testing
    policy = owner.policy()
    owner.policy_path.parent.mkdir(parents=True, exist_ok=True)
    owner.policy_path.write_text(OwnerTestPolicy.model_validate({**policy.model_dump(),
        'debug_journal_enabled': enabled, 'debug_journal_device_bindings': list(bindings),
        'debug_journal_retention_days': 7}).model_dump_json(), encoding='utf-8')
    # Linux tests use a visibly different reversible fixture, never a substitute
    # for the existing Windows DPAPI production encryptor.
    original.journal.protect = lambda value: b'FIXTURE-CIPHER:'+base64.b64encode(value)
    original.journal.unprotect = lambda value: base64.b64decode(value.removeprefix(b'FIXTURE-CIPHER:'))


def turn(session, ident='turn-1', text=QUESTION):
    value = NativeTurn(id=ident, input_id='input-'+ident, query=text, answer=ANSWER)
    session.current = value
    session.turns.append(value)
    return value


def output(value, **extra):
    return {'turn_id': value.id, 'item_id': value.input_id, 'response_id': 'response-1',
        'question': QUESTION, 'answer_transcript': ANSWER,
        'playback': 'client_playback_reported', 'truncated': False,
        'not_acoustic_proof': True, **extra}


async def records(original):
    journal = original.journal
    assert await journal.flush()
    if not journal.path.exists():
        return []
    with journal.connect() as db:
        rows = db.execute('SELECT sealed FROM events ORDER BY id').fetchall()
    return [json.loads(journal.unprotect(row[0])) for row in rows]


def test_exact_terminal_final_input_and_output_use_existing_encrypted_scope_once(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        try:
            opt_in(original)
            proxy = manager.journal
            assert type(proxy) is OwnerTerminalDiagnosticJournal
            assert proxy.journal is original.journal is board.journal
            assert proxy.status('board')['text_recording']
            assert proxy.status('board')['retention_days'] == 7
            value = turn(session)
            data = {'text': QUESTION, 'final': True, 'context': FORBIDDEN,
                    'instructions': FORBIDDEN, 'audio': FORBIDDEN}
            assert proxy.session_event(session, 'B', 'input_transcript', data)
            assert not proxy.session_event(session, 'B', 'input_transcript', data)
            assert proxy.session_event(session, 'B', 'direct_dialogue_turn', output(value))
            assert not proxy.session_event(session, 'B', 'direct_dialogue_turn', output(value))
            items = await records(original)
            assert [item['data']['text_source'] for item in items] == [
                'input_asr_hypothesis', 'assistant_output_transcript']
            assert items[0]['data']['text'] == QUESTION
            assert items[1]['data']['answer_transcript'] == ANSWER
            assert 'question' not in items[1]['data']
            assert items[1]['data']['playback'] == 'client_playback_reported'
            for item in items:
                data = item['data']
                assert data['diagnostic_only'] and data['untrusted_text'] and data['not_acoustic_proof']
                assert data['text_recording_scope'] == 'owner_terminal_board'
                assert data['ids_hashed'] and not data['content_free']
                assert data['turn_id'] == hashlib.sha256(value.id.encode()).hexdigest()
                assert data['item_id'] == hashlib.sha256(value.input_id.encode()).hexdigest()
            assert FORBIDDEN not in json.dumps(items, ensure_ascii=False)
            with original.journal.connect() as db:
                rows = db.execute('SELECT scope,session,sealed FROM events').fetchall()
            assert all(row[0] == original.journal.scope('board', 'board', None) for row in rows)
            assert all(row[1] == session.id for row in rows)
            assert all(QUESTION.encode() not in row[2] and ANSWER.encode() not in row[2] for row in rows)
            assert all(event['type'] != 'response.create' for socket in provider.sockets for event in socket.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('change', [
    'opted_out', 'phone_opt_in_only', 'other_device', 'other_client', 'browser',
    'profile_epoch', 'confirmed_profile', 'phone_binding', 'remember',
    'speaker_consent', 'developer_acceptance', 'different_budget', 'different_authorization',
])
def test_text_requires_exact_device_and_separate_live_diagnostic_opt_in(tmp_path, settings, change):
    async def run():
        original, board, manager, session, _ = await setup_terminal(tmp_path, settings)
        try:
            opt_in(original, enabled=change != 'opted_out',
                   bindings=() if change == 'phone_opt_in_only' else ('board',))
            value = turn(session)
            offered = {
                'other_device': {'device_id': 'someone-else'},
                'other_client': {'client_id': 'phone'},
                'browser': {'client_kind': 'panel'},
                'profile_epoch': {'profile_epoch': 'different-profile'},
                'phone_binding': {'owner_test_binding': 'phone'},
                'remember': {'remember': True},
                'speaker_consent': {'speaker_consent': True},
                'developer_acceptance': {'developer_acceptance': True},
            }
            if change in offered:
                session.offer = session.offer.model_copy(update=offered[change])
            if change == 'browser':
                session.source = 'browser'
            if change == 'confirmed_profile':
                session.access = SimpleNamespace(confirmed_profile_id='private-family-member')
            if change == 'different_budget':
                session.manager = SimpleNamespace(budget=original.budget)
            if change == 'different_authorization':
                session.policy = session.policy.model_copy(update={'authorization': 'not-pinned'})
            manager.journal.session_event(session, 'B', 'input_transcript', {'text': QUESTION, 'final': True})
            manager.journal.session_event(session, 'B', 'direct_dialogue_turn', output(value))
            data = json.dumps(await records(original), ensure_ascii=False)
            assert QUESTION not in data and ANSWER not in data
            assert 'assistant_output_transcript' not in data and 'input_asr_hypothesis' not in data
        finally:
            # Restore only the fixture reference required by native cleanup.
            session.manager = manager
            session.current = None
            session.turns.clear()
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_other_factories_and_legacy_events_keep_metadata_only(tmp_path, settings):
    async def run():
        original, board, manager, session, _ = await setup_terminal(tmp_path, settings)
        try:
            opt_in(original)
            turn(session)
            assert type(direct_journal(original)) is ContentFreeJournal
            # A duck-typed manager with the same budget cannot opt in a browser.
            fake = SimpleNamespace(journal=original.journal, budget=board.budget,
                                   owner_testing=original.owner_testing)
            assert type(direct_journal(fake)) is ContentFreeJournal
            proxy = manager.journal
            for kind in ('text_delta', 'answer_transcript', 'stt_final', 'transcript', 'dialogue_turn'):
                proxy.session_event(session, 'B', kind, {
                    'text': QUESTION, 'answer_transcript': ANSWER, 'question': QUESTION,
                    'raw_audio': FORBIDDEN, 'final': True})
            proxy.session_event(session, 'B', 'input_transcript', {'text': QUESTION, 'final': False})
            proxy.session_event(session, 'B', 'input_transcript', {'text': QUESTION, 'final': 1})
            proxy.session_event(session, 'B', 'provider_command', {
                'event_type': 'response.create', 'event': {'instructions': FORBIDDEN, 'input': QUESTION},
                'reason': 'input_final_transcript', 'trigger': 'followup', 'turn_id': 'turn-1'})
            data = await records(original)
            serialized = json.dumps(data, ensure_ascii=False)
            assert QUESTION not in serialized and ANSWER not in serialized and FORBIDDEN not in serialized
            assert all(item['data']['content_free'] for item in data)
            assert data[-1]['data']['reason'] == 'input_final_transcript'
            assert data[-1]['data']['trigger'] == 'followup'
            assert 'event' not in data[-1]['data']
            assert metadata({'reason': FORBIDDEN, 'trigger': FORBIDDEN}) == {'reason': 'other', 'trigger': 'other'}
            assert metadata({'code': 'response_acknowledgement_timeout'}) == {
                'code': 'response_acknowledgement_timeout'}
            rejected = metadata({'event': 'response_correlation_rejected',
                'reason': 'stale_or_unknown_request', 'response_id': 'old-response',
                'automatic_retry': False, 'provider_payload': FORBIDDEN})
            assert rejected == {'event': 'response_correlation_rejected',
                'reason': 'stale_or_unknown_request',
                'response_id': hashlib.sha256(b'old-response').hexdigest(),
                'automatic_retry': False}
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_final_text_is_bounded_redacted_and_disabled_immediately_without_retention_change(tmp_path, settings):
    async def run():
        original, board, manager, session, _ = await setup_terminal(tmp_path, settings)
        try:
            opt_in(original)
            value = turn(session)
            secret = 'sk-'+('x'*40)
            text = 'Bearer my-secret '+secret+' password=hunter2 https://fixture.test/path?token=hidden '+('я'*24000)
            proxy = manager.journal
            assert proxy.session_event(session, 'B', 'input_transcript', {'text': text, 'final': True})
            assert proxy.session_event(session, 'B', 'direct_dialogue_turn', output(value,
                answer_transcript=text, playback='unconfirmed_or_interrupted'))
            items = await records(original)
            assert len(items[0]['data']['text']) <= INPUT_TEXT_LIMIT
            assert len(items[1]['data']['answer_transcript']) <= OUTPUT_TEXT_LIMIT
            assert all(item['data']['diagnostic_text_truncated'] for item in items)
            data = json.dumps(items, ensure_ascii=False)
            assert all(secret not in data for secret in ('my-secret', 'hunter2', 'token=hidden', 'sk-'+'x'*40))
            assert items[1]['data']['playback'] == 'unconfirmed_or_interrupted'
            assert QUESTION not in json.dumps(list(proxy._text_events), ensure_ascii=False)
            before = original.owner_testing.policy().debug_journal_retention_days
            opt_in(original, False)
            turn(session, 'new-turn')
            assert not proxy.session_event(session, 'B', 'input_transcript', {'text': QUESTION, 'final': True})
            assert not proxy.status('board')['text_recording']
            assert proxy.status('board')['retention_days'] == before == 7
            assert len(await records(original)) == 2
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_final_hook_binds_old_finished_turn_not_new_current_turn(tmp_path, settings):
    async def run():
        original, board, manager, session, _ = await setup_terminal(tmp_path, settings)
        try:
            opt_in(original)
            old = turn(session, 'old-turn')
            turn(session, 'new-turn')
            await session.finish(old, False)
            await session.finish(old, False)
            items = [item for item in await records(original)
                     if item['data'].get('text_source') == 'assistant_output_transcript']
            assert len(items) == 1 and items[0]['turn_id'] == old.id
            assert items[0]['data']['turn_id'] == hashlib.sha256(old.id.encode()).hexdigest()
            assert items[0]['data']['playback'] == 'unconfirmed_or_interrupted'
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_diagnostic_duplicate_cache_is_bounded_and_stores_no_text(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, _ = await setup_terminal(tmp_path, settings)
        try:
            opt_in(original)
            # Exercise the real scoped wrapper without stressing the asynchronous
            # journal queue; persistence/worker ownership is tested above.
            monkeypatch.setattr(original.journal, 'session_event', lambda *args: True)
            for index in range(TEXT_DEDUP_LIMIT+10):
                turn(session, 'turn-'+str(index))
                assert manager.journal.session_event(session, 'B', 'input_transcript', {'text': QUESTION, 'final': True})
            assert len(manager.journal._text_events) == TEXT_DEDUP_LIMIT
            assert QUESTION not in json.dumps(list(manager.journal._text_events), ensure_ascii=False)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('ending', ['question', 'name_only', 'empty', 'failed'])
def test_every_received_final_asr_gate_decision_is_scoped_and_recorded_once(tmp_path, settings, ending):
    async def run():
        original, board, manager, session, _ = await setup_terminal(tmp_path, settings)
        try:
            opt_in(original)
            await session.wake('synthetic-input', trigger='wake_word')
            await session.append_pcm(bytes(9600))
            await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'input-final'})
            gate = session._wake_fragment
            text = {'question': QUESTION, 'name_only': 'София', 'empty': '',
                    'failed': FORBIDDEN}[ending]
            await session.handle({'type': 'conversation.item.input_audio_transcription.'+
                ('failed' if ending == 'failed' else 'completed'),
                'item_id': 'input-final', 'transcript': text})
            await gate['task']
            inputs = [item for item in await records(original)
                      if item['data'].get('text_source') == 'input_asr_hypothesis']
            assert len(inputs) == 1
            assert inputs[0]['data']['text'] == ('' if ending == 'failed' else text)
            assert inputs[0]['data']['asr_status'] == ('failed' if ending == 'failed' else 'completed')
            assert inputs[0]['data']['diagnostic_only'] and not inputs[0]['data']['content_free']
            assert FORBIDDEN not in json.dumps(inputs, ensure_ascii=False)
            if ending != 'question':
                assert not any(event['type'] == 'response.create' for event in session.ws.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_late_activation_asr_records_old_item_without_replacing_current_question(tmp_path, settings, monkeypatch):
    from gobot import realtime_ws
    monkeypatch.setattr(realtime_ws, '_FAST_TRANSCRIPT_TIMEOUT_SECONDS', .01)
    async def run():
        original, board, manager, session, _ = await setup_terminal(tmp_path, settings)
        try:
            opt_in(original)
            await session.wake('synthetic-capture', trigger='wake_word', capture={
                'stream_epoch': 'fixture', 'selected_start': 40000, 'detector_sample': 56000,
                'sample_rate': 16000, 'interrupt': False})
            for samples in (24000, 24000, 840):
                await session.append_pcm(bytes(samples*2))
            await session.handle({'type': 'input_audio_buffer.speech_stopped',
                                  'item_id': 'only-activation', 'audio_end_ms': 1472})
            await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'only-activation'})
            gate = session._wake_fragment
            await asyncio.wait_for(gate['task'], 1)
            old = session.current
            assert old.cancelled and old.query == '' and old.req is None
            await session.append_pcm(bytes(9600))
            await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'actual-question'})
            question_gate = session._wake_fragment
            current = session.current
            late = {'type': 'conversation.item.input_audio_transcription.completed',
                    'item_id': 'only-activation', 'transcript': 'Синтетическая ошибочная гипотеза.'}
            await session.handle(late)
            await session.handle(late)
            assert current.query == '' and not current.input_ready.is_set()
            await session.handle({'type': 'conversation.item.input_audio_transcription.completed',
                                  'item_id': 'actual-question', 'transcript': QUESTION})
            await question_gate['task']
            inputs = [item for item in await records(original)
                      if item['data'].get('text_source') == 'input_asr_hypothesis']
            assert len(inputs) == 2
            assert inputs[0]['turn_id'] == old.id
            assert inputs[0]['data']['turn_id'] == hashlib.sha256(old.id.encode()).hexdigest()
            assert inputs[0]['data']['item_id'] == hashlib.sha256(b'only-activation').hexdigest()
            assert inputs[1]['turn_id'] == current.id and inputs[1]['data']['text'] == QUESTION
            assert old.query == '' and current.query == QUESTION
            assert sum(event['type'] == 'response.create' for event in session.ws.sent) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('enabled', [False, True])
def test_private_final_hook_never_writes_outside_existing_board_opt_in(tmp_path, settings, enabled):
    async def run():
        original, board, manager, session, _ = await setup_terminal(tmp_path, settings)
        try:
            opt_in(original, enabled=enabled, bindings=('board',) if not enabled else ('phone',))
            value = turn(session)
            session.journal_final_input(value, QUESTION)
            assert not [item for item in await records(original)
                        if item['data'].get('text_source') == 'input_asr_hypothesis']
            assert original.owner_testing.policy().debug_journal_retention_days == 7
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
