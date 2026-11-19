"""L1 experimental ready-before-touch lifecycle, NOT attached to live gateway.
No provider client or implicit financial permission lives here. The existing
server budget adapter must claim an explicit ready-B grant before factory.open.
Tests supply fakes. A real provider/budget binding is intentionally not installed.
"""
from __future__ import annotations
from dataclasses import dataclass
import asyncio
import math
import time
import uuid

@dataclass(frozen=True)
class PreparedScope:
    device_id:str
    profile_epoch:str
    transport_epoch:str

@dataclass(frozen=True)
class ReadyProof:
    session_ack:bool
    sdp_ack:bool
    media_ready:bool
    configuration_ack:bool
    input_disabled:bool
    transcription_disabled:bool
    model:str
    voice:str

@dataclass(frozen=True)
class CloseProof:
    local_resources_released:bool
    provider_close_confirmed:bool
    usage_final_received:bool

class PreparedB:
    """One claim / one open / one activation / bounded close, no retries.
    admission.claim must be durable, atomic, purpose-scoped and finite. A normal
    B conversational grant MUST NOT be treated as a prewarm grant by its adapter.
    This class never refunds or clears a claim, ledger, reserve or unknown usage.
    """
    def __init__(self,scope,*,admission=None,factory=None,clock=time.monotonic,ready_ttl=10.,lifetime=60.):
        if not isinstance(scope,PreparedScope) or any(not isinstance(x,str) or not x or len(x)>128 for x in (scope.device_id,scope.profile_epoch,scope.transport_epoch)):
            raise ValueError('prepared_b_scope_required')
        if not 0<ready_ttl<=30 or not ready_ttl<=lifetime<=60:raise ValueError('invalid_prepared_b_limits')
        self.scope=scope;self.admission=admission;self.factory=factory;self.clock=clock
        self.ready_ttl=ready_ttl;self.lifetime=lifetime;self.state='UNOPENED';self.operation_id=uuid.uuid4().hex
        self.created=None;self.ready_at=None;self.activation_id=None;self.handle=None;self.claim=None
        self.close_proof=CloseProof(False,False,False);self.rejected_ambient_samples=0;self.activation_attempted=False
        self.close_attempted=False;self.lock=asyncio.Lock()
    async def prepare(self):
        async with self.lock:
            if self.state!='UNOPENED':raise RuntimeError('no_automatic_prewarm_retry')
            if self.admission is None or self.factory is None:raise PermissionError('separate_finite_owner_grant_required')
            # Financial claim precedes every provider-facing method. No permissive bool fallback.
            self.claim=await self.admission.claim(self.scope,self.operation_id,purpose='B_READY_BEFORE_TOUCH',max_lifetime=self.lifetime)
            if self.claim is None:raise PermissionError('prewarm_claim_denied')
            self.created=self.clock();self.state='OPENING'
            try:
                async with asyncio.timeout(10):
                    self.handle,proof=await self.factory.open(self.operation_id,self.scope,self.claim)
                if not isinstance(proof,ReadyProof) or not all(v is True for v in (proof.session_ack,proof.sdp_ack,proof.media_ready,proof.configuration_ack,proof.input_disabled,proof.transcription_disabled)):
                    raise ValueError('prepared_b_readiness_unconfirmed')
                if proof.model!='gpt-realtime-2.1-mini' or proof.voice!='marin':raise ValueError('prepared_b_model_or_voice_changed')
                if self.clock()-self.created>=self.lifetime:raise TimeoutError('prepared_b_expired_while_opening')
                self.ready_at=self.clock();self.state='READY'
            except BaseException:
                await self._close();raise
            return self.operation_id
    def input_frame(self,pcm):
        if not isinstance(pcm,(bytes,bytearray)) or len(pcm)%2 or len(pcm)>1920:raise ValueError('bounded_mono_pcm_required')
        if self.state!='ACTIVE' or self.expired():
            self.rejected_ambient_samples+=len(pcm)//2
            return None # Never buffered for later replay and never sent to transcription.
        return pcm
    def expired(self):
        now=self.clock()
        if self.created is None:return False
        return now-self.created>=self.lifetime or (self.state=='READY' and now-self.ready_at>=self.ready_ttl)
    async def activate(self,scope,activation_id):
        async with self.lock:
            if scope!=self.scope:raise PermissionError('prepared_b_scope_changed')
            if not isinstance(activation_id,str) or not 1<=len(activation_id)<=64:raise ValueError('activation_id_required')
            if self.activation_attempted or self.state!='READY':raise RuntimeError('prepared_b_not_ready_or_already_used')
            if self.expired():await self._close();raise TimeoutError('prepared_b_expired')
            self.activation_attempted=True
            try:
                async with asyncio.timeout(5):
                    effective=await self.factory.activate(self.handle,activation_id)
                if effective is not True or self.expired():raise ValueError('prepared_b_input_configuration_unconfirmed')
                self.activation_id=activation_id;self.state='ACTIVE'
            except BaseException:
                await self._close();raise
    async def tick(self):
        # Called by the existing owning loop; no new scheduler/persistent service.
        async with self.lock:
            if self.expired() and self.state in {'READY','ACTIVE','OPENING'}:await self._close()
    async def _close(self):
        if self.close_attempted:return self.close_proof
        self.close_attempted=True;self.state='CLOSING'
        try:
            async with asyncio.timeout(8):
                proof=await self.factory.close(self.operation_id,self.handle)
            if isinstance(proof,CloseProof) and all(type(x) is bool for x in (proof.local_resources_released,proof.provider_close_confirmed,proof.usage_final_received)):
                self.close_proof=proof
        except BaseException:
            # Never replace unknown finalization with a local timer assumption.
            self.state='UNCONFIRMED'
            raise
        finally:
            self.state='CLOSED_CONFIRMED' if self.close_proof.provider_close_confirmed else 'UNCONFIRMED'
        return self.close_proof
    async def close(self):
        async with self.lock:
            if self.state=='UNOPENED':return self.close_proof
            return await self._close()

PARITY_FIELDS=('model','voice','instructions_digest','context_digest','endpointing_digest','audio_preset','max_output_tokens')
def compare_manifest(web,board):
    missing=[k for k in PARITY_FIELDS if k not in web or k not in board]
    different=[k for k in PARITY_FIELDS if k in web and k in board and web[k]!=board[k]]
    return {'comparable':not missing and not different,'missing':missing,'different':different,
            'variants':['web_b_cold','spotpear_b_cold','spotpear_b_ready','spotpear_b_followup'],
            'real_session_started':False,'price_or_latency_prediction':None}
