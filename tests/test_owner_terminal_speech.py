"""Permanent board speech: real temporary ledgers, synthetic providers only."""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from gobot.expert_stream import EXPERT_CUE_ID, EXPERT_CUE_TEXT, expert_service_cache
from gobot.owner_terminal import (
    OwnerTerminalBoardRealtime, authorize_owner_terminal_proposal,
    prepare_owner_terminal_proposal,
)
from gobot.processes import AgentError
from gobot.realtime_ws import DirectRealtimeManager
from gobot.unified_voice_budget import UnifiedVoiceBudget, narrator_cost
from test_realtime_native import configured
from test_realtime_ws import Provider, cleanup, offer
from test_unified_voice_budget import SpeechFixture, usage


async def terminal(tmp_path, settings, *, complete=True):
    original, _, _ = configured(tmp_path, settings)
    root, cache = tmp_path/'terminal', tmp_path/'fixture-public-cue'
    proposal = prepare_owner_terminal_proposal(root, 'board', expert_profile='ARGON_DEEP')
    expert_service_cache(cache).put('marin', EXPERT_CUE_ID, bytes(4800), 24000, EXPERT_CUE_TEXT)
    # This statement authorizes only this test's newly created temporary files.
    authorize_owner_terminal_proposal(root, proposal['proposal_sha256'],
        owner_direct='Synthetic pytest owner authorization for this temporary fixture.', cache_root=cache)
    board = OwnerTerminalBoardRealtime(original, root)
    authorization = UnifiedVoiceBudget(max_expert_audio_seconds=180,
                                       expert_operation_timeout_seconds=240)
    manager = DirectRealtimeManager(board, provider=Provider(), speech=SpeechFixture(complete=complete),
        narrator_authorizer=authorization.narrator, transcription_authorizer=authorization.transcription)
    session = await manager.accept(offer(expert_quota_consent=True))
    return original, board, manager, session, authorization


def assert_phone_ledger_unused(original):
    with original.owner_testing.connect() as db:
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0


