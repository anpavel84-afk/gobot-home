"""Real owner ledgers with synthetic voice providers; no external calls."""
import asyncio
import json
import time
from types import SimpleNamespace

import pytest

from gobot.audio import TTS_MODEL
from gobot.processes import AgentError
from gobot.realtime_ws import DirectOffer, DirectRealtimeManager
from gobot.unified_voice_budget import UnifiedVoiceBudget, narrator_cost
from test_owner_testing import activate
from test_realtime_native import configured
from test_realtime_ws import Provider, setup, offer, cleanup


def usage(index=0, *, complete=True):
    return {'response_id': 'tts-'+str(index), 'model': TTS_MODEL, 'status': 'completed',
            'usage_reported': complete,
            'usage': {'input_tokens': 20, 'output_tokens': 100,
                      'input_token_details': {'text_tokens': 20, 'audio_tokens': 0,
                                             'cached_tokens': 5,
                                             'cached_tokens_details': {'text_tokens': 5, 'audio_tokens': 0}},
                      'output_token_details': {'text_tokens': 0, 'audio_tokens': 100}} if complete else {}}


class SpeechFixture:
    def __init__(self, *, complete=True):
        self.turns = []
        self.complete = complete

    def turn(self):
        turn = TurnFixture(self.complete)
        self.turns.append(turn)
        return turn


class TurnFixture:
    def __init__(self, complete):
        self.complete = complete
        self.requests_started = 0
        self.usage_records = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def prepare(self, provider, voice, *, paid_consent):
        assert (provider, voice, paid_consent) == ('openai', 'marin', True)

    async def synthesize(self, text, provider, voice, *, paid_consent):
        self.requests_started += 1
        yield bytes(480), 24000
        self.usage_records.append(usage(self.requests_started, complete=self.complete))


async def owner_setup(tmp_path, settings, *, developer=False, complete=True):
    original, _, native_budget = configured(tmp_path, settings)
    owner, _ = activate(original, native_budget)
    p = owner.policy().model_copy(update={'developer_acceptance_expires_at': time.time()+60,
        'developer_realtime_limit': 1, 'developer_estimate_usd_limit': 1})
    owner.policy_path.write_text(p.model_dump_json())
    authorization = UnifiedVoiceBudget()
    manager = DirectRealtimeManager(original, provider=Provider(), speech=SpeechFixture(complete=complete),
        narrator_authorizer=authorization.narrator, transcription_authorizer=authorization.transcription)
    session = await manager.accept(DirectOffer(session_id='voice-budget', conversation_id='conv-budget',
        device_id='browser-1', client_id='client-1', consent=True, client_kind='panel',
        requested_model=TTS_MODEL, expert_quota_consent=True, developer_acceptance=developer))
    return original, manager, session, owner, authorization


async def close(original, manager):
    await manager.shutdown()
    await original.shutdown()


def test_empty_transport_and_board_callbacks_never_borrow_owner_grant(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings, enabled=False)
        authorization = UnifiedVoiceBudget()
        try:
            s = await manager.accept(offer())
            with pytest.raises(PermissionError, match='existing_owner'):
                await authorization.transcription(s)
            manager.speech = SpeechFixture()
            with pytest.raises(PermissionError, match='existing_owner'):
                await authorization.narrator(s, SimpleNamespace(id='job', max_result_characters=24000))
            with original.owner_testing.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_stt_settles_actual_pcm_duration_and_keeps_separate_origin(tmp_path, settings):
    async def run():
        original, manager, s, owner, authorization = await owner_setup(tmp_path, settings)
        try:
            with owner.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
            admission = await authorization.transcription(s)
            assert admission['max_audio_seconds'] == 60 and admission['operation_timeout_seconds'] == 100
            with owner.connect() as db:
                assert db.execute('SELECT cost,pending,origin FROM attempts').fetchone() == (.5, 1, 'web_stt')
            await admission['settle'](audio_seconds=12, provider_usage={'type': 'duration', 'seconds': 12.1}, usage_reported=True)
            await admission['settle'](audio_seconds=2)  # Replay cannot rewrite measured cost.
            with owner.connect() as db:
                cost, pending = db.execute('SELECT cost,pending FROM attempts').fetchone()
                evidence = json.loads(db.execute('SELECT measurement FROM unified_voice_usage').fetchone()[0])
            assert cost == pytest.approx(12.1/60*.017) and pending == 0
            assert evidence['input_pcm_audio_seconds'] == 12
            assert evidence['provider_duration_reported'] is True
        finally:
            await close(original, manager)
    asyncio.run(run())


