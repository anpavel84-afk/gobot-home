"""Opt-in local SYNTHETIC diagnostic fixtures, never human wake acceptance.

Uses existing read-only Russian Piper voice. Does not record the microphone.
Wake name and question are synthesized in ONE continuous utterance;
no stitched word-only files pretending to test coarticulation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import wave

REPLIES = [
    ("wake-gobot", "positive", "gobot", "Гобот"),
    ("wake-gabot", "positive", "gabot", "Габот"),
    ("wake-hey-gobot", "positive", "hey_gobot", "Эй Гобот"),
    ("wake-privet-gobot", "positive", "privet_gobot", "Привет Гобот"),
    ("wake-a-gobot", "positive", "a_gobot", "А Гобот"),
    ("wake-gobot-question", "positive", "gobot", "Гобот какая сегодня погода"),
    ("wake-gabot-question", "positive", "gabot", "Габот какая сегодня погода"),
    ("wake-gobot-time", "positive", "gobot", "Гобот который час сейчас"),
    ("negative-robot", "negative", None, "Робот помог человеку"),
    ("negative-rabota", "negative", None, "Работа идет своим чередом"),
    ("negative-mentions", "negative", None, "Мне рассказывали про роботов"),
    ("negative-hello", "negative", None, "Привет добрый день"),
    ("negative-tv-like", "negative", None, "По телевизору показывают прогноз погоды"),
]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--piper-model", type=Path, required=True)
    p.add_argument("--out-dir", type=Path, required=True)
    p.add_argument("--ffmpeg", type=Path, required=True)
    args = p.parse_args()
    from piper import PiperVoice
    voice = PiperVoice.load(args.piper_model)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for clip_id, kind, expected, text in REPLIES:
        output = args.out_dir / (clip_id + ".wav")
        if not output.exists():
            chunks = list(voice.synthesize(text))
            if not chunks:
                raise RuntimeError("empty_tts_output:" + clip_id)
            sr = chunks[0].sample_rate
            if any(c.sample_rate != sr for c in chunks):
                raise RuntimeError("inconsistent_synthesis_rate")
            temporary = args.out_dir / (clip_id + ".raw-" + str(sr) + ".wav")
            with wave.open(str(temporary), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sr)
                wav.writeframes(b"".join(c.audio_int16_bytes for c in chunks))
            subprocess.run([
                str(args.ffmpeg), "-hide_banner", "-loglevel", "error",
                "-nostdin", "-y", "-i", str(temporary), "-ac", "1",
                "-ar", "16000", "-c:a", "pcm_s16le", str(output),
            ], check=True)
            temporary.unlink()
        with wave.open(str(output), "rb") as wav:
            if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 16000):
                raise ValueError("bad_generated_pcm")
            pcm = wav.readframes(wav.getnframes())
        records.append({
            "id": clip_id, "kind": kind, "source": "synthetic",
            "path": output.name, "expected_phrase": expected,
            # No independent annotation of where the name ends in full
            # coarticulated speech; never fake latency.
            "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        })
        print(clip_id, "duration_s", round(len(pcm) / 32000, 2))
    manifest = args.out_dir / "manifest_synthetic.json"
    manifest.write_text(json.dumps(
        {"description": "Piper ru_RU-denis-medium SYNTHETIC ONLY, NO HUMAN ACCEPTANCE",
         "samples": records}, ensure_ascii=False, indent=2
    ), encoding="utf-8")
    print("SYNTHETIC_MANIFEST", manifest)


if __name__ == "__main__":
    main()
