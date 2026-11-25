"""One short, locally synthesized Russian HOST test phrase.

Never invokes OpenAI/B/C/CLI, network providers, recording, or disk audio.
Existing private PLAN Piper voice and config are read-only. Synthesized PCM
is captured in RAM, with mutable PCM buffer best-effort zeroized afterward.
NOT a Brain/model response.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import numpy as np

SAMPLE_RATE = 22050
OUTPUT_PACKET_LIMIT = 64
MAX_RAW_SECONDS = 3.3
MAX_PCM_ABS = 6000
DEFAULT_PHRASE = "Привет, я Гобот."


def offline_russian_packets(model_path: Path, *, text: str = DEFAULT_PHRASE,
                            piper_path: Path | None = None) -> tuple[bytes, ...]:
    from gobot_device_gateway import OpusOutput

    model = Path(model_path).resolve()
    config = Path(str(model) + ".json")
    if not model.is_file() or not config.is_file() or model.suffix != ".onnx":
        raise ValueError("local_offline_voice_missing")
    details = json.loads(config.read_text(encoding="utf8"))
    if (details.get("language", {}).get("code") != "ru_RU" or
            details.get("audio", {}).get("sample_rate") != SAMPLE_RATE):
        raise ValueError("unexpected_local_voice_rate_or_language")
    if not text or len(text) > 55 or "\n" in text or "\r" in text:
        raise ValueError("test_phrase_outside_short_bound")

    piper = (Path(piper_path) if piper_path is not None
             else Path(sys.executable).with_name("piper.exe")).resolve()
    if not piper.is_file():
        raise ValueError("piper_executable_missing")
    # Only a preexisting local ONNX voice. The subprocess sees a fixed string;
    # stdout is captured in RAM, not an audio file, and cannot reach a service.
    cmd = [str(piper), "--model", str(model), "--output-raw",
           "--volume", "0.25", "--length-scale", "0.95",
           "--sentence-silence", "0"]
    process = subprocess.run(cmd, input=(text+"\n").encode("utf8"),
                             stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             timeout=25,check=False,
                             env={**os.environ,"PYTHONIOENCODING":"utf-8",
                                  "PYTHONUTF8":"1"})
    if process.returncode != 0:
        raise ValueError("offline_piper_synthesis_failed")
    raw = bytearray(process.stdout)
    try:
        if len(raw)%2 or not (SAMPLE_RATE*.3*2 <= len(raw) <= SAMPLE_RATE*MAX_RAW_SECONDS*2):
            raise ValueError("offline_phrase_duration_outside_3s3_bound")
        source = np.frombuffer(raw,dtype="<i2")
        peak = int(np.max(np.abs(source.astype(np.int32))))
        # A deliberate physical speaker test must be at low safe volume;
        # reduce uniformly instead of hard-clipping peaks.
        gain=min(1., MAX_PCM_ABS/max(peak,1))
        if gain<1:
            source[:]=np.rint(source.astype(np.float32)*gain).astype("<i2")
        encoder=OpusOutput()
        packets=encoder.feed(bytes(raw),SAMPLE_RATE)
        packets.extend(encoder.finish())
        if not 2<=len(packets)<=OUTPUT_PACKET_LIMIT or any(
                not isinstance(pkt,bytes) or not 0<len(pkt)<=4096
                for pkt in packets):
            raise ValueError("offline_phrase_24k_opus_bounds_failed")
        return tuple(packets)
    finally:
        raw[:]=bytes(len(raw))
