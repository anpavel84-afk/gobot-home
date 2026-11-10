"""Native Realtime contracts. No GPT-Live events and no legacy speech pipeline."""
import re
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .models import ID

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
    action: Literal['text','ptt_start','ptt_end','ptt_cancel','followup','interrupt','playback_started','playback_stopped','close']
    text: str|None = Field(default=None,min_length=1,max_length=8000)
    response_id: str|None = Field(default=None,pattern=ID)

class RealtimePolicy(Strict):
    """Local owner-controlled admission file, not writable by model tools."""
    enabled: bool = False
    accepted_as_default: bool = False
    authorization: str = Field(default='',max_length=200)
    audience: Literal['owner_interactive','developer_trial'] = 'developer_trial'
    expires_at: float = Field(default=0,ge=0,allow_inf_nan=False)
    max_sessions: int = Field(default=0,ge=0,le=100)
    max_responses_per_session: int = Field(default=8,ge=1,le=50)
    max_session_seconds: int = Field(default=180,ge=30,le=900)
    max_output_tokens: int = Field(default=384,ge=64,le=1024)
    observed_token_limit: int = Field(default=12000,ge=1000,le=1000000)
    input_transcription: bool = False
    transcription_model: Literal['gpt-transcribe'] = 'gpt-transcribe'
    voice: Literal['marin','cedar','alloy','ash','ballad','coral','echo','sage','shimmer','verse'] = 'marin'
    allowed_client_id: str|None = Field(default=None,pattern=ID)
    expert_jobs_allowed: bool = False
    image_generation_allowed: bool = False

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

def settings_applied(actual, expected):
    """A tracing-only session.updated is not a configuration acknowledgement."""
    return (actual.get('model')==MODEL and actual.get('instructions')==expected['instructions']
            and actual.get('output_modalities')==expected['output_modalities']
            and actual.get('audio',{}).get('output',{}).get('voice')==expected['audio']['output']['voice']
            and actual.get('audio',{}).get('input',{}).get('turn_detection') is None
            and actual.get('max_output_tokens')==expected['max_output_tokens']
            and actual.get('truncation')==expected['truncation']
            and actual.get('tools')==expected['tools'])
