"""Unified A exercises the actual Brain/SQLite through ASGI, without providers."""
import asyncio
import time
from types import SimpleNamespace

import httpx
import pytest

from gobot.brain import create_app
from gobot.conversation_modes import ModeConversation
from gobot.models import ChatRequest
from gobot.owner_testing import OwnerTestPolicy
from gobot.realtime_budget import RealtimeBudget


@pytest.fixture
def legacy_scope(tmp_path, settings, monkeypatch):
    import gobot.brain as brain_module
    import gobot.realtime as realtime_module

    monkeypatch.setattr(realtime_module, 'RealtimeBudget',
                        lambda *args, **kwargs: RealtimeBudget(tmp_path / 'native-budget'))
    monkeypatch.setattr(brain_module, 'agent_status', lambda *args, **kwargs: {})
    calls = []

    def forbidden_bridge(*args, **kwargs):
        calls.append('cli')
        raise AssertionError('No CLI in this offline fixture')

    async def forbidden_provider(*args, **kwargs):
        calls.append('provider')
        raise AssertionError('No native provider in this offline fixture')

    monkeypatch.setattr(brain_module, 'bridge_stream', forbidden_bridge)
    app = create_app(settings)
    manager = app.state.live
    monkeypatch.setattr(manager.provider, 'create', forbidden_provider)
    monkeypatch.setattr(manager.realtime.provider, 'create', forbidden_provider)
    profile = manager.brain.configuration.devices.profile('browser-fixture@local')
    manager.owner_testing.policy_path.write_text(OwnerTestPolicy(
        enabled=True, authorization='synthetic-fixture', allowed_client_id=profile.client_id,
        live_enabled=True).model_dump_json())
    flow = ModeConversation('browser-fixture', profile.client_id, 'fixture-epoch', profile.client_id, mode='legacy')
    manager.modes.items[flow.id] = flow
    probe = ChatRequest(text='Контекст', device_id=flow.scope, conversation_id=flow.conversation,
                        client_id=flow.client, profile_epoch=flow.epoch, remember=False)
    return SimpleNamespace(app=app, manager=manager, brain=manager.brain, flow=flow, calls=calls,
                           guest=probe, timer=probe.model_copy(update={'device_id': 'realtime-device:' + flow.client}),
                           settings=probe.model_copy(update={'device_id': flow.owner}), token=settings.api_token)


def client_for(scope):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=scope.app), base_url='http://fixture',
                             headers={'Authorization': 'Bearer ' + scope.token})


async def say(client, scope, text, **overrides):
    response = await client.post('/api/v1/chat/voice/stream', json={
        'text': text, 'device_id': scope.flow.owner, 'client_id': scope.flow.client,
        'profile_epoch': scope.flow.epoch, 'mode_conversation_id': scope.flow.id,
        'speak': False, 'remember': True, 'screen_preferences': {'automatic_illustrations': False},
        **overrides})
    return response


def timers(scope):
    with scope.brain.memory.connect() as connection:
        return [dict(row) for row in connection.execute('SELECT id,device_id,deadline,status FROM timers')]


async def shutdown(scope):
    await scope.manager.shutdown()
    await scope.manager.realtime.shutdown()
    assert scope.calls == []


def test_quantity_is_consumed_in_one_timer_namespace_and_cannot_repeat(legacy_scope):
    scope = legacy_scope

    async def run():
        try:
            async with client_for(scope) as client:
                response = await say(client, scope, 'Поставь таймер на пять')
                assert response.status_code == 200 and 'секунды, минуты или часы' in response.text
                assert timers(scope) == []
                pending = scope.brain.memory.context(scope.timer)['pending_action']
                assert pending['kind'] == 'timer_duration' and pending['payload']['quantity'] == 'пять'
                assert not scope.brain.memory.context(scope.guest)['pending_action']
                assert not scope.brain.memory.context(scope.settings)['pending_action']
                response = await say(client, scope, 'Минут')
                assert response.status_code == 200 and 'timer_widget' in response.text
                assert len(timers(scope)) == 1 and timers(scope)[0]['device_id'] == scope.timer.device_id
                assert 295 < timers(scope)[0]['deadline'] - time.time() <= 300
                assert not scope.brain.memory.context(scope.timer)['pending_action']
                assert not scope.brain.memory.context(scope.guest)['pending_action']
                # There is no pending quantity now. An unconfigured reasoning provider
                # may decline this fragment, but it must never start another timer.
                response = await say(client, scope, 'Минут')
                assert response.status_code == 200 and 'timer_widget' not in response.text
                assert len(timers(scope)) == 1
                with scope.brain.memory.connect() as connection:
                    assert connection.execute('SELECT count(*) FROM conversations').fetchone()[0] == 0
        finally:
            await shutdown(scope)
    asyncio.run(run())


