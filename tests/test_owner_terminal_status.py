"""The installed board status endpoint accepts continuing owner authorization."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gobot.board_realtime_api import attach_board_realtime


@pytest.mark.parametrize('remaining,pending,enabled,reason', [
    (None, [], True, None),
    (None, ['unconfirmed-call'], False, 'board_previous_hangup_unconfirmed'),
    (0, [], False, 'board_session_limit'),
    (3, [], True, None),
])
def test_status_nullable_quota_keeps_pending_hangup_gate(remaining,pending,enabled,reason):
    budget = SimpleNamespace(
        board_status=lambda: {'enabled': True, 'sessions_remaining': remaining},
        pending_calls=lambda: pending)
    manager = SimpleNamespace(budget=budget,sessions={})
    app = FastAPI()
    async def auth():
        return None
    attach_board_realtime(app,manager,auth)
    with TestClient(app) as client:
        response = client.get('/api/v1/voice-ab/b/status')
    assert response.status_code == 200
    state = response.json()
    assert state['enabled'] is enabled
    assert state['admission_reason'] == reason
    assert state['sessions_remaining'] == remaining
