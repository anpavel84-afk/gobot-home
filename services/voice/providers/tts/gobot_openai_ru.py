import os,asyncio
from pathlib import Path
import httpx
from core.providers.tts.base import TTSProviderBase
class TTSProvider(TTSProviderBase):
    def __init__(self,config,delete_audio_file):super().__init__(config,delete_audio_file);self.config=config
    async def text_to_speak(self,text,output_file):
        if os.getenv('GOBOT_ALLOW_PAID')!='1':raise PermissionError('Paid TTS disabled')
        key=self.config.get('api_key');url=self.config.get('api_url','https://api.openai.com/v1/audio/speech')
        if not key or not url.startswith('https://'):raise ValueError('TTS configuration missing')
        async with httpx.AsyncClient(timeout=20,trust_env=False) as client:
            response=await client.post(url,headers={'Authorization':'Bearer '+key},json={'model':self.config.get('model','tts-1'),'voice':self.config.get('voice','alloy'),'input':text,'response_format':'wav'})
            if response.status_code!=200:raise RuntimeError('TTS provider rejected request')
            data=response.content
        if output_file:await asyncio.to_thread(Path(output_file).write_bytes,data)
        else:return data
