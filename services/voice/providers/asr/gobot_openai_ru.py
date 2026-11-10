import asyncio,io,os,wave
from pathlib import Path
import httpx
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType
class ASRProvider(ASRProviderBase):
    def __init__(self,config,delete_audio_file):
        super().__init__();self.config=config;self.interface_type=InterfaceType.NON_STREAM;self.output_dir=config.get('output_dir','tmp');self.delete_audio_file=delete_audio_file;Path(self.output_dir).mkdir(exist_ok=True)
    async def speech_to_text(self,opus_data,session_id,artifacts=None):
        if os.getenv('GOBOT_ALLOW_PAID')!='1':raise PermissionError('Paid ASR disabled')
        if artifacts is None:return '',None
        key=self.config.get('api_key');url=self.config.get('base_url','https://api.openai.com/v1/audio/transcriptions')
        if not key or not url.startswith('https://'):raise ValueError('ASR configuration missing')
        # artifacts are upstream-decoded/resampled PCM, 16 kHz mono s16le.
        out=io.BytesIO()
        with wave.open(out,'wb') as wav:wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(artifacts.pcm_bytes)
        async with httpx.AsyncClient(timeout=20,trust_env=False) as client:
            response=await client.post(url,headers={'Authorization':'Bearer '+key},data={'model':self.config.get('model_name','whisper-1'),'language':'ru'},files={'file':('segment.wav',out.getvalue(),'audio/wav')})
            if response.status_code!=200:raise RuntimeError('ASR provider rejected request')
            return response.json().get('text',''),None
