"""Expired finite input must leave the real wake path idle, with no refill."""
import asyncio
import json

import pytest

from test_realtime_ws import setup, offer, cleanup
from test_sophia_gateway import connection


def test_expired_pcm_closes_input_without_detaching_or_admitting_another_start(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            await s.wake('first')
            s.operation_started -= 61
            assert not await s.append_pcm(bytes(2880))
            assert s.ready and s.attached and not s.closed and not s.input_open
            assert s.input_mode == 'idle' and s.state == 'ready'
            assert s.followup_deadline is None
            assert board.budget.status()['sessions_reserved'] == 1
            assert not any(e['type'] == 'input_audio_buffer.append' for e in s.ws.sent)
            terminal = [e for e in list(s.outgoing._queue) if e and e['type'] == 'input_closed'][-1]
            assert terminal['data']['generation_allowed'] is True
            # Only the next explicit wake may consume another finite start.
            assert (await s.wake('next'))['accepted']
            assert board.budget.status()['sessions_reserved'] == 2
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_expired_last_start_is_blocked_not_listening_and_never_refilled(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            await s.wake('first')
            for index in range(7):
                board.budget.reserve_session('other-'+str(index), True, 'board')
            s.operation_started -= 61
            s._input_started = True
            s.followup_deadline = None
            await asyncio.sleep(.2)
            assert not s.input_open and s.input_mode == 'idle' and s.state == 'blocked'
            assert s.ready and s.attached and not s.generation_allowed()
            assert s._maintenance and not s._maintenance.done()
            with pytest.raises(PermissionError):
                await s.wake('later')
            assert board.budget.status()['sessions_reserved'] == 8
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_stale_expiry_cannot_close_a_new_input_generation(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            s = await manager.accept(offer())
            await s.wake('first')
            previous = s._input_gate_epoch
            await s.stop()
            await s.wake('next')
            before = len(s.ws.sent)
            assert not await s.close_fast_input('paid_operation_expired_new_wake_required', input_epoch=previous)
            assert s.input_open and s.state == 'listening'
            assert len(s.ws.sent) == before
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('kind,reason', [
    ('input_closed', 'paid_operation_expired_new_wake_required'),
    ('followup_closed', 'paid_operation_expired_new_wake_required'),
    ('admission_denied', 'board_estimated_budget_exhausted'),
])
def test_gateway_finite_closure_releases_physical_wake_and_playback_ring(kind, reason):
    async def run():
        c = connection()
        c.ring.set_blocked(True, reason='playback')
        c.forward = True
        c.stats.update(input_open=True, generation_allowed=True)
        await c.cloud_event({'type': kind, 'data': {
            'reason': reason, 'generation_allowed': False, 'state': 'blocked'}})
        assert not c.forward and not c.stats['input_open'] and not c.ring.blocked
        assert not c.stats['generation_allowed']
        controls = [json.loads(item) for item in c.device.sent]
        assert [e['state'] for e in controls if e['type'] == 'gobot_host_state'] == ['ready']
        card = [e['payload'] for e in controls if e['type'] == 'custom'][-1]
        assert 'Допуск к быстрому разговору закрыт' in card['text']
        assert 'Связь' not in card['text']
        assert c.ring.begin({'wake_id': 'new-local-wake', 'stream_epoch': c.ring.epoch,
                             'detector_sample': c.ring.end})
        assert not c.forward and c.brain.sent == []
    asyncio.run(run())


def test_normal_endpoint_still_waits_for_answer():
    async def run():
        c = connection()
        await c.cloud_event({'type': 'input_closed', 'data': {'reason': 'provider_endpoint'}})
        controls = [json.loads(item) for item in c.device.sent]
        assert [e['state'] for e in controls if e['type'] == 'gobot_host_state'] == ['thinking']
        assert not c.forward
    asyncio.run(run())
