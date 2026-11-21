"""Offline working-context tests; the injected cipher is a test fixture only."""
import base64
from pathlib import Path
import sys
import time

import pytest

from gobot.context_manager import ContextManager, tokens
from gobot.memory import Memory
from gobot.models import ChatRequest


def protect(value):
    return b'test-cipher:' + base64.b64encode(value[::-1])


def unprotect(value):
    assert value.startswith(b'test-cipher:')
    return base64.b64decode(value[len(b'test-cipher:'):])[::-1]


def memory(tmp_path, name='memory.sqlite', cipher=True):
    return Memory(str(tmp_path / name), **({'working_protect': protect, 'working_unprotect': unprotect} if cipher else {}))


def request(text='Следующий вопрос', *, owner='realtime-guest:fixture', conversation='scope-1', epoch='epoch-1', **kwargs):
    return ChatRequest(text=text, device_id=owner, conversation_id=conversation, profile_epoch=epoch,
                       remember=False, **kwargs)


def exchange(store, text, answer, *, status='completed', heard=None, **scope):
    req = request(text, **scope)
    store.start(req)
    store.finish(req, status, answer, 'openai:synthetic-fixture', [], heard=heard)
    return req


def configured(store, req=None, authorization='fixture-approved-authorization', persist=True):
    return store.configure_working_scope(req or request(), ttl_seconds=43200,
                                         persist=persist, authorization=authorization)


def test_default_guest_is_ram_only_and_expires_after_one_hour(tmp_path, monkeypatch):
    clock = [1700000000.]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    store = memory(tmp_path)
    exchange(store, 'Temporary secret subject', 'Temporary secret reply')
    assert len(store.context(request())['messages']) == 2
    with store.connect() as connection:
        assert connection.execute('SELECT count(*) FROM working_memory_checkpoints').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM archive_messages').fetchone()[0] == 0
    assert not memory(tmp_path).context(request())['messages']
    clock[0] += 3601
    assert not store.context(request())['messages']


def test_authorized_encrypted_checkpoint_survives_restart_and_two_hour_pause(tmp_path, monkeypatch):
    clock = [1700000000.]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'PRIVATE_SOURCE_CANARY бензин', 'PRIVATE_REPLY_CANARY про октановое число')
    with store.connect() as connection:
        sealed = bytes(connection.execute('SELECT sealed FROM working_memory_checkpoints').fetchone()[0])
        assert sealed.startswith(b'test-cipher:')
        assert b'PRIVATE_SOURCE_CANARY' not in sealed and b'PRIVATE_REPLY_CANARY' not in sealed
        assert connection.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM archive_messages').fetchone()[0] == 0
    clock[0] += 7200
    restarted = memory(tmp_path)
    assert not restarted.context(request())['messages']  # no authorization, no restore
    state = configured(restarted)
    assert state['restored_exchanges'] == 1 and state['persisted']
    assert 'PRIVATE_SOURCE_CANARY' in restarted.context(request())['messages'][0]['content']
    assert restarted.recall(request('Какие особенности бензина?'))['useful']


@pytest.mark.parametrize('changes', [dict(owner='realtime-guest:another'), dict(conversation='other-conversation'), dict(epoch='epoch-2')])
def test_checkpoint_isolated_by_owner_conversation_and_epoch(tmp_path, changes):
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'SCOPED_PRIVATE_SOURCE', 'SCOPED_PRIVATE_REPLY')
    restarted = memory(tmp_path)
    scoped = request(**changes)
    configured(restarted, scoped)
    assert not restarted.context(scoped)['messages']
    assert not restarted.recall(scoped.model_copy(update={'text': 'SCOPED_PRIVATE_SOURCE'}))['useful']
    assert not restarted.summary_snapshot(scoped)['sources']


def test_changed_authorization_cannot_restore_old_checkpoint(tmp_path):
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'OLD_AUTH_SOURCE', 'OLD_AUTH_REPLY')
    restarted = memory(tmp_path)
    configured(restarted, authorization='replacement-authorization')
    assert not restarted.context(request())['messages']
    # Revoked authorization cannot be reintroduced by an old queued job.
    restored_again = memory(tmp_path)
    configured(restored_again)
    assert not restored_again.context(request())['messages']


