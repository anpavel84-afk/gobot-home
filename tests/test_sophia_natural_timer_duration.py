"""Free regressions for natural timer durations, before physical acceptance."""
import time
from types import SimpleNamespace

import pytest
from gobot.timer_duration import timer_seconds, source_timer_seconds, is_timer_duration_reply


@pytest.mark.parametrize("text,seconds", [
    ("Таймер на 5 мин",300),("Таймер на 5мин.",300),
    ("Таймер на пять минут",300),("Поставь таймер на 30 сек.",30),
    ("Таймер на 10 с",10),("Таймер на 2 ч.",7200),
    ("Таймер на 1 час 30 мин",5400),("Таймер на 1 мин. и 30 сек.",90),
    ("Таймер на полчаса",1800),("Таймер на 1,5 мин.",90),
    ("Таймер на -5 мин",0),("Таймер на минус 5 мин",0),
    ("Таймер на 0 мин",0),("Таймер на 5 минералов",None),
    ("Таймер на 5 мин или 10 мин",None),("Таймер на двадцать пять минут",1500),
    ("Таймер на 999999999999999999999 мин",None),
    ("София, кстати, можешь поставить, пожалуйста, таймер на две с половиной минуты?",150),
    ("Поставь мне таймер на минуту и тридцать секунд",90),
    ("На минуту поставь таймер",60),("поставь таймер минут на пять",300),
    ("таймер на сто двадцать секунд",120),("таймер на 1:30",90),
    ("таймер на 00:01:30",90),("поставь таймер на пол минуты",30),
    ("поставь таймер на полторы минуты",90),
    ("поставь таймер на 1 минуту, 30 секунд",90),("таймер на час с половиной",5400),
    ("таймер на пять",None),("таймер до 12:30",None),
    ("не ставь таймер на 5 минут",None),("расскажи как поставить таймер на 5 минут",None),
    ("таймер на 2 минуты, затем включи телевизор",None),
    ("таймер на «5 минут»",None),("таймер на 00:65",None),
    ("таймер на триста двадцать пять секунд",325),
    ("минутку",60),("час и 20 минут",4800),
])
def test_complete_duration(text,seconds):
    assert timer_seconds(text)==seconds


@pytest.mark.parametrize("utterance,argument,seconds",[
    ("Поставь таймер на пять минут","300 секунд",300),
    ("София, поставь таймер на полторы минуты","90 сек.",90),
    ("Кстати, поставь таймер минут на пять","5 минут",300),
    ("Поставь таймер на минуту и тридцать секунд","1,5 минуты",90),
    ("Поставь таймер на 1:30","90 секунд",90),
    ("На сто двадцать секунд","2 минуты",120),
    ("Поставь таймер на двадцать пять минут","25 мин",1500),
])
def test_equivalent_arguments(utterance,argument,seconds):
    assert source_timer_seconds(utterance,argument)==seconds


@pytest.mark.parametrize('utterance,argument,seconds',[
    ('Включи кухонный отсчёт на минутку.','60 секунд',60),
    ('Запусти обратный отсчёт на полторы минуты.','90 секунд',90),
    ('Начни отсчёт на минуту и тридцать секунд.','1,5 минуты',90),
])
def test_semantic_command_duration_equivalence_does_not_require_router_noun(utterance,argument,seconds):
    assert timer_seconds(utterance) is None  # Native tool, not quick intent.
    assert source_timer_seconds(utterance,argument)==seconds
    tools,starts=_executor()
    req=SimpleNamespace(text=utterance,turn_id='semantic')
    assert tools.execute_timer_action(req,'start',argument,action_id='native-timer:semantic',is_current=lambda:True)==seconds
    assert starts==[(seconds,'native-timer:semantic')]
    tools,starts=_executor()
    assert tools.execute_timer_action(req,'start',None,action_id='native-timer:semantic',is_current=lambda:True)==seconds
    assert starts==[(seconds,'native-timer:semantic')]


@pytest.mark.parametrize('utterance,argument',[
    ('Начни отсчёт на минутку.','120 секунд'),
    ('Начни отсчёт на минуту и тридцать секунд.','30 секунд'),
    ('Начни отсчёт на минутку или две.','60 секунд'),
    ('Начни отсчёт на минутку, затем выключи свет.','60 секунд'),
    ('Не включай отсчёт на минутку.','60 секунд'),
    ('Он сказал «включи отсчёт на минутку».','60 секунд'),
    ('Через пять минут включи отсчёт на минутку.','60 секунд'),
    ('Начни отсчёт до 12:30.','750 секунд'),
    ('Мы выйдем на минутку.','60 секунд'),
    ('Он включил отсчёт на минутку.','60 секунд'),
    ('Если включить отсчёт на минутку.','60 секунд'),
    ('Как включить кухонный отсчёт на минутку?','60 секунд'),
])
def test_semantic_command_never_omits_conflicts_quotes_or_other_actions(utterance,argument):
    with pytest.raises(ValueError,match='timer_duration_source_mismatch'):
        source_timer_seconds(utterance,argument)


