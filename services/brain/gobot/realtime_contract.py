"""Native Realtime contracts. No GPT-Live events and no legacy speech pipeline."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field,model_validator,field_validator
from .models import ID
from .expert_profiles import ExpertProfileName

MODEL = 'gpt-realtime-2.1-mini'
VOICES = ('marin','cedar','alloy','ash','ballad','coral','echo','sage','shimmer','verse')

class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid')

class RealtimeOffer(Strict):
    session_id: str = Field(pattern=ID)
    conversation_id: str = Field(pattern=ID)
    sdp: str = Field(min_length=30,max_length=65536)
    consent: bool = False
    expert_quota_consent: bool = False
    requested_expert_profile:ExpertProfileName|None=None
    remember: bool = True
    speak: bool = True
    # These are injected by the authenticated gateway, never accepted from the browser.
    device_id: str = Field(pattern=ID)
    client_id: str = Field(pattern=ID)
    profile_epoch: str|None = Field(default=None,pattern=ID)
    confirmed_profile_epoch: str|None = Field(default=None,pattern=ID)
    personalization_mode: Literal['guest','confirmed_profile'] = 'guest'
    speaker_consent: bool = False
    requested_voice: Literal['marin','cedar','alloy','ash','ballad','coral','echo','sage','shimmer','verse']|None=None
    client_kind: Literal['panel','device'] = 'panel'

class RealtimeCommand(Strict):
    command_id: str = Field(pattern=ID)
    action: Literal['text','ptt_start','ptt_end','ptt_cancel','followup','interrupt','playback_started','playback_stopped','visual_presented','visual_failed','close']
    frame_id: str|None=Field(default=None,pattern=ID)
    turn_id: str|None=Field(default=None,pattern=ID)
    text: str|None = Field(default=None,min_length=1,max_length=8000)
    response_id: str|None = Field(default=None,pattern=ID)
    close_reason: Literal['user_stop','page_hidden','network_offline','webrtc_failed','webrtc_disconnected','audio_suspended','audio_play_denied','microphone_ended','events_disconnected','provider_error','server_closed','setup_failed','capture_cancelled','settings_changed']|None=None

class RealtimePolicy(Strict):
    """Local owner-controlled admission file, not writable by model tools."""
    enabled: bool = False
    accepted_as_default: bool = False
    authorization: str = Field(default='',max_length=200)
    audience: Literal['owner_interactive','developer_trial'] = 'developer_trial'
    expires_at: float|None = Field(default=0,ge=0,allow_inf_nan=False)
    max_sessions: int|None = Field(default=0,ge=0,le=100)
    max_responses_per_session: int|None = Field(default=8,ge=1,le=50)
    max_session_seconds: int|None = Field(default=180,ge=30,le=3600)
    max_output_tokens: int = Field(default=384,ge=64,le=4096)
    observed_token_limit: int|None = Field(default=12000,ge=1000,le=1000000)
    input_transcription: bool = False
    transcription_model: Literal['gpt-transcribe'] = 'gpt-transcribe'
    voice: Literal['marin','cedar','alloy','ash','ballad','coral','echo','sage','shimmer','verse'] = 'marin'
    allowed_client_id: str|None = Field(default=None,pattern=ID)
    expert_jobs_allowed: bool = False
    image_generation_allowed: bool = False
    image_generation_daily_limit:int=Field(default=0,ge=0,le=20)
    device_settings_allowed: bool = False
    owner_assistant_preferences:dict|None=None

    @field_validator('owner_assistant_preferences')
    @classmethod
    def validated_owner_preferences(cls,value):
        if value is None:return None
        from .family_preferences import AssistantPreferences
        return AssistantPreferences.model_validate(value).model_dump()

    @model_validator(mode='after')
    def unlimited_requires_owner_interactive(self):
        if self.device_settings_allowed and (self.audience!='owner_interactive' or not self.allowed_client_id):
            raise ValueError('Device settings capability requires an explicitly bound owner client')
        if self.owner_assistant_preferences is not None and (self.audience!='owner_interactive' or not self.allowed_client_id):
            raise ValueError('Owner conversation style requires an explicitly bound owner client')
        if any(getattr(self,key) is None for key in ('expires_at','max_sessions','max_responses_per_session','max_session_seconds','observed_token_limit')):
            if self.audience!='owner_interactive' or not self.allowed_client_id:
                raise ValueError('Uncapped use requires an explicitly authorized owner client')
        return self

def audio_only_sdp(sdp):
    """Enforce the boundary on both offer and answer, not only browser JS."""
    if not isinstance(sdp,str) or len(sdp.encode())>65536 or '\x00' in sdp or not sdp.startswith('v=0'):
        raise ValueError('invalid_sdp')
    media = [line.strip().split() for line in re.split(r'\r?\n',sdp) if line.startswith('m=')]
    if len(media)!=1 or len(media[0])<4 or media[0][0]!='m=audio' or not media[0][1].isdigit() or int(media[0][1])==0:
        raise ValueError('audio_only_sdp_required')
    if any('sctp' in line.lower() for line in sdp.splitlines()):
        raise ValueError('data_channel_denied')
    return sdp

def session_config(policy, instructions, tools, *, speak=True):
    input_config={'turn_detection':None,'noise_reduction':{'type':'near_field'}}
    if policy.input_transcription:
        input_config['transcription']={'model':policy.transcription_model,'language':'ru'}
    return {'type':'realtime','model':MODEL,'instructions':instructions,
            'output_modalities':['audio'] if speak else ['text'],
            'audio':{'input':input_config,'output':{'voice':policy.voice}},
            'tools':tools,'tool_choice':'auto','parallel_tool_calls':False,
            'max_output_tokens':policy.max_output_tokens,'tracing':None,
            'truncation':{'type':'retention_ratio','retention_ratio':.8,'token_limits':{'post_instructions':6000}}}

def input_settings_applied(session,expected):
    """session.updated contains effective defaults, not just our update fragment."""
    audio=session.get('audio',{}).get('input',{})
    if 'turn_detection' not in audio:return False
    actual=audio['turn_detection']
    if expected is None:return actual is None
    if not isinstance(actual,dict):return False
    # Requested safety controls must match; harmless extra defaults are OK.
    # A provider idle prompt must stay disabled during our silent followup window.
    return actual.get('idle_timeout_ms') is None and all(
        actual.get(k)==v if k=='idle_timeout_ms' and v is None else k in actual and actual[k]==v
        for k,v in expected.items())


def settings_applied(actual, expected):
    """A tracing-only session.updated is not a configuration acknowledgement."""
    return (actual.get('model')==MODEL and actual.get('instructions')==expected['instructions']
            and actual.get('output_modalities')==expected['output_modalities']
            and actual.get('audio',{}).get('output',{}).get('voice')==expected['audio']['output']['voice']
            and actual.get('audio',{}).get('input',{}).get('turn_detection') is None
            and actual.get('max_output_tokens')==expected['max_output_tokens']
            and actual.get('truncation')==expected['truncation']
            and actual.get('tools')==expected['tools'])
