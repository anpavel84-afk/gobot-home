"""Real routing/tool handlers with mock transports; no model or acoustic test."""
import asyncio
import json

import pytest

from gobot.quality import RiskAssessment
from gobot.realtime import INSTRUCTIONS, TOOLS
from test_realtime_native import configured, start
from test_realtime_ws import cleanup
from test_unified_google_expert import setup


ORDINARY = [
    'Какой самый быстрый летательный аппарат?',
    'София, какой самый быстрый летательный аппарат?',
    'Какой самый быстрый самолёт?',
    'Почему небо синее?',
    'Что такое фотосинтез?',
    'Расскажи о фильме Титаник',
    'Как работает самолёт?',
    'Назови столицу Франции',
    'А почему?',
    'Как проверить факт в интернете?',
    'Проверь факторизацию числа 91',
    'Сегодня расскажи самый смешной анекдот',
    'Сейчас объясни самый простой способ сложения дробей',
    'Какой самый быстрый способ сложения дробей сейчас?',
]


def outputs(session, call_id):
    return [json.loads(event['item']['output']) for event in session.ws.sent
            if event.get('item', {}).get('call_id') == call_id]


@pytest.mark.parametrize('query', ORDINARY)
def test_unnecessary_tool_call_returns_to_conversation_without_expert(tmp_path, settings, query):
    async def run():
        original, board, manager, session = await setup(tmp_path, settings)
        replies, operations = [], []
        async def respond():
            replies.append(True)
        def no_operation(*args, **kwargs):
            operations.append(args[0])
            raise AssertionError('ordinary question must not execute a server tool')
        session.response = respond
        session.manager.brain.tools.execute = no_operation
        try:
            turn = await session.new_turn(query=query)
            await session.tool('knowledge', 'gobot_tool', json.dumps({'query': query}), turn)
            result, = outputs(session, 'knowledge')
            assert result['status'] == 'no_matching_server_operation'
            assert result['ordinary_conversation_available'] and result['executed'] is False
            assert result['evidence'] == {'method': 'no_matching_server_operation',
                'verified': False, 'server_action_executed': False, 'external_sources_checked': False}
            assert result['text'] == result['spoken_text'] == ''
            assert 'source_check' not in result and 'expert_proposal' not in result
            assert 'mode_proposal' not in result and not session.experts.jobs
            assert replies == [True] and operations == []
            assert board.budget.status()['sessions_reserved'] == 0
            assert session.experts.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('actual,argument,verification', [
    (ORDINARY[0], 'Проверь в интернете актуальный рекорд скорости самолёта', False),
    ('Проверь в интернете, какой самый быстрый самолёт', ORDINARY[0], True),
    ('Какой самый быстрый самолёт сейчас?', ORDINARY[0], True),
])
def test_actual_question_owns_source_requirement(tmp_path, settings, actual, argument, verification):
    async def run():
        original, board, manager, session = await setup(tmp_path, settings)
        operations = []
        execute = session.manager.brain.tools.execute
        def recorded(tool, req, slots):
            operations.append((tool, req.text))
            return execute(tool, req, slots)
        async def respond():
            pass
        session.response = respond
        session.manager.brain.tools.execute = recorded
        try:
            turn = await session.new_turn(query=actual)
            await session.tool('rewrite', 'gobot_tool', json.dumps({'query': argument}), turn)
            result, = outputs(session, 'rewrite')
            if verification:
                assert operations == [('verification', actual)]
                assert result['evidence']['abstained']
                assert result['source_check']['verified'] is False
                assert result.get('status') != 'no_matching_server_operation'
            else:
                assert not operations and not session.experts.jobs
                assert result['status'] == 'no_matching_server_operation'
            assert board.budget.status()['sessions_reserved'] == 0
            assert session.experts.budget.status()['sessions_reserved'] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('query', [
    'Проверь этот факт: X-15 быстрее всех самолётов',
    'София, можешь проверить в интернете рекорд скорости самолёта?',
    'Поищи в сети самый быстрый самолёт',
    'Какой самый быстрый летательный аппарат сейчас?',
    'Какой самолёт самый быстрый сегодня?',
    'Какой рекорд скорости на данный момент?',
    'Какой последний фильм с Ди Каприо?',
    'Какая новейшая версия программы?',
    'Какую дозировку лекарства дать ребёнку?',
])
def test_freshness_explicit_verification_and_high_consequence_stay_guarded(query):
    assessment = RiskAssessment().assess(query, {})
    assert assessment.verification_required and assessment.external_verification
    assert assessment.method == 'external_sources'


