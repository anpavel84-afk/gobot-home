import asyncio,json,sqlite3,time
from uuid import uuid4
import pytest
from gobot.memory import Memory,Conflict
from gobot.models import ChatRequest
from gobot.context_manager import ContextManager,tokens
from gobot.live_agents import context_prompt

def complete(memory,text,conversation='day',owner='personal:one',**options):
    req=ChatRequest(text=text,mode='fast',conversation_id=conversation,device_id=owner,**options)
    assert memory.start(req) is None
    memory.finish(req,'completed','Ответ: '+text,'bridge:antigravity',[])
    return req

def test_idempotence_ids_not_text(tmp_path):
    m=Memory(str(tmp_path/'db.sqlite'));r=complete(m,'Одинаковый вопрос',request_id='delivery-1',utterance_id='voice-1')
    assert m.start(r.model_copy(update={'turn_id':str(uuid4())}))['status']=='completed'
    complete(m,'Одинаковый вопрос',request_id='delivery-2')
    assert len(m.history('day','personal:one')['messages'])==4
    assert m.archive.utterance('personal:one','u','Про',False)
    assert m.archive.utterance('personal:one','u','Привет',True)
    assert not m.archive.utterance('personal:one','u','Повтор',True)
    with m.connect() as c:assert c.execute('SELECT count(*) FROM utterance_drafts').fetchone()[0]==1

def test_topic_timer_resume_and_scope(tmp_path):
    m=Memory(str(tmp_path/'db.sqlite'))
    first=complete(m,'Обсудим теплицу и помидоры')
    with m.connect() as c:topic=c.execute('SELECT topic_id FROM turn_topics WHERE turn_id=?',(first.turn_id,)).fetchone()[0]
    timer=complete(m,'Поставь таймер на пять минут')
    with m.connect() as c:
        row=c.execute('SELECT * FROM turn_topics WHERE turn_id=?',(timer.turn_id,)).fetchone()
        assert row['topic_id']==topic and row['outcome']=='side_action'
    complete(m,'Космические корабли летят к Марсу')
    resumed=ChatRequest(text='Вернёмся к теплице',mode='codex',device_id='personal:one',conversation_id='weeks-later')
    m.start(resumed);ctx=m.context(resumed)
    assert ctx['topic']['outcome']=='resume_topic' and ctx['topic']['topic_id']==topic
    assert any('помидоры' in r['content'] for r in ctx['messages'])
    assert not m.archive.search('personal:other','теплица')
    unknown=ChatRequest(text='Вернёмся к вертолётам',mode='fast',device_id='personal:one')
    m.start(unknown);assert m.context(unknown)['topic']['outcome']=='ambiguous'

def test_diagnostics_and_interrupted_not_retrieved(tmp_path):
    m=Memory(str(tmp_path/'db.sqlite'))
    r=ChatRequest(text='mock помидоры',mode='mock');m.start(r);m.finish(r,'completed','mock помидоры','mock',[])
    r=ChatRequest(text='Неоконченные помидоры',mode='fast');m.start(r);m.finish(r,'cancelled','Помидоры','bridge:antigravity',[])
    assert not m.archive.search('local-test','помидоры')
    with m.connect() as c:assert c.execute('SELECT count(*) FROM messages').fetchone()[0]==4
    complete(m,'CLI test tomatoes',conversation='live-approved-fixture',owner='local-test')
    assert not m.archive.search('local-test','tomatoes')

def test_delete_and_correct_fact_no_resurrection(tmp_path):
    m=Memory(str(tmp_path/'db.sqlite'));complete(m,'Теплица красная')
    m.add_fact('personal:one','Люблю чай',True)
    fact=m.archive.inspect('personal:one','day')['facts'][0]
    assert not m.archive.revise_fact('personal:other',fact['id'],'Люблю кофе')
    assert m.archive.revise_fact('personal:one',fact['id'],'Люблю кофе')
    assert [r['content'] for r in m.archive.inspect('personal:one','day')['facts']]==['Люблю кофе']
    assert m.archive.forget_conversation('personal:one','day');m.archive.maintain_one()
    assert not m.archive.search('personal:one','теплица')
    with m.connect() as c:assert c.execute('SELECT count(*) FROM topic_summaries').fetchone()[0]==0

def test_temporary_no_content_on_disk_and_restart(tmp_path):
    path=str(tmp_path/'db.sqlite');m=Memory(path)
    r=ChatRequest(text='NEVER_PERSIST_ME',mode='fast',remember=False,request_id='tmp')
    m.start(r);m.finish(r,'completed','PRIVATE_REPLY','bridge:antigravity',[])
    assert m.start(r)['result']=='PRIVATE_REPLY'
    with m.connect() as c:assert c.execute('SELECT count(*) FROM messages').fetchone()[0]==0
    assert not m.context(r)['messages']
    complete(m,'сохранившаяся теплица')
    assert Memory(path).archive.search('personal:one','теплица')

