"""Local lifecycle checks; no provider, column, personal history or live database."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from gobot import brain
from gobot.memory import Memory
from gobot.native_archive import ArchiveBinding, NativeArchiveService


async def until(predicate):
    async def poll():
        while not predicate():
            await asyncio.sleep(.001)
    await asyncio.wait_for(poll(), 2.)


def test_retention_runs_without_voice_session_and_stops_promptly(tmp_path):
    async def scenario():
        memory = Memory(str(tmp_path/'archive.sqlite'))
        clock = [1000000.]
        archive = memory.native_archive = NativeArchiveService(memory, clock=lambda: clock[0])
        binding = ArchiveBinding('synthetic-board', 'synthetic-board', 'synthetic-board@synthetic-owner')
        state = archive.configure(binding, {
            'write_enabled': True, 'read_enabled': True, 'retention_days': 1, 'timezone': 'UTC'},
            0, operation_id='synthetic-enable', actor_id='synthetic-owner')
        archive.record_question(binding, 'question-1', 'conversation-1', 'Синтетическая тема',
                                generation=state['generation'])
        clock[0] += 2*86400
        service = SimpleNamespace(memory=memory)
        stop = asyncio.Event()
        worker = asyncio.create_task(brain.expire_native_archive(service, stop))
        try:
            await until(lambda: getattr(service, 'native_archive_expiry_status', {}).get('checked_at'))
            assert service.native_archive_expiry_status['expired'] == 1
            assert service.native_archive_expiry_status['error'] is None
            with memory.connect() as db:
                assert db.execute('SELECT count(*) FROM native_archive_turns').fetchone()[0] == 0
                assert db.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
        finally:
            stop.set()
            await asyncio.wait_for(worker, .5)
            await archive.close()
        assert service.native_archive_expiry_status['running'] is False
    asyncio.run(scenario())


def test_expiry_error_is_metadata_only_and_next_interval_recovers(monkeypatch):
    async def scenario():
        attempts = []
        def expire():
            attempts.append(True)
            if len(attempts) == 1:
                raise RuntimeError('PRIVATE_SYNTHETIC_DATABASE_CONTENT')
            return 2
        service = SimpleNamespace(memory=SimpleNamespace(native_archive=SimpleNamespace(expire=expire)))
        stop = asyncio.Event()
        monkeypatch.setattr(brain, 'NATIVE_ARCHIVE_EXPIRY_INTERVAL_SECONDS', .02)
        worker = asyncio.create_task(brain.expire_native_archive(service, stop))
        try:
            await until(lambda: getattr(service, 'native_archive_expiry_status', {}).get('error'))
            first = dict(service.native_archive_expiry_status)
            assert first['error'] == 'archive_expiry_unavailable'
            assert first['checked_at'] is not None and first['expired'] == 0
            assert 'PRIVATE' not in json.dumps(first)
            await until(lambda: service.native_archive_expiry_status['expired'] >= 2)
            assert service.native_archive_expiry_status['error'] is None
        finally:
            stop.set()
            await asyncio.wait_for(worker, .5)
        assert service.native_archive_expiry_status['running'] is False
    asyncio.run(scenario())


@pytest.mark.parametrize('failure', [None, 'body', 'worker', 'manager'])
def test_lifespan_drains_archive_after_voice_producers_stop(settings, monkeypatch, failure):
    async def scenario():
        events = []
        class BodyFailure(Exception):
            pass
        class CleanupFailure(Exception):
            pass
        monkeypatch.setattr(brain, 'agent_status', lambda: {})
        monkeypatch.setattr(brain, 'extract_entity', lambda *args: None)
        app = brain.create_app(settings)
        service = app.state.service
        async def worker(service, stop):
            events.append('archive_worker_started')
            await stop.wait()
            events.append('archive_worker_stopped')
            if failure == 'worker':
                raise CleanupFailure()
        monkeypatch.setattr(brain, 'expire_native_archive', worker)
        for name in ('direct_browser', 'live', 'realtime'):
            manager = getattr(app.state, name)
            async def shutdown(name=name):
                events.append(name+'_closed')
                if failure == 'manager' and name == 'direct_browser':
                    raise CleanupFailure()
            monkeypatch.setattr(manager, 'shutdown', shutdown)
        async def identity_close(self):
            events.append('identity_closed')
        monkeypatch.setattr(brain.SpeakerIdentity, 'close', identity_close)
        original_close = service.memory.native_archive.close
        async def archive_close(*, grace_seconds):
            assert grace_seconds == 2
            events.append('archive_drained')
            await original_close(grace_seconds=grace_seconds)
        monkeypatch.setattr(service.memory.native_archive, 'close', archive_close)
        raised = False
        try:
            async with app.router.lifespan_context(app):
                await until(lambda: 'archive_worker_started' in events)
                if failure == 'body':
                    raise BodyFailure()
        except BodyFailure:
            assert failure == 'body'
            raised = True
        except CleanupFailure:
            assert failure in {'worker', 'manager'}
            raised = True
        assert raised is (failure is not None)
        assert events == ['archive_worker_started', 'archive_worker_stopped',
                          'direct_browser_closed', 'live_closed', 'realtime_closed',
                          'identity_closed', 'archive_drained']
        assert service.timer_expiry_status['running'] is False
    asyncio.run(scenario())
