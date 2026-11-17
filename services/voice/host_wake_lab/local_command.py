"""Local deterministic clock/timer smoke. No Brain process, service, or paid API.

The response is specifically a LOCAL COMMAND, not an LLM answer.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
import re
import threading

# Live test is finite; refuse timers that cannot finish within the bounded demo.
MAX_DEMO_TIMER_SECONDS = 180


@dataclass(frozen=True)
class LocalIntent:
    kind: str
    seconds: int = 0


def parse_local_intent(text: str) -> LocalIntent | None:
    cleaned = " ".join(re.findall(r"[а-яё0-9]+", text.casefold()))
    if re.search(r"\b(который час|сколько времени|время сейчас|скажи время)\b", cleaned):
        return LocalIntent("time")
    m = re.search(r"\bтаймер(?: на)? (\d{1,3}) (секунд\w*|минут\w*)\b", cleaned)
    if m:
        value = int(m.group(1))
        seconds = value * (60 if m.group(2).startswith("минут") else 1)
        if 1 <= seconds <= MAX_DEMO_TIMER_SECONDS:
            return LocalIntent("timer", seconds)
    return None


def schedule_local_timer(seconds: int, on_alarm, *, timer_factory=threading.Timer):
    """One bounded timer, never a resident service; caller joins or cancels."""
    if type(seconds) is not int or not 1 <= seconds <= MAX_DEMO_TIMER_SECONDS:
        raise ValueError("local_demo_timer_out_of_bounds")
    timer = timer_factory(seconds, on_alarm)
    timer.daemon = True
    timer.start()
    return timer


def time_answer(now=None) -> str:
    now = now or datetime.now()
    return f"Сейчас {now.hour} часов {now.minute} минут."


def timer_answer(seconds: int) -> str:
    return f"Таймер на {seconds} секунд запущен локально."


class OfflineSpeaker:
    """Optional existing read-only Russian Piper model + local PC speakers."""
    def __init__(self, model_path):
        from piper import PiperVoice
        self.voice = PiperVoice.load(model_path)

    def speak(self, sentence: str) -> None:
        import numpy as np
        import sounddevice as sd
        chunks = list(self.voice.synthesize(sentence))
        if not chunks:
            raise RuntimeError("local_piper_tts_empty")
        rate = chunks[0].sample_rate
        audio = b"".join(c.audio_int16_bytes for c in chunks)
        samples = np.frombuffer(audio, dtype="<i2")
        sd.play(samples, samplerate=rate, blocking=True)


def beep_ack():
    import winsound
    winsound.Beep(880, 120)