def test_budget_actual_prompt_and_no_duplicate_fragments():
    ctx={'messages':[{'id':1,'role':'user','content':'Теплица '*1000,'provider':'input'}],
         'retrieved':[{'message_id':1,'topic_id':'t','content':'Теплица '*1000,'created':0}],
         'facts':['чай '*1000],'summary':'помидоры '*1000}
    packet=ContextManager().pack('Привет',ctx,'FAST_CHAT')
    assert tokens(context_prompt('Привет',packet))==packet['_context_meta']['packet_tokens']<=6000
    assert packet['_context_meta']['omitted']
    with pytest.raises(Exception,match='context_request_exceeds_budget'):ContextManager(maximum=300).pack('x '*1000,{},'FAST_CHAT')

def test_sqlite_online_backup_includes_wal(tmp_path):
    path=tmp_path/'legacy.sqlite';c=sqlite3.connect(path);c.execute('PRAGMA journal_mode=WAL')
    from gobot.memory import SCHEMA
    c.executescript(SCHEMA);c.execute("INSERT INTO conversations VALUES('legacy','one',0)")
    c.execute("INSERT INTO messages VALUES(1,'legacy','user','WAL_CONTENT','input','turn',0)");c.commit()
    Memory(str(path))
    backup=next((tmp_path/'backups').glob('*.sqlite'));b=sqlite3.connect(backup)
    assert b.execute('SELECT content FROM messages').fetchone()[0]=='WAL_CONTENT';b.close();c.close()

def test_budget_gate_counts_retries_and_requires_actual_usage(tmp_path):
    m=Memory(str(tmp_path/'db.sqlite'));r=complete(m,'Привет')
    assert not m.archive.reserve_auxiliary('summary',1,enabled=True)
    p=ContextManager().pack(r.text,{},'FAST_CHAT');m.archive.record_context(r,p,'fixture')
    m.archive.record_usage(r,{'total_tokens':1000})
    assert not m.archive.reserve_auxiliary('summary',20)
    assert m.archive.reserve_auxiliary('summary',60,enabled=True)
    assert m.archive.reserve_auxiliary('summary',40,enabled=True)
    assert not m.archive.reserve_auxiliary('summary',1,enabled=True)
    with m.connect() as c:assert c.execute('SELECT tokens,attempts FROM auxiliary_usage').fetchone()[:]==(100,2)

def test_pending_timer_expires_and_does_not_reset_topic(tmp_path):
    from gobot.local_tools import LocalTools
    from gobot.routing import SmartRouter
    m=Memory(str(tmp_path/'db.sqlite'));tools=LocalTools(m)
    r=complete(m,'Поставь таймер');assert 'сколько' in tools.execute('timer',r).text
    next_req=ChatRequest(text='пять минут',mode='auto',device_id=r.device_id,conversation_id=r.conversation_id)
    m.start(next_req);ctx=m.context(next_req)
    assert SmartRouter().choose(next_req,ctx,{}).tool=='timer'
    with m.connect() as c:c.execute('UPDATE pending_actions SET expires=0')
    assert not m.context(next_req)['pending_action']

def test_summary_source_attribution_and_generation_delete(tmp_path):
    m=Memory(str(tmp_path/'db.sqlite'))
    for i in range(5):complete(m,'А подробнее про теплицу '+str(i))
    m.archive.maintain_one()
    with m.connect() as c:
        summary=c.execute('SELECT * FROM topic_summaries').fetchone();assert summary
        content=json.loads(summary['content']);assert content['decisions']==[]
        for quote in content['source_excerpts']:
            assert c.execute('SELECT content FROM messages WHERE id=?',(quote['id'],)).fetchone()[0].startswith(quote['excerpt'])
    m.archive.forget_owner('personal:one');m.archive.maintain_one()
    with m.connect() as c:
        assert c.execute('SELECT count(*) FROM topics').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM retrieval_chunks').fetchone()[0]==0

def test_idle_episode_weeks_return_and_ambiguous_offline(tmp_path,monkeypatch):
    from gobot import archive
    from gobot.routing import SmartRouter
    clock=[1700000000.0];monkeypatch.setattr(archive.time,'time',lambda:clock[0])
    m=Memory(str(tmp_path/'db.sqlite'));first=complete(m,'Теплица и помидоры')
    with m.connect() as c:topic=c.execute('SELECT topic_id FROM turn_topics WHERE turn_id=?',(first.turn_id,)).fetchone()[0]
    clock[0]+=7200;second=complete(m,'А подробнее про теплицу?')
    with m.connect() as c:
        assert c.execute('SELECT count(*) FROM episodes').fetchone()[0]==2
        assert c.execute('SELECT topic_id FROM turn_topics WHERE turn_id=?',(second.turn_id,)).fetchone()[0]==topic
    clock[0]+=14*86400
    req=ChatRequest(text='Вернёмся к теплице',mode='fast',device_id='personal:one',conversation_id='another-day')
    m.start(req);assert m.context(req)['topic']['topic_id']==topic
    ambiguous=ChatRequest(text='Оно?',mode='auto',device_id='personal:other')
    m.start(ambiguous);ctx=m.context(ambiguous)
    assert ctx['topic']['outcome']=='ambiguous'
    assert SmartRouter().choose(ambiguous,ctx,{}).tool=='clarify_topic'
