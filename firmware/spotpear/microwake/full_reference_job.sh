#!/bin/bash
# Offline public-only CPU job; run under a bounded systemd transient service.
# Never installs a model or opens a Brain/provider session.
set -euo pipefail
stage=$(realpath "$1")
code=$(realpath "$2")
prefix="$3"
[[ "$prefix" =~ ^full-reference-[0-9]{8}$ ]] || exit 2
cd "$stage"
test ! -e "$prefix-model"
export PYTHONPATH="$stage/mww"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 TF_NUM_INTRAOP_THREADS=2 TF_NUM_INTEROP_THREADS=2
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
env/bin/python "$code/full_corpus.py" "$stage" "$stage/$prefix-corpus"
# Two existing held-out synthetic voices: never used by the generator/trainer.
for voice in aleksandr elena; do
    test ! -e "$prefix-corpus/$voice"
    cp -a "variant-job-20261114/corpora/train/$voice" "$prefix-corpus/$voice"
done
env/bin/python "$code/train_reference.py" "$prefix-corpus" "$prefix-model" --expanded --word-anchored --full-corpus --steps 10000 --windows 100000
env/bin/python "$code/validate_reference.py" "$prefix-corpus" "$prefix-model" --kernel native_reference
echo 'Public training/evaluation complete; no installation or human acceptance implied.'
