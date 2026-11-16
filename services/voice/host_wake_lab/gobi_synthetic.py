"""Create read-only publicly trained TTS fixtures for candidate comparison.

Only standalone *synthetic* Russian Piper examples, NOT human recordings.
Generates identical PCM for ALL candidate-model comparisons, and SHA-pinned
per-candidate manifests. Never assumes synthetic words have correct stress.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import wave
from .gobi_policy import CANDIDATES

P = {
 "gobi": ["Гоби", "Гоби", "Гоби какая сегодня погода",
          "Гоби сколько времени", "Гоби включи музыку",
          "Гоби скажи пожалуйста который час"],
 "globi": ["Глоби", "Глоби", "Глоби какая сегодня погода",
           "Глоби сколько времени", "Глоби включи музыку",
           "Глоби скажи пожалуйста который час"],
 "a_gobi": ["А Гоби", "А Гоби", "А Гоби какая сегодня погода",
            "А Гоби сколько времени", "А Гоби включи музыку",
            "А Гоби скажи пожалуйста который час"],
 "hey_gobi": ["Эй Гоби", "Эй Гоби", "Эй Гоби какая сегодня погода",
              "Эй Гоби сколько времени", "Эй Гоби включи музыку",
              "Эй Гоби скажи пожалуйста который час"],
}
NEG = [
 ("robot", "Робот"),
 ("gobot", "Гобот"),
 ("lips", "Губы"),
 ("globe", "Глобус"),
 ("gobi-desert", "В пустыне Гоби очень жарко"),
 ("robot-weather", "Робот какая сегодня погода"),
 ("gobot-weather", "Гобот какая сегодня погода"),
 ("lips-sentence", "Губы должны быть сомкнуты"),
 ("globe-sentence", "Глобус стоит на столе"),
 ("radio", "Обычный разговор по радио"),
 ("somebody-said", "Он сказал Гоби, но не обращался к помощнику"),
 ("hello-robot", "Эй робот давай работать"),
 ("globe-name", "Я люблю читать о глобусе"),
 ("guby-conversation", "Не кусай губы пожалуйста"),
]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--piper-model",type=Path,required=True)
    p.add_argument("--out-dir",type=Path,required=True)
    p.add_argument("--ffmpeg",type=Path,required=True)
    a=p.parse_args()
    from piper import PiperVoice
    voice=PiperVoice.load(a.piper_model)
    a.out_dir.mkdir(exist_ok=True,parents=True)
    all_records=[]
    specs=[]
    for name,texts in P.items():
        for i,text in enumerate(texts):
            ident=f"{name}_{i:02d}"
            specs.append((ident,name,text))
    for ident,text in NEG:
        specs.append(("negative_"+ident,None,text))
    for ident,candidate_id,text in specs:
        out=a.out_dir / (ident+".wav")
        if not out.is_file():
            chunks=list(voice.synthesize(text))
            if not chunks:
                raise RuntimeError("piper_empty_speech:"+ident)
            rate=chunks[0].sample_rate
            raw=a.out_dir / (ident+".temporary.wav")
            with wave.open(str(raw),"wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(rate)
                w.writeframes(b"".join(c.audio_int16_bytes for c in chunks))
            subprocess.run([str(a.ffmpeg),"-y","-nostdin","-hide_banner",
                "-loglevel","error","-i",str(raw),"-ac","1",
                "-ar","16000","-c:a","pcm_s16le",str(out)],check=True)
            raw.unlink()
        with wave.open(str(out),"rb") as w:
            assert (w.getnchannels(),w.getsampwidth(),w.getframerate())==(1,2,16000)
            pcm=w.readframes(w.getnframes())
        all_records.append({
            "id":ident,"spoken_target":candidate_id,"source":"synthetic",
            "path":out.name,"pcm_sha256":hashlib.sha256(pcm).hexdigest(),
            "duration_s":round(len(pcm)/32000.,3),
            "text":text,
        })
    for candidate in CANDIDATES:
        samples=[]
        for record in all_records:
            samples.append({
                "id":record["id"], "path":record["path"],
                "kind":"positive" if record["spoken_target"]==candidate else "negative",
                "source":"synthetic", "expected_phrase":candidate if record["spoken_target"]==candidate else None,
                "pcm_sha256":record["pcm_sha256"],
            })
        # All models/candidates use the IDENTICAL audio clips; only ground truth changes.
        manifest={"schema":"gobi_owner_candidate_v1",
          "candidate":candidate,"human_voice":False,
          "note":"Single existing Piper Russian voice; stress not independently verified.",
          "samples":samples}
        dest=a.out_dir/f"manifest_{candidate}.json"
        dest.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),
                        encoding="utf-8")
    catalog=a.out_dir/"corpus_catalog.json"
    catalog.write_text(json.dumps(all_records,ensure_ascii=False,indent=2),
                       encoding="utf-8")
    print("SYNTHETIC_ONLY clips",len(all_records),
          "positive_per_candidate",len(P["gobi"]),
          "negative_per_candidate",len(all_records)-len(P["gobi"]))
    print("MANIFESTS",*(x.name for x in a.out_dir.glob("manifest_*.json")))
    print("CORPUS_SHA256",hashlib.sha256(catalog.read_bytes()).hexdigest())


if __name__=="__main__":
    main()
