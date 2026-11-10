"""Free connection regressions; independent SQLite, no provider calls."""
import asyncio,time
import pytest
from gobot import brain
from gobot.models import ChatRequest
from gobot.pipeline import voiced_events

def run_local(settings,monkeypatch,texts,*,remember=False,seed=None):
    async def run():
        service=brain.Service(settings)
        monkeypatch.setattr(brain,'agent_status',lambda *_:(_ for _ in ()).throw(AssertionError('No CLI admission for local intent')))
        if seed:seed(service)
        events=[]
        for text in texts:
            req=ChatRequest(text=text,mode='auto',remember=remember,device_id='fixture-owner',conversation_id='fixture-conversation')
            replay=await service.prepare(req)
            rows=[e async for e in service.events(req,replay)]
            assert rows[-1].type=='final',rows
            assert rows[-1].data['provider']=='local'
            events.append(rows)
        return service,events
    return asyncio.run(run())

@pytest.mark.parametrize('text',[
    'Таймер на полчаса или на час','Поставь таймер на полчаса и расскажи стих',
    'Поставь таймер не на пять минут','Таймер на пять минут или час',
    'Поставь таймер на полчаса завтра','Поставь таймер на час и открой дверь',
])
def test_whole_timer_command_cannot_escape_through_legacy(settings,monkeypatch,text):
    s,rows=run_local(settings,monkeypatch,[text])
    with s.memory.connect() as c:assert c.execute('SELECT count(*) FROM timers').fetchone()[0]==0
    assert not any(e.type=='widget_command' for e in rows[0])

def timers(service):
    with service.memory.connect() as c:
        for ident,owner,delay in [('first','fixture-owner',300),('second','fixture-owner',600),('foreign','other',900)]:
            c.execute("INSERT INTO timers VALUES(?,?,?,?,'running')",(ident,owner,'fixture-conversation',time.time()+delay))

@pytest.mark.parametrize('command,cancelled',[
    ('Отмени второй таймер',{'second'}),('Отмени таймер',set()),
    ('Отмени все таймеры',{'first','second'}),('Отмени таймер неизвестный',set()),
])
def test_timer_target_resolved_before_mutation(settings,monkeypatch,command,cancelled):
    s,_=run_local(settings,monkeypatch,[command],seed=timers)
    with s.memory.connect() as c:
        assert {r['id'] for r in c.execute("SELECT id FROM timers WHERE status='cancelled'")}==cancelled

@pytest.mark.parametrize('remember',[True,False])
def test_pending_decline_is_scoped_and_does_not_close_session(settings,monkeypatch,remember):
    s,rows=run_local(settings,monkeypatch,['Поставь таймер','Нет'],remember=remember,seed=timers)
    assert any(e.type=='tool_status' and e.data.get('status')=='pending_declined' for e in rows[1])
    assert not any(e.type=='tool_status' and e.data.get('status')=='conversation_ended' for e in rows[1])
    with s.memory.connect() as c:assert c.execute("SELECT count(*) FROM timers WHERE status='cancelled'").fetchone()[0]==0
    assert not s.memory.context(ChatRequest(text='test',device_id='fixture-owner',conversation_id='fixture-conversation',remember=remember,mode='auto')).get('pending_action')

@pytest.mark.parametrize('text',['Запусти секундомер','Поставь будильник на семь','Добавь молоко в покупки','Поставь музыку на паузу'])
def test_known_unconnected_actions_are_local_not_fictional_success(settings,monkeypatch,text):
    _,rows=run_local(settings,monkeypatch,[text])
    assert 'не подключ' in rows[0][-1].data['text'].lower() or 'не поддерж' in rows[0][-1].data['text'].lower()

def test_compound_decline_keeps_new_question(settings,monkeypatch):
    _,rows=run_local(settings,monkeypatch,['Нет, спасибо, а сколько сейчас времени?'])
    assert 'сервера' in rows[0][-1].data['text']
    assert not any(e.type=='tool_status' and e.data.get('status')=='conversation_ended' for e in rows[0])

