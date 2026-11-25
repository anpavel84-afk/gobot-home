"""Read-only availability and expiry reporting; synthetic providers/temporary ledgers."""
import asyncio
import json
import threading
import time

import pytest

from gobot.board_unified import UnifiedBoardRealtime
from gobot.realtime_ws import DirectRealtimeManager
from gobot.unified_voice_budget import UnifiedVoiceBudget
from gobot.unified_voice_journal import KINDS, metadata
from test_realtime_native import configured
from test_realtime_ws import Provider, offer, cleanup
from test_unified_joint_review_grant import activate_fixture
from test_unified_voice_budget import SpeechFixture


async def setup(tmp_path, settings):
    original, _, _ = configured(tmp_path, settings)
    root = tmp_path/'joint-board'
    activate_fixture(root)
    board = UnifiedBoardRealtime(original, root)
    authority = UnifiedVoiceBudget(max_expert_audio_seconds=180, expert_operation_timeout_seconds=240)
    provider = Provider()
    manager = DirectRealtimeManager(board, provider=provider, speech=SpeechFixture(),
        transcription_authorizer=authority.transcription, narrator_authorizer=authority.narrator)
    session = await manager.accept(offer(expert_quota_consent=True))
    return original, board, manager, session, provider


def events(session):
    return [event['data'] for event in session.events if event['type'] == 'admission_status']


def no_generation(provider):
    assert not any(event['type'] in {'input_audio_buffer.append', 'response.create'}
                   for socket in provider.sockets for event in socket.sent)


def ledger_snapshot(manager):
    result = {}
    for label, budget in [('fast', manager.budget), ('expert', manager.public_expert_budget),
                          ('owner', manager.owner_testing)]:
        with budget.connect() as db:
            result[label] = '\n'.join(db.iterdump())
    return result


