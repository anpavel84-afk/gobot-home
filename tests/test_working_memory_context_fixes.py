"""Scoped synthetic memory regressions; no provider or microphone calls."""
import json

import pytest

from gobot.context_manager import ContextManager, serialize_context, tokens
from gobot.local_tools import LocalTools
from gobot.memory import Memory
from gobot.models import ChatRequest
from gobot.quality import RiskAssessment, SelectiveVerifier


def native_context(messages):
    return {'messages':messages, 'summary':'', '_memory_meta':{
        'version':7, 'available_exchanges':len(messages)//2,
        'scope_id':'scope-hash-not-for-provider', 'coverage':'partial_working_context',
        'persisted':False, 'ttl_seconds':3600}}


def exchange(prefix, question, answer, **changes):
    return [
        {'id':prefix+':user', 'turn_id':prefix, 'role':'user', 'content':question,
         'provider':'input', 'status':'completed'},
        {'id':prefix+':assistant', 'turn_id':prefix, 'role':'assistant',
         'content':answer, 'provider':'realtime', 'heard':True,
         'status':'completed', **changes},
    ]


def test_native_long_latest_replays_older_exchange_and_marked_excerpt():
    prior=exchange('prior', 'В условном саду обсуждали сорт 427.', 'Сорт 427 остаётся темой примера.')
    newest=exchange('newest', 'Разбери подробности этого сорта.',
                    'Начало подробного ответа. '+('Развёрнутое объяснение. '*2000)+
                    'Конец: это пример, а не подтверждённый факт.')
    packet=ContextManager().pack('А что мы решили?', native_context(prior+newest), 'FAST_CHAT')
    messages=packet['messages'];ids={item['id'] for item in messages}
    assert {'prior:user','prior:assistant','newest:user','newest:assistant'}<=ids
    clipped=next(item for item in messages if item['id']=='newest:assistant')
    assert clipped['heard'] is True and clipped['status']=='completed'
    assert clipped['content_complete'] is False and clipped['excerpted'] is True
    assert clipped['content'].startswith('Начало подробного ответа.')
    assert clipped['content'].endswith('это пример, а не подтверждённый факт.')
    meta=packet['_context_meta']
    assert meta['section_tokens']['messages']<=1500
    assert tokens(packet['messages'])<=1500
    assert tokens(serialize_context('А что мы решили?',packet))==meta['packet_tokens']<=6000
    assert 'newest:assistant' in meta['partial_source_message_ids']
    assert 'newest:assistant' not in meta['complete_source_message_ids']
    assert 'prior:assistant' in meta['complete_source_message_ids']
    assert packet['memory_state']['version']==7
    assert 'scope_id' not in packet['memory_state']


def test_legacy_long_latest_does_not_suppress_older_complete_pair():
    old=[{'id':1,'turn_id':'old','role':'user','content':'Предыдущий короткий вопрос.'},
         {'id':2,'turn_id':'old','role':'assistant','content':'Предыдущий короткий ответ.'}]
    long=[{'id':3,'turn_id':'new','role':'user','content':'Подробности?'},
          {'id':4,'turn_id':'new','role':'assistant','content':'Длинное объяснение. '*4000}]
    packet=ContextManager().pack('Уточнение',{'messages':old+long},'FAST_CHAT')
    assert [item['id'] for item in packet['messages']]==[1,2]
    assert 'recent_exchange_over_budget' in packet['_context_meta']['omitted']


def test_oversized_historical_question_is_explicitly_partial():
    question='Начало условия 427. '+('Подробное условие. '*2000)+'Конец: не выполнять действие.'
    packet=ContextManager().pack('Продолжим',native_context(exchange('large',question,'Ответ на условие.')),'FAST_CHAT')
    user=next(item for item in packet['messages'] if item['role']=='user')
    assert user['content_complete'] is False
    assert user['content'].endswith('не выполнять действие.')
    assert user['source_characters']==len(question)
    assert packet['_context_meta']['section_tokens']['messages']<=1500
    assert tokens(packet['messages'])<=1500
    # Unlike historical excerpts, the current input must not be silently clipped.
    with pytest.raises(Exception,match='context_request_exceeds_budget'):
        ContextManager().pack(question,native_context([]),'FAST_CHAT')


