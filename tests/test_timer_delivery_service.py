"""Temporary SQLite and controlled clocks only; no real device or alarm audio."""
import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest

from gobot.live import LiveSession
from gobot.local_tools import LocalTools
from gobot.memory import Memory
from gobot.models import ChatRequest
from gobot.timer_service import TimerService


def setup(tmp_path):
    memory = Memory(str(tmp_path/'timers.sqlite'))
    service = TimerService(memory, clock=lambda: 1000.)
    req = ChatRequest(text='SYNTHETIC_HOUSEHOLD_LABEL_NOT_FOR_RECEIPTS',
        device_id='realtime-device:board', client_id='board', profile_epoch='profile-1',
        conversation_id='conversation-1', turn_id='turn-1', remember=False)
    return memory, service, req


def test_start_and_cancel_are_atomic_per_turn_and_receipts_survive_restart(tmp_path):
    memory, service, req = setup(tmp_path)
    first = service.start(req, 30, action_id='start-1')
    restored = TimerService(memory, clock=lambda: 1004.)
    again = restored.start(req, 30, action_id='start-1')
    assert again['replayed'] and again['timer_id'] == first['timer_id'] and again['deadline'] == 1030
    with pytest.raises(ValueError, match='action_payload_conflict'):
        restored.start(req, 60, action_id='start-1')
    with pytest.raises(ValueError, match='action_payload_conflict'):
        restored.cancel(req, action_id='start-1')
    cancelled = restored.cancel(req, action_id='cancel-1')
    later = restored.start(req, 60, action_id='start-2')
    replay = TimerService(memory, clock=lambda: 1005.).cancel(req, action_id='cancel-1')
    assert replay['replayed'] and replay['timer_cancelled_ids'] == cancelled['timer_cancelled_ids'] == [first['timer_id']]
    assert [row['id'] for row in restored.active(req)] == [later['timer_id']]
    with memory.connect() as db:
        assert db.execute('SELECT count(*) FROM timers').fetchone()[0] == 2
        receipts = str([tuple(row) for row in db.execute('SELECT * FROM timer_action_receipts')])
    assert req.text not in receipts
    assert req.text not in json.dumps(restored.snapshot(req))


def test_concurrent_replays_create_one_timer_and_one_alarm_claim(tmp_path):
    memory, service, req = setup(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: service.start(req, 5, action_id='same-turn'), range(4)))
    assert len({result['timer_id'] for result in results}) == 1
    assert sum(not result['replayed'] for result in results) == 1
    with ThreadPoolExecutor(max_workers=4) as pool:
        deliveries = list(pool.map(lambda n: service.claim_due(req, 'consumer-'+str(n), now=1006), range(4)))
    assert sum(len(items) for items in deliveries) == 1
    assert not TimerService(memory).claim_due(req, 'after-restart', now=1007)


@pytest.mark.parametrize('change', [{'device_id': 'another-board'}, {'client_id': 'other-client'},
                                  {'profile_epoch': 'profile-2'}])
def test_all_status_cancel_claim_and_ack_operations_are_exactly_scoped(tmp_path, change):
    memory, service, req = setup(tmp_path)
    first = service.start(req, 5, action_id='start')
    other = req.model_copy(update=change)
    assert service.snapshot(other)['timers'] == []
    result = service.cancel(other, 'all', action_id='cancel')
    assert not result['executed'] and not result['timer_cancelled_ids']
    assert not service.claim_due(other, 'other-consumer', now=1006)
    delivery, = service.claim_due(req, 'correct-consumer', now=1006)
    assert not service.ack(other, delivery['alarm_id'], delivery['claim_id'], 'finished', now=1007)
    assert service.ack(req, delivery['alarm_id'], delivery['claim_id'], 'finished', now=1007)
    assert service.snapshot(req, now=1007)['timers'][0]['timer_id'] == first['timer_id']


def test_deadlines_persist_without_voice_and_future_timer_resumes_after_restart(tmp_path):
    memory, service, req = setup(tmp_path)
    start = service.start(req, 10, action_id='start')
    before = service.snapshot(req, now=1003)
    assert before['timers'][0]['remaining_ms'] == 7000
    after_restart = TimerService(memory, clock=lambda: 1011.)
    assert after_restart.expire_due() == 1
    expired = after_restart.snapshot(req)
    assert expired['revision'] > before['revision']
    assert expired['timers'][0]['state'] == 'expired' and expired['timers'][0]['remaining_ms'] == 0
    alarm, = after_restart.claim_due(req, 'attached-device')
    assert alarm['timer_id'] == start['timer_id'] and alarm['expires_at'] == 1130
    assert after_restart.expire_due() == 0 and not after_restart.claim_due(req, 'another-attachment')


