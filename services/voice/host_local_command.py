"""Strict, free, TOUCH-ONLY offline Russian time response for the HOST test listener.

This module is NOT a wake detector, general chatbot, model answer simulator,
paid inference, or a production Brain route. No network, file recording, logs
of spoken input, transcripts or keys. Uses preexisting private local models.
Returns a bounded 24kHz Opus phrase only for an explicitly recognized command.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo

import numpy as np

from host_local_tts import offline_russian_packets

RATE=16000
MAX_AUDIO_SECONDS=15
TZ=ZoneInfo("America/Sao_Paulo")


def classify_command(text:str)->str|None:
    if not isinstance(text,str) or len(text)>180:
        return None
    normalized=" ".join(re.findall(r"[а-яё0-9]+",text.lower()))
    if not normalized:
        return None
    words=set(normalized.split())
    has_time=(("времени" in words or "время" in words or "времечко" in words)
              and bool(words & {"сколько","сейчас","которое","скажи","подскажи"}))
    which_hour=("час" in words and bool(words & {"который","сколько","сейчас"}))
    return "local_time" if has_time or which_hour else None


def time_reply(now:datetime|None=None)->str:
    moment=now if now is not None else datetime.now(TZ)
    return f"Сейчас {moment.hour}:{moment.minute:02d}."


class OfflineTimeResponder:
    """Call from a dedicated worker after a physical touch and input finish."""
    def __init__(self,asr_path:Path,voice_path:Path):
        self.asr_path=Path(asr_path).resolve()
        self.voice_path=Path(voice_path).resolve()
        if not (self.asr_path/"model.bin").is_file():
            raise ValueError("local_whisper_model_not_present")
        if not self.voice_path.is_file():
            raise ValueError("local_russian_voice_not_present")
        self._model=None

    def __call__(self,pcm:bytes)->tuple[bytes,...]|None:
        if not isinstance(pcm,(bytes,bytearray)) or len(pcm)%2 or not (
                RATE//2*2 <= len(pcm) <= RATE*MAX_AUDIO_SECONDS*2):
            return None
        mono=np.frombuffer(pcm,dtype="<i2").astype(np.float32)/32768
        if len(mono)<RATE//2 or float(np.sqrt(np.mean(mono*mono)))<.006:
            return None
        if self._model is None:
            from faster_whisper import WhisperModel
            self._model=WhisperModel(str(self.asr_path),device="cpu",
                                     compute_type="int8",local_files_only=True,
                                     cpu_threads=4,num_workers=1)
        segments,_=self._model.transcribe(mono,language="ru",beam_size=1,
                                          temperature=0,condition_on_previous_text=False,
                                          vad_filter=False,word_timestamps=False)
        # Transcript used only in RAM for strict classification and discarded.
        transcript=" ".join(x.text for x in segments)
        if classify_command(transcript)!="local_time":
            return None
        return offline_russian_packets(self.voice_path,text=time_reply())
