"""No provider calls: scoped semantic notes, exact budget, stale/unknown safety."""
import asyncio
import copy
import json
import sqlite3
import threading
import time
from contextlib import contextmanager

import httpx
import pytest

from gobot.models import ChatRequest
from gobot.working_memory_summary import (
    FIELDS, MODEL, MAX_INPUT_TOKENS, MAX_OUTPUT_TOKENS,
    WorkingMemorySummaryCoordinator, make_payload, numeric_usage, validate_summary,
)

NOW = 1_800_000_000.
QUOTE = 'Я не хочу тратить более 95 рублей.'


def request(scope='one'):
    return ChatRequest(text='Синтетическая реплика', remember=False, device_id=scope,
                       conversation_id='conversation-' + scope, turn_id='question-' + scope)


def snapshot(scope='one', count=4):
    sources = []
    for index in range(count):
        ident = scope + '-' + str(index)
        sources.extend([
            {'id': ident + ':u', 'turn_id': ident, 'role': 'user', 'content': QUOTE,
             'status': 'completed', 'heard': False},
            {'id': ident + ':a', 'turn_id': ident, 'role': 'assistant', 'content': 'Условие учтено.',
             'status': 'completed', 'heard': True},
        ])
    return {'enabled': True, 'summary_enabled': True, 'scope_id': 'configured-' + scope,
            'version': 5, 'generation': 5, 'expires': NOW + 43200,
            'sources': sources, 'source_ids': [s['id'] for s in sources],
            'completed_turns': count, 'summary_source_ids': [], 'previous_summary': None}


class FakeMemory:
    def __init__(self, path):
        self.path = path
        self.snapshots = {'one': snapshot()}
        self.applied = []

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def summary_snapshot(self, req, max_messages=16):
        return copy.deepcopy(self.snapshots.get(req.device_id, {'enabled': False}))

    def apply_summary(self, req, summary, *, source_version, source_ids,
                      complete_source_ids=None):
        current = self.snapshots[req.device_id]
        if not current['enabled'] or source_version != current['version'] or current['expires'] <= NOW:
            return False
        assert set(source_ids) <= set(current['source_ids'])
        assert complete_source_ids is not None and set(complete_source_ids) <= set(source_ids)
        self.applied.append((req.device_id, summary, source_ids))
        return True


def notes(source='one-3:u'):
    result = {'topic': 'Ограничение бюджета', **{key: [] for key in FIELDS}}
    result['conditions'] = [{'text': QUOTE, 'source_ids': [source], 'source_quote': QUOTE,
                             'provenance': 'user_statement'}]
    return result


def completed(summary=None, *, usage=None, model=MODEL, status='completed'):
    return {'model': model, 'status': status,
            'usage': usage or {'input_tokens': 600, 'output_tokens': 100, 'total_tokens': 700},
            'output': [{'type': 'message', 'role': 'assistant',
                        'content': [{'type': 'output_text', 'text': json.dumps(summary or notes())}]}]}


def coordinator(tmp_path, handler, *, memory=None, **kwargs):
    memory = memory or FakeMemory(tmp_path / 'brain.sqlite')
    worker = WorkingMemorySummaryCoordinator(memory, clock=lambda: NOW,
        key_loader=lambda: 'synthetic-key', transport=httpx.MockTransport(handler), **kwargs)
    return memory, worker


def fund(worker, req=None, response='r1', tokens=20000):
    req = req or request()
    return worker.record_primary_usage(req, response,
        {'input_tokens': tokens - 100, 'output_tokens': 100, 'total_tokens': tokens})


def test_unknown_primary_usage_disabled_and_insufficient_delta_make_no_requests(tmp_path):
    async def run():
        calls = []
        async def handler(req):
            calls.append(req)
            raise AssertionError('No endpoint is allowed without budget and scoped delta')
        memory, worker = coordinator(tmp_path, handler)
        assert (await worker.submit(request()))['reason'] == 'measured_usage_budget_unavailable'
        assert not worker.record_primary_usage(request(), 'r1', {'total_tokens': 20000})
        assert not worker.record_primary_usage(request(), 'r1', {'input_tokens': True, 'output_tokens': 1})
        assert fund(worker)
        assert not fund(worker)  # repeated response.done does not mint allowance
        memory.snapshots['one']['summary_enabled'] = False
        assert not (await worker.submit(request()))['accepted']
        memory.snapshots['one'] = snapshot(count=3)
        assert (await worker.submit(request()))['reason'] == 'insufficient_new_completed_turns'
        assert not calls
        await worker.close()
    asyncio.run(run())


