"""Create an immutable NEW V3 dataset from V1/V2 TTS TRAIN ONLY + new test.

No H0 or existing corpus written. V1/V2 prior validation and test clips
are NOT training inputs. V3 uses a fresh eight-voice holdout synthesizer
(licensed RHVoice Aleksandr-hq), which the trainer NEVER loads.
"""
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copyfile

TRAIN=("denis","dmitri","espeak-ru","anna","irina")
VALID=("aleksandr",)
TEST=("elena","aleksandr-hq")
NAME="мо\u0301ника"

def allowed(label,text,split):
    if split!="train":return True
    t=text.strip().casefold()
    if label=="positive":
        return t.startswith(NAME) or t.startswith("моника")
    # An identical initial spoken 'Моника' cannot be simultaneously a
    # negative and positive phonetic target without semantic context.
    return not (t.startswith("моника ") or t.startswith("мо\u0301ника "))

def merge(v1:Path,v2:Path,hq:Path,out:Path):
    if out.exists():raise ValueError("no overwrite of old datasets")
    if not all((x/"complete.json").is_file() for x in (v1,v2,hq)):
        raise ValueError("one required source corpus is incomplete")
    out.mkdir(parents=True)
    records=[]
    for speaker in (*TRAIN,*VALID,*TEST):
        group="train" if speaker in TRAIN else "validation" if speaker in VALID else "test"
        output=out/speaker;output.mkdir()
        for label in ("positive","negative"):
            entries=[]
            sources=(
                (("v1",v1),("v2",v2)) if group=="train"
                else (("v2",v2),) if speaker!="aleksandr-hq"
                else (("v3-hq",hq),)
            )
            for source_name,root in sources:
                directory=root/speaker
                raw=json.loads((directory/f"manifest-{label}.json").read_text(encoding="utf8"))
                for item in raw:
                    if not allowed(label,item["text"],group):continue
                    if (item["speaker"]!=speaker or item["label"]!=label
                        or item["split"]!=group or item["synthetic"] is not True):
                        raise ValueError("cross_split_or_speaker_leakage")
                    path=directory/item["file"]
                    if path.name!=item["file"] or path.is_symlink():
                        raise ValueError("unsafe_source_path")
                    data=path.read_bytes()
                    if hashlib.sha256(data).hexdigest()!=item["sha256"]:
                        raise ValueError("source_audio_digest_changed")
                    filename=f"{source_name}-{item['file']}"
                    if (output/filename).exists():raise FileExistsError(filename)
                    (output/filename).write_bytes(data)
                    entries.append({**item,"file":filename,
                                    "source_v":source_name})
            if not entries:raise ValueError("missing_class")
            (output/f"manifest-{label}.json").write_text(
                json.dumps(entries,ensure_ascii=False,indent=2),encoding="utf8")
            records.append({"speaker":speaker,"split":group,
                            "label":label,"clips":len(entries)})
            print("MERGED",speaker,label,len(entries),flush=True)
    (out/"complete.json").write_text(json.dumps({
        "schema":"gobot-monika-mww-merged-v3",
        "training_only_sources":["v1","v2"],
        "validation_only_source":"v2_aleksandr",
        "test_source_elena":"v2_previously_examined",
        "test_source_aleksandr_hq":"fresh_v3_never_seen_by_trainer",
        "h0_mutated":False,"human_audio":False,"paid_calls":0,
        "counts":records},ensure_ascii=False,indent=2))
    print("V3_MERGED_CORPUS_READY",sum(x["clips"] for x in records),flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    for k in ("v1","v2","hq","out"):
        p.add_argument("--"+k,type=Path,required=True)
    a=p.parse_args()
    merge(a.v1,a.v2,a.hq,a.out)
