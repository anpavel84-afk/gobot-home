"""Model-actual hypothesis traces; only in local console, NEVER persisted.

This is *diagnostic* decoding, not a wake match decision. It exposes:
- Vosk: interim partials, segment final, bounded utterance FinalResult
- Sherpa T-one: decoded CTC interim texts and input_finished() final
- Sherpa Zipformer: rolling offline window snapshots, then whole-PCM offline final

No forced lexicon, no phonetic alias, no cloud call. The final result happens
AFTER the utterance and CANNOT count as an early streaming wake event. Never
print private human transcripts to a file or GitHub. Consent-gated runner sends
them to the visible local PLAN terminal only.
"""
from __future__ import annotations
import json
import wave
from pathlib import Path

from .engines import ToneOnline, VoskOnline, ZipformerWindow

HZ = 16000
FRAME = 960


def get_final_hypothesis(backend, original_pcm: bytes | bytearray):
    """Return (type,text) of a genuine model-generated *utterance-end* result."""
    if isinstance(backend, VoskOnline):
        try:
            return "VOSK_FINAL_RESULT", str(json.loads(
                backend.rec.FinalResult()).get("text", ""))
        except Exception as exc:
            return "VOSK_FINAL_ERROR", type(exc).__name__
    if isinstance(backend, ToneOnline):
        try:
            backend.stream.input_finished()
            while backend.recognizer.is_ready(backend.stream):
                backend.recognizer.decode_stream(backend.stream)
            result = backend.recognizer.get_result_all(backend.stream)
            return "TONE_INPUT_FINISHED_FINAL", str(result.text)
        except Exception as exc:
            return "TONE_FINAL_ERROR", type(exc).__name__
    if isinstance(backend, ZipformerWindow):
        import numpy as np
        try:
            a = np.frombuffer(original_pcm, dtype="<i2").astype(np.float32) / 32768.
            stream = backend.recognizer.create_stream()
            stream.accept_waveform(HZ, a)
            backend.recognizer.decode_stream(stream)
            result = backend.recognizer.get_result(stream) if hasattr(
                backend.recognizer, "get_result") else stream.result
            return "ZIP_OFFLINE_FULL_UTTERANCE", (
                str(result.text) if hasattr(result, "text") else str(result)
            )
        except Exception as exc:
            return "ZIP_FINAL_ERROR", type(exc).__name__
    return "UNKNOWN_BACKEND_NO_FINAL", ""


def replay_model_hypotheses(backend, pcm: bytes | bytearray, *,
                            label: str, output=print, tail_silence_s: float=1.2,
                            max_printed_partial: int=30) -> dict:
    """Print *real* model text changes on identical PCM and return counts only.

    Output is local console; only integer counters and final-kind are returned.
    The detector is reset at the end; this is never sent to Brain/gateway.
    """
    if not 0 <= tail_silence_s <= 2:
        raise ValueError("tail_silence_seconds_out_of_bounds")
    backend.reset()
    previous = None
    printed = 0
    partials = 0
    endpoints = 0
    data = bytearray(pcm)
    data.extend(b"\0\0" * int(HZ * tail_silence_s))
    last_segment_final = ""
    for pos in range(0,len(data),FRAME*2):
        samples = bytes(data[pos:pos+FRAME*2])
        if not samples:
            continue
        hyp = backend.feed_pcm(samples)
        if hyp.endpoint:
            endpoints += 1
            if hyp.text:
                last_segment_final = hyp.text
        if hyp.updated and (hyp.text != previous or hyp.endpoint):
            if printed < max_printed_partial:
                stage = ("SEGMENT_FINAL" if hyp.endpoint else
                         "ZIP_WINDOW" if isinstance(backend,ZipformerWindow)
                         else "PARTIAL")
                output("ASR_TRACE",label,"stage",stage,
                       "audio_offset_ms",round((pos//2 + len(samples)//2)/HZ*1000,1),
                       "text",repr(hyp.text[:150]))
                printed += 1
            partials += 1
            previous = hyp.text
    kind,text = get_final_hypothesis(backend, pcm)
    if kind == "VOSK_FINAL_RESULT" and not text and last_segment_final:
        # The true last spoken segment already ended in Vosk.Result().
        # FinalResult after a completed segment is correctly empty.
        kind = "VOSK_PREVIOUS_SEGMENT_FINAL"
        text = last_segment_final
    output("ASR_TRACE",label,"stage",kind,
           "audio_offset_ms",round(len(pcm)/2/HZ*1000,1),
           "text",repr(text[:180]))
    backend.reset()
    data[:] = bytes(len(data))
    data.clear()
    return {
        "stage":kind,"updates_observed":partials,
        "endpoints_observed":endpoints,"printed_updates":printed,
        "final_available":not kind.endswith("_ERROR"),
        "pcm_saved":False,"hypotheses_persisted":False,
    }


def audit_pcm_file(path: Path) -> dict:
    """Read a historical public/synthetic fixture without altering it."""
    import hashlib
    import numpy as np
    with wave.open(str(path), "rb") as reader:
        rate,channels,width,compression=(
            reader.getframerate(),reader.getnchannels(),
            reader.getsampwidth(),reader.getcomptype())
        if (rate,channels,width,compression)!=(HZ,1,2,"NONE"):
            raise ValueError("bad_canonical_pcm_file")
        data=reader.readframes(reader.getnframes())
    samples=np.frombuffer(data,dtype="<i2")
    rms=float(np.sqrt(np.mean(samples.astype("f8")**2))) if samples.size else 0
    peak=int(np.max(np.abs(samples.astype("i4")))) if samples.size else 0
    return {
        "sample_rate":rate,"channels":channels,"bits_per_sample":width*8,
        "pcm_bytes":len(data),"duration_s":round(len(data)/2/HZ,3),
        "sha256":hashlib.sha256(data).hexdigest(),
        "rms_dbfs":float(round(20*np.log10(max(rms,1e-8)/32768),2)),
        "peak_dbfs":float(round(20*np.log10(max(peak,1e-8)/32768),2)),
        "audio_is_synthetic":True,
        "pronunciation_stress_acoustically_verified":False,
    }
