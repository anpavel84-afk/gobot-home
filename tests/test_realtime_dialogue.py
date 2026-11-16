"""Automatic half-duplex B conversation: protocol fixtures, never paid calls."""
import asyncio,time,json,subprocess
from pathlib import Path
import pytest
from test_realtime_native import configured,start,command,tick

async def until_closed(s):
    for _ in range(120):
        if s.closed:return
        await asyncio.sleep(.02)
    raise AssertionError('bounded idle/noise close missing')

def test_first_question_and_two_followups_without_ptt_or_new_session(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);s=await start(m)
        try:
            await command(s,'listen')
            assert s.current is None and s.input_mode=='followup'
            assert 0<s.followup_deadline-time.monotonic()<=10
            assert not any(e['type']=='response.create' for e in s.ws.sent)
            for i in range(3):
                detection=s.ws.config['audio']['input']['turn_detection']
                assert not detection['create_response'] and not detection['interrupt_response']
                await s.handle({'type':'input_audio_buffer.speech_started'})
                deadline=s.auto_input_deadline
                await s.handle({'type':'input_audio_buffer.speech_started'})
                assert s.auto_input_deadline==deadline # Noise cannot extend an utterance forever.
                await s.handle({'type':'input_audio_buffer.speech_stopped'})
                await s.handle({'type':'input_audio_buffer.committed','item_id':f'question-{i}'})
                await tick();response=f'resp_{i+1}'
                assert s.input_mode=='processing' and s.auto_input_deadline is None
                await s.handle({'type':'input_audio_buffer.committed','item_id':f'question-{i}'})
                await tick()
                assert sum(e['type']=='response.create' for e in s.ws.sent)==i+1
                await s.handle({'type':'response.output_audio_transcript.delta','response_id':response,'delta':'Проверенный тестовый ответ.'})
                await s.handle({'type':'output_audio_buffer.started','response_id':response})
                await s.handle({'type':'response.done','response':{'id':response,'status':'completed'}})
                with pytest.raises(ValueError,match='playback_not_finished'):await command(s,'listen')
                await command(s,'playback_started',response_id=response)
                await s.handle({'type':'output_audio_buffer.stopped','response_id':response})
                with pytest.raises(ValueError,match='playback_not_finished'):await command(s,'listen')
                await command(s,'playback_stopped',response_id=response)
                assert s.current.stored
                await command(s,'listen')
            assert len(m.sessions)==1 and not s.closed
            assert not any(e['type']=='input_audio_buffer.commit' for e in s.ws.sent)
            s.followup_deadline=time.monotonic()-1;await until_closed(s)
            assert s.close_reason=='followup_timeout'
        finally:await m.shutdown()
    asyncio.run(run())

def test_continuous_noise_is_bounded_without_committing_a_truncated_question(tmp_path,settings):
    async def run():
        m,p,b=configured(tmp_path,settings);s=await start(m)
        try:
            await command(s,'listen');await s.handle({'type':'input_audio_buffer.speech_started'})
            s.auto_input_deadline=time.monotonic()-1;await until_closed(s)
            assert s.close_reason=='input_time_limit'
            assert not any(e['type']=='response.create' for e in s.ws.sent)
        finally:await m.shutdown()
    asyncio.run(run())

def test_production_browser_automatic_dialogue_cases():
    result=subprocess.run(['node','tests/realtime_dialogue.cjs'],cwd=Path(__file__).parents[1],text=True,capture_output=True,timeout=20)
    assert result.returncode==0,result.stdout+result.stderr
    evidence=json.loads(result.stdout);assert evidence['sessions']==1 and evidence['provider_calls']==0 and evidence['without_second_tap']