@pytest.mark.parametrize('terminal', ['finished', 'cancelled', 'suppressed', 'unknown'])
def test_alarm_receipts_are_monotonic_and_never_reauthorize_sound(tmp_path, terminal):
    memory, service, req = setup(tmp_path)
    service.start(req, 1, action_id='start')
    alarm, = service.claim_due(req, 'consumer', now=1002)
    args = req, alarm['alarm_id'], alarm['claim_id']
    assert service.ack(*args, 'started', now=1002)
    assert service.ack(*args, terminal, now=1003)
    assert service.ack(*args, terminal, now=1004)
    assert not service.ack(*args, 'started', now=1004)
    assert not service.claim_due(req, 'repeat', now=1004)
    assert not TimerService(memory).claim_due(req, 'restarted', now=1005)


def test_late_unclaimed_alarm_is_suppressed_and_cancelled_timer_never_expires(tmp_path):
    memory, service, req = setup(tmp_path)
    late = service.start(req, 5, action_id='late')
    cancelled = service.start(req, 10, action_id='cancelled')
    service.cancel(req, cancelled['timer_id'], action_id='cancel', now=1001)
    assert service.expire_due(now=1126) == 1
    assert not service.claim_due(req, 'late-consumer', now=1126)
    with memory.connect() as db:
        rows = [dict(row) for row in db.execute('SELECT timer_id,state FROM timer_alarm_deliveries')]
    assert rows == [{'timer_id': late['timer_id'], 'state': 'suppressed'}]


def test_stale_current_user_authority_rolls_back_mutation_and_receipt(tmp_path):
    memory, service, req = setup(tmp_path)
    checks = []

    def invalidated_before_commit():
        checks.append(True)
        return len(checks) == 1

    with pytest.raises(PermissionError, match='timer_action_context_changed'):
        service.start(req, 30, action_id='start', is_current=invalidated_before_commit)
    with memory.connect() as db:
        assert db.execute('SELECT count(*) FROM timers').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM timer_action_receipts').fetchone()[0] == 0
        assert db.execute('SELECT count(*) FROM timer_scope_versions').fetchone()[0] == 0
    first = service.start(req, 30, action_id='start', is_current=lambda: True)
    checks.clear()
    with pytest.raises(PermissionError):
        service.cancel(req, action_id='cancel', is_current=invalidated_before_commit)
    assert [row['id'] for row in service.active(req)] == [first['timer_id']]


def test_ordinal_selection_uses_the_actual_announced_ids_not_new_order(tmp_path):
    memory, service, req = setup(tmp_path)
    first = service.start(req, 10, action_id='first')
    second = service.start(req, 20, action_id='second')
    announced = [first['timer_id'], second['timer_id']]
    # When the old first timer expires, ordinal two still means the announced second.
    service.expire_due(now=1011)
    result = service.cancel(req, '2', listed_ids=announced, action_id='cancel-second', now=1011)
    assert result['timer_cancelled_ids'] == [second['timer_id']]
    expired = service.cancel(req, '1', listed_ids=announced, action_id='cancel-expired', now=1011)
    assert expired['timer_cancelled_ids'] == [first['timer_id']]


def test_old_rows_are_not_adopted_and_old_live_c_cannot_claim_native_alarm(tmp_path):
    memory, service, req = setup(tmp_path)
    now = time.time()
    native = service.start(req, 1, action_id='native', now=now-2)
    with memory.connect() as db:
        db.execute("INSERT INTO timers VALUES(?,?,?,?,'running')", ('legacy-row', req.device_id, 'legacy', now-1))
    assert all(row['timer_id'] != 'legacy-row' for row in service.snapshot(req, now=now-2)['timers'])
    spoken, events = [], []

    async def append(*args): spoken.append(args)

    session = SimpleNamespace(manager=SimpleNamespace(brain=SimpleNamespace(memory=memory)),
        offer=SimpleNamespace(client_id='board'), closed=False, closing=False,
        emit=lambda *args, **kwargs: events.append((args, kwargs)), append=append)
    asyncio.run(LiveSession.expired_timers(session))
    with memory.connect() as db:
        states = dict(db.execute('SELECT id,status FROM timers'))
    assert states['legacy-row'] == 'completed'
    assert states[native['timer_id']] == 'running'
    assert spoken == [('commentary', 'Таймер завершён.', None)]
    assert len(service.claim_due(req, 'native-consumer', now=now)) == 1


