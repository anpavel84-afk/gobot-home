"""Download pinned public model artifacts locally; never use account tokens."""
import hashlib
import json
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]

def download(url, destination, expected=None):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and (expected is None or hashlib.sha256(destination.read_bytes()).hexdigest() == expected):
        return
    temporary = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
        while chunk := response.read(1024 * 1024):
            output.write(chunk)
    digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
    if expected and digest != expected:
        raise ValueError("Model checksum mismatch")
    temporary.replace(destination)

def main():
    # Reproduction requires the checked-in lock, never a private/generated metadata file.
    lock = json.loads((ROOT / 'docs/audio-models.lock.json').read_text(encoding='utf-8'))
    model = lock['stt']
    whisper_dir = ROOT / "data/models/faster-whisper-small"
    files = []
    for item in model["files"]:
        filename = item["name"]
        if filename not in {"config.json", "tokenizer.json", "vocabulary.txt", "model.bin"}:
            continue
        expected = item['sha256']
        path = whisper_dir / filename
        print("Downloading public STT artifact:", filename, flush=True)
        download("https://huggingface.co/Systran/faster-whisper-small/resolve/" + model["revision"] + "/" + filename, path, expected)
        files.append({"name": filename, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    asset = lock['tts']
    archive = ROOT / "data/models" / asset["asset"]
    print("Downloading public Russian TTS artifact", flush=True)
    download('https://github.com/k2-fsa/sherpa-onnx/releases/download/tts-models/'+asset['asset'], archive, asset['sha256'].removeprefix('sha256:'))
    destination = ROOT / "data/models/vits-piper-ru_RU-denis-medium"
    if not destination.exists():
        with tarfile.open(archive) as package:
            package.extractall(ROOT / "data/models", filter="data")
    card = ROOT / "data/models/denis-MODEL_CARD.txt"
    download("https://huggingface.co/rhasspy/piper-voices/resolve/main/ru/ru_RU/denis/medium/MODEL_CARD", card)
    report = {"stt": {"repo": "Systran/faster-whisper-small", "revision": model["revision"], "files": files},
              "tts": {"asset": asset["asset"], "sha256": asset["sha256"], "dataset_license": "CC0",
                      "license_source": "https://huggingface.co/rhasspy/piper-voices/blob/main/ru/ru_RU/denis/medium/MODEL_CARD"}}
    (ROOT / "docs/audio-models.lock.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("Pinned public audio models prepared", flush=True)

if __name__ == "__main__":
    main()
