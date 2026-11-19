"""Owner-directed natural OpenAI voice cache for deterministic Russian time.

One-off generation of fixed phrases (no user audio uploaded) via the Speech
API, then instant local playback from verified Opus24 cache. The expensive
API call is never on the wake -> answer path. No Piper time fallback.
Not a production service or background paid session. Small explicit batches.
"""
from __future__ import annotations

import base64
from datetime import datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import time

import httpx
import numpy as np

from host_a_paid_budget import HostPaidTrialBudget
from host_local_command import TZ

MODEL = "gpt-4o-mini-tts"
VOICE = "marin"
VOICE_SCHEMA = "host-a-natural-russian-time-opus24-v1"
ENDPOINT = "https://api.openai.com/v1/audio/speech"
MAX_GENERATION_SECONDS = 30
MAX_PACKET_COUNT = 64
INSTRUCTIONS = (
    "Говори на русском живым, тёплым, естественным женским голосом; "
    "быстро, но без спешки, как в обычном разговоре с другом. "
    "Не говори официально и не перечисляй часы и минуты по отдельности. "
    "Произнеси только предоставленную короткую фразу, "
    "без вступлений, комментариев и пауз в начале."
)

ONES = ("ноль", "один", "два", "три", "четыре", "пять", "шесть",
        "семь", "восемь", "девять", "десять", "одиннадцать",
        "двенадцать", "тринадцать", "четырнадцать", "пятнадцать",
        "шестнадцать", "семнадцать", "восемнадцать", "девятнадцать")
TENS = {20: "двадцать", 30: "тридцать", 40: "сорок", 50: "пятьдесят"}


def number_word(n: int) -> str:
    if type(n) is not int or not 0 <= n < 60:
        raise ValueError("time_digit_outside_range")
    if n < 20:
        return ONES[n]
    root, rem = divmod(n, 10)
    return TENS[root * 10] + (" " + ONES[rem] if rem else "")


def spoken_time(hour: int, minute: int) -> str:
    if type(hour) is not int or not 0 <= hour <= 23:
        raise ValueError("invalid_clock_hour")
    if type(minute) is not int or not 0 <= minute <= 59:
        raise ValueError("invalid_clock_minute")
    if hour == 0 and minute == 0:
        return "Сейчас ровно полночь."
    if hour == 12 and minute == 0:
        return "Сейчас ровно полдень."
    if minute == 0:
        return f"Сейчас {number_word(hour)} ровно."
    if minute < 10:
        return f"Сейчас {number_word(hour)} ноль {number_word(minute)}."
    return f"Сейчас {number_word(hour)} {number_word(minute)}."


class NaturalVoiceError(RuntimeError):
    pass


