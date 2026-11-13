"""One RAM-only conversation over the existing Live and legacy pipelines.

Mode selection is not identity or permission. A mode never grants private memory.
"""
import re,time
from dataclasses import dataclass,field
from uuid import uuid4

IDLE_SECONDS=10

def mode_intent(text):
    # Only a complete direct speech act: quoted/narrated text never selects a mode.
    value=' '.join(re.sub(r'[,.!?:;—–-]+',' ',text.casefold().replace('ё','е')).split())
    value=re.sub(r'^(?:гобот|го бот)\s+','',value)
    value=re.sub(r'^(?:ну |хорошо |ладно )','',value)
    value=re.sub(r'^пожалуйста | пожалуйста$','',value)
    value=re.sub(r'^(?:ты можешь|можешь(?: ли)?(?: ты)?|можно ли)\s+','',value)
    value=re.sub(r' (?:давай|да)$','',value)
    if value in {'стоп','stop','закончи разговор','закончим разговор','заверши разговор','давай закончим','спасибо закончили'}:return 'end'
    verb=r'(?:включи|включить|переключи(?:сь| меня| нас)?|переведи(?: меня| нас)?|перевести(?: меня| нас)?|перейди|перейдем|включим|давай (?:перейдем|включим|переключимся|переключи(?: меня)?|перейди))'
    prefix=r'(?:'+verb+r'(?: в| на)? )?'
    if re.fullmatch(prefix+r'(?:экспертный|вдумчивый) (?:режим|вариант)(?: [aа])?',value) or value in {'давай разберем подробно','разберем подробно'}:return 'legacy'
    if re.fullmatch(verb+r'(?: в| на)? режим [aа]',value):return 'legacy'
    if re.fullmatch(prefix+r'(?:обычный режим|быстрый режим|живой разговор)(?: [cс])?',value) or value in {'вернись к обычному разговору','вернись в обычный режим'}:return 'live'
    return None

def expert_mode_request(text):
    """Owner-selected keyword trigger, applied only to an actual user transcript.
    Financial/identity checks still happen in NativeHandoff, never from tool text.
    """
    match=re.search(r'\bэкспертн(?:ый|ого|ом|ому|ым)\s+режим(?:а|е|у|ом)?\b',text,re.I)
    if match:
        before=text[:match.start()]
        if re.search(r'\b(?:не\s+(?:включай|включать|переключай|переводи)|отмени)\b',before,re.I):return None
        if re.match(r'^\s*(?:сравни|объясни|расскажи|разбери|проверь|как|почему|что|чем|сколько|како[йея])\b',before,re.I):return text.strip()[:8000]
        question=text[match.end():].lstrip(' \t\r\n:;—.,?!«»"').strip()
        if re.fullmatch(r'(?:[aа]|пожалуйста|сейчас|давай|включи|включить|переведи|переключи|меня|мне)(?:\s+(?:пожалуйста|сейчас|давай|меня|мне))*',question,re.I):return ''
        return question[:8000]
    if mode_intent(text)=='legacy':return ''
    # Punctuation is supplied by ASR, not spoken by the user. Accept its stable
    # separators and allow a wake-name comma before the complete mode command.
    for separator in re.finditer(r'[:;—.,?!]\s*',text):
        question=text[separator.end():].strip()
        if question and mode_intent(text[:separator.start()])=='legacy':return question[:8000]
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
    transition_messages:list=field(default_factory=list)
    pending_question:str=''
    handoff_turn_id:str|None=None
    legacy_profile:str|None=None
    legacy_policy:object=None

    def public(self):
        return {'mode_conversation_id':self.id,'mode':self.mode if self.active else 'live',
            'active':self.active,'reason':self.reason,'idle_seconds':IDLE_SECONDS,
            'provider_closed':self.provider_closed,'private_access':False,'remember':False,
            'wake_word_ready':False}

class ConversationModes:
    def __init__(self,brain,owner_testing):self.brain=brain;self.owner_testing=owner_testing;self.items={};self.hardware_legacy=None
    def legacy_allowed(self,binding):
        return self.owner_testing.authorized(binding) or bool(self.hardware_legacy and self.hardware_legacy.allowed(binding))
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
        if not flow.active or not (self.owner_testing.voice_authorized(flow.binding) or self.legacy_allowed(flow.binding)):raise PermissionError('conversation_mode_inactive')
    def from_native(self,offer,messages,question,operation_id):
        """Reuse the same A coordinator. Caller must first confirm native hangup.

        Guest RAM only, exact financial binding; never impersonate the phone.
        """
        binding=offer.owner_test_binding or offer.client_id
        if not self.legacy_allowed(binding):raise PermissionError('hardware_cli_not_authorized')
        if offer.personalization_mode!='guest' or offer.remember or offer.profile_epoch or offer.confirmed_profile_epoch:
            raise PermissionError('native_handoff_guest_scope_required')
        for flow in self.items.values():
            if flow.active and (flow.owner==offer.device_id or flow.client==offer.client_id):raise PermissionError('conversation_mode_already_active')
        if len(self.items)>=256:raise PermissionError('conversation_mode_capacity')
        flow=ModeConversation(offer.device_id,offer.client_id,None,binding,mode='legacy')
        flow.transition_messages=[{'role':m['role'],'content':m['content'][:1600]} for m in messages[-6:]
            if m.get('role') in {'user','assistant'} and isinstance(m.get('content'),str)]
        flow.pending_question=question[:8000];flow.handoff_turn_id=operation_id
        self.items[flow.id]=flow
        return flow
    def select(self,flow,target):
        self.authorized(flow)
        if target not in {'live','legacy'}:raise ValueError('invalid_conversation_mode')
        if target=='legacy' and not self.legacy_allowed(flow.binding):
            raise PermissionError('hardware_cli_not_authorized')
        flow.mode=target;flow.last_activity=time.monotonic()
        flow.input_active=False;flow.playback_active=False
        return flow.public()
    def end(self,flow,reason='conversation_ended'):
        flow.active=False;flow.mode='live';flow.reason=reason;flow.last_activity=time.monotonic()
        flow.transition_messages.clear();flow.pending_question=''
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
        if not self.legacy_allowed(flow.binding):raise PermissionError('hardware_cli_not_authorized')
        if flow.mode!='legacy' or not flow.provider_closed:raise PermissionError('conversation_mode_not_ready')
        if flow.legacy_turn:raise PermissionError('conversation_mode_busy')
        if flow.pending_question:
            if req.turn_id!=flow.handoff_turn_id or req.text!=flow.pending_question:raise PermissionError('handoff_question_required_first')
        if not self.owner_testing.authorized(flow.binding):
            flow.legacy_policy=self.hardware_legacy.reserve(flow.binding,req.turn_id)
            flow.legacy_profile='SOL_HIGH'
        flow.legacy_turn=req.turn_id;flow.last_activity=time.monotonic()
        # Guest scope is generated by Brain, not provided by the browser or a PIN cookie.
        return flow,req.model_copy(update={'device_id':flow.scope,'conversation_id':flow.conversation,
            'remember':False,'mode':'codex' if flow.legacy_profile else 'auto',
            'provider':'codex' if flow.legacy_profile else 'auto','model_id':'gpt-6.1-sol' if flow.legacy_profile else None})