@pytest.mark.parametrize('decline', ['Нет, спасибо', 'Нет'])
def test_timer_decline_uses_pending_namespace_and_keeps_unified_flow(legacy_scope, decline):
    scope = legacy_scope

    async def run():
        try:
            async with client_for(scope) as client:
                assert (await say(client, scope, 'Поставь таймер')).status_code == 200
                assert scope.brain.memory.context(scope.timer)['pending_action']['kind'] == 'timer_duration'
                response = await say(client, scope, decline)
                assert response.status_code == 200 and 'pending_declined' in response.text
                assert scope.flow.active and scope.flow.mode == 'legacy'
                assert not scope.brain.memory.context(scope.timer)['pending_action']
                await say(client, scope, 'На пять минут')
                assert timers(scope) == []
        finally:
            await shutdown(scope)
    asyncio.run(run())


def test_decline_selects_latest_settings_namespace_without_cancelling_another_pending(legacy_scope):
    scope = legacy_scope
    timer = scope.brain.memory.set_pending(scope.timer, 'timer_duration', {'quantity': 'пять'})
    timer['expires'] = time.time() + 60
    settings = scope.brain.configuration.pending(scope.settings, 'weather_city')

    async def run():
        try:
            context, _, _ = await scope.brain.tool_context(scope.guest, scope.flow)
            assert context['pending_namespace'] == 'settings' and context['pending_action']['id'] == settings['id']
            async with client_for(scope) as client:
                response = await say(client, scope, 'Нет, спасибо')
                assert response.status_code == 200 and 'pending_declined' in response.text
                assert scope.flow.active and scope.flow.mode == 'legacy'
                assert not scope.brain.memory.context(scope.settings)['pending_action']
                assert scope.brain.memory.context(scope.timer)['pending_action']['id'] == timer['id']
                await say(client, scope, 'Нет')
                assert not scope.brain.memory.context(scope.timer)['pending_action']
                assert timers(scope) == []
        finally:
            await shutdown(scope)
    asyncio.run(run())


def test_temporary_weather_query_decline_is_ram_only_and_does_not_end_flow(legacy_scope):
    scope = legacy_scope
    original = scope.brain.configuration.devices.profile('browser-fixture@local').model_dump()
    pending = scope.brain.configuration._set_weather_query_pending(
        scope.settings, 'weather_query_location', {'operation': 'weather_forecast', 'offset': 1})

    async def run():
        try:
            context, _, _ = await scope.brain.tool_context(scope.guest, scope.flow)
            assert context['pending_namespace'] == 'weather_query' and context['pending_action']['id'] == pending['id']
            async with client_for(scope) as client:
                response = await say(client, scope, 'Нет, спасибо')
                assert response.status_code == 200 and 'pending_declined' in response.text
                assert not scope.brain.configuration.weather_query_context(scope.settings)
                assert scope.flow.active and scope.flow.mode == 'legacy'
                assert scope.brain.configuration.devices.profile('browser-fixture@local').model_dump() == original
        finally:
            await shutdown(scope)
    asyncio.run(run())


def test_timer_snapshot_and_pending_keep_client_epoch_and_conversation_binding(legacy_scope):
    scope = legacy_scope

    async def run():
        try:
            first = scope.brain.tools.execute('timer', scope.timer, {'seconds': 300})
            second = scope.brain.tools.execute('timer', scope.timer, {'seconds': 600})
            async with client_for(scope) as client:
                assert (await say(client, scope, 'Покажи таймеры')).status_code == 200
                context, _, _ = await scope.brain.tool_context(scope.guest, scope.flow)
                assert context['timer_list_ids'] == [first.evidence['timer_id'], second.evidence['timer_id']]
                assert context['timer_followup']
                assert not scope.brain.tools.timer_context(scope.timer.model_copy(update={'client_id': 'other-client'}))
                for overrides in ({'client_id': 'other-client'}, {'profile_epoch': 'other-epoch'},
                                  {'device_id': 'other-owner'}):
                    response = await say(client, scope, 'Отмени второй', **overrides)
                    assert response.status_code == 403
                response = await say(client, scope, 'Отмени второй')
                assert response.status_code == 200 and 'cancelled_ids' in response.text
                assert {row['id']: row['status'] for row in timers(scope)} == {
                    first.evidence['timer_id']: 'running', second.evidence['timer_id']: 'cancelled'}
                wrong_epoch = scope.timer.model_copy(update={'profile_epoch': 'other-epoch'})
                scope.brain.memory.set_pending(wrong_epoch, 'timer_duration', {'quantity': 'два'})
                context, _, _ = await scope.brain.tool_context(scope.guest, scope.flow)
                assert not context.get('pending_action')
        finally:
            await shutdown(scope)
    asyncio.run(run())