def test_unavailable_cipher_never_falls_back_to_plaintext(tmp_path):
    def unavailable(_):
        raise RuntimeError('fixture encryption unavailable')
    store = Memory(str(tmp_path / 'memory.sqlite'), working_protect=unavailable, working_unprotect=unavailable)
    configured(store)
    exchange(store, 'NO_PLAINTEXT_FALLBACK', 'private reply')
    state = store.working_status(request())
    assert not state['persisted'] and state['error'] == 'checkpoint_encryption_or_write_unavailable'
    assert len(store.context(request())['messages']) == 2
    with store.connect() as connection:
        assert connection.execute('SELECT count(*) FROM working_memory_checkpoints').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM messages').fetchone()[0] == 0


def test_checkpoint_expiry_removes_ram_and_sql_rows(tmp_path, monkeypatch):
    clock = [1700000000.]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'Expiring topic', 'Expiring answer')
    clock[0] += 43201
    store.purge_expired_working()
    assert not store.context(request())['messages']
    with store.connect() as connection:
        assert connection.execute('SELECT count(*) FROM working_memory_checkpoints').fetchone()[0] == 0


def test_interrupted_question_survives_without_claiming_unheard_answer(tmp_path):
    store = memory(tmp_path)
    exchange(store, 'Вопрос о теплице', 'UNHEARD_SECRET', status='cancelled')
    exchange(store, 'Уточнение про теплицу', 'UNCONFIRMED_PARTIAL', status='incomplete')
    messages = store.context(request())['messages']
    assert [item['role'] for item in messages] == ['user', 'user']
    assert all('UNHEARD' not in item['content'] and 'UNCONFIRMED' not in item['content'] for item in messages)
    recall = store.recall(request('Что учесть для теплицы?'))
    assert recall['useful'] and all(item['role'] == 'user' for item in recall['messages'])


def test_physically_heard_truncated_answer_is_explicitly_partial(tmp_path):
    store = memory(tmp_path)
    exchange(store, 'Вопрос о теплице', 'Услышанное начало ответа', status='incomplete', heard=True)
    answer = store.context(request())['messages'][-1]
    assert answer['role'] == 'assistant' and answer['heard']
    assert answer['status'] == 'incomplete' and not answer['content_complete']


def test_inflight_checkpoint_restores_question_as_cancelled_not_action(tmp_path):
    store = memory(tmp_path)
    configured(store)
    req = request('Незаконченный вопрос')
    store.start(req)
    restarted = memory(tmp_path)
    configured(restarted)
    messages = restarted.context(request())['messages']
    assert len(messages) == 1 and messages[0]['role'] == 'user'
    assert messages[0]['status'] == 'cancelled'


def test_ordinary_question_recalls_older_topic_beyond_six_exchanges(tmp_path):
    store = memory(tmp_path)
    exchange(store, 'Обсудим бензин и октановое число', 'Синтетическая заметка о бензине')
    for index in range(8):
        exchange(store, f'Космос: пункт {index}', f'Синтетическое объяснение космоса {index}')
    hot = store.context(request('Расскажи про космос'))
    assert len(hot['messages']) == 12
    assert all('бензин' not in message['content'] for message in hot['messages'])
    assert hot['summary'] and tokens(hot['summary']) <= 480
    assert not set(hot['summary_sources']) & {message['id'] for message in hot['messages']}
    result = store.recall(request('Какие особенности бензина?'))
    assert result['useful'] and any('бензин' in message['content'] for message in result['messages'])
    assert not store.recall(request('Как приготовить омлет?'))['useful']
    assert not store.recall(request('Какие особенности бензина?'), exclude_source_ids=result['source_ids'])['useful']


def test_exact_current_context_is_available_to_generic_recall(tmp_path):
    store = memory(tmp_path)
    exchange(store, 'Обсудим бензин', 'Синтетический ответ про бензин')
    result = store.recall(request('Что мы обсуждали?'))
    assert result['useful'] and len(result['messages']) == 2


def semantic_item(snapshot, text, *, quote=None, role='user'):
    source = next(item for item in snapshot['sources'] if item['role'] == role)
    return {'text': text, 'source_ids': [source['id']], 'source_quote': quote or source['content'],
            'provenance': 'user_statement'}


def test_grounded_semantic_summary_and_clear_fence(tmp_path):
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'Решил купить 3 саженца, без химикатов.', 'Синтетическое предложение')
    req = request()
    snapshot = store.summary_snapshot(req)
    summary = {'topic': 'Саженцы', 'decisions': [semantic_item(snapshot, 'Решил купить 3 саженца без химикатов.')],
               'goals': [], 'conditions': [], 'facts': [], 'open_questions': []}
    assert store.apply_summary(req, summary, source_version=snapshot['version'], source_ids=snapshot['source_ids'])
    updated = store.summary_snapshot(req)
    assert updated['previous_summary']['decisions'][0]['provenance'] == 'user_statement'
    assert store.working_status(req)['summary_kind'] == 'grounded_semantic_working_summary'
    store.clear_working_scope(req)
    assert not store.apply_summary(req, summary, source_version=updated['version'])
    configured(store)
    assert not store.context(req)['messages']
    restarted = memory(tmp_path)
    configured(restarted)
    assert not restarted.context(req)['messages']


