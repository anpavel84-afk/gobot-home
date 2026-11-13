"""Generate isolated Russian TTS clips. No recording or network access."""
import argparse
import hashlib
import json
import subprocess
from pathlib import Path
import wave

import numpy as np
import onnxruntime
from piper import PiperVoice, SynthesisConfig
from scipy.signal import resample_poly
from math import gcd

POSITIVE = ["Гобо́т.", "Го́бот.", "Гобот!", "Гобо́т?", "Го́бот?"]
NEGATIVE = """робот|работа|работает|готов|готово|гобой|гоблин|бот|вот|забота|капот|компот|колобок|голод|город|какой бот|год|говорит|погода|погоди|Глеб|гудок|губа|гобелен|работай|голос|грохот|гогот|мотобот|глоток|хобот|вот бот|этот робот|домашний робот|голубой|да|нет|стоп|доброе утро|сколько времени|который час|поставь таймер|а завтра|какая погода сегодня|какой прогноз на завтра|открой окно|на кухне играет радио|ребёнок читает книгу|спасибо за ответ|она работает дома|это его ботинки|пока бот отвечает|включи музыку|кто живёт в лесу|горбатый кит|кубок|в поход|забудь|завод|головой|годовой отчёт|в огород|ну вот|вагон|по работе|где мой блокнот""".split("|")
HASHES = {
    "denis": ("879bc365cb14d1380e3f5ed6044162ccf54c99f6161871569b7f830aec3ce841", "e4fb4ab60262d1ab802c8c39301976c4135e545bc834a33c6eedc1f764df3bd6"),
    "dmitri": ("9ed9941bac7373f2ec1be36627e0e71a349a59ca5522d4363fd50701db05193a", "b7ed744f65ec73deb57fc8e419a5db5c0c5532026cf1cd21247f75937b6fbee2"),
}
def pcm16(samples, rate):
    factor = gcd(16000, rate)
    return np.clip(resample_poly(samples, 16000 // factor, rate // factor), -32768, 32767).astype("<i2")

def generate(directory, out, speaker, positive_phrases=None):
    paths = [directory / f"ru_RU-{speaker}-medium.{ext}" for ext in ("onnx", "onnx.json")]
    if speaker in HASHES:
        for path, digest in zip(paths, HASHES[speaker]):
            if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError(f"Unexpected voice digest: {path}")
        onnxruntime.set_seed(1042)
        voice = PiperVoice.load(paths[0])
    elif speaker not in ("espeak-ru", "elena", "anna", "aleksandr"):
        raise ValueError("Unreviewed voice")
    folder = out / speaker
    folder.mkdir(parents=True, exist_ok=True)
    rows = []
    for label, phrases in (("positive", positive_phrases or POSITIVE), ("negative", NEGATIVE)):
        for index, phrase in enumerate(phrases):
            for speed in (82, 100, 118):
                if speaker in ("elena", "anna", "aleksandr"):
                    from tempfile import TemporaryDirectory
                    with TemporaryDirectory() as tmp:
                        wav_path = Path(tmp) / "clip.wav"
                        subprocess.run(["RHVoice-test", "-p", speaker.title(), "-r", str(100-speed), "-o", str(wav_path)],
                                       input=phrase.encode(), check=True)
                        with wave.open(str(wav_path)) as wav:
                            samples = np.frombuffer(wav.readframes(wav.getnframes()), "<i2")
                            pcm = pcm16(samples.astype(float), wav.getframerate())
                elif speaker == "espeak-ru":
                    result = subprocess.run(["espeak-ng", "-v", "ru", "-s", str(round(16500 / speed)), "--stdout", phrase], check=True, capture_output=True)
                    from io import BytesIO
                    with wave.open(BytesIO(result.stdout)) as wav:
                        samples = np.frombuffer(wav.readframes(wav.getnframes()), "<i2")
                        pcm = pcm16(samples.astype(float), wav.getframerate())
                else:
                    chunks = voice.synthesize(phrase, SynthesisConfig(length_scale=speed / 100))
                    pcm = pcm16(np.concatenate([c.audio_float_array for c in chunks]) * 32767, voice.config.sample_rate)
                filename = f"{label}-{index}-{speed}.pcm"
                pcm.tofile(folder / filename)
                rows.append(dict(file=filename, text=phrase, speaker=speaker, label=label, synthetic=True,
                                 sha256=hashlib.sha256(pcm.tobytes()).hexdigest()))
    (folder / "manifest.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("voices", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("speakers", nargs="+", choices=[*HASHES, "espeak-ru","elena","anna","aleksandr"])
    p.add_argument('--wake-variants',action='store_true',help='New isolated accent-variant corpus; existing output is forbidden')
    args = p.parse_args()
    positives=None
    if args.wake_variants:
        from wake_variants import VARIANTS
        if args.output.exists():raise ValueError('variant_corpus_requires_new_output_directory')
        positives=[v['text'] for v in VARIANTS]
    for speaker in args.speakers:
        generate(args.voices, args.output, speaker, positives)
