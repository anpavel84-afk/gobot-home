"""Working conversation across tentative topic boundaries. No real models."""
import json
from gobot.context_manager import ContextManager, tokens
from gobot.live_agents import context_prompt
from gobot.memory import Memory
from gobot.models import ChatRequest


def request(text, **changes):
    return ChatRequest(text=text, mode='fast', conversation_id='window',
                       device_id='window-owner', **changes)


def exchange(memory, question, answer, **changes):
    req=request(question, **changes)
    memory.start(req)
    memory.finish(req, 'completed', answer, 'bridge:antigravity', [])
    return req


def pack(memory, text, **changes):
    req=request(text, **changes)
    memory.start(req)
    return req, ContextManager().pack(text, memory.context(req), 'FAST_CHAT')


def test_assistant_entities_participate_in_topic_decision(tmp_path):
    memory=Memory(str(tmp_path/'db.sqlite'))
    first=exchange(memory, 'Какие фрукты растут в саду?', 'В примере растут яблоки и груши.')
    _, packet=pack(memory, 'Как приготовить груши?')
    assert packet['topic']['outcome']=='continue'
    assert 'яблоки и груши' in context_prompt('Как приготовить груши?',packet)
    assert packet['topic']['topic_id']==memory.archive.inspect(first.device_id,first.conversation_id)['topic']['id']


def test_uncertain_statement_keeps_dialogue_instead_of_reset(tmp_path):
    memory=Memory(str(tmp_path/'db.sqlite'))
    exchange(memory, 'Обсудим ремонт велосипеда', 'Начнём с проверки цепи.')
    _, packet=pack(memory, 'Вчера обнаружилась ещё одна неприятность.')
    assert packet['topic']['outcome']=='continue'
    assert packet['topic']['reason']=='uncertain_boundary_preserves_dialogue'
    assert len(packet['messages'])==2


def test_inferred_topic_change_still_has_last_three_exchanges(tmp_path):
    memory=Memory(str(tmp_path/'db.sqlite'))
    for i in range(5):
        exchange(memory, f'Обсудим велосипед номер {i}', f'Состояние велосипеда номер {i}.')
    _, packet=pack(memory, 'Как приготовить греческий салат?')
    assert packet['topic']['outcome']=='new_topic'
    assert packet['dialogue_state']['classification_kind']=='provisional_local_heuristic'
    assert len(packet['messages'])==6
    assert all(str(i) not in packet['messages'][0]['content'] for i in (0,1))
    assert [m['role'] for m in packet['messages']]==['user','assistant']*3
    ids=[m['id'] for m in packet['messages']]
    assert len(ids)==len(set(ids))
    assert ids==packet['_context_meta']['recent_dialogue_source_ids']


def test_explicit_topic_reset_stays_a_boundary_on_subsequent_turn(tmp_path):
    memory=Memory(str(tmp_path/'db.sqlite'))
    exchange(memory, 'Обсудим велосипед', 'Старое обсуждение велосипеда.')
    req, first=pack(memory, 'Новая тема: рецепты')
    assert not first['messages']
    memory.finish(req,'completed','Начинаем обсуждать рецепты.','bridge:antigravity',[])
    _, second=pack(memory, 'А подробнее?')
    assert len(second['messages'])==2
    assert all('велосипед' not in m['content'] for m in second['messages'])


