"""Offline real coordinator + temporary SQLite; no model or hardware calls."""
import asyncio
import json
import time
import pytest
from gobot.timer_duration import timer_seconds
from gobot.unified_voice_journal import metadata
from test_owner_terminal_direct import setup_terminal
from test_direct_voice_mode import SyntheticRecognition
from test_realtime_ws import cleanup
from test_timer_action_source import tools


@pytest.mark.parametrize("phrase", ["Кстати, поставь на пять минут", "На полминуты", "На полторы минуты", "На две с половиной минуты"])
def test_elliptic_timer_requires_pending(tools, phrase):
    from test_timer_action_source import request,action,count
    req=request(phrase)
    with pytest.raises(PermissionError):action(tools,req,"start")
    assert count(tools)==0
    action(tools,request("Поставь таймер.","ask"),"start")
    result=action(tools,request(phrase,"reply"),"start")
    assert result.evidence["executed"] and count(tools)==1


@pytest.mark.parametrize("phrase", ["Поставь таймер на десять минут.", "Минут на пять поставь таймер.", "Засеки тридцать секунд."])
def test_persistent_expert_input_timer_never_launches_cli_or_changes_mode(tmp_path,settings,phrase):
    async def run():
        original,board,manager,s,provider=await setup_terminal(tmp_path,settings)
        manager.recognition=SyntheticRecognition(phrase)
        async def forbidden(*args):raise AssertionError("timer sent to CLI")
        s.experts.start_local=forbidden
        try:
            s.timers.capabilities({"type":"timer_capabilities","display_supported":True,"signal_supported":True})
            await s.select_mode("expert")
            await s.wake("local-timer")
            await s.append_pcm(bytes(4800))
            await s.finish_input()
            await s._stt_task
            with manager.brain.memory.connect() as db:
                assert db.execute("select count(*) from timers").fetchone()[0]==1
            assert s.selected_mode=="expert" and not s.experts.jobs
            assert not any(e['type']=='error' for e in s.events)
            for _ in range(20):
                await s.timers.refresh(force=True)
                if any(e['type']=='timer_snapshot' for e in s.events):break
                await asyncio.sleep(.02)
            assert any(e['type']=='timer_snapshot' for e in s.events)
            responses=[e for socket in provider.sockets for e in socket.sent if e['type']=='response.create']
            assert len(responses)==1 and responses[0]['response']['tool_choice']=='none'
            assert not any(e.get('item',{}).get('type')=='function_call_output' for socket in provider.sockets for e in socket.sent)
        finally:await cleanup(original,board,manager)
    asyncio.run(run())


def test_timer_journal_keeps_numeric_decision_not_arbitrary_arguments():
    result=metadata({'name':'timer_action','arguments':{'operation':'start','duration_text':'600 секунд','query':'secret'},'result':{'executed':False,'error':'timer_duration_source_mismatch','text':'secret'}})
    assert result=={'name':'timer_action','arguments':{'operation':'start','duration_seconds':600},'result':{'executed':False,'error':'timer_duration_source_mismatch'}}


@pytest.mark.parametrize("control",["stop","mute","new_turn","mode_change"])
def test_expert_local_timer_sql_wait_keeps_current_turn_authority(tmp_path,settings,monkeypatch,control):
    import threading
    async def run():
        original,board,manager,s,provider=await setup_terminal(tmp_path,settings)
        release=threading.Event();entered=threading.Event();task=None
        try:
            await s.select_mode('expert')
            turn=await s.new_turn(query='Поставь таймер на пять минут')
            real=s.manager.brain.tools.timers.start
            def held(*a,**kw):
                entered.set();assert release.wait(3);return real(*a,**kw)
            monkeypatch.setattr(s.manager.brain.tools.timers,'start',held)
            task=asyncio.create_task(s.timers.local_input(turn))
            assert await asyncio.to_thread(entered.wait,2)
            if control=='stop':await s.stop()
            elif control=='mute':await s.mute(True)
            elif control=='new_turn':await s.new_turn(query='Другой вопрос')
            else:await s.select_mode('fast')
            release.set();await task
            with manager.brain.memory.connect() as db:assert db.execute('select count(*) from timers').fetchone()[0]==0
            assert not any(e['type']=='response.create' for socket in provider.sockets for e in socket.sent)
        finally:
            release.set()
            if task:await asyncio.gather(task,return_exceptions=True)
            await cleanup(original,board,manager)
    asyncio.run(run())
