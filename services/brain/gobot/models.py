from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict
from .device_contract import ScreenPreferences

ID = r"^[A-Za-z0-9_.:-]{1,100}$"
ExecutorModel=Literal['gemini-3.8-flash-low','gemini-3.8-flash-medium','gemini-4-argon-medium','gpt-6.1-sol','gpt-6-astra']
def uid(): return str(uuid4())
class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=8000)
    device_id: str = Field(default="local-test", pattern=ID)
    conversation_id: str = Field(default_factory=uid, pattern=ID)
    turn_id: str = Field(default_factory=uid, pattern=ID)
    correlation_id: str = Field(default_factory=uid, pattern=ID)
    route: Literal["auto", "fast", "agent"] = "auto"
    provider: Literal["auto", "mock", "codex", "cursor", "gemini", "openai", "antigravity", "google"] = "auto"
    mode: Literal["auto", "fast", "reasoning", "codex", "gemini", "google", "antigravity", "mock"] | None = None
    usage_consent: bool = False
    model_id: ExecutorModel | None = None
    paid_chat_consent:bool=False
    expensive_fallback_approved:bool=False
    request_id:str|None=Field(default=None,pattern=ID)
    utterance_id:str|None=Field(default=None,pattern=ID)
    event_id:str|None=Field(default=None,pattern=ID)
    remember:bool=True
    new_topic:bool=False
    context_detail:Literal['standard','detailed']='standard'
    client_kind:Literal['panel','device']='panel'
    client_id:str|None=Field(default=None,pattern=ID)
    trace_id:str|None=Field(default=None,pattern=ID)
    profile_epoch:str|None=Field(default=None,pattern=ID)
    screen_preferences:ScreenPreferences|None=None

class VoiceRequest(ChatRequest):
    speaker_job_id: str | None = Field(default=None, pattern=r'^[a-f0-9-]{36}$')
    speak: bool = True
    tts_provider: Literal["openai", "denis"] = "openai"
    tts_voice: str = Field(default="marin", max_length=30)
    paid_tts_consent: bool = False
    tts_character_limit: int | None = Field(default=None,ge=0,le=32000,strict=True)

class Event(BaseModel):
    type: Literal["text_delta","sentence_ready","tool_status","widget_command","visual_response","screen_scene","final","error","cancelled"]
    correlation_id: str
    device_id: str
    conversation_id: str
    turn_id: str
    data: dict = Field(default_factory=dict)

def event(req, kind, **data):
    return Event(type=kind, **{k:getattr(req,k) for k in ["correlation_id","device_id","conversation_id","turn_id"]}, data=data)
