"""Synthetic conversations and temporary SQLite only; no model/device calls."""
import asyncio
from datetime import datetime
import json
import threading
from zoneinfo import ZoneInfo

import pytest

from gobot.memory import Memory
from gobot.native_archive import ArchiveBinding, NativeArchiveService, validate_policy


def setup(tmp_path, *, days=0, read=True, write=True, zone='America/Sao_Paulo'):
    memory = Memory(str(tmp_path/'memory.sqlite'))
    clock = [datetime(2026,11,20,23,59,tzinfo=ZoneInfo(zone)).timestamp()]
    service = NativeArchiveService(memory,clock=lambda:clock[0])
    binding = ArchiveBinding('board','board','board@enrolled-owner')
    state = service.configure(binding,{'write_enabled':write,'read_enabled':read,
        'retention_days':days,'timezone':zone},0,operation_id='enable',actor_id='verified-owner')
    return memory,service,binding,clock,state


def question(service,binding,state,text='Обсудим бензин без рекомендаций покупки.',turn='turn-1',**kwargs):
    return service.record_question(binding,turn,'conversation-1',text,
        generation=state['generation'],**kwargs)


def answer(service,binding,state,text='Бензин обсуждался только для сравнения.',turn='turn-1',**kwargs):
    return service.record_answer(binding,turn,text,generation=state['generation'],
        heard=True,provider='openai:synthetic',**kwargs)


def test_new_store_is_disabled_and_does_not_adopt_existing_archive(tmp_path):
    from gobot.models import ChatRequest
    memory = Memory(str(tmp_path/'memory.sqlite'))
    binding = ArchiveBinding('board','board','board@owner')
    req = ChatRequest(text='Старый отдельный разговор про бензин',device_id=binding.archive_owner,mode='fast')
    memory.start(req); memory.finish(req,'completed','Старый ответ','bridge:antigravity',[])
    status = memory.native_archive.status(binding)
    assert status['revision']==0 and not status['policy']['write_enabled']
    with memory.connect() as db:
        assert db.execute('SELECT count(*) FROM native_archive_scopes').fetchone()[0]==0
    state = memory.native_archive.configure(binding,{'write_enabled':True,'read_enabled':True,
        'retention_days':0,'timezone':'UTC'},0,operation_id='enable',actor_id='owner')
    assert not memory.native_archive.recall(binding,'Бензин')['useful']
    memory.native_archive.clear(binding,state['revision'],operation_id='clear',actor_id='owner')
    assert memory.archive.search(binding.archive_owner,'Бензин')


@pytest.mark.parametrize('days',[2,30])
def test_archive_survives_days_restart_and_new_logical_conversation(tmp_path,days):
    memory,service,binding,clock,state=setup(tmp_path)
    q=question(service,binding,state); answer(service,binding,state)
    assert question(service,binding,state)['replayed']
    assert answer(service,binding,state)['replayed']
    clock[0]+=days*86400
    restored=NativeArchiveService(Memory(memory.path),clock=lambda:clock[0])
    found=restored.recall(binding,'Какие особенности бензина?',exclude_turn_id='brand-new-turn')
    assert found['useful'] and [m['role'] for m in found['messages']]==['user','assistant']
    assert found['messages'][0]['id']==q['source_id']
    assert all(m['source_kind']=='device_archive' for m in found['messages'])
    assert found['messages'][0]['local_date']=='2026-11-20'
    assert restored.status(binding)['counts']['turns']==1


@pytest.mark.parametrize('query',['О чём мы говорили вчера?','Что я спрашивал вчера?','Про бензин вчера',
    'Напомни, о чём шла речь вчера','О чём мы беседовали вчера?',
    'Какие темы мы обсуждали вчера?','О чём был вчерашний разговор?'])
def test_period_queries_use_device_calendar_across_utc_midnight(tmp_path,query):
    memory,service,binding,clock,state=setup(tmp_path)
    question(service,binding,state)
    clock[0]+=120  # UTC date was already the 21st; the configured local date now changes.
    found=service.recall(binding,query)
    assert found['useful'] and found['messages'][0]['local_date']=='2026-11-20'
    assert not service.recall(binding,'Про самолёты вчера')['useful']
    assert not service.recall(binding,'Расскажи про речь вчера')['useful']
    clock[0]+=86400
    assert service.recall(binding,'Что я спрашивал позавчера?')['useful']
    assert not service.recall(binding,'Про бензин вчера')['useful']


