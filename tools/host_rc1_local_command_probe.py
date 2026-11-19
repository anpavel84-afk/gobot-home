"""Synthetic phrase -> local offline Russian ASR preflight. NO room capture, no disk audio.

Independent of HOST-B wake lab. Reads existing private Piper/Faster-Whisper
models, uses only local CPU. Never calls Brain/OpenAI/B/C/CLI or cloud TTS.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import numpy as np


def prepare_pcm(piper:Path,model:Path,text:str)->np.ndarray:
    e=os.environ.copy()
    e["PYTHONUTF8"]="1";e["PYTHONIOENCODING"]="utf-8"
    proc=subprocess.run([str(piper),"--model",str(model),"--output-raw",
                         "--volume","0.8","--sentence-silence","0"],
                        input=(text+"\n").encode("utf8"),
                        stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                        env=e,timeout=25,check=False)
    if proc.returncode or not proc.stdout or len(proc.stdout)%2:
        raise ValueError("offline_piper_probe_failed")
    src=np.frombuffer(proc.stdout,dtype="<i2").astype(np.float32)/32768
    if not 22050//3 <= len(src) <= 22050*6:raise ValueError("unexpected_local_phrase_duration")
    pos=np.arange(int(round(len(src)*16000/22050)),dtype=np.float64)*(22050/16000)
    mono=np.interp(pos,np.arange(len(src)),src).astype(np.float32)
    return mono

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--asr",type=Path,required=True)
    p.add_argument("--voice",type=Path,required=True)
    p.add_argument("--phrase",default="Скажи, сколько сейчас времени?")
    args=p.parse_args()
    root=args.asr.resolve(); voice=args.voice.resolve()
    if not (root/"model.bin").is_file() or not (root/"config.json").is_file():
        raise ValueError("offline_small_whisper_missing")
    if not voice.is_file() or not Path(str(voice)+".json").is_file():
        raise ValueError("offline_russian_voice_missing")
    piper=Path(sys.executable).with_name("piper.exe")
    if not piper.is_file():raise ValueError("piper_binary_missing")
    if len(args.phrase)>90 or "\n" in args.phrase:raise ValueError("phrase_too_long")
    started=time.monotonic()
    wave=prepare_pcm(piper,voice,args.phrase)
    from faster_whisper import WhisperModel
    model=WhisperModel(str(root),device="cpu",compute_type="int8",
                       local_files_only=True,cpu_threads=4,num_workers=1)
    snippets,meta=model.transcribe(wave,language="ru",beam_size=1,
                                   temperature=0,condition_on_previous_text=False,
                                   vad_filter=False,word_timestamps=False)
    recognized=" ".join(chunk.text.strip() for chunk in snippets).strip()
    del wave,model
    print(json.dumps({"fixture":"synthetic_local_only","speech_recorded":False,
                      "recognition_source":"faster_whisper_small_cpu",
                      "transcript":recognized,
                      "cpu_elapsed_seconds":round(time.monotonic()-started,2),
                      "cloud_or_paid_calls":0},ensure_ascii=True),flush=True)

if __name__=="__main__":
    main()
