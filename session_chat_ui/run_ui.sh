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

export PYTHONDONTWRITEBYTECODE=1

echo "Starting the independent QBot session chat UI..."
echo "Enter the NVIDIA API key in the UI opened at localhost."

exec "$QBOT_UI_PYTHON" -B "$UI_DIR/server.py" "$@"
