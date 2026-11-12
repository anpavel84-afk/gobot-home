"""Offline Russian keyword experiment. Synthetic data only; train and test voices are disjoint."""
import argparse
import json
from pathlib import Path

import numpy as np

POSITIVE = ("Гобо́т.", "Го́бот.", "Гобот.")
NEGATIVE = ("робот", "работа", "готов", "погода", "бот", "капот", "компот", "голод",
            "город", "колобок", "год", "говорит", "какой бот", "вот", "погоди",
            "Глеб", "гараж", "домой", "сколько времени", "поставь таймер", "да", "нет",
            "игрок", "привет", "гудок", "Го", "голос", "сегодня тепло", "роботы работают")
HOP = 256
EDGES = np.unique(np.rint((700 * (np.exp(np.linspace(np.log1p(100/700), np.log1p(7900/700), 21)) - 1)) * HOP / 16000).astype(int))
STEPS = 20


def synthesize(model, folder):
    from piper import PiperVoice, SynthesisConfig
    voice = PiperVoice.load(model)
    folder.mkdir(parents=True, exist_ok=True)
    for speed in (85, 100, 115):
        for label, words in (("positive", POSITIVE), ("negative", NEGATIVE)):
            for index, word in enumerate(words):
                path = folder / f"{label}-{index}-{speed}.pcm"
                if path.exists():
                    continue
                raw = np.concatenate([c.audio_float_array for c in voice.synthesize(
                    word, SynthesisConfig(length_scale=speed / 100))])
                scale = voice.config.sample_rate / 16000
                pcm = np.interp(np.arange(0, len(raw), scale), np.arange(len(raw)), raw)
                (np.clip(pcm, -1, 1) * 32767).astype("<i2").tofile(path)


def signature(pcm):
    pcm = np.pad(pcm, (0, (-len(pcm)) % HOP)).astype(float).reshape(-1, HOP)
    rms = np.sqrt(np.mean(pcm ** 2, axis=1))
    active = np.flatnonzero(rms >= max(60, rms.max() * 0.055))
    if len(active) < 5:
        return None
    frames = pcm[active[0]:active[-1]+1]
    if not 8 <= len(frames) <= 85:
        return None
    power = np.abs(np.fft.rfft(frames * np.hanning(HOP))) ** 2
    bands = np.stack([power[:, a:b].mean(axis=1) for a, b in zip(EDGES, EDGES[1:])], axis=1)
    log_bands = np.log(np.maximum(bands, 1))
    norm = np.maximum(log_bands - log_bands.max(axis=1, keepdims=True), -10)
    indices = np.rint(np.linspace(0, len(frames) - 1, STEPS)).astype(int)
    return np.rint(norm[indices] * 10).astype(np.int8)


def evaluate(train_dirs, heldout):
    vectors, labels = [], []
    for folder in train_dirs:
        for p in sorted(folder.glob("*.pcm")):
            feat = signature(np.fromfile(p, dtype="<i2"))
            if feat is not None:
                vectors.append(feat)
                labels.append(p.name.startswith("positive"))
    train = np.array(vectors, dtype=np.float32)
    labels = np.array(labels)
    if not labels.any() or labels.all():
        raise ValueError("Both training classes are required")
    counts = dict(positives=0, negatives=0, detected=0, false_positives=0)
    missed, false = [], []
    for p in sorted(heldout.glob("*.pcm")):
        positive = p.name.startswith("positive")
        counts["positives" if positive else "negatives"] += 1
        feat = signature(np.fromfile(p, dtype="<i2"))
        hit = False
        if feat is not None:
            distance = np.mean(np.abs(train - feat), axis=(1, 2))
            pos, neg = distance[labels].min(), distance[~labels].min()
            hit = pos < 23 and pos < .92 * neg
        counts["detected" if positive else "false_positives"] += int(hit)
        if hit != positive:
            (missed if positive else false).append(p.name)
    if not counts["positives"] or not counts["negatives"]:
        raise ValueError("Missing held-out corpus")
    return dict(**counts, missed=missed, false=false)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    gen = sub.add_parser("synthesize")
    gen.add_argument("model", type=Path)
    gen.add_argument("folder", type=Path)
    bench = sub.add_parser("evaluate")
    bench.add_argument("--train", type=Path, nargs="+", required=True)
    bench.add_argument("--heldout", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "synthesize":
        synthesize(args.model, args.folder)
    else:
        if args.heldout.resolve() in [p.resolve() for p in args.train]:
            raise ValueError("Held-out speaker cannot be a training speaker")
        print(json.dumps(evaluate(args.train, args.heldout), indent=2))


if __name__ == "__main__":
    main()
