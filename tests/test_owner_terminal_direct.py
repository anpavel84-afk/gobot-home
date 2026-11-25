"""Permanent board admission with real temporary ledgers and synthetic providers."""
import asyncio
import json
import time

import pytest

from gobot.expert_stream import EXPERT_CUE_ID, EXPERT_CUE_TEXT, expert_service_cache
from gobot.owner_terminal import (OwnerTerminalBoardRealtime,
    prepare_owner_terminal_proposal, authorize_owner_terminal_proposal)
from gobot.realtime_ws import DirectRealtimeManager
from gobot.unified_voice_budget import UnifiedVoiceBudget
from test_direct_admission_status import ledger_snapshot, no_generation
from test_realtime_native import configured
from test_realtime_ws import Provider, offer, cleanup
from test_unified_voice_budget import SpeechFixture


async def setup_terminal(tmp_path, settings):
    original, _, _ = configured(tmp_path, settings)
    root = tmp_path/'permanent-board'
    proposal = prepare_owner_terminal_proposal(root, 'board', expert_profile='ARGON_DEEP')
    cache = tmp_path/'fixture-public-cue'
    expert_service_cache(cache).put('marin', EXPERT_CUE_ID, bytes(4800), 24000, EXPERT_CUE_TEXT)
    authorize_owner_terminal_proposal(root, proposal['proposal_sha256'], cache_root=cache,
        owner_direct='Synthetic owner authorizes permanent uncapped board testing')
    board = OwnerTerminalBoardRealtime(original, root)
    authority = UnifiedVoiceBudget(max_expert_audio_seconds=180, expert_operation_timeout_seconds=240)
    provider = Provider()
    manager = DirectRealtimeManager(board, provider=provider, speech=SpeechFixture(),
        transcription_authorizer=authority.transcription, narrator_authorizer=authority.narrator)
    session = await manager.accept(offer(expert_quota_consent=True))
    return original, board, manager, session, provider


def test_permanent_ready_after_time_and_rotation_keeps_provider_maximum_without_spend(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        try:
            assert session.ready and not session.input_open
            assert session.config['max_output_tokens'] == 'inf'
            assert provider.sockets[0].config['max_output_tokens'] == 'inf'
            before = ledger_snapshot(manager)
            future = time.time()+10*365*24*3600
            monkeypatch.setattr(time, 'time', lambda: future)
            assert session.admission_status() == {'mode': 'fast', 'input_allowed': True,
                'generation_allowed': True, 'code': 'available'}
            preview = manager.admission_preview(client_id='board', device_id='board')
            assert preview['allowed'] and preview['expert_available']
            assert board.budget.board_status()['sessions_remaining'] is None
            assert await session.rotate()
            assert len(provider.sockets) == 2 and provider.sockets[0].closed
            assert provider.sockets[1].config['max_output_tokens'] == 'inf'
            assert session.ready and not session.input_open
            assert ledger_snapshot(manager) == before
            no_generation(provider)
        finally:
            monkeypatch.undo()
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_permanent_operation_survives_previous_start_response_time_token_and_cost_limits(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        try:
            for index in range(5):
                board.budget.reserve_session('prior-terminal-start-'+str(index), True, 'board')
            await session.wake('first-terminal-question')
            await session.stop()
            operation, policy = session.operation_id, session.operation_policy
            session.operation_started -= 31*24*3600
            with board.budget.connect() as db:
                db.execute('UPDATE sessions SET started=? WHERE id=?',
                    (time.time()-31*24*3600, board.budget.key(operation)))
            # Synthetic accounting exceeds the old three-start, 12-response,
            # 180-second, 100k-token and $2 estimate limits without any API call.
            usage = {'total_tokens': 21000, 'input_tokens': 20000, 'output_tokens': 1000,
                'input_token_details': {'text_tokens': 0, 'audio_tokens': 20000,
                    'cached_tokens': 0, 'cached_tokens_details': {'text_tokens': 0, 'audio_tokens': 0}},
                'output_token_details': {'text_tokens': 0, 'audio_tokens': 1000}}
            for index in range(13):
                board.budget.reserve_response(operation, policy)
                assert board.budget.record(operation, 'synthetic-accounted-'+str(index), usage)
            assert session.operation_has_response_capacity(policy)
            assert session.generation_allowed()
            assert manager.admission_preview(client_id='board', device_id='board')['allowed']
            state = board.budget.board_status()
            assert state['sessions_reserved'] == 6 and state['response_attempts'] == 13
            assert state['reported_response_estimate_usd'] > 2
            assert state['sessions_remaining'] is None and state['estimated_allowance_usd'] is None
            before = ledger_snapshot(manager)
            await session.wake('next-terminal-question')
            assert session.input_open and session.operation_id == operation
            await session.stop()
            assert ledger_snapshot(manager) == before
            assert session.lifecycle_status()['operation_remaining_seconds'] is None
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_permanent_expert_preview_retains_accounting_without_expiry_count_or_cost_caps(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        try:
            for index in range(3):
                manager.public_expert_budget.reserve_session('prior-expert-'+str(index), True, 'board')
                key = manager.board_speech_ledger.reserve('board', 'stt', 'prior-stt-'+str(index), audio_seconds=1)
                manager.board_speech_ledger.settle(key, 2.)
            before = ledger_snapshot(manager)
            future = time.time()+365*24*3600
            monkeypatch.setattr(time, 'time', lambda: future)
            await session.select_mode('expert')
            assert session.admission_status() == {'mode': 'expert', 'input_allowed': True,
                'generation_allowed': True, 'code': 'available'}
            assert manager.admission_preview(client_id='board', device_id='board')['expert_available']
            status = manager.board_speech_ledger.status()['operations']['stt']
            assert status['attempts'] == 3 and status['estimated_usd_including_pending'] == 6
            assert ledger_snapshot(manager) == before
            assert not session.input_open and not session.experts.jobs
            no_generation(provider)
        finally:
            monkeypatch.undo()
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_permanent_scope_revocation_still_denies_actual_wake_without_spend(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        try:
            assert session.admission_status()['input_allowed']
            for relative in ('policy.json', 'experts/policy.json', 'speech-policy.json'):
                path = board.budget.root/relative
                policy = json.loads(path.read_text())
                path.write_text(json.dumps({**policy, 'enabled': False}))
            before = ledger_snapshot(manager)
            assert not session.admission_status()['input_allowed']
            assert not manager.admission_preview(client_id='board', device_id='board')['allowed']
            with pytest.raises(PermissionError):
                await session.wake('revoked-terminal-question')
            assert not session.input_open and session.state == 'blocked'
            assert ledger_snapshot(manager) == before
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_permanent_terminal_keeps_stalled_input_timeout_and_accepts_next_wake(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup_terminal(tmp_path, settings)
        try:
            await session.wake('stalled-terminal-input')
            session.auto_input_deadline = time.monotonic()-1
            async def wait_closed():
                while session.input_open:
                    await asyncio.sleep(.01)
            await asyncio.wait_for(wait_closed(), 2)
            assert session.state == 'ready' and session.generation_allowed()
            assert not session._maintenance.done()
            assert any(event['type'] == 'input_closed' and event['data'].get('reason') == 'input_time_limit'
                       for event in session.events)
            await session.wake('next-after-input-timeout')
            assert session.input_open and session.state == 'listening'
            await session.stop()
            assert board.budget.board_status()['sessions_reserved'] == 1
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
