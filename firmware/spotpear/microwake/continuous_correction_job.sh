#!/bin/bash
set -euo pipefail
stage=$(realpath "$1")
code=$(realpath "$2")
mode=${3:-continuous}
[[ "$mode" == continuous || "$mode" == balanced ]] || exit 2
mine_flags=()
train_flags=()
if [[ "$mode" == balanced ]]; then mine_flags=(--complete); train_flags=(--alias-balanced); fi
cd "$stage"
export PYTHONPATH="$stage/mww" OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 TF_NUM_INTRAOP_THREADS=2 TF_NUM_INTEROP_THREADS=1
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
base=full-reference-20261115
test ! -e "$base-$mode-model"
test ! -e "$base-$mode-hard.npy"
env/bin/python "$code/mine_reference.py" "$base-gabot-corpus" "$base-gabot-model" "$base-$mode-hard.npy" --kernel native_reference "${mine_flags[@]}"
env/bin/python "$code/refine_continuous.py" "$base-gabot-model" "$base-$mode-hard.npy" "$base-$mode-model" "${train_flags[@]}"
env/bin/python "$code/validate_reference.py" "$base-gabot-corpus" "$base-$mode-model" --kernel native_reference --alias-validation "$base-gabot-heldout"