def test_semantic_summary_restores_only_after_matching_authorization(tmp_path):
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'Решил купить 3 саженца, без химикатов.', 'Синтетическое предложение')
    req = request()
    snapshot = store.summary_snapshot(req)
    assert store.apply_summary(req, {'decisions': [semantic_item(snapshot, 'Решил купить 3 саженца без химикатов.')]},
                               source_version=snapshot['version'], source_ids=snapshot['source_ids'])
    restarted = memory(tmp_path)
    assert restarted.summary_snapshot(req)['previous_summary'] is None
    configured(restarted)
    summary = restarted.summary_snapshot(req)['previous_summary']
    assert summary['decisions'][0]['text'] == 'Решил купить 3 саженца без химикатов.'


def test_question_without_question_mark_cannot_become_user_fact(tmp_path):
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'Как содержать яхту', 'Синтетический ответ')
    req = request()
    snapshot = store.summary_snapshot(req)
    assert not store.apply_summary(req, {'facts': [semantic_item(snapshot, 'У пользователя яхта')]},
                                   source_version=snapshot['version'])


def test_new_summary_replaces_covered_open_question_instead_of_retaining_it_forever(tmp_path):
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'Мне нужны саженцы', 'Какой нужен срок?')
    req = request()
    first = store.summary_snapshot(req)
    assert store.apply_summary(req, {'open_questions': [semantic_item(first, 'Какой нужен срок?', role='assistant')]},
                               source_version=first['version'], source_ids=first['source_ids'])
    exchange(store, 'Нужны к пятнице', 'Срок учтён в разговоре')
    second = store.summary_snapshot(req)
    source = next(item for item in second['sources'] if item['content'] == 'Нужны к пятнице')
    item = {'text': 'Нужны к пятнице', 'source_quote': 'Нужны к пятнице',
            'source_ids': [source['id']], 'provenance': 'user_statement'}
    assert store.apply_summary(req, {'conditions': [item], 'open_questions': []},
                               source_version=second['version'], source_ids=second['source_ids'])
    updated = store.summary_snapshot(req)['previous_summary']
    assert updated['open_questions'] == [] and len(updated['conditions']) == 1


def test_continuation_preserves_heard_partial_status_and_invalidates_old_summary_version(tmp_path):
    store = memory(tmp_path)
    configured(store)
    original = exchange(store, 'Вопрос о теплице', 'Первый услышанный ответ')
    version = store.summary_snapshot(request())['version']
    store.complete_native_continuation(original, 'Первый услышанный ответ. Начало уточнения',
                                       'openai:synthetic-fixture', [], complete=False)
    updated = store.context(request())['messages'][-1]
    assert updated['heard'] and updated['status'] == 'incomplete' and not updated['content_complete']
    assert store.summary_snapshot(request())['version'] > version


def test_expiring_old_row_is_removed_from_still_live_encrypted_checkpoint(tmp_path, monkeypatch):
    import json
    import zlib
    clock = [1700000000.]
    monkeypatch.setattr(time, 'time', lambda: clock[0])
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'EXPIRED_SOURCE_CANARY', 'old answer')
    clock[0] += 3600
    exchange(store, 'CURRENT_SOURCE_CANARY', 'current answer')
    clock[0] += 43200 - 3600 + 1
    store.purge_expired_working()
    with store.connect() as connection:
        sealed = bytes(connection.execute('SELECT sealed FROM working_memory_checkpoints').fetchone()[0])
    raw = zlib.decompress(unprotect(sealed)[4:]).decode()
    assert 'EXPIRED_SOURCE_CANARY' not in raw and 'CURRENT_SOURCE_CANARY' in raw


