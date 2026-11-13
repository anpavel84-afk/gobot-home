"""Offline catalog/validation/dry-run. Never calls a speech provider."""
import argparse,json,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];os.chdir(ROOT);sys.path.insert(0,str(ROOT/'services/brain'))
from gobot.voice_library import VoiceLibrary
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['inventory','dry-run']);a=p.parse_args()
    library=VoiceLibrary();print(json.dumps(library.dry_run() if a.command=='dry-run' else library.inventory(),ensure_ascii=False,indent=2))
