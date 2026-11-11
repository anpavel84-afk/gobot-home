"""GPT-Live protocol, separate from Realtime. Only documented API model IDs."""
import re
from pydantic import BaseModel,ConfigDict,Field
from typing import Literal
from .models import ID
from .realtime_contract import VOICES

LIVE_MODEL='gpt-live-1'
class LiveOffer(BaseModel):
    model_config=ConfigDict(extra='forbid')
    session_id:str=Field(pattern=ID)
    conversation_id:str=Field(pattern=ID)
    sdp:str=Field(min_length=30,max_length=65536)
    consent:bool=False
    device_id:str=Field(pattern=ID)
    client_id:str=Field(pattern=ID)
    profile_epoch:str|None=Field(default=None,pattern=ID)
    confirmed_profile_epoch:str|None=Field(default=None,pattern=ID)
    owner_test_binding:str|None=Field(default=None,pattern=ID)
    requested_model:Literal['gpt-live-1']=LIVE_MODEL
    requested_voice:Literal['marin','cedar','alloy','ash','ballad','coral','echo','sage','shimmer','verse']='marin'
    personalization_mode:Literal['guest','confirmed_profile']='guest'
    input_mode:Literal['continuous','hold']='continuous'
    remember:bool=False
    speaker_consent:bool=False
    expert_quota_consent:bool=False
    client_kind:Literal['panel','device']='device'
    developer_acceptance:bool=False

class LiveCommand(BaseModel):
    model_config=ConfigDict(extra='forbid')
    command_id:str=Field(pattern=ID)
    action:Literal['mute','unmute','stop_speech','end','text','activity','visual_presented','visual_failed','cancel_task']
    text:str|None=Field(default=None,max_length=8000)
    job_id:str|None=Field(default=None,pattern=ID)
    turn_id:str|None=Field(default=None,pattern=ID)
    frame_id:str|None=Field(default=None,pattern=ID)
    input_active:bool=False
    playback_active:bool=False
    reason:Literal['user_stop','page_hidden','network_offline','webrtc_failed','microphone_ended','profile_changed','settings_changed','events_disconnected']='user_stop'

def live_sdp(sdp):
    """Live's one audio + optional SCTP section; does not relax Realtime validation."""
    if not isinstance(sdp,str) or len(sdp.encode())>65536 or '\x00' in sdp or not sdp.startswith('v=0'):raise ValueError('invalid_live_sdp')
    sections=[line.strip().split() for line in re.split(r'\r?\n',sdp) if line.startswith('m=')]
    audio=[s for s in sections if len(s)>=4 and s[0]=='m=audio' and s[1].isdigit() and int(s[1])>0]
    data=[s for s in sections if len(s)>=4 and s[0]=='m=application' and s[1].isdigit() and int(s[1])>0 and s[2]=='UDP/DTLS/SCTP' and s[3]=='webrtc-datachannel']
    if len(audio)!=1 or len(data)>1 or len(audio)+len(data)!=len(sections):raise ValueError('live_audio_and_bounded_data_only')
    return sdp

def live_config(voice,instructions,history):
    if voice not in VOICES:raise ValueError('live_voice_not_allowed')
    return {'model':LIVE_MODEL,'audio':{'output':{'voice':voice}},'delegation':{'type':'client'},
        'store':False,'instructions':instructions,'input':history,
        'client':{'data_channel':{'allowed_client_events':[],'allowed_server_events':[]}}}

def live_applied(actual,expected):
    return (actual.get('model')==expected['model'] and actual.get('delegation',{}).get('type')=='client'
        and actual.get('audio',{}).get('output',{}).get('voice')==expected['audio']['output']['voice']
        and actual.get('store') is False
        and actual.get('client',{}).get('data_channel',{}).get('allowed_client_events')==[]
        and actual.get('client',{}).get('data_channel',{}).get('allowed_server_events')==[]
        and actual.get('instructions')==expected['instructions'])