def test_question_and_only_confirmed_heard_answer_are_separate_sources(tmp_path):
    memory,service,binding,clock,state=setup(tmp_path)
    question(service,binding,state)
    assert not service.record_answer(binding,'turn-1','НЕУСЛЫШАННЫЙ ХВОСТ',
        generation=state['generation'],heard=False)['recorded']
    assert [m['role'] for m in service.recall(binding,'Бензин')['messages']]==['user']
    answer(service,binding,state,'Услышанная часть про бензин.',complete=False)
    result=service.recall(binding,'Бензин')
    heard=result['messages'][1]
    assert heard['heard'] and not heard['content_complete'] and heard['status']=='incomplete'
    assert heard['provenance']=='assistant_statement'
    with memory.connect() as db:
        assert not db.execute("SELECT 1 FROM messages WHERE content LIKE '%НЕУСЛЫШАННЫЙ%'").fetchone()


def test_answer_continuation_is_idempotent_and_cannot_rewrite_heard_prefix(tmp_path):
    memory,service,binding,clock,state=setup(tmp_path)
    question(service,binding,state); answer(service,binding,state,'Бензин: первая часть.')
    answer(service,binding,state,'Бензин: первая часть. Уточнение.',source_revision=2)
    assert answer(service,binding,state,'Бензин: первая часть. Уточнение.',source_revision=2)['replayed']
    with pytest.raises(ValueError,match='archive_source_conflict'):
        answer(service,binding,state,'Другой ответ.',source_revision=3)
    assert len(service.recall(binding,'Бензин')['messages'])==2


@pytest.mark.parametrize('changed',[ArchiveBinding('other','other','other@owner'),
    ArchiveBinding('board','board','board@new-owner')])
def test_foreign_binding_cannot_read_or_modify_sources(tmp_path,changed):
    memory,service,binding,clock,state=setup(tmp_path)
    question(service,binding,state)
    with pytest.raises(PermissionError):
        service.recall(changed,'Бензин')
    service.clear(changed,0,operation_id='clear-foreign',actor_id='owner')
    assert service.recall(binding,'Бензин')['useful']
    with pytest.raises(ValueError,match='archive_binding_invalid'):
        ArchiveBinding('personal:one','personal:one','personal:one@owner')


def test_policy_cas_receipts_disable_and_clear_do_not_renew_an_old_operation(tmp_path):
    memory,service,binding,clock,state=setup(tmp_path)
    question(service,binding,state); answer(service,binding,state)
    disabled=service.configure(binding,{**state['policy'],'write_enabled':False},state['revision'],
        operation_id='disable',actor_id='owner')
    assert service.recall(binding,'Бензин')['useful']
    with pytest.raises(PermissionError,match='archive_context_changed'):
        question(service,binding,state,turn='late')
    cleared=service.clear(binding,disabled['revision'],operation_id='clear',actor_id='owner')
    assert cleared['counts']['messages']==0 and not service.recall(binding,'Бензин')['useful']
    replay=service.configure(binding,{**state['policy'],'write_enabled':False},state['revision'],
        operation_id='disable',actor_id='owner')
    assert replay['operation']['replayed'] and replay['revision']==cleared['revision']
    assert service.status(binding,operation_id='clear',actor_id='owner')['operation']['applied_revision']==cleared['revision']
    assert service.status(binding,operation_id='clear',actor_id='other')['operation'] is None
    with pytest.raises(ValueError,match='archive_operation_conflict'):
        service.clear(binding,cleared['revision'],operation_id='clear',actor_id='owner')
    with pytest.raises(ValueError,match='archive_revision_conflict'):
        service.clear(binding,0,operation_id='new-clear',actor_id='owner')


def test_retention_deletes_all_derived_sources_and_increments_generation(tmp_path):
    memory,service,binding,clock,state=setup(tmp_path,days=1)
    for index in range(4):
        question(service,binding,state,turn='q'+str(index)); answer(service,binding,state,turn='q'+str(index))
    memory.archive.maintain_one(owner=binding.archive_owner)
    assert service.status(binding)['counts']['blocks']>0
    clock[0]+=2*86400
    assert service.expire(binding)==4
    assert service.policy(binding)['generation']>state['generation']
    assert not service.recall(binding,'Бензин')['useful']
    memory.archive.maintain_one(owner=binding.archive_owner)
    with memory.connect() as db:
        for table in ('messages','retrieval_chunks','topic_summaries','memory_jobs','native_archive_turns','native_archive_sources'):
            assert db.execute('SELECT count(*) FROM '+table).fetchone()[0]==0
        assert db.execute('SELECT count(*) FROM native_archive_operations').fetchone()[0]==1


