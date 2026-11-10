import os, json
from pathlib import Path
from dataclasses import dataclass
from urllib.parse import urlparse

@dataclass
class Settings:
    db: str = "data/gobot.sqlite"
    api_token: str = ""
    bridge_secret: str = ""
    bridge_url: str = "http://127.0.0.1:18782"
    timeout: float = 20
    fast_provider: str = "mock"
    api_base: str = "https://api.openai.com/v1"
    api_model: str = ""
    api_key: str = ""
    allow_paid: bool = False
    asr: str = "mock"
    tts: str = "mock"
    vad: str = "mock"
    def validate(self):
        if self.fast_provider not in {"mock","openai"}: raise ValueError("Unsupported fast provider")
        if self.asr not in {"mock","openai","faster_whisper","sherpa_onnx"}: raise ValueError("Unsupported ASR")
        if self.tts not in {"mock","openai","piper"}: raise ValueError("Unsupported TTS")
        if self.vad not in {"mock","silero"}: raise ValueError("Unsupported VAD")
        bridge=urlparse(self.bridge_url)
        if bridge.scheme!="http" or bridge.hostname!="127.0.0.1" or bridge.username or bridge.password or bridge.path or bridge.query or bridge.fragment or not bridge.port: raise ValueError("Bridge must be loopback")
        if len(self.api_token)<32 or len(self.bridge_secret)<32: raise ValueError("Missing local credentials")
        if self.fast_provider=="openai" and self.api_key and not self.api_base.startswith("https://"): raise ValueError("API requires HTTPS")
        return self

def load():
    # Read only this project's .env, with no shell evaluation and no PATH or credential-home overrides.
    allowed={'GOBOT_DB','GOBOT_BRIDGE_URL','GOBOT_FAST_PROVIDER','GOBOT_API_BASE','GOBOT_API_MODEL','GOBOT_API_KEY','GOBOT_ALLOW_PAID','GOBOT_ASR','GOBOT_TTS','GOBOT_VAD'}
    envfile=Path('.env')
    if envfile.exists():
        for line in envfile.read_text(encoding='utf-8').splitlines():
            if '=' not in line or line.lstrip().startswith('#'):continue
            name,value=line.split('=',1)
            if name.strip() in allowed:os.environ.setdefault(name.strip(),value.strip())
    keys=json.loads(Path("run/keys.json").read_text(encoding='utf-8'))
    return Settings(db=os.getenv("GOBOT_DB","data/gobot.sqlite"),api_token=keys["api_token"],bridge_secret=keys["bridge_secret"],bridge_url=os.getenv("GOBOT_BRIDGE_URL","http://127.0.0.1:18782"),fast_provider=os.getenv("GOBOT_FAST_PROVIDER","mock"),api_base=os.getenv("GOBOT_API_BASE","https://api.openai.com/v1"),api_model=os.getenv("GOBOT_API_MODEL",""),api_key=os.getenv("GOBOT_API_KEY",""),allow_paid=os.getenv("GOBOT_ALLOW_PAID")=="1",asr=os.getenv("GOBOT_ASR","mock"),tts=os.getenv("GOBOT_TTS","mock"),vad=os.getenv("GOBOT_VAD","mock")).validate()
