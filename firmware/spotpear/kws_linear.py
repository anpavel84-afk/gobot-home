"""Small offline ridge-classifier baseline using the same quantized Russian speech frontend."""
import argparse
import json
from pathlib import Path
import numpy as np
from kws_bench import signature


def train(folders):
    rows, targets = [], []
    rng = np.random.default_rng(42)
    for folder in folders:
        for path in sorted(folder.glob("*.pcm")):
            pcm = np.fromfile(path, dtype="<i2").astype(float)
            for scale in (.80, .9, 1., 1.1, 1.2):
                warped = np.interp(np.arange(0, len(pcm), scale), np.arange(len(pcm)), pcm)
                for amplitude, noise in ((1., 0.), (.35, 25.)):
                    vector = signature(warped*amplitude + rng.normal(0, noise, len(warped)))
                    if vector is None:
                        continue
                    rows.append(vector.flatten()/100.)
                    targets.append(path.name.startswith("positive"))
    x, y = np.asarray(rows), np.asarray(targets)
    x = np.column_stack((x, np.ones(len(x))))
    weight = np.where(y, .5/y.sum(), .5/(~y).sum())
    regularizer = np.eye(x.shape[1]) * .003
    regularizer[-1,-1] = 0
    return np.linalg.solve((x.T*weight)@x + regularizer, (x.T*weight)@(y*2.-1))


def score(folder, model):
    hits = misses = false = rejected = 0
    for p in sorted(folder.glob("*.pcm")):
        vector = signature(np.fromfile(p, dtype="<i2"))
        detected = vector is not None and vector.flatten()@model[:-1]/100.+model[-1] >= .25
        if p.name.startswith("positive"):
            hits += int(detected)
            misses += int(not detected)
        else:
            false += int(detected)
            rejected += int(not detected)
    return dict(detected=hits, positives=hits+misses, false_positives=false, negatives=false+rejected)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--train", nargs="+", type=Path, required=True)
    parser.add_argument("--test", nargs="+", type=Path, required=True)
    parser.add_argument("--export", type=Path, help="write the experimental float32 weights locally")
    args = parser.parse_args()
    if set(p.resolve() for p in args.train) & set(p.resolve() for p in args.test):
        parser.error("use disjoint speaker folders")
    model = train(args.train)
    if args.export:
        model.astype("<f4").tofile(args.export)
    print(json.dumps({p.name:score(p, model) for p in args.test}, indent=2))
