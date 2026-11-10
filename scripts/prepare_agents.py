"""Restore the pinned official Codex configuration schema, without model calls."""
import hashlib,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
URL='https://raw.githubusercontent.com/openai/codex/rust-v0.159.2/codex-rs/core/config.schema.json'
SHA='eda7251b7e46e0b9d0f3d8eef5dab451e11a55d723e2b802e152b7208045836a'
def main():
    path=ROOT/'vendor/references/live-agents/config.schema.json'
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest()!=SHA:raise RuntimeError('Existing schema differs; not overwritten')
    else:
        data=urllib.request.urlopen(URL,timeout=30).read()
        if hashlib.sha256(data).hexdigest()!=SHA:raise RuntimeError('Official schema checksum mismatch')
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    print('Codex 0.159.2 schema SHA-256 verified; no model request')
if __name__=='__main__':main()
