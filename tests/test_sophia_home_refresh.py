"""Saved home -> actual provider instructions ACK, with in-memory transport only."""
import asyncio
import json
import sqlite3
from contextlib import asynccontextmanager

import pytest

from gobot.device_contract import DeviceProfile, WeatherPreferences
from gobot.realtime_ws import home_context_revision
from gobot.settings_tools import device_home_context
from test_realtime_ws import Provider, Socket, cleanup, offer, setup


DEVICE = 'spotpear-000000000001'


class HomeSocket(Socket):
    def __init__(self, *, acknowledge=True):
        super().__init__()
        self.acknowledge_home = acknowledge

    async def send(self, raw):
        event = json.loads(raw)
        if event['type'] == 'session.update' and set(event['session']) == {'type', 'instructions'}:
            self.sent.append(event)
            self.config['instructions'] = event['session']['instructions']
            if self.acknowledge_home:
                await self.queue.put({'type': 'session.updated',
                                      'session': json.loads(json.dumps(self.config))})
        else:
            await super().send(raw)


class HomeProvider(Provider):
    def __init__(self, *, acknowledge=True):
        super().__init__()
        self.acknowledge_home = acknowledge

    @asynccontextmanager
    async def open(self, model):
        assert model == 'gpt-realtime-2.1-mini'
        socket = HomeSocket(acknowledge=self.acknowledge_home)
        self.sockets.append(socket)
        try:
            yield socket
        finally:
            await socket.close()


def configured(tmp_path, settings, *, acknowledge=True):
    original, board, manager, _ = setup(tmp_path, settings)
    provider = manager.provider = HomeProvider(acknowledge=acknowledge)
    devices = manager.brain.configuration.devices
    policy = board.budget.policy().model_copy(update={'allowed_client_id': DEVICE})
    board.budget.policy_path.write_text(policy.model_dump_json())
    profile = DeviceProfile(client_id=DEVICE, client_kind='spotpear', weather=WeatherPreferences(
        enabled=True, location_name='Fixture Home One', latitude=10, longitude=20))
    with sqlite3.connect(devices.db) as db:
        db.execute('INSERT INTO profiles VALUES(?,?)', (DEVICE+'@hardware', profile.model_dump_json()))
    return original, board, manager, provider


async def start(manager):
    session = await manager.accept(offer().model_copy(update={'device_id': DEVICE, 'client_id': DEVICE}))
    session._maintenance.cancel()
    await asyncio.gather(session._maintenance, return_exceptions=True)
    return session


def saved_home(manager, name='Fixture Home Two', **changes):
    devices = manager.brain.configuration.devices
    devices.update(DEVICE+'@hardware', {'weather': {'location_name': name, **changes}})
    return device_home_context(devices, DEVICE, DEVICE)


def home_updates(socket):
    return [event for event in socket.sent
            if event['type'] == 'session.update' and 'model' not in event['session']
            and 'instructions' in event['session']]


async def settle():
    # Only yield the event loop to the already-running in-memory provider reader.
    await asyncio.sleep(0)
    await asyncio.sleep(0)


