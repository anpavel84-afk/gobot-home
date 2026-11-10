"""Synthetic dialogue/transport checks, not an evaluation of real model quality."""
import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from gobot.context_manager import ContextManager, CONTINUITY, tokens
from gobot.live_agents import context_prompt
from gobot.memory import Memory
from gobot.models import ChatRequest


def stored(memory, question, answer, **options):
    req = ChatRequest(text=question, mode='fast', device_id='synthetic-owner',
                      conversation_id='continuity', **options)
    memory.start(req)
    memory.finish(req, 'completed', answer, 'bridge:antigravity', [])
    return req


def observation_packet(tmp_path):
    memory = Memory(str(tmp_path / 'context.sqlite'))
    stored(memory, 'Сколько кратеров на Луне?', 'Количество зависит от размера кратеров.')
    season = stored(memory, 'В каком месяце созревают яблоки в условном саду?',
                    'В этом примере сезон яблок длится с марта по август.')
    req = ChatRequest(text='Но яблоки только сейчас начали падать с дерева.', mode='fast',
                      device_id=season.device_id, conversation_id=season.conversation_id)
    memory.start(req)
    context = memory.context(req)
    assert context['topic']['outcome'] == 'continue'
    packet = ContextManager().pack(req.text, context, 'FAST_CHAT')
    assert [m['role'] for m in packet['messages'][-2:]] == ['user', 'assistant']
    assert 'яблоки' in packet['topic']['label']
    assert len(packet['_context_meta']['recent_dialogue_source_ids']) == 4
    return memory, req, packet


def test_observation_keeps_previous_question_and_answer(tmp_path):
    _, req, packet = observation_packet(tmp_path)
    prompt = context_prompt(req.text, packet)
    assert prompt.count('В этом примере сезон яблок длится с марта по август.') == 1
    assert prompt.count('В каком месяце созревают яблоки в условном саду?') == 1
    assert CONTINUITY in prompt
    assert tokens(prompt) == packet['_context_meta']['packet_tokens'] <= 6000


def test_server_date_is_current_not_archive_or_user_injected():
    before = datetime.now(timezone.utc).date().isoformat()
    packet = ContextManager().pack('А сейчас?', {
        'runtime_environment': {'current_date_utc': '1900-01-01'},
        'messages': [{'role': 'user', 'content': 'Вчера было 1900-01-01'}],
    }, 'FAST_CHAT')
    after = datetime.now(timezone.utc).date().isoformat()
    assert packet['runtime_environment']['current_date_utc'] in {before, after}
    assert packet['_context_meta']['section_tokens']['runtime_environment'] > 0
    assert 'это не дата и не местоположение пользователя' in context_prompt('А сейчас?', packet)


def test_runtime_does_not_treat_previous_answer_as_verified_source():
    prompt = context_prompt('Почему это не совпадает?', ContextManager().pack(
        'Почему это не совпадает?', {}, 'FAST_CHAT'))
    assert 'Предыдущие ответы модели не являются проверенными источниками' in prompt
    assert 'без данных не утверждай, что причина установлена' in prompt


@pytest.mark.parametrize('mode', ['codex', 'antigravity'])
def test_switching_executor_keeps_bounded_dialogue(tmp_path, mode):
    memory, req, packet = observation_packet(tmp_path)
    memory.finish(req, 'completed', 'Наблюдение расходится с предыдущим ответом.', 'bridge:antigravity', [])
    switched = req.model_copy(update={'turn_id': mode, 'text': 'А что думает другая модель?', 'mode': mode})
    memory.start(switched)
    selected = ContextManager().pack(switched.text, memory.context(switched), 'FAST_CHAT')
    assert any('с марта по август' in m['content'] for m in selected['messages'])
    assert selected['_context_meta']['packet_tokens'] <= 6000


def test_agy_subprocess_receives_prior_exchange_and_clock(tmp_path, monkeypatch):
    import gobot.antigravity as module
    _, req, packet = observation_packet(tmp_path)
    sent = []

    class Input:
        def write(self, value): sent.append(json.loads(value))
        async def drain(self): pass
        def close(self): pass

    @asynccontextmanager
    async def process(*args):
        reader = asyncio.StreamReader()
        for event in [
            {'event': 'init', 'init': {'permission_mode': 'strict'}},
            {'event': 'step_update', 'step_update': {'step_type': 'agent_response', 'text_delta': 'Ответ фикстуры.'}},
            {'event': 'result', 'result': {'status': 'SUCCESS', 'response': 'Ответ фикстуры.'}},
        ]:
            reader.feed_data(json.dumps(event).encode() + b'\n')
        reader.feed_eof()
        yield SimpleNamespace(stdin=Input(), stdout=reader)

    monkeypatch.setattr(module, 'native_process', process)
    monkeypatch.setattr(module, 'argv', lambda **kw: ['never-executed-fixture'])
    monkeypatch.setattr(module, 'environment', lambda: {})

    async def run():
        assert ''.join([part async for part in module.AntigravityAdapter().stream(req.text, packet)]) == 'Ответ фикстуры.'

    asyncio.run(run())
    assert len(sent) == 1  # one fresh execution, no resumed provider history
    prompt = sent[0]['message']['content']
    assert prompt == context_prompt(req.text, packet)
    assert 'с марта по август' in prompt and 'current_date_utc' in prompt