@pytest.mark.parametrize('valid_checks',[0,1])
def test_revocation_before_commit_rolls_back_sources_and_operation_receipts(tmp_path,valid_checks):
    memory,service,binding,clock,state=setup(tmp_path)
    checks=[]
    def current():
        checks.append(True); return len(checks)<=valid_checks
    with pytest.raises(PermissionError,match='archive_context_changed'):
        question(service,binding,state,is_current=current)
    assert service.status(binding)['counts']['messages']==0
    checks.clear()
    with pytest.raises(PermissionError,match='archive_context_changed'):
        service.clear(binding,state['revision'],operation_id='clear',actor_id='owner',is_current=current)
    assert service.status(binding)['revision']==state['revision']
    assert service.status(binding,operation_id='clear',actor_id='owner')['operation'] is None


def test_background_write_keeps_acceptance_date_and_bounded_shutdown_drains(tmp_path,monkeypatch):
    async def run():
        memory,service,binding,clock,state=setup(tmp_path)
        entered=threading.Event(); release=threading.Event(); original=service.record_question
        def delayed(*args,**kwargs):
            entered.set(); release.wait(2); return original(*args,**kwargs)
        monkeypatch.setattr(service,'record_question',delayed)
        accepted=clock[0]
        service.enqueue(binding,'question',source_turn_id='delayed',conversation_id='conversation',
            text='Бензин вчера вечером.',generation=state['generation'],accepted_at=accepted,is_current=lambda:True)
        await asyncio.to_thread(entered.wait,1)
        assert service.pending_writes[binding.key]==1
        clock[0]+=120
        release.set()
        await service.close(grace_seconds=2)
        found=service.recall(binding,'Про бензин вчера')
        assert found['messages'][0]['created_at']==accepted
        assert service.pending_writes[binding.key]==0
    asyncio.run(run())


@pytest.mark.parametrize('values',[
    {'write_enabled':True},
    {'write_enabled':1,'read_enabled':True,'retention_days':0,'timezone':'UTC'},
    {'write_enabled':True,'read_enabled':True,'retention_days':-1,'timezone':'UTC'},
    {'write_enabled':True,'read_enabled':True,'retention_days':0,'timezone':'made-up-zone'}])
def test_invalid_policy_fails_closed(values):
    with pytest.raises(ValueError):validate_policy(values)


def test_old_same_owner_topics_and_notes_are_never_adopted_or_deleted(tmp_path):
    from gobot.models import ChatRequest
    memory=Memory(str(tmp_path/'memory.sqlite'))
    service=memory.native_archive
    binding=ArchiveBinding('board','board','board@existing-owner')
    for index in range(4):
        req=ChatRequest(text='Бензин LEGACY_CANARY '+str(index),device_id=binding.archive_owner,
            conversation_id='legacy-conversation',turn_id='legacy-'+str(index),mode='fast')
        memory.start(req);memory.finish(req,'completed','LEGACY_CANARY старый ответ','bridge:antigravity',[])
    memory.archive.maintain_one(owner=binding.archive_owner)
    tables=('topics','episodes','messages','retrieval_chunks','topic_summaries','turn_topics','conversations','turns')
    with memory.connect() as db:
        before={table:[tuple(row) for row in db.execute('SELECT * FROM '+table)] for table in tables}
    assert service.status(binding)['counts']==dict(turns=0,messages=0,topics=0,blocks=0,backlog=0)
    state=service.configure(binding,dict(write_enabled=True,read_enabled=True,retention_days=0,timezone='UTC'),
        0,operation_id='enable',actor_id='owner')
    for index in range(4):
        question(service,binding,state,'Помнишь бензин? Только новый разрешённый разговор.',turn='native-'+str(index))
        answer(service,binding,state,'Новый ответ про бензин.',turn='native-'+str(index))
    memory.archive.maintain_one(native_binding=binding.key)
    assert service.status(binding)['counts']['blocks']==1
    with memory.connect() as db:
        notes=db.execute('''SELECT content FROM topic_summaries WHERE topic_id IN (
            SELECT tt.topic_id FROM turn_topics tt JOIN native_archive_turns n ON n.archive_turn_id=tt.turn_id
            WHERE n.binding_key=?)''',(binding.key,)).fetchall()
        assert notes and all('LEGACY_CANARY' not in row[0] for row in notes)
    service.clear(binding,state['revision'],operation_id='clear',actor_id='owner')
    with memory.connect() as db:
        after={table:[tuple(row) for row in db.execute('SELECT * FROM '+table)] for table in tables}
    assert after==before


