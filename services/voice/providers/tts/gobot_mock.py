import io,wave,asyncio
from pathlib import Path
from core.providers.tts.base import TTSProviderBase
class TTSProvider(TTSProviderBase):
    def __init__(self,config,delete_audio_file):super().__init__(config,delete_audio_file)
    async def text_to_speak(self,text,output_file):
        # Fixture silence, explicitly NOT Russian synthesized speech.
        out=io.BytesIO()
        with wave.open(out,'wb') as wav:
            wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(24000);wav.writeframes(b'\0'*2880)
        data=out.getvalue()
        if output_file:await asyncio.to_thread(Path(output_file).write_bytes,data)
        else:return data
