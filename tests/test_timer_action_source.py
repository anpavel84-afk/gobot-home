"""Native timer inputs use exact synthetic transcripts, not model rewrites."""
import pytest

from gobot.local_tools import LocalTools
from gobot.memory import Memory
from gobot.models import ChatRequest
from gobot.timer_duration import source_timer_seconds


@pytest.fixture
def tools(tmp_path):
    return LocalTools(Memory(str(tmp_path/'timer-source.sqlite')))


def request(text, turn='turn-1'):
    return ChatRequest(text=text, device_id='realtime-device:board', client_id='board',
        profile_epoch='test-epoch', conversation_id='conversation-1', turn_id=turn, remember=False)


def action(tools, req, operation, **kwargs):
    return tools.execute_timer_action(req, operation, action_id='native-timer:'+req.turn_id,
                                      is_current=lambda: True, **kwargs)


def count(tools):
    with tools.memory.connect() as db:
        return db.execute('SELECT count(*) FROM timers').fetchone()[0]


@pytest.mark.parametrize('utterance,duration,seconds', [
    ('София, поставь таймер на пять минут.', 'пять минут', 300),
    ('Поставь, пожалуйста, таймер на пять минут.', 'пять минут', 300),
    ('Давай, пока мы разговариваем, поставим таймер на пять минут.', 'пять минут', 300),
    ('Поставь таймер на пять минут и продолжай отвечать.', 'пять минут', 300),
    ('Мне нужен таймер на один час и тридцать минут.', 'один час и тридцать минут', 5400),
    ('Отсчитай 1,5 минуты, пожалуйста.', '1,5 минуты', 90),
    ('Поставь таймер на сорок две секунды.', 'сорок две секунды', 42),
])
def test_semantic_action_accepts_current_duration_without_command_phrase_allowlist(tools, utterance, duration, seconds):
    req = request(utterance)
    result = action(tools, req, 'start', duration_text=duration)
    assert result.evidence['executed'] and result.evidence['verified']
    assert result.evidence['duration_seconds'] == seconds
    assert result.widget['payload']['timer_id'] == result.evidence['timer_id']
    assert count(tools) == 1
    assert tools.timers.snapshot(req)['timers'][0]['duration_ms'] == seconds*1000


@pytest.mark.parametrize('utterance,duration', [
    ('Поставь таймер на двадцать пять минут.', 'пять минут'),
    ('Поставь таймер на 25 минут.', '5 минут'),
    ('Поставь таймер на сто пять минут.', 'пять минут'),
    ('Поставь таймер на один час и тридцать минут.', 'один час'),
    ('Поставь таймер на один час и тридцать минут.', 'тридцать минут'),
    ('Поставь таймер на один час. И тридцать минут.', 'один час'),
    ('Поставь таймер на один час. И тридцать минут.', 'тридцать минут'),
    ('Поставь таймер на один час, тридцать минут.', 'тридцать минут'),
    ('Поставь таймер на пять минут или десять минут.', 'пять минут'),
    ('Поставь таймер на пять минут или десять минут.', 'десять минут'),
    ('Поставь таймер на пять минут.', '5 минут'),
    ('Поставь таймер на пять минут.', 'десять минут'),
    ('Повтори «Поставь таймер на пять минут».', 'пять минут'),
])
def test_model_cannot_invent_rewrite_or_shorten_the_actual_duration(tools, utterance, duration):
    with pytest.raises((ValueError, PermissionError)):
        action(tools, request(utterance), 'start', duration_text=duration)
    assert count(tools) == 0


@pytest.mark.parametrize('utterance', [
    'Не ставь таймер на пять минут.',
    'Не нужно запускать таймер на пять минут.',
    'Если поставить таймер на пять минут, что будет?',
    'Что будет, если поставить таймер на пять минут?',
    'Расскажи, как поставить таймер на пять минут.',
    'Он сказал поставить таймер на пять минут.',
])
def test_obvious_negation_or_report_cannot_become_a_current_timer_command(tools, utterance):
    with pytest.raises(PermissionError, match='current_user_command_required'):
        action(tools, request(utterance), 'start', duration_text='пять минут')
    assert count(tools) == 0


def test_missing_duration_asks_once_without_timer_then_uses_real_new_reply(tools):
    missing = action(tools, request('Поставь таймер.'), 'start')
    assert missing.evidence['needs_parameters'] and missing.evidence['executed'] is False
    assert count(tools) == 0
    result = action(tools, request('На пять минут.', 'turn-2'), 'start', duration_text='пять минут')
    assert result.evidence['duration_seconds'] == 300 and count(tools) == 1


def test_duration_only_reply_without_pending_request_never_creates_timer(tools):
    with pytest.raises(PermissionError, match='current_user_command_required'):
        action(tools, request('Пять минут.'), 'start', duration_text='Пять минут')
    assert count(tools) == 0


@pytest.mark.parametrize('check,action_id', [(None, 'native-timer:turn-1'),
    (lambda: False, 'native-timer:turn-1'), (lambda: True, 'native-timer:different-turn')])
def test_native_mutation_requires_live_server_turn_authority(tools, check, action_id):
    with pytest.raises(PermissionError):
        tools.execute_timer_action(request('Поставь таймер на пять минут.'), 'start',
            duration_text='пять минут', action_id=action_id, is_current=check)
    assert count(tools) == 0