def test_initial_availability_is_after_ready_and_reserves_nothing(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        try:
            kinds = [event['type'] for event in session.events]
            assert kinds.index('ready') < kinds.index('admission_status')
            assert events(session) == [{'mode': 'fast', 'input_allowed': True,
                                       'generation_allowed': True, 'code': 'available'}]
            before = ledger_snapshot(manager)
            await session.publish_admission_status()
            await session.publish_admission_status()
            assert len(events(session)) == 1
            assert ledger_snapshot(manager) == before
            assert board.budget.board_status()['sessions_remaining'] == 3
            assert manager.board_speech_ledger.status()['operations'] == {}
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_expired_unused_scope_denies_with_expiry_reason_and_retains_three_starts(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        try:
            expiry = board.budget.policy().expires_at
            before = ledger_snapshot(manager)
            grant_bytes = {path: path.read_bytes() for path in board.budget.root.rglob('*.json')}
            monkeypatch.setattr(time, 'time', lambda: expiry+1)
            with pytest.raises(PermissionError, match='^realtime_budget_expired$'):
                await session.wake('after-expiry')
            assert not session.input_open and session.state == 'blocked'
            denial = [e['data'] for e in session.events if e['type'] == 'admission_denied'][-1]
            assert denial['reason'] == 'realtime_budget_expired'
            assert denial['generation_allowed'] is False
            assert session.admission_status() == {'mode': 'fast', 'input_allowed': False,
                                                 'generation_allowed': False, 'code': 'scope_expired'}
            status = board.budget.board_status()
            assert status['enabled'] is False and status['sessions_remaining'] == 3
            assert ledger_snapshot(manager) == before
            assert all(path.read_bytes() == raw for path, raw in grant_bytes.items())
            assert not session._admission_attempts
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_idle_expiry_publishes_one_transition_without_closing_ready_transport(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        try:
            before = ledger_snapshot(manager)
            expiry = board.budget.policy().expires_at
            monkeypatch.setattr(time, 'time', lambda: expiry+1)
            session._admission_checked_at -= 2
            await asyncio.sleep(.2)
            assert events(session)[-1]['code'] == 'scope_expired'
            assert len(events(session)) == 2
            await asyncio.sleep(1.1)
            assert len(events(session)) == 2
            assert session.ready and session.attached and session.state == 'ready'
            assert not session.closed and not session.input_open
            assert len(provider.sockets) == 1
            assert ledger_snapshot(manager) == before
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('active_kind', ['output', 'expert'])
def test_expiry_advertisement_does_not_interrupt_output_or_expert(tmp_path, settings, monkeypatch, active_kind):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        try:
            if active_kind == 'output':
                session.output_owner, session.output_response = 'fast_answer', 'synthetic-output'
                session.speaking, session.state = True, 'speaking'
            else:
                session.experts.active = lambda: True
                session.state = 'thinking'
            expected = (session.state, session.speaking, session.output_owner,
                        session.output_response, session._input_gate_epoch)
            before = ledger_snapshot(manager)
            expiry = board.budget.policy().expires_at
            monkeypatch.setattr(time, 'time', lambda: expiry+1)
            session._admission_checked_at -= 2
            previous_events = len(session.events)
            await session.publish_admission_status()
            assert (session.state, session.speaking, session.output_owner,
                    session.output_response, session._input_gate_epoch) == expected
            assert [event['type'] for event in list(session.events)[previous_events:]] == ['admission_status']
            assert events(session)[-1]['code'] == 'scope_expired'
            assert ledger_snapshot(manager) == before
            no_generation(provider)
        finally:
            session.experts.active = lambda: False
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_start_exhaustion_is_not_expiry_and_current_last_operation_keeps_responses(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        try:
            for index in range(2):
                board.budget.reserve_session('fixture-prior-'+str(index), True, 'board')
            await session.wake('last-start')
            await session.stop()
            assert board.budget.board_status()['sessions_remaining'] == 0
            assert session.admission_status()['code'] == 'available'
            assert session.generation_allowed()
            session.operation_started -= 181
            assert session.admission_status() == {'mode': 'fast', 'input_allowed': False,
                                                 'generation_allowed': False, 'code': 'starts_exhausted'}
            before = ledger_snapshot(manager)
            with pytest.raises(PermissionError, match='budget_exhausted'):
                await session.wake('no-fourth-start')
            assert ledger_snapshot(manager) == before
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_expert_remains_available_after_fast_starts_exhausted_and_preview_never_reserves(tmp_path, settings):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        try:
            for index in range(3):
                board.budget.reserve_session('fixture-prior-'+str(index), True, 'board')
            assert session.admission_status()['code'] == 'starts_exhausted'
            before = ledger_snapshot(manager)
            previous_events = len(session.events)
            await session.select_mode('expert')
            assert [e['type'] for e in list(session.events)[previous_events:]] == ['mode_selected', 'admission_status']
            assert events(session)[-1] == {'mode': 'expert', 'input_allowed': True,
                                          'generation_allowed': False, 'code': 'available'}
            assert ledger_snapshot(manager) == before
            assert manager.board_speech_ledger.status()['operations'] == {}
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('blocker', ['expert_count', 'stt_count', 'speech_estimate', 'unknown_authorizer'])
def test_expert_preview_respects_job_and_stt_constraints(tmp_path, settings, blocker):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        try:
            if blocker == 'expert_count':
                for index in range(2):
                    manager.public_expert_budget.reserve_session('prior-'+str(index), True, 'board')
            elif blocker in {'stt_count', 'speech_estimate'}:
                key = manager.board_speech_ledger.reserve('board', 'stt', 'prior-1', audio_seconds=1)
                if blocker == 'stt_count':
                    manager.board_speech_ledger.settle(key, .01)
                    key = manager.board_speech_ledger.reserve('board', 'stt', 'prior-2', audio_seconds=1)
                    manager.board_speech_ledger.settle(key, .01)
                else:
                    # One outstanding STT plus another permitted narrator hold
                    # uses the estimate, while the second STT count is unspent.
                    manager.board_speech_ledger.reserve('board', 'tts', 'prior-tts', job_id='prior-job')
            else:
                async def unknown_authorizer(_):
                    raise AssertionError('preview_must_not_invoke_authorizer')
                manager.transcription_authorizer = unknown_authorizer
            before = ledger_snapshot(manager)
            await session.select_mode('expert')
            assert events(session)[-1]['input_allowed'] is False
            assert events(session)[-1]['generation_allowed'] is True
            assert events(session)[-1]['code'] == ('unavailable' if blocker == 'unknown_authorizer' else 'starts_exhausted')
            assert ledger_snapshot(manager) == before
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('blocker', ['consent', 'expert_consent', 'invalid_policy'])
def test_missing_consent_and_invalid_policy_have_distinct_fixed_codes(tmp_path, settings, monkeypatch, blocker):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        try:
            if blocker == 'consent':
                session.offer.consent = False
            elif blocker == 'expert_consent':
                session.offer.expert_quota_consent = False
                await session.select_mode('expert')
            else:
                def invalid_policy():
                    raise ValueError('private arbitrary policy diagnostic')
                monkeypatch.setattr(board.budget, 'policy', invalid_policy)
            before = ledger_snapshot(manager)
            status = session.admission_status()
            assert not status['input_allowed']
            assert status['code'] == ('unavailable' if blocker == 'invalid_policy' else 'consent_required')
            assert 'private' not in json.dumps(status)
            if blocker == 'consent':
                with pytest.raises(PermissionError, match='^realtime_consent_required$'):
                    await session.wake('missing-consent')
            assert ledger_snapshot(manager) == before
            no_generation(provider)
        finally:
            monkeypatch.undo()
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_periodic_check_is_rate_limited_and_reattach_replays_status_after_ready(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        try:
            calls = []
            original_status = session.admission_status
            def counted_status():
                calls.append(True)
                return original_status()
            monkeypatch.setattr(session, 'admission_status', counted_status)
            await session.publish_admission_status()
            await session.publish_admission_status()
            assert calls == []
            session._admission_checked_at -= 2
            await session.publish_admission_status()
            assert calls == [True]
            assert len(events(session)) == 1  # Unchanged snapshots are not re-advertised.
            await session.detach()
            previous_events = len(session.events)
            await session.reattach()
            kinds = [e['type'] for e in list(session.events)[previous_events:]]
            assert kinds.index('ready') < kinds.index('admission_status')
            assert len(events(session)) == 2
            assert board.budget.board_status()['sessions_remaining'] == 3
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_slow_snapshot_for_old_mode_cannot_overwrite_new_mode(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        entered, release = threading.Event(), threading.Event()
        pending = switch = None
        try:
            original_status = session.admission_status
            def delayed_status():
                value = original_status()
                entered.set()
                assert release.wait(2)
                return value
            monkeypatch.setattr(session, 'admission_status', delayed_status)
            previous_events = len(session.events)
            pending = asyncio.create_task(session.publish_admission_status(force=True))
            assert await asyncio.to_thread(entered.wait, 1)
            switch = asyncio.create_task(session.select_mode('expert'))
            # Selecting expert now reads the current restrictive owner flag.
            # Wait for the observable mode transition, not one scheduler tick.
            async with asyncio.timeout(1):
                while session.selected_mode != 'expert':
                    await asyncio.sleep(.001)
            assert session.selected_mode == 'expert'
            release.set()
            await asyncio.gather(pending, switch)
            newer = list(session.events)[previous_events:]
            assert [event['type'] for event in newer] == ['mode_selected', 'admission_status']
            assert newer[-1]['data']['mode'] == 'expert' and newer[-1]['data']['input_allowed']
            no_generation(provider)
        finally:
            release.set()
            await asyncio.gather(*(t for t in (pending, switch) if t is not None), return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_expiry_crossing_actual_reservation_is_still_classified_without_consumption(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        try:
            expiry = board.budget.policy().expires_at
            reserve = board.budget.reserve_session
            before = ledger_snapshot(manager)
            def expire_at_reservation(*args, **kwargs):
                monkeypatch.setattr(time, 'time', lambda: expiry+1)
                return reserve(*args, **kwargs)
            monkeypatch.setattr(board.budget, 'reserve_session', expire_at_reservation)
            with pytest.raises(PermissionError, match='^realtime_budget_expired$'):
                await session.wake('boundary')
            assert ledger_snapshot(manager) == before
            assert not session._admission_attempts and not session.input_open
            assert board.budget.board_status()['sessions_remaining'] == 3
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_admission_journal_has_only_fixed_fields_and_codes():
    assert 'admission_status' in KINDS
    assert metadata({'mode': 'expert', 'input_allowed': True, 'generation_allowed': False,
                     'code': 'available', 'text': 'must not be retained', 'audio': 'secret'}) == {
        'mode': 'expert', 'input_allowed': True, 'generation_allowed': False, 'code': 'available'}
    assert metadata({'code': 'arbitrary sensitive string', 'input_allowed': 1}) == {'code': 'other'}


@pytest.mark.parametrize('active_kind', ['input', 'output'])
def test_unexpected_display_preview_failure_does_not_end_maintenance_or_active_work(tmp_path, settings, monkeypatch, active_kind):
    async def run():
        original, board, manager, session, provider = await setup(tmp_path, settings)
        try:
            await session.select_mode('expert')
            if active_kind == 'input':
                session.input_open, session.state = True, 'listening'
            else:
                session.output_owner, session.output_response = 'expert_answer', 'physical-owner'
                session.speaking, session.state = True, 'speaking'
            expected = (session.input_open, session.state, session.speaking,
                        session.output_owner, session.output_response, session._input_gate_epoch)
            before = ledger_snapshot(manager)
            actual_status = session.experts.status
            def failed_preview(*, include_profiles=True):
                # Expert status reads a mutable jobs mapping from a worker.
                # Any unexpected inspection failure must stay in the UI path.
                raise RuntimeError('dictionary changed size during iteration')
            monkeypatch.setattr(session.experts, 'status', failed_preview)
            session._admission_checked_at -= 2

            async def wait_code(code):
                while not events(session) or events(session)[-1]['code'] != code:
                    await asyncio.sleep(.01)
            await asyncio.wait_for(wait_code('unavailable'), 2)
            assert not session._maintenance.done()
            assert (session.input_open, session.state, session.speaking,
                    session.output_owner, session.output_response, session._input_gate_epoch) == expected
            assert not any(e['type'] == 'error' and e['data'].get('code') == 'voice_maintenance_failed'
                           for e in session.events)
            assert events(session)[-1] == {'mode': 'expert', 'input_allowed': False,
                                          'generation_allowed': False, 'code': 'unavailable'}
            assert ledger_snapshot(manager) == before
            no_generation(provider)

            monkeypatch.setattr(session.experts, 'status', actual_status)
            session._admission_checked_at -= 2
            await asyncio.wait_for(wait_code('available'), 2)
            assert not session._maintenance.done()
            assert (session.input_open, session.state, session.speaking,
                    session.output_owner, session.output_response, session._input_gate_epoch) == expected
            assert ledger_snapshot(manager) == before
            no_generation(provider)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