@pytest.mark.parametrize('query,tool', [
    ('Сколько будет 127 × 43?', 'calculator'),
    ('Что мы обсуждали вчера?', 'memory'),
    ('Как меня зовут?', 'memory'),
])
def test_exact_calculation_and_scoped_memory_keep_their_real_tools(tmp_path, settings, query, tool):
    async def run():
        original, board, manager, session = await setup(tmp_path, settings)
        operations = []
        requests = []
        execute = session.manager.brain.tools.execute
        def recorded(name, req, slots):
            operations.append(name)
            requests.append(req)
            return execute(name, req, slots)
        async def respond():
            pass
        session.response = respond
        session.manager.brain.tools.execute = recorded
        try:
            turn = await session.new_turn(query=query)
            await session.tool('scoped', 'gobot_tool', json.dumps({'query': ORDINARY[0]}), turn)
            result, = outputs(session, 'scoped')
            assert operations == [tool]
            assert result.get('status') != 'no_matching_server_operation'
            assert not session.experts.jobs
            if tool == 'calculator':
                assert result['evidence']['verified'] and '5461' in result['text']
            else:
                assert requests[0].remember is False
                assert result['evidence']['abstained'] and 'PIN' not in result['text']
                assert result['evidence']['status'] == 'not_found'
                assert result['evidence']['scope'] == 'current_conversation'
                assert result['evidence']['source_message_ids'] == []
                assert result['evidence']['private_archive_checked'] is False
                # An explicit private archive request still needs identity;
                # the current-conversation path cannot confer archive access.
                private = execute('memory', requests[0].model_copy(update={'remember': True}), {})
                assert private.evidence['abstained'] and 'PIN' in private.text
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('query', [
    'Удали файл',
    'Открой неизвестное хранилище',
    'Какой у меня пароль?',
    'Почему небо синее, и удали файл',
])
def test_unmatched_requests_never_claim_action_or_verified_knowledge(tmp_path, settings, query):
    async def run():
        original, board, manager, session = await setup(tmp_path, settings)
        async def respond():
            pass
        session.response = respond
        try:
            turn = await session.new_turn(query=query)
            await session.tool('unknown', 'gobot_tool', json.dumps({'query': query}), turn)
            result, = outputs(session, 'unknown')
            assert result['executed'] is False
            assert result['evidence']['server_action_executed'] is False
            assert result['evidence']['verified'] is False
            assert 'knowledge_answer_allowed' not in result
            assert 'requires_user_confirmation' not in result
            assert not session.experts.jobs
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('query', ['Включи музыку', 'Можешь открыть дверь?'])
def test_unsupported_adapter_and_hallucinated_write_do_not_use_conversation_fallback(tmp_path, settings, query):
    async def run():
        original, board, manager, session = await setup(tmp_path, settings)
        async def respond():
            pass
        session.response = respond
        try:
            turn = await session.new_turn(query=query)
            await session.tool('adapter', 'gobot_tool', json.dumps({'query': turn.query}), turn)
            result, = outputs(session, 'adapter')
            assert result['evidence']['abstained']
            assert result.get('status') != 'no_matching_server_operation'
            turn = await session.new_turn(query=ORDINARY[0])
            await session.tool('fake-write', 'gobot_tool', json.dumps({'query': 'Поставь таймер на 5 минут'}), turn)
            result, = outputs(session, 'fake-write')
            assert result['error'] == 'tool_validation_or_execution_failed'
            assert not result['executed']
            with session.manager.brain.memory.connect() as connection:
                assert connection.execute('SELECT COUNT(*) FROM timers').fetchone()[0] == 0
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_tool_before_transcript_is_nonexecuting_and_cancelled_turn_cannot_continue(tmp_path, settings):
    async def run():
        original, board, manager, session = await setup(tmp_path, settings)
        replies = []
        async def respond():
            replies.append(True)
        session.response = respond
        try:
            turn = await session.new_turn()
            arguments = json.dumps({'query': ORDINARY[0]})
            await session.tool('early', 'gobot_tool', arguments, turn)
            result, = outputs(session, 'early')
            assert result['status'] == 'no_matching_server_operation'
            assert result['executed'] is False and replies == [True]
            turn.cancelled = True
            await session.tool('cancelled', 'gobot_tool', arguments, turn)
            cancelled, = outputs(session, 'cancelled')
            assert cancelled['cancelled'] and cancelled['executed'] is False
            assert replies == [True]
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_browser_and_device_receive_same_direct_answer_contract(tmp_path, settings):
    async def run():
        manager, _, _ = configured(tmp_path, settings)
        browser = await start(manager)
        try:
            assert INSTRUCTIONS in browser.config['instructions']
            assert 'На обычные вопросы по общим знаниям отвечай сразу' in browser.config['instructions']
            assert 'status=no_matching_server_operation' in browser.config['instructions']
        finally:
            await manager.shutdown()
        original, board, direct, session = await setup(tmp_path/'device', settings)
        try:
            config = await session.build_config()
            assert INSTRUCTIONS in config['instructions']
            expected = next(tool for tool in TOOLS if tool['name'] == 'gobot_tool')
            assert next(tool for tool in config['tools'] if tool['name'] == 'gobot_tool') == expected
            assert 'обычные вопросы по общим знаниям' in expected['description']
        finally:
            await cleanup(original, board, direct)
    asyncio.run(run())
