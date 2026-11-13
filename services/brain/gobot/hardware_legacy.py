"""Optional device A allowance, reusing the existing finite expert ledger.
No grant is implicitly created/enabled. Separate from B, C and the phone.
"""
import asyncio
from pathlib import Path
from .expert_store import ExpertBudget
from .processes import AgentError

def bound_packet(question,packet,policy):
    from copy import deepcopy
    from .context_manager import tokens,serialize_context
    packet=deepcopy(packet)
    for key in ('messages','retrieved','facts'):
        while tokens(serialize_context(question,packet))>policy.max_context_tokens and packet.get(key):packet[key].pop(0)
    if tokens(serialize_context(question,packet))>policy.max_context_tokens:packet.pop('summary',None)
    if tokens(serialize_context(question,packet))>policy.max_context_tokens:raise AgentError('expert_context_limit')
    return packet

async def bounded_stream(source,policy):
    count=0
    try:
        async with asyncio.timeout(policy.job_timeout_seconds):
            async for delta in source:
                count+=len(delta)
                if count>policy.max_result_characters:raise AgentError('expert_result_limit')
                yield delta
    finally:await source.aclose()

class HardwareLegacy:
    def __init__(self,root):self.root=Path(root)
    def budget(self):return ExpertBudget(self.root)
    def allowed(self,client):
        if not (self.root/'policy.json').exists():return False
        try:b=self.budget();p=b.policy()
        except (OSError,ValueError,PermissionError):return False
        return bool(b.active(p) and not p.owner_full_test and p.allowed_client_id==client
            and p.allowed_profiles==['SOL_HIGH'] and p.max_sessions in (1,2)
            and p.expires_at is not None and p.job_timeout_seconds<=90
            and p.max_context_tokens<=3000 and p.max_result_characters<=6000
            and b.status()['sessions_remaining']>0)
    def reserve(self,client,ident):
        if not self.allowed(client):raise PermissionError('hardware_a_allowance_required')
        return self.budget().reserve_session(ident,True,client)
