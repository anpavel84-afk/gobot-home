#!/bin/bash
# Offline public-only CPU job; run under a bounded systemd transient service.
# Never installs a model or opens a Brain/provider session.
set -euo pipefail
stage=$(realpath "$1")
code=$(realpath "$2")
prefix="$3"
[[ "$prefix" =~ ^full-reference-[0-9]{8}$ ]] || exit 2
cd "$stage"
test ! -e "$prefix-gabot-model"
export PYTHONPATH="$stage/mww"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 TF_NUM_INTRAOP_THREADS=2 TF_NUM_INTEROP_THREADS=2
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
env/bin/python "$code/full_corpus.py" "$stage" "$stage/$prefix-corpus"
env/bin/python "$code/alias_corpus.py" "$stage" "$stage/$prefix-corpus" "$stage/$prefix-gabot-corpus" "$stage/$prefix-gabot-heldout"
# Two existing held-out synthetic voices: never used by the generator/trainer.
for voice in aleksandr elena; do
    test ! -e "$prefix-gabot-corpus/$voice"
    cp -a "variant-job-20261114/corpora/train/$voice" "$prefix-gabot-corpus/$voice"
done
env/bin/python "$code/train_reference.py" "$prefix-gabot-corpus" "$prefix-gabot-model" --expanded --word-anchored --full-corpus --steps 10000 --windows 102000
env/bin/python "$code/validate_reference.py" "$prefix-gabot-corpus" "$prefix-gabot-model" --kernel native_reference --alias-validation "$prefix-gabot-heldout"
echo 'Public training/evaluation complete; no installation or human acceptance implied.'
