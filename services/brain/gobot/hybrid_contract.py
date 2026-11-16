"""vNext proposals are data; only the server constructs approved decisions."""
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from .models import ID

class Strict(BaseModel):model_config=ConfigDict(extra='forbid')
class SkillManifest(Strict):
    skill_id:str
    version:int=1
    category:str
    implementation_status:Literal['implemented','experimental','unavailable']
    templates:list[str]=Field(default_factory=list)
    parameter_schema:dict=Field(default_factory=dict)
    allowed_context:list[str]=Field(default_factory=list)
    side_effect_class:str='read'
    permissions:list[str]=Field(default_factory=lambda:['owner_preview'])
    requires_confirmation:bool=False
    provider_dependencies:list[str]=Field(default_factory=list)
    cost_components:list[str]=Field(default_factory=lambda:['tool_local','optional_stt','optional_tts'])
    response_template:str='verified_result'
    tests:list[str]=Field(default_factory=lambda:['test_hybrid'])

class IntentCandidate(Strict):
    matched_by:str='quick_intents'
    skill_id:str
    spans:list[tuple[int,int]]=Field(default_factory=list)
    proposed_args:dict=Field(default_factory=dict)
    missing_slots:list[str]=Field(default_factory=list)
    ambiguity:list[str]=Field(default_factory=list)
    provenance:str='user_text'

class AnswerEnvelope(Strict):
    canonical_facts:dict=Field(default_factory=dict)
    speech_text:str=''
    display_data:dict=Field(default_factory=dict)
    source:str='GoBot Brain'
    valid_until:float|None=None
    voice:str='marin'
    language:str='ru'
    template_id:str='verified_result'
    clip_key:str|None=None
    provenance:str='server_tool'
    presentation_epoch:int=0

class ActionResult(Strict):
    operation_id:str
    action_id:str
    status:Literal['success','failed','unknown','not_run']
    verified_data:dict=Field(default_factory=dict)
    evidence:dict=Field(default_factory=dict)
    state_version:int=1
    timestamp:float
    error_code:str|None=None

RouteType=Literal['EXECUTE_TOOL','MEDIA_CONTROL','START_STORYTELLER','OPEN_CONVERSATION_B','OPEN_CONVERSATION_C','DELEGATE_EXPERT_A','CLARIFY_SLOT','ABSTAIN_UNAVAILABLE','NO_ACTION']
class RouteDecision(Strict):
    schema_version:int=1
    decision_id:str
    operation_id:str
    turn_id:str
    route_type:RouteType
    candidates:list[IntentCandidate]=Field(default_factory=list)
    approved:bool=False
    reason:str|None=None
    results:list[ActionResult]=Field(default_factory=list)
    answer:AnswerEnvelope=Field(default_factory=AnswerEnvelope)
    handover:dict|None=None
    replay:bool=False
    timings_ms:dict=Field(default_factory=dict)

class PreviewInput(Strict):
    conversation_id:str=Field(pattern=ID)
    operation_id:str=Field(pattern=ID)
    text:str=Field(min_length=1,max_length=2000)
    mode:Literal['hybrid','b','c']='hybrid'
    truncated:bool=False

class PlaybackAck(Strict):
    client_id:str=Field(pattern=ID)
    stream_id:str=Field(pattern=ID)
    segment_id:str=Field(pattern=ID)
    epoch:int=Field(ge=1)
    event:Literal['started','progress','drained','interrupted']
    position_seconds:float=Field(ge=0,le=600,allow_inf_nan=False)
    precision:Literal['audio_clock','coarse_segment']='audio_clock'
    clock_domain:Literal['audio_context','media_element']='audio_context'