def test_stt_has_no_lifetime_timer_count_or_money_cap_and_keeps_unknown_holds(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, authorization = await terminal(tmp_path, settings)
        try:
            ledger = manager.board_speech_ledger
            assert ledger.require('board').expires_at is None
            # A persistent terminal does not inherit the previous two-hour window.
            future = time.time()+365*86400
            monkeypatch.setattr('gobot.unified_voice_budget.time.time', lambda: future)
            admissions = [await authorization.transcription(session) for _ in range(4)]
            assert len({value['reservation_id'] for value in admissions}) == 4
            assert all(value['paid_consent'] is True and value['max_audio_seconds'] == 180
                       and value['operation_timeout_seconds'] == 240 for value in admissions)
            for value in admissions:
                await value['validate']()
            with ledger.connect() as db:
                assert db.execute('SELECT count(*),sum(cost),sum(pending) FROM unified_speech_attempts').fetchone() == (4, 2., 4)
            await admissions[0]['settle'](audio_seconds=180,
                provider_usage={'seconds': 181}, usage_reported=True)
            await admissions[0]['settle'](audio_seconds=1)  # Duplicate completion cannot reduce recorded cost.
            await admissions[1]['settle'](audio_seconds=181)  # Beyond one request's input resource bound.
            with ledger.connect() as db:
                rows = db.execute('SELECT cost,pending FROM unified_speech_attempts ORDER BY pending').fetchall()
                methods = db.execute('SELECT method FROM unified_voice_usage').fetchall()
            assert rows[0] == (pytest.approx(181/60*.017), 0)
            assert rows[1:] == [(.5, 1)]*3
            assert methods.count(('pending_provider_usage',)) == 3
            assert not manager.speech.turns
            assert board.budget.status()['sessions_reserved'] == 0
            assert_phone_ledger_unused(original)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_narrator_exceeds_old_response_and_character_caps_but_records_every_call(tmp_path, settings):
    async def run():
        original, board, manager, session, authorization = await terminal(tmp_path, settings)
        try:
            job = SimpleNamespace(id='terminal-long-answer', max_result_characters=24000)
            admission = await authorization.narrator(session, job)
            assert admission['tts_character_limit'] == 24000
            async with admission['speech'].turn() as turn:
                await turn.prepare('openai', 'marin', paid_consent=True)
                for _ in range(14):
                    assert [chunk async for chunk in turn.synthesize('С'*600, 'openai', 'marin', paid_consent=True)]
                job.narrator_usage = {'requests_started': turn.requests_started,
                                     'responses': turn.usage_records, 'complete': True}
            await admission['settle'](job)
            ledger = manager.board_speech_ledger
            with ledger.connect() as db:
                rows = db.execute('SELECT cost,pending,characters FROM unified_speech_attempts').fetchall()
                evidence = db.execute('SELECT measurement FROM unified_voice_usage').fetchall()
            assert len(rows) == 14 and sum(row[2] for row in rows) == 8400
            assert all(row[:2] == (pytest.approx(narrator_cost(usage())), 0) for row in rows)
            assert all('С'*600 not in row[0] for row in evidence)
            assert manager.speech.turns[0].requests_started == 14
            # The producer's per-job resource ceiling remains separate from lifetime expense policy.
            with pytest.raises(PermissionError, match='expert_narration_limit_invalid'):
                await authorization.narrator(session, SimpleNamespace(id='invalid', max_result_characters=32001))
            assert_phone_ledger_unused(original)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_unknown_narrator_cost_remains_pending_without_automatic_retry(tmp_path, settings):
    async def run():
        original, board, manager, session, authorization = await terminal(tmp_path, settings, complete=False)
        try:
            first = SimpleNamespace(id='unknown-answer', max_result_characters=6000)
            admission = await authorization.narrator(session, first)
            assert admission['tts_character_limit'] == 6000  # No inherited finite 3000-character grant cap.
            async with admission['speech'].turn() as turn:
                assert [chunk async for chunk in turn.synthesize('Один ответ.', 'openai', 'marin', paid_consent=True)]
            await admission['settle'](first)
            with pytest.raises(PermissionError, match='already_reserved'):
                await authorization.narrator(session, first)
            assert len(manager.speech.turns) == 1 and manager.speech.turns[0].requests_started == 1
            # A distinct user-requested answer is allowed; the unknown prior attempt remains intact.
            await authorization.narrator(session, SimpleNamespace(id='new-explicit-answer', max_result_characters=6000))
            with manager.board_speech_ledger.connect() as db:
                assert db.execute('SELECT cost,pending FROM unified_speech_attempts').fetchall() == [(.5, 1), (.5, 1)]
            assert len(manager.speech.turns) == 1
            assert_phone_ledger_unused(original)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_permanent_profile_revocation_blocks_new_provider_work_and_preserves_holds(tmp_path, settings):
    async def run():
        original, board, manager, session, authorization = await terminal(tmp_path, settings)
        try:
            stt = await authorization.transcription(session)
            narrator = await authorization.narrator(session, SimpleNamespace(id='revoked-answer', max_result_characters=24000))
            # Disable the complete scope; never change original authorization IDs or usage.
            for relative in ('policy.json', 'experts/policy.json', 'speech-policy.json'):
                path = board.budget.root/relative
                data = json.loads(path.read_text())
                path.write_text(json.dumps({**data, 'enabled': False}))
            with pytest.raises(PermissionError):
                await stt['validate']()
            with pytest.raises(PermissionError):
                await authorization.transcription(session)
            async with narrator['speech'].turn() as turn:
                with pytest.raises(AgentError, match='narration_budget_denied'):
                    _ = [chunk async for chunk in turn.synthesize('Запрещённый вызов.', 'openai', 'marin', paid_consent=True)]
            assert manager.speech.turns[0].requests_started == 0
            with manager.board_speech_ledger.connect() as db:
                assert db.execute('SELECT count(*),sum(cost),sum(pending) FROM unified_speech_attempts').fetchone() == (2, 1., 2)
            assert_phone_ledger_unused(original)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('patch', [
    {'client_id': 'phone'}, {'owner_test_binding': 'board'},
    {'remember': True}, {'expert_quota_consent': False},
])
def test_permanent_speech_cannot_expand_guest_or_device_scope(tmp_path, settings, patch):
    async def run():
        original, board, manager, session, authorization = await terminal(tmp_path, settings)
        try:
            session.offer = session.offer.model_copy(update=patch)
            with pytest.raises(PermissionError, match='exact_board_public_speech_scope_required'):
                await authorization.transcription(session)
            with pytest.raises(PermissionError, match='exact_board_public_speech_scope_required'):
                await authorization.narrator(session, SimpleNamespace(id='wrong-scope', max_result_characters=24000))
            assert manager.board_speech_ledger.status()['operations'] == {}
            assert not manager.speech.turns
            assert_phone_ledger_unused(original)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
