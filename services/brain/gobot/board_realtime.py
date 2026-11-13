"""Opt-in hardware B, same NativeSession/Brain, separate admission and ledger.

Attached only by the explicit host mount flag. C deployment does not activate B.
"""
import asyncio,time,json
from pathlib import Path
from .realtime import RealtimeManager,NativeSession
from .realtime_budget import RealtimeBudget,estimate_usd
from .realtime_contract import RealtimePolicy

class BoardBudget(RealtimeBudget):
    ESTIMATED_LIMIT=1.
    def reserve_session(self,ident,consent,client_id=None,owner_test_binding=None):
        if owner_test_binding:raise PermissionError('board_must_not_borrow_phone_binding')
        p=self.policy()
        if (p.max_sessions!=8 or p.max_session_seconds!=60 or p.max_responses_per_session!=8 or
            p.max_output_tokens!=512 or p.voice!='marin' or p.model!='gpt-realtime-2.1-mini' or
            p.allowed_models!=['gpt-realtime-2.1-mini'] or not p.input_transcription or
            p.owner_full_test or p.expert_jobs_allowed or p.image_generation_allowed or p.device_settings_allowed):
            raise PermissionError('board_policy_outside_owner_allowance')
        # Count/time/response/token controls are enforced by NativeSession too.
        # A reservation remains after uncertain failure; no retry or automatic refund.
        with self.connect() as db:
            used=db.execute('SELECT count(*) FROM sessions').fetchone()[0]*.125
            observed=sum(estimate_usd(json.loads(r[0])) for r in db.execute('SELECT usage FROM usage'))
            if max(used,observed)+.125>self.ESTIMATED_LIMIT:raise PermissionError('board_estimated_budget_exhausted')
        # The existing atomic sessions row itself reserves 1/8 of the estimate.
        return super().reserve_session(ident,consent,client_id,owner_test_binding)

    def board_status(self):
        p=self.policy()
        with self.connect() as db:
            count=db.execute('SELECT count(*) FROM sessions').fetchone()[0]
            reserve=db.execute('SELECT count(*) FROM sessions').fetchone()[0]*.125
            observed=sum(estimate_usd(json.loads(r[0])) for r in db.execute('SELECT usage FROM usage'))
        return {'enabled':self.active(p),'model':p.model,'voice':p.voice,'sessions_remaining':max(0,8-count),
            'session_seconds':60,'responses_per_session':8,'output_tokens_per_response':512,
            'estimated_allowance_usd':1,'reserved_estimate_usd':reserve,
            'reported_response_estimate_usd':observed,'transcription_billed_separately':True,
            'transcription_final_cost_confirmed':False,'hard_dollar_cap_guaranteed':False,
            'automatic_paid_retries':False,'hardware_accepted':False}

    def reserve_response(self,ident,policy):
        with self.connect() as db:
            observed=sum(estimate_usd(json.loads(r[0])) for r in db.execute('SELECT usage FROM usage'))
        if observed>=self.ESTIMATED_LIMIT:raise PermissionError('board_estimated_budget_exhausted')
        return super().reserve_response(ident,policy)

class BoardSession(NativeSession):
    def __init__(self,manager,offer,profile,policy):
        profile=profile.model_copy(deep=True)
        profile.voice=profile.voice.model_copy(update={'voice':'marin'})
        super().__init__(manager,offer,profile,policy)
        self.automatic_dialogue=True

    async def listen_initial(self):
        async with self.lock:
            if not self.ready or self.current or self.input_mode=='followup':raise ValueError('initial_listening_not_available')
            detection={'type':'server_vad','threshold':.55,'prefix_padding_ms':300,
                'silence_duration_ms':self.profile.conversation.silence_ms,
                'create_response':False,'interrupt_response':False,'idle_timeout_ms':None}
            await self.update_input(detection)
            await self.send({'type':'input_audio_buffer.clear'})
            self.input_mode='followup';self.followup_deadline=time.monotonic()+10
            self.emit('listening',active=True)

class BoardRealtime(RealtimeManager):
    def __init__(self,original,root,*,provider=None):
        self.original=original
        super().__init__(original.brain,provider=provider,budget=BoardBudget(root),profile_loader=original.profile_loader,
            identity=original.identity,journal=original.journal,owner_testing=original.owner_testing,session_factory=BoardSession)
        self.lock=original.lock
        self.live=getattr(original,'live',None)
        # One lease for shared device across native C, phone B and this opt-in adapter.
        self.voice_peers=[original];original.voice_peers.append(self)

    async def start(self,offer):
        p=self.budget.policy()
        if (offer.device_id!=p.allowed_client_id or offer.client_id!=p.allowed_client_id or
            offer.owner_test_binding or offer.profile_epoch or offer.confirmed_profile_epoch or
            offer.personalization_mode!='guest' or offer.remember or offer.speaker_consent or
            offer.expert_quota_consent or offer.developer_acceptance or offer.requested_model!=p.model or
            offer.requested_voice!='marin' or not offer.speak):raise PermissionError('exact_board_guest_offer_required')
        return await super().start(offer)

def prepare_policy(root,board_id):
    """Local operator preparation only: never changes an existing policy/grant."""
    root=Path(root);root.mkdir(parents=True,exist_ok=True);path=root/'policy.json'
    if path.exists():return path
    from uuid import uuid4
    policy=RealtimePolicy(enabled=False,authorization=uuid4().hex,audience='owner_interactive',
        allowed_client_id=board_id,expires_at=None,max_sessions=8,max_session_seconds=60,
        max_responses_per_session=8,max_output_tokens=512,input_transcription=True,voice='marin',
        model='gpt-realtime-2.1-mini',allowed_models=['gpt-realtime-2.1-mini'],owner_full_test=False)
    with path.open('x',encoding='utf8') as out:out.write(policy.model_dump_json(indent=2))
    return path