def test_duplicate_delivery_does_not_repeat_tool(settings,monkeypatch):
    async def run():
        s=brain.Service(settings)
        req=ChatRequest(text='Таймер на полчаса',mode='auto',remember=False,request_id='fixed-request')
        await s.prepare(req)
        first=[e async for e in s.events(req)]
        repeated=req.model_copy(update={'turn_id':'different'})
        replay=await s.prepare(repeated)
        second=[e async for e in s.events(repeated,replay)]
        assert second[-1].data.get('replayed')
        with s.memory.connect() as c:assert c.execute('SELECT count(*) FROM timers').fetchone()[0]==1
    asyncio.run(run())

def test_actual_browser_opening_connection():
    import subprocess
    from pathlib import Path
    result=subprocess.run(['node','tests/opening_connection.cjs'],cwd=Path(__file__).parents[1],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stdout+result.stderr

@pytest.mark.parametrize('remember',[True,False])
def test_completed_text_survives_cancel_of_optional_visual(settings,monkeypatch,remember):
    async def run():
        service=brain.Service(settings)
        monkeypatch.setattr(brain,'agent_status',lambda *_:{'antigravity':{'available':True}})
        async def model(*_):yield 'Чёрная дыра — область пространства с сильной гравитацией.'
        async def picture(*a,**k):await asyncio.sleep(30)
        monkeypatch.setattr(brain,'bridge_stream',model)
        service.visual.attachment=picture
        req=ChatRequest(text='Что такое чёрная дыра?',mode='fast',remember=remember,device_id='fixture',conversation_id='completed-before-image')
        await service.prepare(req)
        stream=service.events(req)
        async for e in stream:
            if e.type=='tool_status' and e.data.get('status')=='speech_input_complete':break
        await stream.aclose()
        next_req=ChatRequest(text='А что ещё?',mode='fast',remember=remember,device_id=req.device_id,conversation_id=req.conversation_id)
        await service.prepare(next_req)
        context=service.memory.context(next_req)
        assert any('сильной гравитацией' in r['content'] for r in context.get('messages',[])+context.get('recent_dialogue',[]))
    asyncio.run(run())

@pytest.mark.parametrize('scenario',['no_audio','speak_off','limit_first','tts_error'])
def test_no_audio_is_not_successful_playback(settings,monkeypatch,scenario):
    async def run():
        service=brain.Service(settings)
        class Voice:
            async def synthesize(self,*a,**kw):
                if scenario=='tts_error':raise RuntimeError('fixture transport failed')
                if scenario!='no_audio':yield b'\1\0'*10,24000
        req=ChatRequest(text='Какая сегодня дата?',mode='auto',remember=False)
        events=[e async for e in voiced_events(service,Voice(),req,speak=scenario!='speak_off',tts_character_limit=0 if scenario=='limit_first' else None)]
        stops=[e for e in events if e['type']=='audio_stop']
        assert not stops if scenario=='speak_off' else stops[-1]['data']['reason']!='finished'
        assert events[-1]['type']=='final'
    asyncio.run(run())

def test_optional_catalog_failure_and_semantic_clip_selection(tmp_path,monkeypatch):
    from gobot import speech_openings as module
    cache=module.OpeningCache(tmp_path)
    rows=module.catalog()
    for row in rows:cache.put('marin',row['id'],b'\1\0'*2400,24000,row['text'])
    first=cache.select('Сравни три архитектуры','marin',{},'first',session='same')
    second=cache.select('Сравни три архитектуры','marin',{},'second',session='same')
    assert first['id']!=second['id']
    assert not any(word in first['text'].lower() for word in ['оба','двух'])
    chosen=cache.select('Придумай имя для кота','marin',{},'name')
    assert not chosen or not any(word in chosen['text'].lower() for word in ['истори','рассказ','сцен'])
    broken=tmp_path/'catalog.json';broken.write_text('{broken')
    monkeypatch.setattr(module,'CATALOG',broken)
    disabled=module.OpeningCache(tmp_path)
    assert disabled.select('Объясни','marin',{},'fixture') is None
    assert disabled.status('unknown')['ready_count']==0