class OpenAITimeVoice:
    def __init__(self, folder: Path, budget: HostPaidTrialBudget, *,
                 key_loader, http_client_factory=httpx.Client, voice=VOICE,
                 clock=None):
        if voice not in ("marin", "cedar"):
            raise ValueError("voice_not_authorized")
        self.folder = Path(folder) / MODEL / voice
        self.budget = budget
        self.key_loader = key_loader
        self.http_client_factory = http_client_factory
        self.voice = voice
        self.clock = clock or (lambda: datetime.now(TZ))

    def _file(self, hour, minute):
        spoken_time(hour, minute)  # validation
        return self.folder / f"{hour:02d}-{minute:02d}.json"

    def load(self, hour, minute) -> tuple[bytes, ...] | None:
        path = self._file(hour, minute)
        if not path.is_file():
            return None
        try:
            info = json.loads(path.read_text(encoding="utf-8"))
            if (info.get("schema") != VOICE_SCHEMA or info.get("voice") != self.voice
                or info.get("model") != MODEL or
                info.get("text") != spoken_time(hour, minute)):
                raise NaturalVoiceError("voice_metadata_mismatch")
            packets = tuple(base64.b64decode(x, validate=True)
                            for x in info["opus24_packets"])
            if not (2 <= len(packets) <= MAX_PACKET_COUNT and
                    all(0 < len(p) <= 4096 for p in packets)):
                raise NaturalVoiceError("invalid_voice_packet_count")
            digest = hashlib.sha256(b"".join(packets)).hexdigest()
            if digest != info.get("packet_sha256"):
                raise NaturalVoiceError("voice_cache_integrity_error")
            return packets
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise NaturalVoiceError("invalid_or_corrupt_voice_cache") from exc

    @staticmethod
    def pcm_to_opus(raw: bytes) -> tuple[bytes, ...]:
        if (not isinstance(raw, bytes) or len(raw) % 2 or
            not 24000 * 2 // 3 <= len(raw) <= 24000 * 2 * 6):
            raise NaturalVoiceError("tts_pcm_outside_duration_bounds")
        pcm = np.frombuffer(raw, dtype="<i2").copy()
        absolute = np.abs(pcm.astype(np.int32))
        loc = np.flatnonzero(absolute >= 90)
        if len(loc):
            start = max(0, int(loc[0]) - 1200)
            end = min(len(pcm), int(loc[-1]) + 1201)
            pcm = pcm[start:end]
        if not 6000 <= len(pcm) <= 24000 * 3.55:
            raise NaturalVoiceError("tts_phrase_too_long_for_device")
        peak = int(np.max(np.abs(pcm.astype(np.int32))))
        if peak > 6500:
            pcm = np.rint(pcm.astype(np.float64) * (6500 / peak)).astype("<i2")
        # Use the existing trusted A-owned device Opus24 encoder.
        from gobot_device_gateway import OpusOutput
        encoder = OpusOutput()
        packets = []
        data = pcm.tobytes()
        for offset in range(0, len(data), 48000):
            packets.extend(encoder.feed(data[offset:offset + 48000], 24000))
        packets.extend(encoder.finish())
        if (not 2 <= len(packets) <= MAX_PACKET_COUNT or
            any(not 0 < len(p) <= 4096 for p in packets)):
            raise NaturalVoiceError("opus24_packetization_outside_device_bound")
        return tuple(packets)

    def generate(self, hour, minute) -> tuple[bytes, ...]:
        """One request, 30s bounded, conservatively charged to Owner ledger."""
        existing = self.load(hour, minute)
        if existing is not None:
            return existing
        phrase = spoken_time(hour, minute)
        # Atomic financial reservation BEFORE any network call, shared with STT.
        booking = self.budget.reserve_voice_phrase(model=MODEL, voice=self.voice,
                                                   seconds=30)
        started = time.monotonic()
        final_status = "FAILED"
        try:
            key = self.key_loader()
            if not isinstance(key, str) or not key.startswith("sk-"):
                raise NaturalVoiceError("openai_secret_unavailable")
            with self.http_client_factory(timeout=MAX_GENERATION_SECONDS,
                                          trust_env=False) as client:
                reply = client.post(
                    ENDPOINT,
                    headers={"Authorization": "Bearer " + key,
                             "Content-Type": "application/json"},
                    json={"model": MODEL, "voice": self.voice,
                          "input": phrase, "instructions": INSTRUCTIONS,
                          "response_format": "pcm", "speed": 1.12},
                )
                if reply.status_code != 200:
                    raise NaturalVoiceError("openai_tts_http_failure_" +
                                            str(reply.status_code))
                packets = self.pcm_to_opus(reply.content)
            self.folder.mkdir(parents=True, exist_ok=True)
            info = {
                "schema": VOICE_SCHEMA, "model": MODEL,
                "voice": self.voice, "text": phrase,
                "packet_sha256": hashlib.sha256(b"".join(packets)).hexdigest(),
                "opus24_packets": [base64.b64encode(x).decode("ascii")
                                   for x in packets],
            }
            dest = self._file(hour, minute)
            temp = dest.with_suffix(".pending")
            temp.write_text(json.dumps(info, ensure_ascii=False),
                            encoding="utf-8")
            os.replace(temp, dest)
            final_status = "COMPLETE"
            return packets
        finally:
            self.budget.finish(
                booking, elapsed_seconds=max(0.0, time.monotonic() - started),
                result=final_status)

    def prefetch(self, count: int = 4):
        """Explicit one-shot only. No unattended 1440-call fan-out."""
        if type(count) is not int or not 1 <= count <= 8:
            raise NaturalVoiceError("unbounded_voice_prefetch")
        now = self.clock().replace(second=0, microsecond=0)
        report = []
        for offset in range(count):
            moment = now + timedelta(minutes=offset)
            current = self.load(moment.hour, moment.minute)
            if current is not None:
                report.append((moment.hour, moment.minute, "CACHED",
                               len(current)))
                continue
            try:
                packets = self.generate(moment.hour, moment.minute)
                report.append((moment.hour, moment.minute, "GENERATED",
                               len(packets)))
            except Exception as exc:
                report.append((moment.hour, moment.minute,
                               type(exc).__name__, 0))
                # Preserve budget; do not burn subsequent requests if API fails.
                break
        return report

    def get(self, moment=None):
        moment = self.clock() if moment is None else moment
        packets = self.load(moment.hour, moment.minute)
        if packets is None:
            return None, False
        return packets, True