def test_legacy_local_tool_route_stays_unbound_and_has_no_new_delivery(tmp_path):
    memory, service, req = setup(tmp_path)
    tools = LocalTools(memory)
    result = tools.start_timer_once(req, 30, 'existing-live-operation')
    with memory.connect() as db:
        assert db.execute('SELECT count(*) FROM timer_bindings').fetchone()[0] == 0
    assert tools.timers.snapshot(req)['timers'] == []
    assert not tools.timers.claim_due(req, 'consumer', now=result.evidence['deadline']+1)
    assert tools.execute('timer_status', req).evidence['active_count'] == 1


def test_idle_schema_install_and_polling_leave_legacy_rows_and_receipts_unchanged(tmp_path):
    memory = Memory(str(tmp_path/'legacy-install.sqlite'))
    with memory.connect() as db:
        db.execute('CREATE TABLE timers(id TEXT PRIMARY KEY,device_id TEXT,conversation_id TEXT,deadline REAL,status TEXT)')
        db.execute('CREATE TABLE timer_action_receipts(owner TEXT,action TEXT,payload_hash TEXT,result TEXT,PRIMARY KEY(owner,action))')
        db.execute("INSERT INTO timers VALUES('old','old-device','old-conversation',10,'running')")
        db.execute("INSERT INTO timer_action_receipts VALUES('old-device','old-action','old-hash','old-result')")
        original = {table: [tuple(row) for row in db.execute('SELECT * FROM '+table)]
                    for table in ('timers', 'timer_action_receipts')}
        columns = [tuple(row) for row in db.execute('PRAGMA table_info(timers)')]
    service = TimerService(memory, clock=lambda: 1000.)
    req = ChatRequest(text='Synthetic status',device_id='new-device')
    for _ in range(2):
        assert service.expire_due() == 0
        assert service.snapshot(req) == {'revision': 0, 'timers': []}
        assert not service.claim_due(req, 'idle-consumer')
    with memory.connect() as db:
        assert [tuple(row) for row in db.execute('PRAGMA table_info(timers)')] == columns
        for table, rows in original.items():
            assert [tuple(row) for row in db.execute('SELECT * FROM '+table)] == rows
        for table in ('timer_bindings', 'timer_scope_versions', 'timer_alarm_deliveries'):
            assert db.execute('SELECT count(*) FROM '+table).fetchone()[0] == 0


@pytest.mark.parametrize('claimed,started', [(False,False),(True,False),(True,True)])
def test_expired_latch_can_be_dismissed_and_inflight_alarm_cannot_finish_after_cancellation(tmp_path, claimed, started):
    memory, service, req = setup(tmp_path)
    timer = service.start(req, 1, action_id='start')
    before = service.snapshot(req, now=1002)
    alarm = None
    if claimed:
        alarm, = service.claim_due(req, 'consumer', now=1002)
    if started:
        assert service.ack(req, alarm['alarm_id'], alarm['claim_id'], 'started', now=1002)
    result = service.cancel(req, 'only', action_id='dismiss', now=1003)
    assert result['executed'] and result['timer_cancelled_ids'] == [timer['timer_id']]
    after = service.snapshot(req, now=1003)
    assert after['revision'] > before['revision'] and after['timers'][0]['state'] == 'cancelled'
    assert not service.current(req, now=1003)
    assert not TimerService(memory).claim_due(req, 'new-consumer', now=1004)
    if alarm:
        assert not service.ack(req, alarm['alarm_id'], alarm['claim_id'], 'finished', now=1004)
        assert service.ack(req, alarm['alarm_id'], alarm['claim_id'], 'cancelled', now=1004)


def test_single_target_never_silently_chooses_running_over_completed_timer(tmp_path):
    memory, service, req = setup(tmp_path)
    completed = service.start(req, 1, action_id='completed')
    running = service.start(req, 30, action_id='running')
    assert service.cancel(req, action_id='ambiguous', now=1002)['reason'] == 'timer_selection_required'
    all_result = service.cancel(req, 'all', action_id='explicit-all', now=1002)
    assert set(all_result['timer_cancelled_ids']) == {completed['timer_id'],running['timer_id']}
    assert not service.current(req, now=1002)


