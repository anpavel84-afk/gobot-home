#!/bin/bash
# Run AFTER bounded public_speech.py preparation; no network/provider/flash.
set -euo pipefail
stage=$(realpath "$1")
code=$(realpath "$2")
cd "$stage"
export PYTHONPATH="$stage/mww" OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 TF_NUM_INTRAOP_THREADS=2 TF_NUM_INTEROP_THREADS=2
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
base=full-reference-20261115
test ! -e "$base-speech-model"
env/bin/python "$code/train_reference.py" "$base-gabot-corpus" "$base-speech-model" --expanded --word-anchored --full-corpus --steps 10000 --windows 102000 --cache "$base-gabot-model" --speech-replay public-speech-20261115/training.npy
env/bin/python "$code/validate_reference.py" "$base-gabot-corpus" "$base-speech-model" --kernel native_reference --alias-validation "$base-gabot-heldout" --public-speech-validation public-speech-20261115
