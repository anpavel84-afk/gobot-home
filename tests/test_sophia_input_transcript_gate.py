"""Physical fast input uses its existing final ASR before any new generation."""
import asyncio
import base64
import json
import threading

import pytest

from test_realtime_ws import setup, offer, cleanup


def response_count(session):
    return sum(event['type'] == 'response.create' for event in session.ws.sent)


def reserved_responses(board):
    with board.budget.connect() as db:
        return db.execute('SELECT coalesce(sum(responses),0) FROM sessions').fetchone()[0]


async def final(session, item='input', text='Сколько будет два плюс три?', *, failed=False):
    await session.handle({'type': 'conversation.item.input_audio_transcription.'+
                         ('failed' if failed else 'completed'),
                         'item_id': item, 'transcript': text})


async def begin(session, *, trigger='manual', item='input', early=None):
    await session.wake('synthetic-'+item, trigger=trigger)
    pcm = b'\x05\x00'*4800
    await session.append_pcm(pcm)
    if early is not None:
        await final(session, item, early)
    await session.handle({'type': 'input_audio_buffer.committed', 'item_id': item})
    return session._wake_fragment, pcm


@pytest.mark.parametrize('early', [False, True])
@pytest.mark.parametrize('trigger', ['manual', 'touch'])
def test_correlated_final_allows_exactly_one_answer_using_original_audio(tmp_path, settings, early, trigger):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            question = 'Расскажи, почему небо выглядит голубым.'
            gate, pcm = await begin(session, trigger=trigger, early=question if early else None)
            assert gate and not gate['wake_resume']
            assert response_count(session) == reserved_responses(board) == 0
            if not early:
                await final(session, 'unrelated-item', 'Это не текущая реплика.')
                await asyncio.sleep(0)
                assert response_count(session) == reserved_responses(board) == 0
                await final(session, text=question)
            await gate['task']
            assert session.current.query == question
            assert response_count(session) == reserved_responses(board) == 1
            assert [base64.b64decode(event['audio']) for event in session.ws.sent
                    if event['type'] == 'input_audio_buffer.append'] == [pcm]
            assert not any(event['type'] == 'conversation.item.create' and
                           event.get('item', {}).get('role') == 'user' for event in session.ws.sent)
            assert not any(event['type'] == 'input_audio_buffer.commit' for event in session.ws.sent)
            await final(session, text=question)
            await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'input'})
            assert response_count(session) == reserved_responses(board) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('ending', ['empty', 'punctuation', 'failed', 'timeout', 'name_only'])
def test_empty_failed_or_missing_final_has_no_response_and_cannot_revive(tmp_path, settings, monkeypatch, ending):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            if ending == 'timeout':
                monkeypatch.setattr('gobot.realtime_ws._FAST_TRANSCRIPT_TIMEOUT_SECONDS', .015)
            session = await manager.accept(offer())
            gate, _ = await begin(session)
            if ending != 'timeout':
                await final(session, text={'empty': ' \n ', 'punctuation': '...?!',
                            'failed': 'unknown', 'name_only': 'София.'}[ending], failed=ending == 'failed')
            await gate['task']
            assert response_count(session) == reserved_responses(board) == 0
            assert session.ready and not session.closed and not session.input_open
            assert session.current.cancelled
            assert any(event['type'] == 'conversation.item.delete' and event['item_id'] == 'input'
                       for event in session.ws.sent)
            await final(session, text='Поздний результат старого распознавания.')
            assert response_count(session) == reserved_responses(board) == 0
            assert session.current.query == ''
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('text', ['Стоп.', 'София, стоп!', 'Хватит', 'Софья, остановись',
                                'Закончим разговор.', 'София, давай закончим'])
