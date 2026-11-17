"""Unforced, actual hypothesis traces on ONE saved public/synthetic WAV.

This utility intentionally rejects any 'consented' or private PCM path; live
human audio is traced only in the opt-in in-memory guided PC test.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import wave

from .gobi_diagnostics import audit_pcm_file,replay_model_hypotheses
from .gobi_policy import CANDIDATES, make_candidate_backend
from .engines import REGISTRY


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures-dir",type=Path,required=True)
    ap.add_argument("--clip",required=True)
    ap.add_argument("--candidate",choices=CANDIDATES,required=True)
    ap.add_argument("--models-root",type=Path,required=True)
    ap.add_argument("--engines",nargs="+",choices=REGISTRY,
                    default=["vosk","t-one","zipformer-window"])
    a=ap.parse_args()
    root=a.fixtures_dir.resolve()
    if not root.name.startswith("gobi_v") or not a.clip.replace("_","").replace("-","").isalnum():
        ap.error("only deterministic named synthetic Gobi fixtures supported")
    sample=(root/(a.clip+".wav")).resolve()
    if sample.parent!=root or not sample.is_file():
        ap.error("synthetic fixture not found")
    audit=audit_pcm_file(sample)
    print("SYNTHETIC_CANONICAL_PCM",sample.name,audit)
    with wave.open(str(sample),"rb") as w:
        pcm=w.readframes(w.getnframes())
    for engine in a.engines:
        print("START_MODEL",engine,"candidate",a.candidate,flush=True)
        try:
            model=make_candidate_backend(engine,a.models_root,a.candidate,threads=1)
        except Exception as e:
            print("MODEL_BLOCKED",engine,type(e).__name__,str(e)[:130])
            continue
        s=replay_model_hypotheses(model,pcm,label=engine)
        print("MODEL_DEBUG_STATUS",engine,s)
    print("ALL_HYPOTHESES_FROM_SYNTHETIC_PCM_NOT_HUMAN_TEST")


if __name__=="__main__":
    main()
