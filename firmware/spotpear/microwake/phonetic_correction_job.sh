#!/bin/bash
set -euo pipefail
stage=$(realpath "$1")
code=$(realpath "$2")
cd "$stage"
export PYTHONPATH="$stage/mww" OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 TF_NUM_INTRAOP_THREADS=2 TF_NUM_INTEROP_THREADS=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
base=full-reference-20261115
test ! -e "$base-phonetic-model"
test ! -e "$base-phonetic.npy"
test ! -e "$base-phonetic-hard.npy"
env/bin/python "$code/phonetic_replay.py" "$base-gabot-corpus" "$base-gabot-model" "$base-phonetic.npy"
env/bin/python "$code/mine_reference.py" "$base-gabot-corpus" "$base-gabot-model" "$base-phonetic-hard.npy" --kernel native_reference
env/bin/python "$code/refine_continuous.py" "$base-gabot-model" "$base-phonetic-hard.npy" "$base-phonetic-model" --phonetic-replay "$base-phonetic.npy"
env/bin/python "$code/validate_reference.py" "$base-gabot-corpus" "$base-phonetic-model" --kernel native_reference --alias-validation "$base-gabot-heldout"
