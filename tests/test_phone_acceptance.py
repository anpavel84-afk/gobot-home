"""Acceptance guard tests use private temporary ledgers; zero provider requests."""
import asyncio,json,time,sys,importlib.util
from pathlib import Path
import pytest
ROOT=Path(__file__).parents[1]
spec=importlib.util.spec_from_file_location('phone_acceptance',ROOT/'scripts/phone_acceptance.py')
acceptance=importlib.util.module_from_spec(spec);spec.loader.exec_module(acceptance)
report_spec=importlib.util.spec_from_file_location('phone_acceptance_report',ROOT/'scripts/phone_acceptance_report.py')
reports=importlib.util.module_from_spec(report_spec);report_spec.loader.exec_module(reports)

def ledger(tmp_path):
    path=tmp_path/'budget.json';path.write_text(json.dumps({'authorization':'owner-20261110-phone-3stt-2flash-800tts','expires':time.time()+100,
        'active':True,'stt_attempts':0,'stt_seconds':0,'chat_reservations':0,'tts_characters_reserved':0,'request_hashes':[]}));return path

def test_one_time_budget_reserves_failures_and_rejects_repeated_attempts(tmp_path):
    async def run():
        path=ledger(tmp_path);budget=acceptance.Budget(path)
        for i in range(3):await budget.reserve('stt','stt-'+str(i),15)
        with pytest.raises(ValueError,match='budget'):await budget.reserve('stt','fourth',1)
        for i in range(2):await budget.reserve('chat','turn-'+str(i))
        with pytest.raises(ValueError,match='budget'):await budget.reserve('chat','third')
        with pytest.raises(ValueError,match='duplicate'):await budget.reserve('chat','turn-0')
        assert json.loads(path.read_text())['tts_characters_reserved']==800
        # Restarting the guard does not replenish allowances.
        with pytest.raises(ValueError):await acceptance.Budget(path).reserve('chat','another')
    asyncio.run(run())

def test_gateway_pins_client_and_forwards_capped_nonremembered_turn(settings,tmp_path,monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from gobot.browser import ORIGIN
    if not (acceptance.RUN/acceptance.REVISION/'manifest.json').exists():acceptance.prepare()
    path=ledger(tmp_path);calls=[]
    async def response(request):
        if request.url.path=='/api/v1/chat/voice/stream':
            calls.append(json.loads(request.content))
            return httpx.Response(200,text='data: {"type":"final","data":{"text":"fixture"}}\n\n')
        return httpx.Response(200,json={'valid':False})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(**{**kw,'transport':httpx.MockTransport(response)}))
    app=acceptance.create_app(settings,budget_path=path)
    with TestClient(app,base_url=ORIGIN,client=('100.120.201.115',1000)) as client:
        body={'text':'Что такое чёрная дыра?','usage_consent':True,'speak':True,'remember':True,'turn_id':'first','tts_character_limit':9999,'mode':'codex'}
        assert client.post('/api/chat/stream',headers={'origin':ORIGIN},json=body).status_code==200
        assert calls[-1]['remember'] is False and calls[-1]['mode']=='fast'
        assert calls[-1]['tts_character_limit']==400 and calls[-1]['expensive_fallback_approved'] is False
        body.update(text='Нет, спасибо',turn_id='closing')
        assert client.post('/api/chat/stream',headers={'origin':ORIGIN},json=body).status_code==200
        assert calls[-1]['speak'] is False and calls[-1]['tts_character_limit']==0
        state=client.get('/api/acceptance/status').json()
        assert state['chat_reservations']==1
        assert client.get('/browser.js').text==(acceptance.RUN/acceptance.REVISION/'services/phone/dist/browser.js').read_text(encoding='utf8')
        # The file-duration gate rejects an oversized utterance before STT.
        import io,wave
        wav=io.BytesIO()
        with wave.open(wav,'wb') as audio:
            audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(16000);audio.writeframes(b'\0\0'*16000*16)
        response=client.post('/api/audio/transcribe?provider=openai&paid_consent=true&trace_id=too-long',headers={'origin':ORIGIN,'content-type':'audio/wav'},content=wav.getvalue())
        assert response.status_code==429
        assert client.get('/api/acceptance/status').json()['stt_attempts']==0

def test_report_separates_feedback_answer_and_remaining_silence():
    def trace(**events):return {'events':[{'name':name,'ms':ms} for name,ms in events.items()]}
    result=reports.summarize(trace(earcon_started=3,filler_started=2250,opening_completed=4250,first_answer_playback=8000))
    assert result['earcon_ms']==3 and result['useful_playback_ms']==8000
    assert result['silence_after_opening_ms']==3750
    preempted=reports.summarize(trace(filler_started=2250,opening_preempted=3000,first_answer_playback=3040))
    assert preempted['silence_after_opening_ms']==0 and not preempted['acoustic_measurement']
    assert reports.summarize(trace(earcon_started=3))['useful_playback_ms'] is None

def test_report_ignores_unrelated_household_traces(tmp_path):
    import sqlite3,hashlib
    path=ledger(tmp_path);data=json.loads(path.read_text());data['created']=0
    data['request_hashes']=[hashlib.sha256(b'allowed-trace').hexdigest()];path.write_text(json.dumps(data))
    db=tmp_path/'traces.sqlite'
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE traces(id TEXT,domain TEXT,data TEXT,created REAL)')
        for ident in ['allowed-trace','other-household-trace']:
            c.execute('INSERT INTO traces VALUES(?,?,?,?)',(ident,'client_monotonic',json.dumps({'events':[{'name':'earcon_started','ms':3}]}),1))
    output=reports.collect(path,db,tmp_path/'unused.sqlite')
    assert output['n']==1 and 'other-household-trace' not in json.dumps(output)
