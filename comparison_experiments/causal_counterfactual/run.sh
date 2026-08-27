#!/usr/bin/env bash
set -e

HERE="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
    pwd
)"
REPO_DIR="$(
    cd "$HERE/../.." >/dev/null 2>&1
    pwd
)"
cd "$REPO_DIR"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

exec python \
    comparison_experiments/causal_counterfactual/ask_causal_counterfactual.py \
    "$@"
