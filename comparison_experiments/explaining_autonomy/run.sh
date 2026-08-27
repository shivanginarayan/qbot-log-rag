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

if [ "$#" -lt 1 ]; then
    echo "Use: build or ask"
    exit 1
fi

MODE="$1"
shift

case "$MODE" in
    build)
        exec python \
            comparison_experiments/explaining_autonomy/build_rosout_index.py \
            "$@"
        ;;
    ask)
        exec python \
            comparison_experiments/explaining_autonomy/ask_rosout_rag.py \
            "$@"
        ;;
    *)
        echo "Unknown mode: $MODE"
        exit 2
        ;;
esac
