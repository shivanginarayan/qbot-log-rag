#!/usr/bin/env bash

set -eu

UI_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$UI_DIR/.." && pwd)"

if [ -x "$REPO_DIR/.venv/bin/python3" ]; then
    QBOT_UI_PYTHON="$REPO_DIR/.venv/bin/python3"
else
    QBOT_UI_PYTHON="$(command -v python3 || true)"
fi

if [ -z "$QBOT_UI_PYTHON" ]; then
    echo "ERROR: python3 was not found."
    exit 1
fi

if ! "$QBOT_UI_PYTHON" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 8) else 1)'; then
    echo "ERROR: The QBot chat UI requires Python 3.8 or newer."
    exit 1
fi

if ! "$QBOT_UI_PYTHON" -c 'import requests'; then
    echo "ERROR: The existing QBot RAG command requires the requests package."
    echo "Install a Python 3.8-compatible requests release, then try again."
    exit 1
fi

if [ -z "${NVIDIA_API_KEY:-}" ]; then
    if [ -t 0 ]; then
        echo "NVIDIA_API_KEY is not set for this UI process."
        read -rsp "Enter NVIDIA API key (input is hidden): " NVIDIA_API_KEY
        echo
        export NVIDIA_API_KEY
    else
        echo "WARNING: NVIDIA_API_KEY is not set; LLM questions will fail."
    fi
fi

export PYTHONDONTWRITEBYTECODE=1

echo "Starting the independent QBot session chat UI..."
echo "The full experiment should be running in another terminal."

exec "$QBOT_UI_PYTHON" -B "$UI_DIR/server.py" "$@"