@pytest.mark.parametrize('elapsed_seconds', [0, 48*3600])
def test_timer_capacity_never_evicts_current_timers_and_failed_action_cannot_replay_later(tmp_path, elapsed_seconds):
    memory, service, req = setup(tmp_path)
    current = [service.start(req, 30+n, action_id='start-'+str(n)) for n in range(16)]
    now = 1000+elapsed_seconds
    restored = TimerService(memory, clock=lambda: now)
    result = restored.start(req, 60, action_id='overflow')
    assert not result['executed'] and result['reason'] == 'timer_limit_reached'
    assert len(restored.current(req)) == 16
    assert {row['timer_id'] for row in restored.snapshot(req)['timers']} == {row['timer_id'] for row in current}
    assert {row['status'] for row in restored.current(req)} == {'expired' if elapsed_seconds else 'running'}
    assert not restored.claim_due(req, 'restarted-device')
    restored.cancel(req, current[0]['timer_id'], action_id='free-slot')
    assert not restored.start(req, 60, action_id='overflow')['executed']
    new = restored.start(req, 60, action_id='new-turn')
    assert new['executed'] and len(restored.current(req)) == 16
    assert {row['timer_id'] for row in restored.snapshot(req)['timers']} == {
        row['timer_id'] for row in current[1:]} | {new['timer_id']}


@pytest.mark.parametrize('delivery_state', ['pending', 'claimed', 'started'])
def test_expired_latch_survives_48_hours_and_restart_until_explicit_dismissal(tmp_path, delivery_state):
    memory, service, req = setup(tmp_path)
    start = service.start(req, 1, action_id='original-turn')
    old = service.snapshot(req, now=1002)
    alarm = None
    if delivery_state != 'pending':
        alarm, = service.claim_due(req, 'before-restart', now=1002)
        if delivery_state == 'started':
            assert service.ack(req, alarm['alarm_id'], alarm['claim_id'], 'started', now=1002)
    now = 1002+48*3600
    restored = TimerService(memory, clock=lambda: now)
    aged = restored.snapshot(req)
    assert aged == old
    assert aged['timers'][0]['state'] == 'expired' and aged['timers'][0]['remaining_ms'] == 0
    assert restored.snapshot(req, now=now+1) == aged
    assert not restored.claim_due(req, 'after-restart')
    if alarm:
        assert not restored.ack(req, alarm['alarm_id'], alarm['claim_id'], 'finished')
    replay = restored.start(req, 1., action_id='original-turn')
    assert replay['replayed'] and replay['timer_id'] == start['timer_id']
    assert [row['id'] for row in restored.current(req)] == [start['timer_id']]
    with memory.connect() as db:
        assert db.execute('SELECT count(*) FROM timer_action_receipts').fetchone()[0] == 1
        assert db.execute('SELECT count(*) FROM timers').fetchone()[0] == 1
        expected = 'suppressed' if delivery_state == 'pending' else 'unknown'
        assert db.execute('SELECT state FROM timer_alarm_deliveries').fetchone()[0] == expected
    dismissed = restored.cancel(req, action_id='explicit-dismiss')
    assert dismissed['executed'] and dismissed['timer_cancelled_ids'] == [start['timer_id']]
    assert restored.current(req) == []
    cleared = restored.snapshot(req)
    assert cleared['revision'] > aged['revision'] and cleared['timers'][0]['state'] == 'cancelled'
    assert not restored.claim_due(req, 'after-dismissal')


@pytest.mark.parametrize('valid_checks', [0,1])
def test_old_attachment_receipt_cannot_commit_after_its_authority_is_lost(tmp_path, valid_checks):
    memory, service, req = setup(tmp_path)
    service.start(req, 1, action_id='start')
    alarm, = service.claim_due(req, 'old-attachment', now=1002)
    checks = []
    def current_attachment():
        checks.append(True)
        return len(checks) <= valid_checks
    with pytest.raises(PermissionError, match='timer_action_context_changed'):
        service.ack(req, alarm['alarm_id'], alarm['claim_id'], 'finished',
                    now=1003, is_current=current_attachment)
    with memory.connect() as db:
        assert db.execute('SELECT state FROM timer_alarm_deliveries').fetchone()[0] == 'claimed'
    assert not service.claim_due(req, 'replacement-attachment', now=1004)