def test_valid_summary_uses_exact_count_and_debits_real_usage_without_speech(tmp_path):
    async def run():
        calls = []
        async def handler(req):
            body = json.loads(req.content)
            calls.append((req.url.path, body))
            assert req.url.host == 'api.openai.com'
            assert body['model'] == MODEL and body['tools'] == [] and body['tool_choice'] == 'none'
            assert body['reasoning'] == {'effort': 'none'}
            assert body['text']['format']['strict'] is True
            assert 'previous_response_id' not in body
            if req.url.path.endswith('input_tokens'):
                return httpx.Response(200, json={'input_tokens': 600})
            assert body['store'] is False and body['stream'] is False
            assert body['max_output_tokens'] == MAX_OUTPUT_TOKENS
            return httpx.Response(200, json=completed())
        memory, worker = coordinator(tmp_path, handler)
        assert fund(worker)
        live_request = request()
        live_request._owner_test_budget = threading.RLock()
        live_request._owner_test_origin = 'owner'
        assert (await worker.submit(live_request))['accepted']
        await worker.wait_idle()
        assert len(calls) == 2 and len(memory.applied) == 1
        state = worker.status(request())
        assert state['last_state'] == 'applied' and not state['active']
        assert state['global_tokens_used_or_reserved'] == 700
        assert state['available_tokens'] == 1300
        assert state['spoken_responses_created'] == 0
        assert not (await worker.submit(request()))['accepted']
        assert QUOTE.encode() not in memory.path.read_bytes()
        assert b'synthetic-key' not in memory.path.read_bytes()
        await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize('count,primary', [(MAX_INPUT_TOKENS + 1, 20000), (600, 8000)])
def test_exact_input_or_fraction_limit_prevents_generation(tmp_path, count, primary):
    async def run():
        calls = []
        async def handler(req):
            calls.append(req.url.path)
            assert req.url.path.endswith('input_tokens')
            return httpx.Response(200, json={'input_tokens': count})
        memory, worker = coordinator(tmp_path, handler)
        fund(worker, tokens=primary)
        assert (await worker.submit(request()))['accepted']
        await worker.wait_idle()
        assert len(calls) == 1 and not memory.applied
        assert worker.status(request())['global_tokens_used_or_reserved'] == 0
        await worker.close()
    asyncio.run(run())


def test_unknown_usage_is_reserved_across_restart_and_never_retried(tmp_path):
    async def run():
        calls = []
        async def handler(req):
            calls.append(req.url.path)
            if req.url.path.endswith('input_tokens'):
                return httpx.Response(200, json={'input_tokens': 600})
            raise httpx.ReadTimeout('synthetic', request=req)
        memory, worker = coordinator(tmp_path, handler)
        fund(worker)
        await worker.submit(request())
        await worker.wait_idle()
        state = worker.status(request())
        assert state['unknown_usage_attempts'] == 1
        assert state['global_tokens_used_or_reserved'] == 600 + MAX_OUTPUT_TOKENS
        await worker.close()
        _, restarted = coordinator(tmp_path, handler, memory=memory)
        assert not (await restarted.submit(request()))['accepted']
        assert len(calls) == 2
        assert restarted.status(request())['unknown_usage_attempts'] == 1
        await restarted.close()
    asyncio.run(run())


def test_absolute_daily_budget_is_shared_between_owner_scopes(tmp_path):
    async def run():
        calls = []
        async def handler(req):
            calls.append(req.url.path)
            if req.url.path.endswith('input_tokens'):
                return httpx.Response(200, json={'input_tokens': 600})
            raise httpx.ReadTimeout('synthetic', request=req)
        memory, worker = coordinator(tmp_path, handler)
        for scope in ('one', 'two', 'three'):
            memory.snapshots[scope] = snapshot(scope)
            fund(worker, request(scope), response='r-' + scope, tokens=100000)
            accepted = (await worker.submit(request(scope)))['accepted']
            if scope == 'three':
                assert not accepted
            else:
                assert accepted
                await worker.wait_idle()
        assert len(calls) == 4
        assert worker.status(request())['global_tokens_used_or_reserved'] == 1968
        await worker.close()
    asyncio.run(run())