def test_invalid_or_missing_stt_completion_retains_hold(tmp_path, settings):
    async def run():
        original, manager, s, owner, authorization = await owner_setup(tmp_path, settings)
        try:
            admission = await authorization.transcription(s)
            await admission['settle'](audio_seconds=float('nan'))
            await admission['settle'](audio_seconds=65)
            with owner.connect() as db:
                assert db.execute('SELECT cost,pending FROM attempts').fetchone() == (.5, 1)
        finally:
            await close(original, manager)
    asyncio.run(run())


def test_each_narrator_response_uses_existing_counter_and_measured_settlement(tmp_path, settings):
    async def run():
        original, manager, s, owner, authorization = await owner_setup(tmp_path, settings)
        try:
            job = SimpleNamespace(id='job', max_result_characters=24000)
            admission = await authorization.narrator(s, job)
            async with admission['speech'].turn() as turn:
                await turn.prepare('openai', 'marin', paid_consent=True)
                for text in ('Первое предложение.', 'Второе предложение.'):
                    assert [item async for item in turn.synthesize(text, 'openai', 'marin', paid_consent=True)]
                job.narrator_usage = {'requests_started': turn.requests_started,
                                     'responses': turn.usage_records, 'complete': True}
            await admission['settle'](job)
            with owner.connect() as db:
                rows = db.execute('SELECT cost,pending,origin FROM attempts').fetchall()
            assert len(rows) == 2
            assert all(row[0] == pytest.approx(narrator_cost(usage())) and row[1:] == (0, 'web_tts') for row in rows)
            assert manager.speech.turns[0].requests_started == 2
        finally:
            await close(original, manager)
    asyncio.run(run())


def test_developer_limit_blocks_second_narrator_response_before_provider(tmp_path, settings):
    async def run():
        original, manager, s, owner, authorization = await owner_setup(tmp_path, settings, developer=True)
        try:
            admission = await authorization.narrator(s, SimpleNamespace(id='job', max_result_characters=24000))
            async with admission['speech'].turn() as turn:
                assert [x async for x in turn.synthesize('Первое.', 'openai', 'marin', paid_consent=True)]
                with pytest.raises(AgentError, match='expert_narration_budget_denied'):
                    [x async for x in turn.synthesize('Второе.', 'openai', 'marin', paid_consent=True)]
            assert manager.speech.turns[0].requests_started == 1
            with owner.connect() as db:
                assert db.execute('SELECT count(*),origin FROM attempts').fetchone() == (1, 'developer')
        finally:
            await close(original, manager)
    asyncio.run(run())


def test_developer_stt_cannot_borrow_available_realtime_credits(tmp_path, settings):
    async def run():
        original, manager, s, owner, authorization = await owner_setup(tmp_path, settings, developer=True)
        try:
            assert owner.policy().developer_realtime_limit == 1
            assert owner.policy().developer_transcription_limit == 0
            s.selected_mode = 'expert'
            with pytest.raises(PermissionError, match='developer_acceptance_limit'):
                await s.start_expert_input()
            assert s.ready and not s.input_open and s._stt_queue is None and s._stt_task is None
            assert await s.append_pcm(bytes(4800)) is False
            assert not any(event['type'] in {'input_audio_buffer.append', 'response.create'}
                           for socket in manager.provider.sockets for event in socket.sent)
            with owner.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
            assert manager.budget.status()['sessions_reserved'] == 0
        finally:
            await close(original, manager)
    asyncio.run(run())