def test_gobot_tool_and_dedicated_action_share_one_turn_receipt(tools):
    req = request('Поставь таймер на пять минут.')
    legacy_tool = tools.execute('timer', req, {'operation': 'start', 'seconds': 300},
        action_id='native-timer:'+req.turn_id, is_current=lambda: True)
    dedicated = action(tools, req, 'start', duration_text='пять минут')
    assert dedicated.evidence['replayed'] and dedicated.widget == legacy_tool.widget
    assert count(tools) == 1
    with pytest.raises(ValueError, match='action_payload_conflict'):
        tools.cancel_timer(req, '', action_id='native-timer:'+req.turn_id, is_current=lambda: True)
    next_request = request(req.text, 'turn-2')
    action(tools, next_request, 'start', duration_text='пять минут')
    assert count(tools) == 2


def test_native_cancel_requires_same_scoped_announced_list_and_exact_ordinal(tools):
    first_req = request('Поставь таймер на пять минут.', 'create-1')
    second_req = request('Поставь таймер на десять минут.', 'create-2')
    first = action(tools, first_req, 'start', duration_text='пять минут')
    second = action(tools, second_req, 'start', duration_text='десять минут')
    no_list = action(tools, request('Отмени второй таймер.', 'cancel-no-list'), 'cancel', target='ordinal', ordinal=2)
    assert no_list.evidence['needs_parameters'] and not no_list.evidence['executed']
    status = action(tools, request('Покажи таймеры.', 'list'), 'status')
    assert status.evidence['timer_ids'] == [first.evidence['timer_id'], second.evidence['timer_id']]
    with pytest.raises(PermissionError, match='timer_target_source_mismatch'):
        action(tools, request('Отмени второй таймер.', 'cancel-wrong'), 'cancel', target='ordinal', ordinal=1)
    cancelled = action(tools, request('Отмени второй таймер.', 'cancel-correct'), 'cancel', target='ordinal', ordinal=2)
    assert cancelled.evidence['timer_cancelled_ids'] == [second.evidence['timer_id']]
    assert len(tools.timers.active(first_req)) == 1


@pytest.mark.parametrize('utterance,target,ordinal', [
    ('Отмени таймер.', 'all', None), ('Отмени все таймеры.', 'only', None),
    ('Отмени второй таймер.', 'only', None), ('Не отменяй все таймеры.', 'all', None),
    ('Повтори «Отмени все таймеры».', 'all', None),
])
def test_cancel_scope_cannot_be_invented_or_narrowed(tools, utterance, target, ordinal):
    req = request('Поставь таймер на пять минут.', 'create')
    action(tools, req, 'start', duration_text='пять минут')
    with pytest.raises(PermissionError):
        action(tools, request(utterance, 'cancel'), 'cancel', target=target, ordinal=ordinal)
    assert len(tools.timers.active(req)) == 1


def test_native_status_announces_completed_latch_and_voice_cancel_clears_it(tools):
    now = tools.timers.clock()
    req = request('Поставь таймер на одну секунду.', 'create')
    result = action(tools, req, 'start', duration_text='одну секунду')
    tools.timers.clock = lambda: now+3
    status = action(tools, request('Какие у меня таймеры?', 'status'), 'status')
    assert 'завершён' in status.text
    assert status.evidence['active_count'] == 0 and status.evidence['current_count'] == 1
    assert status.evidence['timers'][0]['state'] == 'expired'
    cancelled = action(tools, request('Убери завершённый таймер.', 'dismiss'), 'cancel')
    assert cancelled.evidence['timer_cancelled_ids'] == [result.evidence['timer_id']]
    assert tools.timers.snapshot(req)['timers'][0]['state'] == 'cancelled'


def test_native_limit_result_never_claims_started_or_returns_fake_widget(tools):
    for index in range(16):
        action(tools, request('Поставь таймер на пять минут.', 'create-'+str(index)), 'start', duration_text='пять минут')
    result = action(tools, request('Поставь таймер на пять минут.', 'overflow'), 'start', duration_text='пять минут')
    assert result.widget is None and result.evidence['executed'] is False
    assert result.evidence['reason'] == 'timer_limit_reached'
    assert 'запущен' not in result.text and count(tools) == 16


def test_stopped_missing_duration_request_does_not_authorize_later_bare_duration(tools, monkeypatch):
    valid = [True]
    original = tools.memory.set_pending
    def stopped_while_waiting(*args, **kwargs):
        pending = original(*args, **kwargs)
        valid[0] = False
        return pending
    monkeypatch.setattr(tools.memory, 'set_pending', stopped_while_waiting)
    req = request('Поставь таймер.')
    with pytest.raises(PermissionError, match='timer_action_context_changed'):
        tools.execute_timer_action(req, 'start', action_id='native-timer:'+req.turn_id,
                                   is_current=lambda: valid[0])
    with pytest.raises(PermissionError, match='current_user_command_required'):
        action(tools, request('На пять минут.', 'unrelated-next-turn'), 'start', duration_text='пять минут')
    assert count(tools) == 0


@pytest.mark.parametrize('valid_before_read', [False,True])
def test_native_status_cannot_publish_or_record_list_after_scope_revocation(tools, monkeypatch, valid_before_read):
    action(tools, request('Поставь таймер на пять минут.', 'create'), 'start', duration_text='пять минут')
    valid = [valid_before_read]
    original = tools.timers.current
    reads = []
    def revoke_during_read(*args, **kwargs):
        reads.append(True)
        rows = original(*args, **kwargs)
        valid[0] = False
        return rows
    monkeypatch.setattr(tools.timers, 'current', revoke_during_read)
    req = request('Покажи таймеры.', 'status')
    with pytest.raises(PermissionError, match='timer_action_context_changed'):
        tools.execute('timer_status', req, action_id='native-timer:'+req.turn_id,
                      is_current=lambda: valid[0])
    assert bool(reads) == valid_before_read
    assert tools.timer_context(req) == {}