@pytest.mark.parametrize('boundary', ['count', 'reservation'])
def test_utc_rollover_cannot_spend_previous_days_primary_allowance(tmp_path, boundary):
    async def run():
        now = [NOW - NOW % 86400 + 86399]
        calls = []
        memory = FakeMemory(tmp_path / 'brain.sqlite')
        memory.snapshots['one']['expires'] = now[0] + 43200

        async def handler(req):
            calls.append(req.url.path)
            assert req.url.path.endswith('input_tokens'), 'A new day requires its own measured allowance'
            if boundary == 'count':
                now[0] += 2
            return httpx.Response(200, json={'input_tokens': 600})

        worker = WorkingMemorySummaryCoordinator(memory, clock=lambda: now[0],
            key_loader=lambda: 'synthetic-key', transport=httpx.MockTransport(handler))
        if boundary == 'reservation':
            reserve = worker._reserve

            def crossing_reserve(operation, input_count):
                accepted = reserve(operation, input_count)
                assert accepted
                now[0] += 2
                return accepted

            worker._reserve = crossing_reserve
        try:
            assert fund(worker)
            assert (await worker.submit(request()))['accepted']
            await worker.wait_idle()
            assert len(calls) == 1 and not memory.applied
            status = worker.status(request())
            assert status['known_primary_tokens'] == 0
            assert status['global_tokens_used_or_reserved'] == 0
            with memory.connect() as connection:
                assert connection.execute(
                    'SELECT sum(reserved_tokens) FROM working_summary_attempts').fetchone()[0] == 0
        finally:
            await worker.close()

    asyncio.run(run())


@pytest.mark.parametrize('change', ['version', 'expiry', 'enabled'])
def test_stale_after_count_never_starts_generation(tmp_path, change):
    async def run():
        calls = []
        memory = FakeMemory(tmp_path / 'brain.sqlite')
        async def handler(req):
            calls.append(req.url.path)
            assert req.url.path.endswith('input_tokens')
            memory.snapshots['one'][change] = {'version': 6, 'expiry': NOW - 1, 'enabled': False}[change]
            if change == 'expiry':
                memory.snapshots['one']['expires'] = NOW - 1
            return httpx.Response(200, json={'input_tokens': 600})
        _, worker = coordinator(tmp_path, handler, memory=memory)
        fund(worker)
        await worker.submit(request())
        await worker.wait_idle()
        assert len(calls) == 1 and not memory.applied
        assert worker.status()['global_tokens_used_or_reserved'] == 0
        await worker.close()
    asyncio.run(run())


def test_revocation_and_late_result_do_not_apply_but_usage_still_settles(tmp_path):
    async def run():
        enabled = [True]
        async def handler(req):
            if req.url.path.endswith('input_tokens'):
                return httpx.Response(200, json={'input_tokens': 600})
            enabled[0] = False
            return httpx.Response(200, json=completed())
        memory, worker = coordinator(tmp_path, handler, enabled_for=lambda req: enabled[0])
        fund(worker)
        await worker.submit(request())
        await worker.wait_idle()
        assert not memory.applied
        assert worker.status()['global_tokens_used_or_reserved'] == 700
        await worker.close()
    asyncio.run(run())


def test_invalidated_active_result_is_discarded_without_erasing_usage(tmp_path):
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        async def handler(req):
            if req.url.path.endswith('input_tokens'):
                return httpx.Response(200, json={'input_tokens': 600})
            started.set()
            await finish.wait()
            return httpx.Response(200, json=completed())
        memory, worker = coordinator(tmp_path, handler)
        fund(worker)
        await worker.submit(request())
        await started.wait()
        worker.invalidate(request())
        finish.set()
        await worker.wait_idle()
        assert not memory.applied and worker.status(request())['global_tokens_used_or_reserved'] == 700
        await worker.close()
    asyncio.run(run())


