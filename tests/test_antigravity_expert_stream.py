"""Documented native response events only; all providers are synthetic."""
import asyncio

import pytest

from gobot.antigravity import AntigravityEvents
from gobot.expert_stream import AnswerDelta
from gobot.processes import AgentError


def initialized(job='job-1'):
    parser = AntigravityEvents(strict_answers=True, job_id=job)
    parser.parse({'event': 'init', 'init': {'permission_mode': 'request-review'}})
    return parser


def step(text, **changes):
    return {'event': 'step_update', 'step_update': {
        'step_type': 'agent_response', 'step_index': 3, 'state': 'ACTIVE',
        'text_delta': text, **changes}}


def result(text, **changes):
    return {'event': 'result', 'result': {'status': 'SUCCESS', 'response': text, **changes}}


def test_documented_partial_answer_is_typed_and_terminal_replay_is_not_spoken_twice():
    parser = initialized()
    first = parser.parse(step('Первый вывод. '))
    assert not parser.completed
    assert isinstance(first[0], AnswerDelta) and first[0].speakable
    assert first[0].metadata() == {
        'item_id': 'antigravity:job-1:3', 'phase': 'partial_answer',
        'job_id': 'job-1', 'verified': True, 'completed': False}
    done = step('Пояснение.', state='DONE')
    second = parser.parse(done)
    assert second[0].completed and second[0].item_id == first[0].item_id
    assert parser.parse(done) == []
    final = result('Первый вывод. Пояснение. Итог.')
    tail = parser.parse(final)
    assert ''.join(first+second+tail) == final['result']['response']
    assert tail[0].phase == 'final_answer' and tail[0].completed
    assert tail[0].item_id == 'antigravity:job-1:result'
    assert parser.parse(final) == []
    assert parser.parse(step('LATE PRIVATE DATA')) == []


@pytest.mark.parametrize('changes', [
    {'step_type': value} for value in ('thinking', 'planning', 'tool', 'tool_call', 'commentary', 'checkpoint')
] + [
    {'phase': 'commentary'}, {'phase': 'analysis'}, {'state': 'UNKNOWN'},
    {'step_index': None}, {'step_index': True}, {'step_index': -1}, {'step_index': 1_000_001},
])
def test_unverified_step_never_becomes_expert_speech(changes):
    parser = initialized()
    assert parser.parse(step('PRIVATE DATA', **changes)) == []
    assert parser.text == ''
    final = parser.parse(result('Проверенный финальный ответ.'))
    assert final[0].speakable and final[0].phase == 'final_answer'
    assert str(final[0]) == 'Проверенный финальный ответ.'


def test_missing_init_missing_job_and_mismatching_final_fail_closed():
    with pytest.raises(AgentError, match='expert_answer_job_required'):
        AntigravityEvents(strict_answers=True)
    parser = AntigravityEvents(strict_answers=True, job_id='job')
    assert parser.parse('raw stdout') == []
    assert parser.parse(step('Unverified early text')) == []
    with pytest.raises(AgentError, match='antigravity_invalid_result'):
        parser.parse(result('Unverified final'))
    parser = initialized()
    parser.parse(step('Начало ответа. '))
    with pytest.raises(AgentError, match='antigravity_final_mismatch'):
        parser.parse(result('Заменённый ответ.'))
    assert not parser.completed
    with pytest.raises(AgentError):
        initialized().parse(result('PRIVATE ERROR PAYLOAD', status='ERROR', error='failed'))


def test_legacy_text_stream_remains_plain_strings_without_strict_metadata():
    parser = AntigravityEvents()
    value = parser.parse({'event': 'step_update', 'step_update': {
        'step_type': 'agent_response', 'text_delta': 'Прежний текст'}})
    assert value == ['Прежний текст'] and type(value[0]) is str
    assert parser.parse(result('Прежний текст')) == []


def test_live_stream_passes_job_and_exact_google_model_through_signed_bridge(settings, monkeypatch):
    import httpx
    import gobot.antigravity as native
    import gobot.bridge as bridge
    import gobot.live_agents as live
    import gobot.providers as providers
    from gobot.models import ChatRequest
    observed = []

    async def stream(self, text, context, model_id=None, *, strict_answers=False, job_id=None):
        observed.append((model_id, strict_answers, job_id))
        parser = AntigravityEvents(strict_answers=strict_answers, job_id=job_id)
        parser.parse({'event': 'init', 'init': {'permission_mode': 'request-review'}})
        for value in parser.parse(step('Проверенный ответ.')):
            yield value
        parser.parse(result('Проверенный ответ.'))

    monkeypatch.setattr(native.AntigravityAdapter, 'stream', stream)
    monkeypatch.setattr(live, 'agent_status', lambda consent: {'antigravity': {'available': True}})
    app = bridge.create_app(settings)
    original = httpx.AsyncClient
    def client(**kwargs):
        return original(transport=httpx.ASGITransport(app=app, client=('127.0.0.1', 1234)), **kwargs)
    monkeypatch.setattr(providers.httpx, 'AsyncClient', client)

    async def run():
        req = ChatRequest(text='Сравни варианты', provider='antigravity', turn_id='job-1',
                          model_id='gemini-4-argon-medium', usage_consent=True)
        values = [item async for item in providers.bridge_stream(settings, req, {}, expert_profile='ARGON_DEEP')]
        assert observed == [('gemini-4-argon-medium', True, 'job-1')]
        assert len(values) == 1 and values[0].speakable
        assert values[0].job_id == 'job-1' and values[0].item_id == 'antigravity:job-1:3'
        with pytest.raises(AgentError, match='expert_answer_transport_not_verified'):
            await anext(live.live_stream('antigravity', 'question', {}, usage_consent=True,
                model_id='gemini-4-argon-medium', expert_profile='ARGON_DEEP', job_id='job-2',
                antigravity_transport='acp_experimental'))
        assert len(observed) == 1
    asyncio.run(run())