@pytest.mark.parametrize('bad', ['unknown_source', 'invented_quote', 'changed_number', 'lost_negation', 'assistant_decision'])
def test_semantic_summary_cannot_forge_grounding_or_decisions(tmp_path, bad):
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'Решил купить 3 саженца, без химикатов.', 'Предлагаю купить 9 деревьев.')
    req = request()
    snapshot = store.summary_snapshot(req)
    item = semantic_item(snapshot, 'Решил купить 3 саженца без химикатов.')
    if bad == 'unknown_source': item['source_ids'] = ['foreign-source']
    if bad == 'invented_quote': item['source_quote'] = 'Вымышленное утверждение'
    if bad == 'changed_number': item['text'] = 'Решил купить 30 саженцев без химикатов.'
    if bad == 'lost_negation': item['text'] = 'Решил купить 3 саженца с химикатами.'
    if bad == 'assistant_decision': item = semantic_item(snapshot, 'Решил купить 9 деревьев.', role='assistant')
    assert not store.apply_summary(req, {'decisions': [item]}, source_version=snapshot['version'])


def test_capacity_evicts_old_completed_exchanges_instead_of_stalling(tmp_path):
    store = memory(tmp_path)
    for index in range(140):
        exchange(store, f'Синтетический вопрос {index}', f'Синтетический ответ {index}')
    assert len(store.transient) == 128
    assert store.context(request())['messages'][-1]['content'].endswith('139')


def test_long_latest_exchange_leaves_grounded_packet(tmp_path):
    store = memory(tmp_path)
    exchange(store, 'Задача о теплице', 'Короткое пояснение')
    exchange(store, 'Подробности по задаче', 'Длинное пояснение для теплицы. ' * 1800)
    req = request('А что мы решили?')
    packet = ContextManager().pack(req.text, store.context(req), 'FAST_CHAT')
    assert packet['messages'] or packet['summary']
    assert packet['_context_meta']['packet_tokens'] <= 6000


def test_disabled_scope_after_restart_purges_checkpoint_without_decrypting(tmp_path):
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'SYNTHETIC_BEFORE_DISABLED_RESTART', 'Synthetic answer')
    assert store.has_working_checkpoint(request())
    decrypted = []

    def forbidden_decryption(value):
        decrypted.append(True)
        raise AssertionError('A metadata check must not decrypt conversation content')

    reopened = Memory(str(tmp_path / 'memory.sqlite'), working_protect=protect,
                      working_unprotect=forbidden_decryption)
    assert not reopened.working_status(request())['enabled']
    assert reopened.has_working_checkpoint(request())
    assert not reopened.has_working_checkpoint(request(owner='other-owner'))
    assert not reopened.has_working_checkpoint(request(conversation='other-conversation'))
    assert not reopened.has_working_checkpoint(request(epoch='other-epoch'))
    assert not decrypted and not reopened.transient
    reopened.clear_working_scope(request(), disable=True)
    assert not reopened.has_working_checkpoint(request())
    final = memory(tmp_path)
    configured(final)
    assert not final.context(request())['messages']
    assert not final.has_working_checkpoint(request())


def test_checkpoint_presence_ignores_expired_record_without_loading_it(tmp_path):
    store = memory(tmp_path)
    configured(store)
    exchange(store, 'SYNTHETIC_EXPIRED_CHECKPOINT', 'Synthetic answer')
    assert store.has_working_checkpoint(request())
    with store.connect() as connection:
        connection.execute('UPDATE working_memory_checkpoints SET expires=?', (time.time() - 1,))
    assert not store.has_working_checkpoint(request())


@pytest.mark.skipif(sys.platform != 'win32', reason='Real Windows DPAPI native acceptance')
def test_native_windows_dpapi_checkpoint_restores_and_clear_is_final(tmp_path):
    store = memory(tmp_path, cipher=False)
    configured(store)
    exchange(store, 'SYNTHETIC_NATIVE_DPAPI_QUESTION', 'SYNTHETIC_NATIVE_DPAPI_ANSWER')
    assert store.working_status(request())['persisted']
    with store.connect() as connection:
        sealed = bytes(connection.execute('SELECT sealed FROM working_memory_checkpoints').fetchone()[0])
        assert connection.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM archive_messages').fetchone()[0] == 0
    assert b'SYNTHETIC_NATIVE_DPAPI' not in sealed
    assert not sealed.startswith(b'test-cipher:')
    reopened = memory(tmp_path, cipher=False)
    assert not reopened.context(request())['messages']  # No restore before authorization.
    configured(reopened)
    assert [item['content'] for item in reopened.context(request())['messages']] == [
        'SYNTHETIC_NATIVE_DPAPI_QUESTION', 'SYNTHETIC_NATIVE_DPAPI_ANSWER']
    assert reopened.working_status(request())['restored_exchanges'] == 1
    reopened.clear_working_scope(request())
    final = memory(tmp_path, cipher=False)
    configured(final)
    assert not final.context(request())['messages']