def test_idle_home_update_waits_for_exact_ack_and_never_changes_media_or_usage(tmp_path, settings):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings, acknowledge=False)
        try:
            session = await start(manager)
            socket = provider.sockets[0]
            original_config = json.loads(json.dumps(session.config))
            old = session.home_context_status()
            assert old['state'] == 'applied'
            assert old['applied_revision'] == home_context_revision(
                device_home_context(manager.brain.configuration.devices, DEVICE, DEVICE))
            home = saved_home(manager)
            assert await session.refresh_home_context(now=session._home_context_next_check)
            pending = session.home_context_status()
            assert pending['state'] == 'pending'
            assert pending['desired_revision'] == home_context_revision(home)
            assert pending['applied_revision'] == old['applied_revision']
            assert pending['applied_at'] == old['applied_at']
            update, = home_updates(socket)
            assert set(update['session']) == {'type', 'instructions'}
            assert 'Fixture Home Two' in update['session']['instructions']
            assert 'Fixture Home One' not in update['session']['instructions']
            assert session.config == original_config

            # A tracing-only or different-instruction echo proves no new home.
            await session.handle({'type': 'session.updated', 'session': {'tracing': 'auto'}})
            await session.handle({'type': 'session.updated', 'session': original_config})
            assert session.home_context_status()['state'] == 'pending'
            await session.handle({'type': 'session.updated', 'session': socket.config})
            actual = session.home_context_status()
            assert actual['state'] == 'applied'
            assert actual['applied_revision'] == home_context_revision(home)
            assert actual['applied_transport_epoch'] == session.transport_epoch
            assert actual['applied_at'] >= old['applied_at']
            assert {k: v for k, v in session.config.items() if k != 'instructions'} == {
                k: v for k, v in original_config.items() if k != 'instructions'}
            assert len(provider.sockets) == 1 and not session.input_open
            assert board.budget.status()['sessions_reserved'] == 0
            assert not any(event['type'] in {'response.create', 'input_audio_buffer.append'} for event in socket.sent)
            assert 'Fixture Home' not in json.dumps(session.lifecycle_status())
            assert 'latitude' not in json.dumps(actual) and 'longitude' not in json.dumps(actual)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('field,value',[
    ('input_open', True), ('speaking', True), ('generating', True),
    ('response_requested', True), ('output_response', 'playing-fixture'),
    ('_stop_count', 1), ('state', 'processing'), ('attached', False),
])
def test_active_or_detached_conversation_defers_metadata_without_touching_media(tmp_path, settings, field, value):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        try:
            session = await start(manager)
            saved_home(manager)
            previous = getattr(session, field)
            setattr(session, field, value)
            assert await session.refresh_home_context(now=session._home_context_next_check) is False
            assert not home_updates(provider.sockets[0])
            assert getattr(session, field) == value
            setattr(session, field, previous)
            assert await session.refresh_home_context(now=session._home_context_next_check)
            await settle()
            assert session.home_context_status()['state'] == 'applied'
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_wake_wins_scoped_read_race_without_metadata_wait_or_extra_source_read(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        try:
            session = await start(manager)
            saved_home(manager)
            entered, release = asyncio.Event(), asyncio.Event()
            original_scope = session.require_transport_scope
            async def held_scope():
                entered.set()
                await release.wait()
                await original_scope()
            monkeypatch.setattr(session, 'require_transport_scope', held_scope)
            refresh = asyncio.create_task(session.refresh_home_context(now=session._home_context_next_check))
            await entered.wait()
            result = await asyncio.wait_for(session.wake('wake-races-home', trigger='wake_word'), 1)
            assert result['accepted'] and session.input_open
            release.set()
            assert await refresh is False
            assert not home_updates(provider.sockets[0])
            assert len(provider.sockets) == 1
            assert not any(event['type'] == 'response.create' for event in provider.sockets[0].sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_pending_home_ack_never_blocks_wake_and_input_echo_can_ack_both(tmp_path, settings):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings, acknowledge=False)
        try:
            session = await start(manager)
            home = saved_home(manager)
            assert await session.refresh_home_context(now=session._home_context_next_check)
            assert session.home_context_status()['state'] == 'pending'
            result = await asyncio.wait_for(session.wake('while-home-unconfirmed', trigger='wake_word'), 1)
            assert result['accepted'] and session.input_open
            # The full actual input echo also proves the instructions on this socket.
            assert session.input_ack.is_set()
            assert session.home_context_status()['applied_revision'] == home_context_revision(home)
            assert session.home_context_status()['state'] == 'applied'
            assert len(home_updates(provider.sockets[0])) == 1
            assert len(provider.sockets) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_stalled_metadata_send_releases_lock_after_bound_and_does_not_wait_for_ack(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings, acknowledge=False)
        try:
            session = await start(manager)
            saved_home(manager)
            socket = provider.sockets[0]
            send = socket.send
            entered, cancelled = asyncio.Event(), asyncio.Event()
            async def stalled_home(raw):
                event = json.loads(raw)
                if event['type'] == 'session.update' and set(event['session']) == {'type', 'instructions'}:
                    entered.set()
                    try:
                        await asyncio.Event().wait()
                    except asyncio.CancelledError:
                        cancelled.set()
                        raise
                else:
                    await send(raw)
            monkeypatch.setattr(socket, 'send', stalled_home)
            refresh = asyncio.create_task(session.refresh_home_context(now=session._home_context_next_check))
            await entered.wait()
            # A metadata frame already being sent can hold the shared writer
            # for at most one second. Its missing ACK never owns the writer.
            wake = asyncio.create_task(session.wake('metadata-backpressure', trigger='wake_word'))
            assert await asyncio.wait_for(refresh, 1.5) is False
            assert cancelled.is_set()
            assert (await asyncio.wait_for(wake, .5))['accepted']
            assert session.input_open and not session.send_lock.locked()
            assert session.home_context_status()['state'] == 'unconfirmed'
            assert len(provider.sockets) == 1 and not socket.closed
            assert not any(event['type'] == 'response.create' for event in socket.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_missing_ack_has_no_repeated_send_and_late_exact_echo_can_confirm(tmp_path, settings):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings, acknowledge=False)
        try:
            session = await start(manager)
            home = saved_home(manager)
            assert await session.refresh_home_context(now=session._home_context_next_check)
            pending = session._home_context_pending
            assert await session.refresh_home_context(now=pending['sent_at']+20) is False
            assert session.home_context_status()['state'] == 'unconfirmed'
            assert session.home_context_status()['reason'] == 'home_context_ack_unconfirmed'
            assert await session.refresh_home_context(now=pending['sent_at']+30) is False
            assert len(home_updates(provider.sockets[0])) == 1
            await session.handle({'type': 'session.updated', 'session': provider.sockets[0].config})
            assert session.home_context_status()['state'] == 'applied'
            assert session.home_context_status()['applied_revision'] == home_context_revision(home)
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_superseded_pending_revision_and_transport_epoch_cannot_confirm_new_home(tmp_path, settings):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings, acknowledge=False)
        try:
            session = await start(manager)
            saved_home(manager)
            assert await session.refresh_home_context(now=session._home_context_next_check)
            old_echo = json.loads(json.dumps(provider.sockets[0].config))
            old_pending = session._home_context_pending
            newest = saved_home(manager, 'Fixture Home Three')
            assert await session.refresh_home_context(now=old_pending['sent_at']+10)
            assert session.home_context_ack(old_echo) is False
            pending = session._home_context_pending
            session.transport_epoch += 1
            assert session.home_context_ack(provider.sockets[0].config) is False
            session.transport_epoch -= 1
            assert session._home_context_pending is pending
            assert session.home_context_ack(provider.sockets[0].config)
            assert session.home_context_status()['applied_revision'] == home_context_revision(newest)
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_normal_rotation_adopts_verified_latest_home_and_discards_old_pending(tmp_path, settings):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings, acknowledge=False)
        try:
            session = await start(manager)
            saved_home(manager)
            assert await session.refresh_home_context(now=session._home_context_next_check)
            old_echo = json.loads(json.dumps(provider.sockets[0].config))
            newest = saved_home(manager, 'Fixture Home Three')
            assert await session.rotate()
            assert session.home_context_status()['state'] == 'applied'
            assert session.home_context_status()['applied_revision'] == home_context_revision(newest)
            assert session.home_context_status()['applied_transport_epoch'] == 2
            assert session._home_context_pending is None
            assert session.home_context_ack(old_echo) is False
            assert len(provider.sockets) == 2 and provider.sockets[0].closed
            assert board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_unchanged_idle_only_reads_every_two_seconds_and_wake_never_polls_home(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        try:
            session = await start(manager)
            calls = []
            def observed(*args):
                calls.append(1)
                return device_home_context(*args)
            monkeypatch.setattr('gobot.settings_tools.device_home_context', observed)
            clock = session._home_context_next_check
            assert await session.refresh_home_context(now=clock) is False
            assert await session.refresh_home_context(now=clock+.1) is False
            assert await session.refresh_home_context(now=clock+1.9) is False
            assert calls == [1]
            assert await session.refresh_home_context(now=clock+2) is False
            assert calls == [1, 1]
            assert not home_updates(provider.sockets[0])
            await session.wake('unchanged-wake', trigger='wake_word')
            assert calls == [1, 1]
            assert not home_updates(provider.sockets[0])
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_revoked_scope_and_unavailable_store_never_apply_or_break_live_transport(tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, provider = configured(tmp_path, settings)
        try:
            session = await start(manager)
            saved_home(manager)
            def unavailable(*args):
                raise sqlite3.OperationalError('private-fixture-value')
            monkeypatch.setattr('gobot.settings_tools.device_home_context', unavailable)
            assert await session.refresh_home_context(now=session._home_context_next_check) is False
            assert session.ready and session.state == 'ready' and not session.input_open
            assert not home_updates(provider.sockets[0])
            assert 'private-fixture-value' not in json.dumps(session.lifecycle_status())
            assert session.home_context_status()['state'] == 'unconfirmed'

            # A changed principal is denied before reading any home context.
            forbidden_reads = []
            def forbidden(*args):
                forbidden_reads.append(True)
                raise AssertionError('Context read after scope revocation')
            monkeypatch.setattr('gobot.settings_tools.device_home_context', forbidden)
            policy = board.budget.policy().model_copy(update={'allowed_client_id': 'other-device'})
            board.budget.policy_path.write_text(policy.model_dump_json())
            assert await session.refresh_home_context(now=session._home_context_next_check) is False
            assert not forbidden_reads
            assert not home_updates(provider.sockets[0])
            assert len(provider.sockets) == 1 and board.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
