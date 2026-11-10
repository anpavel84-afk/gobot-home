"""Identity/access policy over existing Family/SpeakerIdentity, not a profile store.

Native media currently bypasses local SpeakerIdentity. Therefore this candidate
cannot carry personal memory, even with a PIN cookie or a claimed voice match.
"""
from dataclasses import dataclass
from uuid import uuid5,NAMESPACE_URL

@dataclass(frozen=True)
class AccessDecision:
    principal:str
    device_id:str
    confirmed_profile_id:str|None
    profile_epoch:str|None
    speaker_state:str
    effective_scope:str
    context_conversation:str
    private_access:bool=False
    native_identity_verified:bool=False
    child_restrictions:bool=True
    memory_mode:str='guest_ram_only'

class IdentityAccessManager:
    def __init__(self,family,speaker_identity=None):
        self.family=family;self.speaker_identity=speaker_identity

    def native(self,offer,observation=None):
        # Observation is never sufficient authorization. Native PCM bridge is not integrated.
        profile_id=offer.device_id.split(':',1)[1] if offer.device_id.startswith('personal:') else None
        state=(observation or {}).get('state','unknown')
        if state not in {'recognized','unknown','ambiguous','insufficient_audio'}:state='unknown'
        scope='realtime-guest:'+str(uuid5(NAMESPACE_URL,offer.client_id+':'+offer.session_id))
        conversation=str(uuid5(NAMESPACE_URL,offer.conversation_id+':'+scope))
        return AccessDecision(principal=offer.device_id,device_id=offer.client_id,confirmed_profile_id=profile_id,
            profile_epoch=offer.profile_epoch,speaker_state=state,effective_scope=scope,context_conversation=conversation)

    @staticmethod
    def invalidates(previous,current):
        return ((previous.principal,previous.device_id,previous.profile_epoch,previous.effective_scope)
                !=(current.principal,current.device_id,current.profile_epoch,current.effective_scope))

    def status(self):
        return {'family_store':'existing_sqlite','biometric_authorizes_private_access':False,
                'native_speaker_identification':'per_turn_local_pcm_mirror_experimental','native_private_access':False,
                'native_memory_mode':'guest_ram_only','child_restrictions':'conservative_guest_no_adult_grants',
                'real_voice_accuracy_verified':False}