def test_window_does_not_cross_owner_conversation_or_provenance(tmp_path):
    memory=Memory(str(tmp_path/'db.sqlite'))
    exchange(memory,'Реальная реплика в примере','Пример ответа.')
    diagnostic=request('TEST_ONLY').model_copy(update={'mode':'mock'})
    memory.start(diagnostic);memory.finish(diagnostic,'completed','MOCK_ONLY','mock',[])
    interrupted=request('INTERRUPTED_ONLY')
    memory.start(interrupted);memory.finish(interrupted,'cancelled','PARTIAL_ONLY','bridge:antigravity',[])
    other=ChatRequest(text='OTHER_USER_ONLY',mode='fast',device_id='other-owner',conversation_id='other-conversation')
    memory.start(other);memory.finish(other,'completed','PRIVATE_OTHER_REPLY','bridge:antigravity',[])
    _, packet=pack(memory,'И что дальше?')
    prompt=context_prompt('И что дальше?',packet)
    for secret in ('TEST_ONLY','MOCK_ONLY','INTERRUPTED_ONLY','PARTIAL_ONLY','OTHER_USER_ONLY','PRIVATE_OTHER_REPLY'):
        assert secret not in prompt
    assert len(packet['messages'])==2
    separate=ChatRequest(text='Привет',mode='fast',device_id='window-owner',conversation_id='separate')
    memory.start(separate)
    assert not memory.context(separate)['recent_dialogue']


def test_mock_topic_reset_does_not_reset_production_dialogue(tmp_path):
    memory=Memory(str(tmp_path/'db.sqlite'))
    exchange(memory,'Обсудим теплицу','У неё будет северный вход.')
    diagnostic=request('MOCK_PRIVATE_TOPIC',new_topic=True).model_copy(update={'mode':'mock'})
    memory.start(diagnostic);memory.finish(diagnostic,'completed','MOCK_ANSWER','mock',[])
    _, packet=pack(memory,'А почему?')
    prompt=context_prompt('А почему?',packet)
    assert 'северный вход' in prompt
    assert 'MOCK_PRIVATE_TOPIC' not in prompt and 'MOCK_ANSWER' not in prompt
    assert packet['topic']['outcome']=='continue'


def test_budget_keeps_complete_exchanges_and_records_omission():
    messages=[{'id':1,'turn_id':'first','role':'user','content':'Вопрос '*100},
              {'id':2,'turn_id':'first','role':'assistant','content':'Ответ '*100}]
    packet=ContextManager(recent=tokens(messages[-1])+10).pack('Уточнение',{'recent_dialogue':messages},'FAST_CHAT')
    assert packet['messages']==[]
    assert 'recent_exchange_over_budget' in packet['_context_meta']['omitted']


def test_summary_retains_topic_origin_and_deduplicates_recent_quotes(tmp_path):
    memory=Memory(str(tmp_path/'db.sqlite'))
    first=exchange(memory,'Обсудим теплицу с северным входом','Пока обсуждаем, решения не приняты.')
    for i in range(12):
        exchange(memory,f'А подробнее про теплицу: пункт {i}',f'Вариант объяснения пункта {i}.')
        memory.archive.maintain_one()
    with memory.connect() as c:
        summary=c.execute('SELECT * FROM topic_summaries ORDER BY version DESC LIMIT 1').fetchone()
        notes=json.loads(summary['content'])
        assert notes['decisions']==notes['open_questions']==[]
        assert tokens(summary['content'])<=500
        original=c.execute("SELECT id FROM messages WHERE turn_id=? AND role='user'",(first.turn_id,)).fetchone()[0]
        assert original in json.loads(summary['source_message_ids'])
    _, packet=pack(memory,'А что ещё важно для теплицы?')
    # Recent messages and nonoverlapping compressed source notes coexist.
    assert packet['summary']
    assert original in packet['_context_meta']['source_message_ids']
    notes=json.loads(packet['summary'])
    assert not {item['id'] for item in notes['source_excerpts']}&{m['id'] for m in packet['messages']}


def test_restart_and_intentional_identical_questions_keep_two_exchanges(tmp_path):
    path=str(tmp_path/'db.sqlite');memory=Memory(path)
    for _ in range(2):exchange(memory,'Повтори ответ','Повторённый ответ.')
    memory=Memory(path)
    _, packet=pack(memory,'Почему?')
    assert [m['content'] for m in packet['messages'] if m['role']=='user']==['Повтори ответ']*2
    assert len(packet['_context_meta']['recent_dialogue_source_ids'])==4