def test_unheard_answer_is_excluded_without_losing_its_question():
    messages=exchange('cancelled','Пользователь успел спросить про бензин.',
                      'UNHEARD_ASSISTANT_CANARY',heard=False,status='cancelled')
    packet=ContextManager().pack('Продолжим',native_context(messages),'FAST_CHAT')
    assert [item['role'] for item in packet['messages']]==['user']
    assert 'UNHEARD_ASSISTANT_CANARY' not in json.dumps(packet,ensure_ascii=False)
    assert 'unheard_assistant_excluded' in packet['_context_meta']['omitted']


def test_string_source_ids_deduplicate_without_losing_playback_metadata():
    messages=exchange('source','Вопрос о примере.','Ответ о примере.',content_complete=False)
    context=native_context(messages)
    context['recent_dialogue']=[dict(item) for item in messages]
    packet=ContextManager().pack('Уточнение',context,'FAST_CHAT')
    assert len(packet['messages'])==2
    answer=packet['messages'][1]
    assert answer['heard'] is True and answer['content_complete'] is False
    assert packet['_context_meta']['source_message_ids']==['source:user','source:assistant']


def stored(memory, question='В условном примере обсуждаем бензин и число 427.',
           answer='В примере речь была о бензине; число 427 условное.', **changes):
    req=ChatRequest(text=question,device_id='realtime-guest:fixture',conversation_id='dialogue',
                    remember=False,**changes)
    memory.start(req)
    memory.finish(req,'completed',answer,'realtime',[])
    return req


@pytest.mark.parametrize('question',[
    'Что мы говорили про бензин?',
    'Что мы обсуждали про бензин?',
    'Помнишь, мы говорили про бензин?',
    'Что я спрашивал?',
])
def test_current_conversation_memory_does_not_require_pin(tmp_path,question):
    memory=Memory(str(tmp_path/'memory.sqlite'));tools=LocalTools(memory)
    previous=stored(memory)
    req=ChatRequest(text=question,device_id=previous.device_id,
                    conversation_id=previous.conversation_id,remember=False)
    result=tools.execute('memory',req)
    assert '427' in result.text and 'PIN' not in result.text
    assert result.evidence['status']=='matched'
    assert result.evidence['scope']=='current_conversation'
    assert result.evidence['source_records_verified'] is True
    assert result.evidence['verification_scope']=='conversation_record_only'
    assert result.evidence['facts_verified'] is False
    assert result.evidence['private_archive_checked'] is False
    assert result.evidence['canonical_answer'] in result.text
    assert result.evidence['source_message_ids']
    with memory.connect() as connection:
        assert connection.execute('SELECT count(*) FROM messages').fetchone()[0]==0
        assert connection.execute('SELECT count(*) FROM archive_messages').fetchone()[0]==0
    assessed=RiskAssessment().assess('Что мы обсуждали про бензин?',{})
    assert SelectiveVerifier().check(assessed,result.text,result.evidence)['accepted'] is True


def test_foreign_scope_cannot_recall_current_or_private_history(tmp_path):
    memory=Memory(str(tmp_path/'memory.sqlite'));tools=LocalTools(memory)
    stored(memory,answer='PRIVATE_OTHER_GUEST_CANARY бензин')
    private=ChatRequest(text='PRIVATE_ARCHIVE_CANARY бензин',device_id='personal:one',
                        conversation_id='private',remember=True,mode='fast')
    memory.start(private);memory.finish(private,'completed','PRIVATE_ARCHIVE_ANSWER','bridge:antigravity',[])
    foreign=ChatRequest(text='Что мы говорили про бензин?',device_id='realtime-guest:other',
                        conversation_id='dialogue',remember=False)
    result=tools.execute('memory',foreign)
    assert 'CANARY' not in result.text and 'PIN' not in result.text
    assert result.evidence['status']=='not_found'
    assert result.evidence['source_message_ids']==[]
    assert result.evidence['private_archive_checked'] is False
    # Temporary mode does not grant archive access even with a personal-looking ID.
    temporary_personal=foreign.model_copy(update={'device_id':'personal:one','conversation_id':'private'})
    assert 'PRIVATE_ARCHIVE' not in tools.execute('memory',temporary_personal).text


def test_durable_guest_memory_still_requires_private_authorization(tmp_path,monkeypatch):
    memory=Memory(str(tmp_path/'memory.sqlite'));tools=LocalTools(memory)
    def forbidden(*args,**kwargs):raise AssertionError('current-memory recall must not bypass durable ACL')
    monkeypatch.setattr(memory,'recall',forbidden,raising=False)
    req=ChatRequest(text='Найди личную историю за неделю',device_id='guest:fixture',remember=True)
    result=tools.execute('memory',req)
    assert 'PIN' in result.text and result.evidence['abstained'] is True
