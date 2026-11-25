"""Typed admission display updates never become paid/input/playback controls."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from test_sophia_gateway import connection


def status(*, mode='fast', allowed=False, generation=False, code='scope_expired', **extra):
    return {'type': 'admission_status', 'data': {'mode': mode, 'input_allowed': allowed,
            'generation_allowed': generation, 'code': code, **extra}}


def test_initial_admission_is_unknown_and_recovered_expert_mode_precedes_status():
    async def run():
        c = connection()
        assert c.stats['admission_status'] == {'known': False, 'mode': 'fast'}
        await c.cloud_event({'type': 'ready', 'data': {'input_mode': 'expert',
                            'generation_allowed': False, 'recovered': True}})
        assert c.stats['admission_status'] == {'known': False, 'mode': 'expert'}
        assert c.stats['selected_mode'] == c.mode == 'expert'
        sent_before = len(c.device.sent)
        await c.cloud_event(status(mode='expert', allowed=True, code='available'))
        message = json.loads(c.device.sent[-1])
        assert len(c.device.sent) == sent_before+1
        assert message == {'type': 'gobot_host_admission', 'mode': 'expert',
            'input_allowed': True, 'code': 'available', 'session_id': c.transport, 'epoch': c.epoch}
        assert c.stats['admission_status']['known'] is True
        assert not c.stats['generation_allowed']  # An expert permit is not a fast permit.
        assert c.brain.sent == [] and not c.forward and c.ring.cursor is None
    asyncio.run(run())


def test_admission_update_preserves_active_capture_and_output_and_sends_only_fixed_fields():
    async def run():
        c = connection()
        c.ring.begin({'wake_id': 'existing', 'stream_epoch': 'capture', 'detector_sample': 0})
        cursor = c.ring.cursor
        c.forward = True
        c.stats.update(input_open=True, voice_phase='listening')
        resampler = c.resampler = object()
        output = c.output = {'response_id': 'physical-owner'}
        await c.cloud_event(status(private='never propagate household data', text='hidden'))
        message = json.loads(c.device.sent[0])
        assert message == {'type': 'gobot_host_admission', 'input_allowed': False,
            'code': 'scope_expired', 'mode': 'fast', 'session_id': c.transport, 'epoch': c.epoch}
        assert len(c.device.sent) == 1 and c.brain.sent == []
        assert c.forward and c.stats['input_open'] and c.stats['voice_phase'] == 'listening'
        assert c.output is output and c.resampler is resampler and c.ring.cursor is cursor
        assert 'private' not in json.dumps(c.stats) and 'hidden' not in json.dumps(c.stats)
    asyncio.run(run())


@pytest.mark.parametrize('data', [
    None, 'private', [], {},
    {'mode': 'fast', 'input_allowed': 1, 'generation_allowed': False, 'code': 'available'},
    {'mode': 'fast', 'input_allowed': False, 'generation_allowed': 0, 'code': 'scope_expired'},
    {'mode': 'private', 'input_allowed': False, 'generation_allowed': False, 'code': 'scope_expired'},
    {'mode': 'fast', 'input_allowed': False, 'generation_allowed': False, 'code': {'private': 'hidden'}},
    {'mode': 'fast', 'input_allowed': False, 'generation_allowed': False, 'code': 'private reason'},
    {'mode': 'fast', 'input_allowed': True, 'generation_allowed': False, 'code': 'scope_expired'},
    {'mode': 'fast', 'input_allowed': False, 'generation_allowed': False, 'code': 'available'},
])
def test_invalid_or_inconsistent_admission_status_is_not_transmitted_or_cached(data):
    async def run():
        c = connection()
        await c.cloud_event({'type': 'admission_status', 'data': data})
        assert c.stats['invalid_admission_status'] == 1
        assert c.stats['admission_status'] == {'known': False, 'mode': 'fast'}
        assert c.device.sent == c.brain.sent == []
        assert not c.forward and c.ring.cursor is None
    asyncio.run(run())


def test_mode_change_invalidates_cached_permit_and_ignores_late_previous_mode_status():
    async def run():
        c = connection()
        await c.cloud_event(status(allowed=True, generation=True, code='available'))
        await c.cloud_event({'type': 'mode_selected', 'data': {'mode': 'expert'}})
        assert c.stats['admission_status'] == {'known': False, 'mode': 'expert'}
        count = len(c.device.sent)
        await c.cloud_event(status(allowed=True, generation=True, code='available'))
        assert len(c.device.sent) == count and c.stats['stale_admission_status'] == 1
        assert c.stats['admission_status'] == {'known': False, 'mode': 'expert'}
        await c.cloud_event(status(mode='expert', allowed=True, generation=False, code='available'))
        assert c.stats['admission_status']['input_allowed'] and not c.stats['generation_allowed']
        await c.cloud_event({'type': 'followup', 'data': {'mode': 'fast'}})
        assert c.stats['admission_status'] == {'known': False, 'mode': 'fast'}
        assert c.stats['selected_mode'] == c.mode == 'fast'
        count = len(c.device.sent)
        await c.cloud_event(status(mode='expert', allowed=True, generation=False, code='available'))
        assert len(c.device.sent) == count and c.stats['stale_admission_status'] == 2
        await c.cloud_event(status(allowed=True, generation=True, code='available'))
        assert c.stats['admission_status']['mode'] == 'fast'
        assert c.stats['admission_status']['input_allowed']
        assert c.brain.sent == []
    asyncio.run(run())


def test_closed_admission_still_sends_deliberate_wake_to_authoritative_server():
    async def run():
        c = connection()
        c.cloud_ready.set()
        await c.cloud_event(status())
        c.ring.cursor = SimpleNamespace(wake_id='owner-wake')
        await c.activate({'wake_id': 'owner-wake', 'stream_epoch': 'capture'}, trigger='wake_word')
        assert len(c.brain.sent) == 1
        message = json.loads(c.brain.sent[0])
        assert message['type'] == 'wake' and message['trigger'] == 'wake_word' and message['mode'] == 'fast'
        assert not c.forward and not c.stats['input_open']
        assert c.stats['admission_status']['code'] == 'scope_expired'
    asyncio.run(run())


def test_denial_lifecycle_preserves_specific_fixed_reason_until_next_authoritative_status():
    async def run():
        c = connection()
        await c.cloud_event(status())
        await c.cloud_event({'type': 'admission_denied', 'data': {
            'reason': 'realtime_budget_expired', 'generation_allowed': False, 'mode': 'fast'}})
        assert c.stats['voice_phase'] == 'ready' and not c.forward and not c.stats['input_open']
        assert c.stats['admission_status'] == {'known': True, 'mode': 'fast', 'input_allowed': False,
            'generation_allowed': False, 'code': 'scope_expired'}
        await c.cloud_event(status(allowed=False, generation=True, code='consent_required'))
        assert c.stats['admission_status']['code'] == 'consent_required'
        assert c.stats['generation_allowed'] and not c.stats['admission_status']['input_allowed']
        assert c.brain.sent == []
    asyncio.run(run())


def receipt(**extra):
    return {'event': 'admission_rendered', 'admission_known': True, 'input_allowed': False,
            'mode': 'fast', 'code': 'scope_expired', 'notice_rendered': True,
            'render_revision': 10, 'render_evidence': 'native_framebuffer_invalidated', **extra}


def test_matching_native_receipt_uses_existing_scope_and_retains_only_fixed_evidence():
    async def run():
        c = connection()
        await c.cloud_event(status())
        envelope = {'session_id': c.transport, 'epoch': c.epoch}
        await c.device.queue.put(json.dumps({'type': 'gobot_host_ack', **envelope,
            **receipt(private='not retained', text='household text')}))
        await c.device.queue.put(json.dumps({'type': 'end_test', **envelope}))
        with pytest.raises(ValueError, match='unsupported_sophia_control'):
            await c.receive()
        saved = c.stats['admission_receipt']
        assert saved['notice_rendered'] and saved['code'] == 'scope_expired'
        assert saved['render_evidence'] == 'native_framebuffer_invalidated'
        assert saved['render_revision'] == 10 and saved['receipt_plan_monotonic'] > 0
        assert 'private' not in json.dumps(saved) and 'household' not in json.dumps(saved)
        assert not c.forward and c.output is None and c.ring.cursor is None and c.brain.sent == []
        c.admission_receipt(receipt(render_evidence='native_framebuffer_unchanged', render_revision=11))
        assert c.stats['admission_receipt']['render_evidence'] == 'native_framebuffer_unchanged'
        previous = c.stats['admission_receipt']
        await c.device.queue.put(json.dumps({'type': 'gobot_host_ack', **envelope, 'epoch': 'stale',
                                            **receipt(render_revision=12)}))
        with pytest.raises(ValueError, match='stale_sophia_transport'):
            await c.receive()
        assert c.stats['admission_receipt'] is previous
    asyncio.run(run())


def test_stale_malformed_or_contradictory_receipts_cannot_replace_current_evidence():
    async def run():
        c = connection()
        c.admission_receipt(receipt())
        assert c.stats['admission_receipt'] is None  # No authoritative status yet.
        await c.cloud_event(status())
        c.admission_receipt(receipt())
        saved = c.stats['admission_receipt']
        for patch in (
            {'admission_known': 1}, {'input_allowed': 0}, {'notice_rendered': 'true'},
            {'mode': 'expert'}, {'code': 'private reason'}, {'input_allowed': True},
            {'render_revision': True}, {'render_revision': -1}, {'render_revision': 10**15+1},
            {'render_revision': float('nan')}, {'render_revision': 9},
            {'render_evidence': {'private': 'data'}}, {'render_evidence': 'panel_pixels_visible'},
        ):
            c.admission_receipt(receipt(**patch))
            assert c.stats['admission_receipt'] is saved
        assert c.stats['discarded_admission_receipts'] == 14
        await c.cloud_event(status(allowed=True, generation=True, code='available'))
        assert c.stats['admission_receipt'] is None
        c.admission_receipt(receipt(input_allowed=True, code='available', notice_rendered=True))
        assert c.stats['admission_receipt'] is None  # Cannot claim an expired notice for an allowed mode.
        c.admission_receipt(receipt(input_allowed=True, code='available', notice_rendered=False))
        assert c.stats['admission_receipt']['input_allowed'] is True
        await c.cloud_event({'type': 'mode_selected', 'data': {'mode': 'expert'}})
        assert c.stats['admission_receipt'] is None
        c.admission_receipt(receipt(input_allowed=True, code='available', notice_rendered=False))
        assert c.stats['admission_receipt'] is None
        assert c.brain.sent == [] and not c.forward and c.output is None
    asyncio.run(run())
