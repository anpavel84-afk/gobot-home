"""One separately approved manual 180s B trial; never renews the original grant.

Public expert expense authorization is not speaker/private-memory authorization.
All settings are local operator files, unavailable to model/browser tool writes.
"""
import time
from pathlib import Path
from uuid import uuid4
from .board_realtime import BoardBudget,BoardSession,BoardRealtime
from .realtime_contract import RealtimePolicy
from .expert_store import ExpertBudget,ExpertPolicy
from .expert_jobs import ExpertJobs

class TrialBudget(BoardBudget):
    LIMITS=(1,180,12,2048)
    RESERVATION=1.
    EXPERTS=True

class PublicExpertBudget(ExpertBudget):
    def policy(self):
        p=super().policy()
        if (p.owner_full_test or not p.allowed_client_id or p.expires_at is None or
            (p.max_sessions,p.job_timeout_seconds,p.max_context_tokens,p.max_result_characters)!=(1,90,3000,6000) or
            p.allowed_profiles!=['SOL_HIGH']):raise PermissionError('board_expert_policy_outside_allowance')
        return p

class TrialSession(BoardSession):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.experts=ExpertJobs(self,budget=PublicExpertBudget(self.manager.budget.root/'experts'))

    def scoped_public_expert_allowed(self):
        p=self.policy;e=self.experts.budget.policy()
        return bool(isinstance(self.manager.budget,TrialBudget) and
            self.manager.budget.active(self.manager.budget.policy()) and self.experts.budget.active(e) and
            p.expert_jobs_allowed and self.offer.expert_quota_consent and
            p.allowed_client_id==self.offer.client_id==self.offer.device_id==e.allowed_client_id and
            self.offer.personalization_mode=='guest' and not self.access.confirmed_profile_id and
            not self.offer.remember and not self.offer.owner_test_binding)

class TrialRealtime(BoardRealtime):
    budget_type=TrialBudget
    session_type=TrialSession

def prepare_trial(root,board_id):
    """Idempotent local grant preparation. No enable, provider call or renewal."""
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    expires=time.time()+86400
    voice=RealtimePolicy(enabled=False,authorization=uuid4().hex,audience='owner_interactive',
        allowed_client_id=board_id,expires_at=expires,max_sessions=1,max_session_seconds=180,
        max_responses_per_session=12,max_output_tokens=2048,observed_token_limit=100000,
        input_transcription=True,voice='marin',expert_jobs_allowed=True)
    expert=ExpertPolicy(enabled=False,authorization=uuid4().hex,audience='owner_interactive',
        allowed_client_id=board_id,expires_at=expires,max_sessions=1,allowed_profiles=['SOL_HIGH'],
        job_timeout_seconds=90,max_context_tokens=3000,max_result_characters=6000)
    for path,p in ((root/'policy.json',voice),(root/'experts/policy.json',expert)):
        path.parent.mkdir(parents=True,exist_ok=True)
        if not path.exists():
            with path.open('x',encoding='utf8') as out:out.write(p.model_dump_json(indent=2))
    return root/'policy.json'