@pytest.mark.parametrize("utterance,argument",[
    ("Поставь таймер на пять минут","10 минут"),
    ("Поставь таймер на двадцать пять минут","пять минут"),
    ("Поставь таймер на 1 минуту 30 секунд","30 секунд"),
    ("Поставь таймер на полторы минуты","1 минута"),
    ("Поставь таймер на пять минут или десять минут","300 секунд"),
    ("Поставь таймер на «5 минут»","5 минут"),
    ("Поставь таймер на пять","5 минут"),
    ("Поставь таймер на пять минут",300),
])
def test_wrong_or_ambiguous_argument_never_starts(utterance,argument):
    with pytest.raises(ValueError,match="timer_duration_source_mismatch"):
        source_timer_seconds(utterance,argument)


@pytest.mark.parametrize("text",["5 мин","полторы минуты","на 1:30","минут на пять","час и 20 минут"])
def test_pending_duration_forms(text):
    assert is_timer_duration_reply(text)


@pytest.mark.parametrize("text",["поставь таймер на пять минут","пять","5 минут назад","таймер на 5 мин или 10 мин"])
def test_not_a_pending_duration(text):
    assert not is_timer_duration_reply(text)


def _executor(pending=None):
    # Isolate the native mutation gate, rather than pretending to exercise a
    # physical timer, real database, model or speaker.
    from gobot.local_tools import LocalTools
    tools=LocalTools.__new__(LocalTools)
    starts=[]
    def current(check):
        if not check():raise PermissionError("timer_action_context_changed")
    tools.timers=SimpleNamespace(_current=current)
    tools.memory=SimpleNamespace(context=lambda req:{"pending_action":pending})
    tools.native_timer_pending=lambda *a:None
    def start(req,seconds,action_id=None,*,is_current=None):
        current(is_current)
        starts.append((seconds,action_id))
        return seconds
    tools.start_timer_once=start
    return tools,starts


@pytest.mark.parametrize("utterance,argument,seconds",[
    ("Поставь таймер на полторы минуты",None,90),
    ("София, кстати, поставь таймер на две с половиной минуты","150 секунд",150),
    ("Кстати, поставь таймер минут на пять","5 минут",300),
])
def test_native_start_uses_current_user_duration(utterance,argument,seconds):
    tools,starts=_executor()
    req=SimpleNamespace(text=utterance,turn_id="test")
    assert tools.execute_timer_action(req,"start",argument,action_id="native-timer:test",is_current=lambda:True)==seconds
    assert starts==[(seconds,"native-timer:test")]


@pytest.mark.parametrize("argument",[None,"90 секунд"])
def test_bare_duration_needs_pending_even_if_normalized(argument):
    tools,starts=_executor()
    req=SimpleNamespace(text="полторы минуты",turn_id="test")
    with pytest.raises(PermissionError,match="current_user_command_required"):
        tools.execute_timer_action(req,"start",argument,action_id="native-timer:test",is_current=lambda:True)
    assert not starts


def test_pending_duration_is_accepted_once_authorized():
    tools,starts=_executor({"kind":"timer_duration","expires":time.time()+60})
    req=SimpleNamespace(text="полторы минуты",turn_id="test")
    assert tools.execute_timer_action(req,"start","90 секунд",action_id="native-timer:test",is_current=lambda:True)==90
    assert starts==[(90,"native-timer:test")]


def test_stale_action_does_not_start():
    tools,starts=_executor()
    req=SimpleNamespace(text="Поставь таймер на пять минут",turn_id="test")
    with pytest.raises(PermissionError,match="timer_action_context_changed"):
        tools.execute_timer_action(req,"start","300 секунд",action_id="native-timer:test",is_current=lambda:False)
    assert not starts


@pytest.mark.parametrize("text,seconds",[
    ("София, кстати, поставь таймер на две с половиной минуты",150),
    ("На минуту поставь таймер",60),
])
def test_generic_timer_intent_shares_resolver(text,seconds):
    from gobot.quick_intents import resolve_quick
    result=resolve_quick(text,{})
    assert result.executor=="timer" and result.status=="validated"
    assert result.slots["seconds"]==seconds