def test_voice_stop_has_no_generated_goodbye_and_keeps_next_wake_available(tmp_path, settings, text):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            gate, _ = await begin(session)
            await final(session, text=text)
            await gate['task']
            assert response_count(session) == reserved_responses(board) == 0
            assert session.current.local_control and session.current.cancelled
            assert session.ready and not session.closed and not session.input_open
            assert manager.sessions[session.id] is session
            assert not session.followup_deadline and not session._guard_task
            assert any(event['type'] == 'stopped' for event in session.events)
            await final(session, text='Позднее событие не должно менять остановку.')
            assert response_count(session) == 0
            gate, _ = await begin(session, item='fresh')
            await final(session, 'fresh', 'Который час?')
            await gate['task']
            assert response_count(session) == reserved_responses(board) == 1
            assert board.budget.status()['sessions_reserved'] == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_followup_uses_same_gate_and_does_not_respond_to_silence(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            await session.wake('synthetic-wake')
            session.input_open = False
            await session.start_fast_input(followup=True)
            await session.append_pcm(bytes(4800))
            await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'followup'})
            gate = session._wake_fragment
            assert gate and session.current.direct_input_trigger == 'followup'
            assert response_count(session) == 0
            await final(session, 'followup', '')
            await gate['task']
            assert response_count(session) == reserved_responses(board) == 0
            assert not session.input_open and not session.closed
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('boundary', ['stop', 'mute', 'detach'])
@pytest.mark.parametrize('phase', ['admission', 'reserved', 'send_lock'])
def test_stop_cannot_create_late_response_across_admission_and_wire_waits(
        tmp_path, settings, monkeypatch, phase, boundary):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        entered, release = asyncio.Event(), asyncio.Event()
        thread_entered, thread_release = threading.Event(), threading.Event()
        stopping = None
        locked = False
        try:
            session = await manager.accept(offer())
            gate, _ = await begin(session)
            original_admission, original_send = session.admission, session.send
            original_reserve = board.budget.reserve_response
            async def admission(**kwargs):
                if phase == 'admission' and session._wake_fragment is None:
                    entered.set()
                    await release.wait()
                return await original_admission(**kwargs)
            def reserve(*args, **kwargs):
                result = original_reserve(*args, **kwargs)
                if phase == 'reserved':
                    thread_entered.set()
                    assert thread_release.wait(3)
                return result
            async def send(event, **kwargs):
                if phase == 'send_lock' and event['type'] == 'response.create':
                    entered.set()
                    await release.wait()
                return await original_send(event, **kwargs)
            monkeypatch.setattr(session, 'admission', admission)
            monkeypatch.setattr(board.budget, 'reserve_response', reserve)
            monkeypatch.setattr(session, 'send', send)
            await final(session)
            async with asyncio.timeout(4):
                if phase == 'reserved':
                    assert await asyncio.to_thread(thread_entered.wait, 2)
                else:
                    await entered.wait()
                if phase == 'send_lock':
                    await session.send_lock.acquire()
                    locked = True
                    release.set()
                    await asyncio.sleep(0)  # The Response now waits on the actual send lock.
                epoch = session._input_gate_epoch
                action = session.stop() if boundary == 'stop' else session.mute(True) \
                    if boundary == 'mute' else session.detach()
                stopping = asyncio.create_task(action)
                while session._input_gate_epoch == epoch:
                    await asyncio.sleep(0)
                if locked:
                    session.send_lock.release()
                    locked = False
                release.set()
                thread_release.set()
                await stopping
                await gate['task']
            assert response_count(session) == 0
            assert reserved_responses(board) == (0 if phase == 'admission' else 1)
            assert not session.input_open and not session.response_requested
        finally:
            release.set(); thread_release.set()
            if locked:
                session.send_lock.release()
            if stopping:
                await asyncio.gather(stopping, return_exceptions=True)
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_browser_keeps_existing_audio_commit_scheduling(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer().model_copy(update={'client_kind': 'panel'}))
            await session.wake('manual-browser', source='browser')
            await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'browser-input'})
            assert session._wake_fragment is None
            assert response_count(session) == reserved_responses(board) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_stale_fast_provider_commit_cannot_take_expert_capture_ownership(tmp_path, settings):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            # Isolate the already-open expert capture state. A late event from
            # the idle fast socket has no authority over the separate STT lane.
            session.selected_mode = session.input_mode = 'expert'
            session.input_open = True
            session.state = 'listening'
            await session.handle({'type': 'input_audio_buffer.committed', 'item_id': 'old-fast-item'})
            assert session.input_open and session.input_mode == 'expert' and session.state == 'listening'
            assert session.current is None and session._wake_fragment is None
            assert response_count(session) == reserved_responses(board) == 0
            assert any(event['type'] == 'conversation.item.delete' and event['item_id'] == 'old-fast-item'
                       for event in session.ws.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def hold_response_acks(session, monkeypatch):
    original_send = session.ws.send
    async def send(raw):
        event = json.loads(raw)
        if event['type'] == 'response.create':
            session.ws.sent.append(event)
        else:
            await original_send(raw)
    monkeypatch.setattr(session.ws, 'send', send)


def sent_response(session):
    return [event for event in session.ws.sent if event['type'] == 'response.create'][-1]


async def created(session, request, response_id):
    await session.handle({'type': 'response.created', 'response': {
        'id': response_id, 'metadata': request['response'].get('metadata')}})


@pytest.mark.parametrize('old_ack_before_stop', [False, True])
@pytest.mark.parametrize('new_ack_first', [False, True])
def test_late_old_response_never_claims_new_turn_pending_or_active(
        tmp_path, settings, monkeypatch, old_ack_before_stop, new_ack_first):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            hold_response_acks(session, monkeypatch)
            old_gate, _ = await begin(session, item='old-question')
            await final(session, 'old-question', 'Сколько будет два плюс три?')
            await old_gate['task']
            old_turn, old_request = session.current, sent_response(session)
            old_operation = session.operation_id
            if old_ack_before_stop:
                await created(session, old_request, 'old-response')
            await session.stop()
            # A new paid operation makes incorrect late-usage attribution
            # visible as well as incorrect question/answer binding.
            session.operation_started = 0.
            new_gate, _ = await begin(session, item='new-question')
            await final(session, 'new-question', 'Сколько будет три плюс четыре?')
            await new_gate['task']
            new_turn, new_request = session.current, sent_response(session)
            new_operation = session.operation_id
            assert old_operation != new_operation
            assert old_request['response']['metadata'] != new_request['response']['metadata']
            assert old_turn.cancelled and new_turn is not old_turn
            if new_ack_first:
                await created(session, new_request, 'new-response')
            else:
                assert session.response_requested and not session.generating
            if not old_ack_before_stop:
                await created(session, old_request, 'old-response')
            assert session.response_turn.get('old-response') is not new_turn
            assert session.current is new_turn and not new_turn.cancelled
            assert not any(event['type'] == 'error' for event in session.events)
            calls = []
            async def forbidden_tool(*args):
                calls.append(args)
            monkeypatch.setattr(session, 'tool', forbidden_tool)
            await session.handle({'type': 'response.output_audio_transcript.delta',
                                  'response_id': 'old-response', 'delta': 'Старый ответ.'})
            await session.handle({'type': 'response.output_audio.delta', 'response_id': 'old-response',
                                  'delta': base64.b64encode(bytes(2880)).decode()})
            await session.handle({'type': 'response.function_call_arguments.done',
                                  'response_id': 'old-response', 'call_id': 'old-tool',
                                  'name': 'expert_start', 'arguments': '{}'})
            usage = {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}
            await session.handle({'type': 'response.done', 'response': {
                'id': 'old-response', 'status': 'cancelled', 'usage': usage}})
            await asyncio.sleep(0)
            assert not calls and not new_turn.answer and session.output_response is None
            assert session.response_operations['old-response'] == old_operation
            with board.budget.connect() as db:
                row = db.execute('SELECT session FROM usage WHERE response=?',
                                 (board.budget.key('old-response'),)).fetchone()
            assert row == (board.budget.key(old_operation),)
            assert board.budget.total_tokens(old_operation) == 15
            assert board.budget.total_tokens(new_operation) == 0
            assert session.generating is new_ack_first
            assert session.response_requested is not new_ack_first
            if not new_ack_first:
                await created(session, new_request, 'new-response')
            assert session.response_turn['new-response'] is new_turn
            assert session.live_response == 'new-response' and session.generating
            assert not session.response_requested
            # A duplicated old terminal event must not finish the new response.
            await session.handle({'type': 'response.done', 'response': {
                'id': 'old-response', 'status': 'cancelled', 'usage': usage}})
            assert session.live_response == 'new-response' and session.generating
            assert response_count(session) == reserved_responses(board) == 2
            if not old_ack_before_stop:
                assert any(event['type'] == 'response.cancel' and
                           event.get('response_id') == 'old-response' for event in session.ws.sent)
            assert not any(event['type'] == 'response.cancel' and
                           event.get('response_id') == 'new-response' for event in session.ws.sent)
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


@pytest.mark.parametrize('metadata', [None, {}, {'gobot_request_id': 'foreign'},
                                     {'gobot_request_id': ['invalid-type']}])
def test_missing_or_foreign_response_correlation_cannot_consume_pending_request(
        tmp_path, settings, monkeypatch, metadata):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            session = await manager.accept(offer())
            hold_response_acks(session, monkeypatch)
            gate, _ = await begin(session)
            await final(session)
            await gate['task']
            request = sent_response(session)
            pending = session._pending_response_request
            await session.handle({'type': 'response.created', 'response': {
                'id': 'foreign-response', 'metadata': metadata}})
            assert session.response_requested and not session.generating
            assert session._pending_response_request == pending
            assert 'foreign-response' not in session.response_turn
            assert 'foreign-response' not in session.response_operations
            assert not any(event['type'] == 'error' for event in session.events)
            await created(session, request, 'current-response')
            assert session.response_turn['current-response'] is session.current
            assert session.generating and not session.response_requested
            before = len(session.ws.sent)
            await created(session, request, 'current-response')
            assert len(session.ws.sent) == before
            assert session.generating and session.live_response == 'current-response'
            assert response_count(session) == reserved_responses(board) == 1
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_missing_response_ack_times_out_to_quiet_ready_without_retry_or_refund(
        tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            monkeypatch.setattr('gobot.realtime_ws._RESPONSE_CREATED_TIMEOUT_SECONDS', .02)
            session = await manager.accept(offer())
            hold_response_acks(session, monkeypatch)
            gate, _ = await begin(session)
            await final(session)
            await gate['task']
            request = sent_response(session)
            async with asyncio.timeout(1):
                while not any(event['type'] == 'stopped' for event in session.events):
                    await asyncio.sleep(.005)
            assert session.ready and not session.closed and session.state == 'ready'
            assert not session.generating and not session.response_requested and not session.input_open
            assert session.current.cancelled and session._pending_response_request is None
            assert response_count(session) == reserved_responses(board) == 1
            await created(session, request, 'late-timeout-response')
            assert 'late-timeout-response' not in session.response_turn
            assert response_count(session) == reserved_responses(board) == 1
            # A later explicit wake is still usable under the same grant.
            gate, _ = await begin(session, item='fresh-after-timeout')
            await final(session, 'fresh-after-timeout', 'Который час?')
            await gate['task']
            await created(session, sent_response(session), 'fresh-response')
            assert session.generating and session.live_response == 'fresh-response'
            assert response_count(session) == reserved_responses(board) == 2
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())


def test_pending_response_registry_has_bounded_retention_and_rotation_clears_only_ram(
        tmp_path, settings, monkeypatch):
    async def run():
        original, board, manager, _ = setup(tmp_path, settings)
        try:
            monkeypatch.setattr('gobot.realtime_ws._RESPONSE_REQUEST_LIMIT', 2)
            monkeypatch.setattr('gobot.realtime_ws._RESPONSE_CREATED_TIMEOUT_SECONDS', .01)
            monkeypatch.setattr('gobot.realtime_ws._RESPONSE_REQUEST_RETENTION_SECONDS', .08)
            session = await manager.accept(offer())
            hold_response_acks(session, monkeypatch)
            for index in range(3):
                item = 'question-'+str(index)
                gate, _ = await begin(session, item=item)
                await final(session, item, 'Сколько будет два плюс три?')
                await gate['task']
                await session.stop()
                assert len(session._response_requests) <= 2
            assert response_count(session) == reserved_responses(board) == 3
            async with asyncio.timeout(1):
                while session._response_requests:
                    await asyncio.sleep(.01)
            assert reserved_responses(board) == 3
            gate, _ = await begin(session, item='before-rotation')
            await final(session, 'before-rotation', 'Который час?')
            await gate['task']
            await session.stop()
            assert session._response_requests
            assert await session.rotate(force=True)
            assert not session._response_requests
            assert reserved_responses(board) == 4
        finally:
            await cleanup(original, board, manager)
    asyncio.run(run())
