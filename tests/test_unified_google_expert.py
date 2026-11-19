"""The finite Google grant owns both explicit and delegated expert selection."""
import asyncio
import json

import httpx
import pytest
from fastapi import FastAPI

from gobot.board_unified import UnifiedBoardRealtime, authorize_proposal, prepare_proposal
from gobot.realtime import TOOLS
from gobot.realtime_ws import DirectRealtimeManager
from gobot.realtime_ws_api import attach_brain_direct_voice
from test_realtime_native import configured
from test_realtime_ws import Provider, offer, cleanup


async def setup(tmp_path, settings, **changes):
    original, _, _ = configured(tmp_path, settings)
    root = tmp_path/'google-board'
    proposal = prepare_proposal(root, 'board', expert_profile='ARGON_DEEP')
    authorize_proposal(root, proposal['proposal_sha256'])
    board = UnifiedBoardRealtime(original, root)
    manager = DirectRealtimeManager(board, provider=Provider())
    session = await manager.accept(offer(expert_quota_consent=True, **changes))
    return original, board, manager, session


def test_fast_tools_and_proposals_use_only_approved_google_profile(tmp_path, settings):
    async def run():
        original, board, manager, session = await setup(tmp_path, settings)
        try:
            tools = (await session.build_config())['tools']
            profile = next(t for t in tools if t['name'] == 'expert_propose')['parameters']['properties']['profile']
            assert profile['enum'] == ['ARGON_DEEP']
            shared = next(t for t in TOOLS if t['name'] == 'expert_propose')
            assert 'SOL_HIGH' in shared['parameters']['properties']['profile']['enum']
            turn = await session.new_turn(query='София, спроси Gemini: сравни два решения')
            with pytest.raises(PermissionError, match='expert_profile_not_in_budget'):
                session.experts.propose(turn.query, 'SOL_HIGH', turn)
            assert not session.experts.jobs
            proposal = session.experts.propose(turn.query, 'ARGON_DEEP', turn)
            assert proposal['confirmed']
            assert session.experts.pending.profile['provider'] == 'antigravity'
            assert session.experts.pending.profile['model'] == 'gemini-4-argon-medium'
            assert session.experts.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_wrong_explicit_profile_is_blocked_before_any_stt_or_cli_reserve(tmp_path, settings):
    async def run():
        original, board, manager, session = await setup(tmp_path, settings, requested_expert_profile='SOL_HIGH')
        calls = []
        manager.transcription_authorizer = lambda s: calls.append('stt')
        try:
            await session.select_mode('expert')
            with pytest.raises(PermissionError, match='expert_profile_not_in_budget'):
                await session.wake('wrong-profile')
            assert calls == [] and not session.input_open
            assert session.experts.budget.status()['sessions_reserved'] == 0
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_default_gateway_offer_selects_google_before_transcription_and_reports_metadata(tmp_path, settings):
    async def run():
        original, board, manager, session = await setup(tmp_path, settings)
        observed = []
        class Recognition:
            async def live(self, chunks, **options):
                async for _ in chunks:
                    pass
                yield {'type': 'stt_final', 'data': {
                    'text': 'Сравни два решения', 'stable': True, 'item_id': 'stt-item'}}
        def admit(s):
            observed.append(('stt', s.selected_expert()['profile']))
            return {'paid_consent': True, 'max_audio_seconds': 180, 'operation_timeout_seconds': 240}
        async def start_local(text, profile, turn):
            assert session.expert_input_authorized(turn)
            observed.append(('expert', profile, text))
        manager.recognition = Recognition()
        manager.transcription_authorizer = admit
        session.experts.start_local = start_local
        app = FastAPI()
        attach_brain_direct_voice(app, None, manager, lambda: None, 'fixture')
        try:
            assert session.offer.requested_expert_profile is None
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://fixture') as client:
                status = (await client.get('/api/v1/voice-ws/status', params={
                    'source': 'device', 'device_id': 'board'})).json()
                expert = status['sessions'][0]['selected_expert']
                assert expert == {'profile': 'ARGON_DEEP', 'provider': 'antigravity',
                    'model': 'gemini-4-argon-medium', 'effort': 'medium', 'requested_label': 'Argon Deep'}
                assert 'authorization' not in json.dumps(expert)
            await session.select_mode('expert')
            await session.wake('google-expert')
            assert await session.append_pcm(bytes(4800))
            await session.finish_input()
            await session._stt_task
            assert observed == [('stt', 'ARGON_DEEP'), ('expert', 'ARGON_DEEP', 'Сравни два решения')]
            assert not any(event['type'] == 'input_audio_buffer.append' for event in session.ws.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
