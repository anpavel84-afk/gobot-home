"""Elapsed-idle and rotation regressions using local ledgers/fake sockets only."""
import asyncio
import time

import pytest

from test_realtime_ws import cleanup, offer, setup
from test_unified_board_admission import offline_expert_registry, setup as expert_setup


async def expire_detached(manager, session):
    await session.detach()
    session.detached_at -= 3601
    return await manager.close(session.id, session.offer.device_id,
                               session.offer.client_id, session.offer.profile_epoch,
                               'detached_expired')


def assert_no_generation(board, provider):
    assert board.budget.status()['sessions_reserved'] == 0
    assert not any(e['type'] in {'response.create', 'input_audio_buffer.append'}
                   for socket in provider.sockets for e in socket.sent)


def test_hours_of_empty_idle_do_not_spend_detached_retention(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings, enabled=False)
        try:
            session = await manager.accept(offer())
            session.started -= 5*3600
            session.last_activity -= 5*3600
            await session.detach()
            first_detach = session.detached_at
            assert not session.detached_expired()
            await asyncio.sleep(.25)  # Two real maintenance ticks, not a fake TTL clock.
            assert not session.closed and not session._maintenance.done()
            await session.detach()
            assert session.detached_at == first_detach
            restored = await manager.accept(offer())
            assert restored is session and restored.detached_at is None
            assert restored.attached and restored.ready and not restored.input_open
            assert_no_generation(board, provider)
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def test_stale_expiry_observation_cannot_close_concurrent_reattach(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings, enabled=False)
        gate, entered = asyncio.Event(), asyncio.Event()
        try:
            session = await manager.accept(offer())
            await session.detach()
            session.detached_at -= 3601
            assert session.detached_expired()
            attach = session.experts.attach
            async def held(current):
                entered.set()
                await gate.wait()
                await attach(current)
            session.experts.attach = held
            reconnect = asyncio.create_task(manager.accept(offer()))
            async with asyncio.timeout(3): await entered.wait()
            assert session.attached  # Lease claimed before the async context restore.
            result = await manager.close(session.id, 'board', 'board', None, 'detached_expired')
            assert result == {'closed': False} and not session.closed
            gate.set()
            assert await reconnect is session
            assert session.detached_at is None and not session._closing
            assert_no_generation(board, provider)
        finally:
            gate.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_only_full_detached_ttl_closes_and_empty_restore_is_exact_and_bounded(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings, enabled=False)
        try:
            session = await manager.accept(offer())
            await session.detach()
            session.detached_at -= 3599
            assert await manager.close(session.id, 'board', 'board', None, 'detached_expired') == {'closed': False}
            session.detached_at -= 2
            async with asyncio.timeout(3):
                while not session.closed: await asyncio.sleep(.02)
            # Cleanup must finish before accepting a replacement transport.
            async with asyncio.timeout(3):
                while session._closing: await asyncio.sleep(.02)
            assert session.close_reason == 'detached_expired'
            assert session.lifecycle_status()['empty_restore_eligible']
            with pytest.raises(PermissionError, match='identity_mismatch'):
                await manager.accept(offer().model_copy(update={'conversation_id': 'foreign'}))
            restored = await manager.accept(offer())
            assert restored is not session and restored.ready and not restored.input_open
            assert restored.id == session.id and not restored.generation_allowed()
            await expire_detached(manager, restored)
            third = await manager.accept(offer())
            await expire_detached(manager, third)
            with pytest.raises(ValueError, match='empty_setup_retry_rate_limited'):
                await manager.accept(offer())
            assert len(provider.sockets) == 3 and len(manager.sessions) == 1
            assert_no_generation(board, provider)
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('reason', ['closed', 'server_shutdown'])
def test_explicit_empty_close_stays_a_tombstone(tmp_path, settings, reason):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await manager.close(session.id, 'board', 'board', None, reason)
            assert not session.lifecycle_status()['empty_restore_eligible']
            with pytest.raises(ValueError, match='logical_conversation_closed'):
                await manager.accept(offer())
            assert len(provider.sockets) == 1
            assert_no_generation(board, provider)
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('activity', ['paid', 'pending'])
def test_used_or_unknown_closed_conversation_is_never_empty_restore(tmp_path, settings, activity):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            if activity == 'paid': await session.wake('paid-wake')
            else: session.pending_reservation = 'existing-unknown-hold'
            reserved = board.budget.status()['sessions_reserved']
            await expire_detached(manager, session)
            assert not session._empty_detached_expired
            with pytest.raises(ValueError, match='logical_conversation_closed'):
                await manager.accept(offer())
            assert board.budget.status()['sessions_reserved'] == reserved
            assert len(provider.sockets) == 1
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def test_cancel_after_durable_b_reserve_before_assignment_keeps_unknown_tombstone(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        gate, reserved = asyncio.Event(), asyncio.Event()
        original_thread = asyncio.to_thread
        reserve = manager.budget.reserve_session
        async def hold(func, *args, **kwargs):
            result = await original_thread(func, *args, **kwargs)
            if func == reserve:
                reserved.set()
                await gate.wait()
            return result
        monkeypatch.setattr(asyncio, 'to_thread', hold)
        try:
            session = await manager.accept(offer())
            wake = asyncio.create_task(session.wake('interrupted-reserve'))
            async with asyncio.timeout(3): await reserved.wait()
            wake.cancel()
            await asyncio.gather(wake, return_exceptions=True)
            assert session.operation_id is None and session._admission_attempts
            assert board.budget.status()['sessions_reserved'] == 1
            await expire_detached(manager, session)
            with pytest.raises(ValueError, match='logical_conversation_closed'):
                await manager.accept(offer())
            assert board.budget.status()['sessions_reserved'] == 1
            assert len(provider.sockets) == 1
        finally:
            gate.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_cancel_after_durable_stt_hold_before_assignment_keeps_unknown_tombstone(tmp_path, settings):
    async def run():
        original, board, manager, session, _ = await expert_setup(tmp_path, settings)
        gate, reserved = asyncio.Event(), asyncio.Event()
        original_authorizer = manager.transcription_authorizer
        session.experts.status = lambda **kwargs: {'enabled': True}
        async def hold(current):
            result = await original_authorizer(current)
            reserved.set()
            await gate.wait()
            return result
        manager.transcription_authorizer = hold
        try:
            wake = asyncio.create_task(session.wake('interrupted-stt-reserve', mode='expert'))
            async with asyncio.timeout(3): await reserved.wait()
            wake.cancel()
            await asyncio.gather(wake, return_exceptions=True)
            assert session._stt_reservation is None and session._admission_attempts
            await expire_detached(manager, session)
            with pytest.raises(ValueError, match='logical_conversation_closed'):
                await manager.accept(session.offer)
            assert manager.board_speech_ledger.status()['operations']['stt']['pending_usage'] == 1
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            gate.set()
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_definite_denial_remains_empty_without_clearing_any_ledger(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings, enabled=False)
        try:
            session = await manager.accept(offer())
            with pytest.raises(PermissionError): await session.wake('denied')
            assert not session._admission_attempts
            await expire_detached(manager, session)
            assert session._empty_detached_expired
            restored = await manager.accept(offer())
            assert not restored.input_open and not restored.generation_allowed()
            assert_no_generation(board, provider)
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def test_prepared_spare_rechecks_scope_before_context_or_adoption(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            old, old_reader = session.ws, session.reader
            session._spare = await session.configured_transport()
            spare = session._spare[1]
            changed = board.budget.policy().model_copy(update={'allowed_client_id': 'another-device'})
            board.budget.policy_path.write_text(changed.model_dump_json())
            def forbidden(_): raise AssertionError('Scope must be checked before reading context')
            monkeypatch.setattr(manager.brain.memory, 'context', forbidden)
            with pytest.raises(PermissionError, match='warm_transport_scope_changed'):
                await session.rotate()
            assert session.ws is old and session.reader is old_reader and session.transport_epoch == 1
            assert session.ready and not old_reader.done() and spare.closed and session._spare is None
            assert len(provider.sockets) == 2
            assert_no_generation(board, provider)
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def test_maintenance_prepares_and_refreshes_spare_without_old_reader_disconnect(tmp_path, settings):
    async def run():
        original, board, manager, provider = setup(tmp_path, settings, enabled=False)
        try:
            session = await manager.accept(offer())
            old, old_reader = session.ws, session.reader
            original_config = session.build_config
            snapshots = []
            async def fresh():
                config = await original_config()
                snapshots.append(len(snapshots)+1)
                config['instructions'] += '\nPublic context snapshot '+str(len(snapshots))
                return config
            session.build_config = fresh
            session.transport_started -= 51*60+1
            async with asyncio.timeout(3):
                while (await session.next_event())['type'] != 'transport_rotated': pass
            await asyncio.sleep(0)
            assert snapshots == [1, 2]  # Prepared once, refreshed at adoption.
            assert session.config['instructions'].endswith('Public context snapshot 2')
            assert session.transport_epoch == 2 and session.ready and session.attached
            assert old.closed and old_reader.done() and not session.reader.done()
            assert not session._maintenance.done() and session._spare is None
            assert_no_generation(board, provider)
        finally: await cleanup(original, board, manager)
    asyncio.run(run())


def test_lifecycle_diagnostics_never_expose_arbitrary_reason_text(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings, enabled=False)
        try:
            session = await manager.accept(offer())
            await session.detach(reason='private arbitrary phrase')
            session.close_reason = 'private arbitrary close'
            state = session.lifecycle_status()
            assert state['last_detach_reason'] == state['close_reason'] == 'other'
            assert 'private' not in str(state)
        finally: await cleanup(original, board, manager)
    asyncio.run(run())