def test_developer_stt_uses_only_explicit_transcription_counter(tmp_path, settings):
    async def run():
        original, manager, s, owner, authorization = await owner_setup(tmp_path, settings, developer=True)
        try:
            policy = owner.policy().model_copy(update={'developer_transcription_limit': 1,
                                                       'developer_realtime_limit': 0})
            owner.policy_path.write_text(policy.model_dump_json())
            admission = await authorization.transcription(s)
            with owner.connect() as db:
                assert db.execute('SELECT kind,cost,pending,origin FROM attempts').fetchone() == (
                    'transcription', .5, 1, 'developer')
            await admission['settle'](audio_seconds=1)
            with pytest.raises(PermissionError, match='developer_acceptance_limit'):
                await authorization.transcription(s)
            with owner.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 1
        finally:
            await close(original, manager)
    asyncio.run(run())


def test_unknown_narrator_usage_keeps_hold_and_revocation_prevents_next_sentence(tmp_path, settings):
    async def run():
        original, manager, s, owner, authorization = await owner_setup(tmp_path, settings, complete=False)
        try:
            admission = await authorization.narrator(s, SimpleNamespace(id='job', max_result_characters=24000))
            async with admission['speech'].turn() as turn:
                assert [x async for x in turn.synthesize('Первое.', 'openai', 'marin', paid_consent=True)]
                owner.update('client-1', {'enabled': False})
                with pytest.raises(AgentError, match='expert_narration_budget_denied'):
                    [x async for x in turn.synthesize('Второе.', 'openai', 'marin', paid_consent=True)]
            with owner.connect() as db:
                assert db.execute('SELECT cost,pending FROM attempts').fetchone() == (.5, 1)
        finally:
            await close(original, manager)
    asyncio.run(run())


@pytest.mark.parametrize('changes', [
    {'usage': {'total_tokens': 100}},
    {'model': 'unpriced-model'},
    {'usage_reported': False},
    {'usage': {'input_token_details': {'text_tokens': float('inf'), 'audio_tokens': 0},
               'output_token_details': {'text_tokens': 0, 'audio_tokens': 1}}},
])
def test_ambiguous_narrator_modality_usage_is_not_zero_cost(changes):
    assert narrator_cost({**usage(), **changes}) is None


def test_long_expert_audio_is_an_explicit_local_configuration():
    authorization = UnifiedVoiceBudget(max_expert_audio_seconds=180, expert_operation_timeout_seconds=240)
    assert authorization.max_audio_seconds == 180
    with pytest.raises(ValueError):
        UnifiedVoiceBudget(max_expert_audio_seconds=301, expert_operation_timeout_seconds=360)


def test_long_stt_configuration_is_capped_by_existing_grant(tmp_path, settings):
    async def run():
        original, manager, s, owner, _ = await owner_setup(tmp_path, settings)
        try:
            policy = manager.budget.policy().model_copy(update={'max_session_seconds': 60})
            manager.budget.policy_path.write_text(policy.model_dump_json())
            authorization = UnifiedVoiceBudget(max_expert_audio_seconds=180, expert_operation_timeout_seconds=240)
            admission = await authorization.transcription(s)
            assert admission['max_audio_seconds'] == 60
            assert manager.budget.policy().max_session_seconds == 60
            expired = policy.model_copy(update={'expires_at': time.time()-1})
            manager.budget.policy_path.write_text(expired.model_dump_json())
            with pytest.raises(PermissionError, match='existing_owner'):
                await authorization.transcription(s)
            with owner.connect() as db:
                assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 1
        finally:
            await close(original, manager)
    asyncio.run(run())


def test_revocation_stops_active_stt_before_next_pcm_without_reopening(tmp_path, settings):
    async def run():
        original, manager, s, owner, authorization = await owner_setup(tmp_path, settings)
        try:
            s._stt_reservation = await authorization.transcription(s)
            queue = s._stt_queue = asyncio.Queue()
            s._stt_task = asyncio.create_task(asyncio.Event().wait())
            s.input_open = True
            s.selected_mode = 'expert'
            owner.update('client-1', {'enabled': False})
            assert await s.append_pcm(bytes(4800)) is False
            assert queue.qsize() == 0 and s._stt_task.cancelled()
            assert s.ready and not s.closed and not s.input_open
            with owner.connect() as db:
                assert db.execute('SELECT count(*),cost,pending FROM attempts').fetchone() == (1, .5, 1)
        finally:
            await close(original, manager)
    asyncio.run(run())