def test_working_and_archive_aliases_deduplicate_each_source_without_orphans(tmp_path):
    from gobot.models import ChatRequest
    from gobot.working_memory import source_message
    memory,service,binding,clock,state=setup(tmp_path)
    memory.native_archive=service
    original=ChatRequest(text='Особенности бензина',device_id='realtime-guest:session',
        conversation_id='conversation',turn_id='turn-1',remember=False)
    memory.start(original);memory.finish(original,'completed','Бензин обсуждался для сравнения','openai:synthetic',[])
    with memory.transient_lock:
        row=memory.transient[original.turn_id]
        user=source_message(original.turn_id,row,'user')['id']
        assistant=source_message(original.turn_id,row,'assistant')['id']
    question(service,binding,state,original.text,aliases=[user])
    answer(service,binding,state,'Бензин обсуждался для сравнения',aliases=[assistant])
    req=original.model_copy(update={'turn_id':'later','text':'Какие особенности бензина?'})
    memory.bind_native_archive(req,binding,state['generation'],lambda:True)
    result=memory.recall(req)
    assert len(result['messages'])==2 and result['source_ids']==[user,assistant]
    assert not service.recall(binding,req.text,exclude_source_ids=[user])['messages']
    only_question=service.recall(binding,req.text,exclude_source_ids=[assistant])['messages']
    assert len(only_question)==1 and only_question[0]['role']=='user'


def test_working_question_retains_new_archived_expert_answer_as_one_exchange(tmp_path):
    from gobot.models import ChatRequest
    from gobot.working_memory import source_message
    from gobot.context_manager import ContextManager
    memory,service,binding,clock,state=setup(tmp_path)
    memory.native_archive=service
    original=ChatRequest(text='Особенности бензина',device_id='realtime-guest:session',
        conversation_id='conversation',turn_id='turn-1',remember=False)
    memory.start(original);memory.finish(original,'incomplete','','openai:synthetic',[],heard=False)
    with memory.transient_lock:
        user=source_message(original.turn_id,memory.transient[original.turn_id],'user')['id']
    question(service,binding,state,original.text,aliases=[user])
    answer(service,binding,state,'Новый услышанный экспертный ответ про бензин.',component='expert:job')
    req=original.model_copy(update={'turn_id':'later','text':'Какие особенности бензина?'})
    memory.bind_native_archive(req,binding,state['generation'],lambda:True)
    result=memory.recall(req)
    assert [item['role'] for item in result['messages']]==['user','assistant']
    assert result['messages'][0]['id']==user
    assert {item['turn_id'] for item in result['messages']}=={'turn-1'}
    packet=ContextManager.configured().pack(req.text,result,'FAST_CHAT')
    assert [item['role'] for item in packet['messages']]==['user','assistant']
    # The real Direct hot packet already contains the user source. Its
    # exclusion must not hide a newly heard expert answer from cold storage.
    hot=ContextManager.configured().pack(req.text,memory.context(req),'FAST_CHAT')
    excluded=hot['_context_meta']['complete_source_message_ids']
    result=memory.recall(req,exclude_source_ids=excluded)
    assert [item['role'] for item in result['messages']]==['user','assistant']
    assert result['messages'][0]['context_only'] and 'id' not in result['messages'][0]
    assert user not in result['source_ids']
    packet=ContextManager.configured().pack(req.text,result,'FAST_CHAT')
    assert [item['role'] for item in packet['messages']]==['user','assistant']
    assert user not in packet['_context_meta']['source_message_ids']
    from gobot.realtime_memory import DialogueMemory
    assert not DialogueMemory.adds_information({'messages':[result['messages'][0]]},'')
    assert DialogueMemory.adds_information({'messages':packet['messages']},'Первое краткое объяснение.')


def test_saved_incremental_blocks_are_grounded_bounded_and_date_scoped(tmp_path):
    from gobot.context_manager import ContextManager,tokens
    memory,service,binding,clock,state=setup(tmp_path)
    for index in range(6):
        question(service,binding,state,'Бензин: сравнивали условие '+str(index),turn='block-'+str(index))
        answer(service,binding,state,'Услышанное объяснение бензина '+str(index),turn='block-'+str(index))
        memory.archive.maintain_one()
    result=service.recall(binding,'Бензин',limit=1)
    assert result['summary'] and result['summary_source_ids']
    assert tokens(result['summary'])<=ContextManager.configured().limits['summary']
    assert not set(result['summary_source_ids']) & {item['id'] for item in result['messages']}
    for note in json.loads(result['summary'])['source_excerpts']:
        with memory.connect() as db:
            source=db.execute('SELECT content FROM messages WHERE id=?',(int(note['id'].split(':')[1]),)).fetchone()
        assert source[0].startswith(note['excerpt']) and note['heard']
        assert note['source_kind']=='device_archive' and note['local_date']=='2026-11-20'
    clock[0]+=2*86400
    assert not service.recall(binding,'О чём мы говорили вчера?')['summary']
