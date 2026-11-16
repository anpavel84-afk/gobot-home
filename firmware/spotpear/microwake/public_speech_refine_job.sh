#!/bin/bash
set -euo pipefail
stage=$(realpath "$1")
code=$(realpath "$2")
cd "$stage"
export PYTHONPATH="$stage/mww" OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 TF_NUM_INTRAOP_THREADS=2 TF_NUM_INTEROP_THREADS=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
base=full-reference-20261115
test ! -e "$base-speech-refined-model"
test ! -e "$base-speech-refined-hard.npy"
env/bin/python "$code/mine_reference.py" "$base-gabot-corpus" "$base-speech-model" "$base-speech-refined-hard.npy" --kernel native_reference
env/bin/python "$code/refine_continuous.py" "$base-speech-model" "$base-speech-refined-hard.npy" "$base-speech-refined-model" --phonetic-replay "$base-phonetic.npy"
env/bin/python "$code/validate_reference.py" "$base-gabot-corpus" "$base-speech-refined-model" --kernel native_reference --alias-validation "$base-gabot-heldout" --public-speech-validation public-speech-20261115
