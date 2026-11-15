"""Generate a separate, previously unseen Russian unit-selection voice test set."""
import argparse
import json
import hashlib
from pathlib import Path
import subprocess
import tempfile
import wave
import numpy as np
from corpus import POSITIVE, NEGATIVE, pcm16

def main(libdir,folder):
    folder.mkdir(parents=True,exist_ok=True)
    rows=[]
    commands=["(voice_msu_ru_nsh_clunits)"]
    with tempfile.TemporaryDirectory() as tmp:
        for label,phrases in (("positive",POSITIVE),("negative",NEGATIVE)):
            for i,phrase in enumerate(phrases):
                phrase=phrase.replace("\u0301","")  # This lexicon rejects combining stress characters.
                for rate in (82,100,118):
                    name=f"{label}-{i}-{rate}"
                    commands.extend([f"(Parameter.set 'Duration_Stretch {rate/100})",
                       f'(utt.save.wave (utt.synth (Utterance Text {json.dumps(phrase,ensure_ascii=False)})) "{tmp}/{name}.wav" (quote riff))'])
                    rows.append(dict(file=name+".pcm",text=phrase,speaker="festival-msu",label=label,synthetic=True))
        subprocess.run(["festival","--datadir",str(libdir),"--libdir",str(libdir),"--pipe"],
                       input="\n".join(commands).encode(),check=True,capture_output=True)
        for row in rows:
            with wave.open(str(Path(tmp)/Path(row["file"]).with_suffix(".wav")),"rb") as wav:
                samples=np.frombuffer(wav.readframes(wav.getnframes()),"<i2")
                clip=pcm16(samples.astype(float),wav.getframerate())
            clip.tofile(folder/row["file"])
            row["sha256"]=hashlib.sha256(clip.tobytes()).hexdigest()
    (folder/"manifest.json").write_text(json.dumps(rows,indent=2,ensure_ascii=False))
if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("libdir",type=Path)
    p.add_argument("output",type=Path)
    a=p.parse_args()
    main(a.libdir,a.output)
