"""One RAM-only conversation over the existing Live and legacy pipelines.

Mode selection is not identity or permission. A mode never grants private memory.
"""
import re,time
from dataclasses import dataclass,field
from uuid import uuid4

IDLE_SECONDS=10

def mode_intent(text):
    value=' '.join(re.sub(r'[,.!?:;—–-]+',' ',text.casefold().replace('ё','е')).split())
    value=re.sub(r'^(?:гобот|го бот)\s+','',value)
    if value in {'стоп','stop','закончи разговор','закончим разговор','заверши разговор','давай закончим','спасибо закончили'}:return 'end'
    prefix=r'(?:(?:включи|включить|переключи(?:сь| меня)?|перейди|давай перейдем)(?: в| на)? )?'
    if re.fullmatch(prefix+r'(?:экспертный|вдумчивый) режим',value) or value in {'давай разберем подробно','разберем подробно'}:return 'legacy'
    if re.fullmatch(prefix+r'(?:обычный режим|быстрый режим|живой разговор)',value) or value in {'вернись к обычному разговору','вернись в обычный режим'}:return 'live'
    return None

@dataclass
class ModeConversation:
    owner:str
    client:str
    epoch:str|None
    binding:str
    id:str=field(default_factory=lambda:str(uuid4()))
    scope:str=field(default_factory=lambda:'voice-guest:'+str(uuid4()))
    conversation:str=field(default_factory=lambda:str(uuid4()))
    mode:str='live'
    active:bool=True
    provider_session:str|None=None
    provider_closed:bool=True
    last_activity:float=field(default_factory=time.monotonic)
    input_active:bool=False
    playback_active:bool=False
    activity_at:float=0
    legacy_turn:str|None=None
    reason:str|None=None
    confirmed_epoch:str|None=None

    def public(self):
        return {'mode_conversation_id':self.id,'mode':self.mode if self.active else 'live',
            'active':self.active,'reason':self.reason,'idle_seconds':IDLE_SECONDS,
            'provider_closed':self.provider_closed,'private_access':False,'remember':False,
            'wake_word_ready':False}

class ConversationModes:
    def __init__(self,brain,owner_testing):self.brain=brain;self.owner_testing=owner_testing;self.items={}
    def owned(self,ident,owner,client,epoch):
        flow=self.items.get(ident)
        if not flow or (flow.owner,flow.client,flow.epoch)!=(owner,client,epoch):raise PermissionError('conversation_mode_not_owned')
        return flow
    def bind(self,offer):
        if offer.mode_conversation_id:
            flow=self.owned(offer.mode_conversation_id,offer.device_id,offer.client_id,offer.profile_epoch)
            if not flow.active or flow.mode!='live' or not flow.provider_closed:raise PermissionError('conversation_mode_not_ready')
        else:
            for flow in self.items.values():
                if flow.active and (flow.owner==offer.device_id or flow.client==offer.client_id):raise PermissionError('conversation_mode_already_active')
            # Bounded RAM; completed conversations are not a durable profile/history database.
            self.items={k:v for k,v in self.items.items() if v.active or time.monotonic()-v.last_activity<3600}
            if len(self.items)>=256:raise PermissionError('conversation_mode_capacity')
            flow=ModeConversation(offer.device_id,offer.client_id,offer.profile_epoch,offer.owner_test_binding or offer.client_id)
            flow.confirmed_epoch=offer.confirmed_profile_epoch
            self.items[flow.id]=flow
        flow.provider_session=offer.session_id;flow.provider_closed=False;flow.last_activity=time.monotonic()
        return flow
    def authorized(self,flow):
        if not flow.active or not self.owner_testing.authorized(flow.binding):raise PermissionError('conversation_mode_inactive')
    def select(self,flow,target):
        self.authorized(flow)
        if target not in {'live','legacy'}:raise ValueError('invalid_conversation_mode')
        flow.mode=target;flow.last_activity=time.monotonic()
        flow.input_active=False;flow.playback_active=False
        return flow.public()
    def end(self,flow,reason='conversation_ended'):
        flow.active=False;flow.mode='live';flow.reason=reason;flow.last_activity=time.monotonic()
        if flow.legacy_turn and flow.legacy_turn in self.brain.running:self.brain.running[flow.legacy_turn].set()
        return flow.public()
    def idle(self,flow,now=None):
        now=time.monotonic() if now is None else now
        # Stale activity cannot hold a paid operation open after a lost client.
        fresh=now-flow.activity_at<2
        return flow.active and not flow.legacy_turn and not (fresh and (flow.input_active or flow.playback_active)) and now-flow.last_activity>=IDLE_SECONDS
    def activity(self,flow,input_active,playback_active):
        self.authorized(flow);flow.activity_at=time.monotonic()
        flow.input_active=input_active;flow.playback_active=playback_active
        if input_active or playback_active:flow.last_activity=flow.activity_at
        if self.idle(flow):self.end(flow,'idle_timeout')
        return flow.public()
    def legacy_request(self,req):
        flow=self.owned(req.mode_conversation_id,req.device_id,req.client_id,req.profile_epoch)
        self.authorized(flow)
        if flow.mode!='legacy' or not flow.provider_closed:raise PermissionError('conversation_mode_not_ready')
        if flow.legacy_turn:raise PermissionError('conversation_mode_busy')
        flow.legacy_turn=req.turn_id;flow.last_activity=time.monotonic()
        # Guest scope is generated by Brain, not provided by the browser or a PIN cookie.
        return flow,req.model_copy(update={'device_id':flow.scope,'conversation_id':flow.conversation,
            'remember':False,'mode':'auto','provider':'auto','model_id':None})
