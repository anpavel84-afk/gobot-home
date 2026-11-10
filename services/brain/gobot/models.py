from typing import Literal
from uuid import uuid4
from pydantic import BaseModel, Field, ConfigDict

ID = r"^[A-Za-z0-9_.:-]{1,100}$"
def uid(): return str(uuid4())
class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=8000)
    device_id: str = Field(default="local-test", pattern=ID)
    conversation_id: str = Field(default_factory=uid, pattern=ID)
    turn_id: str = Field(default_factory=uid, pattern=ID)
    correlation_id: str = Field(default_factory=uid, pattern=ID)
    route: Literal["auto", "fast", "agent"] = "auto"
    provider: Literal["auto", "mock", "codex", "cursor", "gemini", "openai"] = "auto"

class Event(BaseModel):
    type: Literal["text_delta","sentence_ready","tool_status","widget_command","final","error","cancelled"]
    correlation_id: str
    device_id: str
    conversation_id: str
    turn_id: str
    data: dict = Field(default_factory=dict)

def event(req, kind, **data):
    return Event(type=kind, **{k:getattr(req,k) for k in ["correlation_id","device_id","conversation_id","turn_id"]}, data=data)