def test_two_coordinators_share_sql_lease_and_attempt_idempotency(tmp_path):
    async def run():
        started, finish = asyncio.Event(), asyncio.Event()
        calls = []
        async def handler(req):
            calls.append(req.url.path)
            if req.url.path.endswith('input_tokens'):
                started.set()
                await finish.wait()
                return httpx.Response(200, json={'input_tokens': 600})
            return httpx.Response(200, json=completed())
        memory, first = coordinator(tmp_path, handler)
        _, second = coordinator(tmp_path, handler, memory=memory)
        fund(first)
        await first.submit(request())
        await started.wait()
        await second.submit(request())
        await second.wait_idle()
        assert len(calls) == 1
        finish.set()
        await first.wait_idle()
        assert len(calls) == 2 and len(memory.applied) == 1
        await first.close()
        await second.close()
    asyncio.run(run())


def test_cancelled_request_retains_unknown_reservation(tmp_path):
    async def run():
        started = asyncio.Event()
        async def handler(req):
            if req.url.path.endswith('input_tokens'):
                return httpx.Response(200, json={'input_tokens': 600})
            started.set()
            await asyncio.Event().wait()
        _, worker = coordinator(tmp_path, handler)
        fund(worker)
        await worker.submit(request())
        await started.wait()
        await worker.close()
        status = worker.status(request())
        assert status['unknown_usage_attempts'] == 1
        assert status['global_tokens_used_or_reserved'] == 600 + MAX_OUTPUT_TOKENS
    asyncio.run(run())


def test_payload_excludes_unheard_assistant_and_ungrounded_summary_text():
    current = snapshot()
    current['sources'][-1]['heard'] = False
    current['sources'][-1]['content'] = 'UNHEARD_SECRET'
    current['previous_summary'] = {'goals': ['UNVERIFIED_OLD_PROSE']}
    payload, sources = make_payload(current)
    assert 'UNHEARD_SECRET' not in payload['input']
    assert 'UNVERIFIED_OLD_PROSE' not in payload['input']
    assert 'one-3:a' not in sources


@pytest.mark.parametrize('change', ['source', 'quote', 'number', 'negation'])
def test_semantic_note_requires_source_quote_numbers_and_negation(change):
    current = snapshot()
    sources = {s['id']: s for s in current['sources']}
    summary = notes()
    item = summary['conditions'][0]
    if change == 'source':
        item['source_ids'] = ['other-person-secret']
    elif change == 'quote':
        item['source_quote'] = 'Я решил всё купить.'
    elif change == 'number':
        item['text'] = 'Я не хочу тратить более 98 рублей.'
    else:
        item['text'] = 'Я хочу тратить более 95 рублей.'
    with pytest.raises(ValueError):
        validate_summary(summary, sources)


def test_assistant_proposal_is_not_user_decision_and_question_not_fact():
    current = snapshot()
    current['sources'][-1]['content'] = QUOTE
    sources = {s['id']: s for s in current['sources']}
    summary = notes('one-3:a')
    summary['decisions'] = summary.pop('conditions')
    summary['conditions'] = []
    with pytest.raises(ValueError, match='user_intent_not_user_source'):
        validate_summary(summary, sources)
    summary = notes()
    summary['conditions'][0]['provenance'] = 'assistant_statement'
    assert validate_summary(summary, sources)['conditions'][0]['provenance'] == 'user_statement'
    assert numeric_usage({'input_tokens': 1, 'output_tokens': 2, 'total_tokens': 99}) is None


def test_a_statement_is_not_a_confirmed_decision_and_uncertainty_is_retained():
    sources = {source['id']: source for source in snapshot()['sources']}
    summary = notes()
    summary['decisions'] = summary['conditions']
    summary['conditions'] = []
    with pytest.raises(ValueError, match='decision_not_user_statement'):
        validate_summary(summary, sources)
    summary = notes()
    quote = 'Наверное, хватит 95 рублей.'
    sources['one-3:u']['content'] = quote
    summary['conditions'][0].update(source_quote=quote, text='Хватит 95 рублей.')
    with pytest.raises(ValueError, match='uncertainty_dropped'):
        validate_summary(summary, sources)
    summary['conditions'][0]['text'] = 'Возможно, хватит 95 рублей.'
    assert validate_summary(summary, sources)['conditions'][0]['text'].startswith('Возможно')


