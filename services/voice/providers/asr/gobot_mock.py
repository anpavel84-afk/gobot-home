from pathlib import Path
from core.providers.asr.base import ASRProviderBase
from core.providers.asr.dto.dto import InterfaceType
class ASRProvider(ASRProviderBase):
    def __init__(self,config,delete_audio_file):
        super().__init__();self.interface_type=InterfaceType.NON_STREAM;self.output_dir=config.get('output_dir','tmp');self.delete_audio_file=delete_audio_file;Path(self.output_dir).mkdir(exist_ok=True)
    async def speech_to_text(self,opus_data,session_id,artifacts=None):
        return ('Поставь таймер на пять минут',None) if artifacts else ('',None)
