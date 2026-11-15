"""Separately authorized, finite Owner wake acceptance; never renew older grants.

This adapter is selected ONLY by an explicit operator mount profile. Preparation
does not mount, enable, call providers, or grant authorization to a speaker.
"""
import json,time
from pathlib import Path
from uuid import uuid4
from .board_realtime import BoardBudget,BoardRealtime
from .realtime_contract import RealtimePolicy

class WakeTestBudget(BoardBudget):
    LIMITS=(3,60,8,512)
    RESERVATION=1/3
    EXPERTS=False

    def policy(self):
        p=super().policy()
        if p.enabled and (p.expires_at is None or p.expires_at>time.time()+86401):
            raise PermissionError('wake_test_requires_bounded_owner_expiry')
        return p

class WakeTestRealtime(BoardRealtime):
    budget_type=WakeTestBudget

def prepare_policy(root,board_id):
    root=Path(root);root.mkdir(parents=True,exist_ok=True);path=root/'policy.json'
    if path.exists():return path
    p=RealtimePolicy(enabled=False,authorization=uuid4().hex,audience='owner_interactive',
        allowed_client_id=board_id,expires_at=None,max_sessions=3,max_session_seconds=60,
        max_responses_per_session=8,max_output_tokens=512,input_transcription=True,voice='marin',
        model='gpt-realtime-2.1-mini',allowed_models=['gpt-realtime-2.1-mini'],owner_full_test=False)
    with path.open('x',encoding='utf-8') as stream:stream.write(p.model_dump_json(indent=2))
    (root/'pending-owner-decision.json').write_text(json.dumps({'enabled':False,'owner_approval_received':False,
        'manual_only':True,'maximum_sessions':3,'maximum_seconds_each':60,'estimated_budget_usd':1,
        'hard_invoice_cap_guaranteed':False,'automatic_paid_retries':False,'cli':False,'image_api':False},indent=2))
    return path