def test_actual_working_memory_accepts_grounded_notes_without_archive_rows(tmp_path):
    from gobot.memory import Memory
    async def run():
        memory = Memory(tmp_path / 'actual-brain.sqlite')
        last = request()
        memory.configure_working_scope(last, ttl_seconds=43200, persist=False, authorization='synthetic-owner')
        for index in range(4):
            last = last.model_copy(update={'turn_id': 'real-turn-' + str(index), 'text': QUOTE})
            memory.start(last)
            memory.finish(last, 'completed', 'Условие учтено.', 'realtime:synthetic', [])
        async def handler(req):
            body = json.loads(req.content)
            if req.url.path.endswith('input_tokens'):
                return httpx.Response(200, json={'input_tokens': 600})
            users = [source for source in json.loads(body['input'])['messages'] if source['role'] == 'user']
            return httpx.Response(200, json=completed(notes(users[-1]['id'])))
        worker = WorkingMemorySummaryCoordinator(memory, key_loader=lambda: 'synthetic-key',
            transport=httpx.MockTransport(handler), enabled_for=lambda req: True, clock=time.time)
        fund(worker, last)
        assert (await worker.submit(last))['accepted']
        await worker.wait_idle()
        assert worker.status(last)['last_state'] == 'applied'
        applied = memory.summary_snapshot(last)['previous_summary']
        assert applied['kind'] == 'grounded_semantic_working_summary'
        assert applied['conditions'][0]['source_quote'] == QUOTE
        with memory.connect() as connection:
            assert connection.execute('SELECT count(*) FROM messages').fetchone()[0] == 0
            assert connection.execute('SELECT count(*) FROM archive_messages').fetchone()[0] == 0
        await worker.close()
    asyncio.run(run())


def test_worker_excerpt_cannot_erase_an_older_condition_outside_transmitted_text(tmp_path):
    from gobot.memory import Memory

    async def run():
        memory = Memory(tmp_path / 'excerpt-brain.sqlite')
        last = request()
        memory.configure_working_scope(last, ttl_seconds=43200, persist=False,
                                       authorization='synthetic-owner')
        prefix = 'Сейчас обсуждаем бензин.'
        long_source = prefix + ' Дополнительное описание.' * 35 + ' ' + QUOTE
        for index in range(4):
            last = last.model_copy(update={'turn_id': 'excerpt-turn-' + str(index),
                'text': long_source if index == 3 else 'Синтетическое короткое сообщение.'})
            memory.start(last)
            memory.finish(last, 'completed', 'Синтетический ответ.', 'realtime:synthetic', [])
        initial = memory.summary_snapshot(last)
        original = next(source for source in initial['sources'] if source['content'] == long_source)
        old_note = notes(original['id'])
        assert memory.apply_summary(last, old_note, source_version=initial['version'],
                                    source_ids=[original['id']])
        current = memory.summary_snapshot(last)
        assert not memory.apply_summary(last, old_note, source_version=current['version'],
            source_ids=[original['id']], complete_source_ids=['foreign-source'])

        async def handler(req):
            body = json.loads(req.content)
            sent = json.loads(body['input'])['messages']
            partial = next(source for source in sent if source['id'] == original['id'])
            assert partial['excerpt'] and len(partial['content']) <= 320
            assert QUOTE not in partial['content']
            if req.url.path.endswith('input_tokens'):
                return httpx.Response(200, json={'input_tokens': 600})
            delta = {'topic': 'Текущая тема', **{field: [] for field in FIELDS}}
            delta['conditions'] = [{'text': prefix, 'source_quote': prefix,
                                   'source_ids': [original['id']], 'provenance': 'user_statement'}]
            return httpx.Response(200, json=completed(delta))

        worker = WorkingMemorySummaryCoordinator(memory, key_loader=lambda: 'synthetic-key',
            transport=httpx.MockTransport(handler), enabled_for=lambda req: True, clock=time.time)
        try:
            assert fund(worker, last)
            assert (await worker.submit(last))['accepted']
            await worker.wait_idle()
            assert worker.status(last)['last_state'] == 'applied'
            retained = memory.summary_snapshot(last)['previous_summary']['conditions']
            assert {note['text'] for note in retained} == {QUOTE, prefix}
            assert any(note['source_quote'] == QUOTE for note in retained)
        finally:
            await worker.close()

    asyncio.run(run())
