#!/usr/bin/env bash

set -eo pipefail
umask 077

CHAT_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$CHAT_REPO_DIR/ros_domain_constants.sh"
CHAT_HOST="${QBOT_CHAT_HOST:-0.0.0.0}"
CHAT_PORT="${QBOT_CHAT_PORT:-8766}"
CHAT_LOG_FILE="${QBOT_CHAT_LOG_FILE:-$CHAT_REPO_DIR/runtime_logs/private_chat/qbot_chat_history.xlsx}"
CHAT_EMBED_LOG="$CHAT_REPO_DIR/runtime_logs/qbot_embedding_server.log"

export ROS_DOMAIN_ID="$QBOT_ROS_DOMAIN_ID"
export HF_HOME="${QBOT_CHAT_HF_HOME:-$CHAT_REPO_DIR/runtime_logs/huggingface}"
export TRANSFORMERS_CACHE="$HF_HOME/transformers"

cd "$CHAT_REPO_DIR"

if [ -x "$CHAT_REPO_DIR/shivangi/bin/python3" ]; then
    CHAT_PYTHON="$CHAT_REPO_DIR/shivangi/bin/python3"
elif [ -x "$CHAT_REPO_DIR/.venv/bin/python3" ]; then
    CHAT_PYTHON="$CHAT_REPO_DIR/.venv/bin/python3"
else
    CHAT_PYTHON="$(command -v python3 || true)"
fi

if [ -z "$CHAT_PYTHON" ]; then
    echo "ERROR: python3 was not found."
    exit 1
fi

if ! "$CHAT_PYTHON" -c "import sentence_transformers" >/dev/null 2>&1; then
    echo "ERROR: sentence-transformers is not installed for $CHAT_PYTHON"
    echo "Run the install command in QBOT_CHAT_UI.md."
    exit 1
fi

if [ -z "${NVIDIA_API_KEY:-}" ]; then
    echo "WARNING: NVIDIA_API_KEY is not set."
    echo "The UI will open, but online LLM requests will fail until it is exported."
fi

echo "Starting QBot RAG chat UI on ROS domain $ROS_DOMAIN_ID..."
echo "Open: http://ROBOT_IP:$CHAT_PORT"
echo "Excel log: $CHAT_LOG_FILE"

mkdir -p "$CHAT_REPO_DIR/runtime_logs" "$HF_HOME"

CHAT_EMBED_PID=""

stop_embedding_server() {
    if [ -n "$CHAT_EMBED_PID" ] && kill -0 "$CHAT_EMBED_PID" 2>/dev/null; then
        kill -TERM "$CHAT_EMBED_PID" 2>/dev/null || true
        wait "$CHAT_EMBED_PID" 2>/dev/null || true
    fi
}

trap stop_embedding_server EXIT INT TERM

if ! curl --silent --fail --max-time 2 \
    http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "Starting the local BGE-M3 embedding service..."
    echo "The first run downloads and caches the model; this can take several minutes."

    "$CHAT_PYTHON" -u "$CHAT_REPO_DIR/src/local_embedding_server.py" \
        --host 127.0.0.1 \
        --port 11434 \
        >"$CHAT_EMBED_LOG" 2>&1 &
    CHAT_EMBED_PID=$!

    CHAT_EMBED_READY=0

    for CHAT_EMBED_ATTEMPT in $(seq 1 300); do
        if curl --silent --fail --max-time 2 \
            http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
            CHAT_EMBED_READY=1
            break
        fi

        if ! kill -0 "$CHAT_EMBED_PID" 2>/dev/null; then
            echo "ERROR: The embedding service stopped during startup."
            tail -n 30 "$CHAT_EMBED_LOG" 2>/dev/null || true
            exit 1
        fi

        if [ $((CHAT_EMBED_ATTEMPT % 10)) -eq 0 ]; then
            echo "Still loading BGE-M3..."
        fi

        sleep 2
    done

    if [ "$CHAT_EMBED_READY" -ne 1 ]; then
        echo "ERROR: Timed out waiting for the embedding service."
        tail -n 30 "$CHAT_EMBED_LOG" 2>/dev/null || true
        exit 1
    fi
fi

if ! curl --silent --fail --max-time 120 \
    --request POST \
    --header "Content-Type: application/json" \
    --data '{"model":"bge-m3","input":"QBot readiness check"}' \
    http://127.0.0.1:11434/api/embed >/dev/null; then
    echo "ERROR: Port 11434 is active, but bge-m3 embedding failed."
    tail -n 30 "$CHAT_EMBED_LOG" 2>/dev/null || true
    exit 1
fi

echo "Embedding service ready."

"$CHAT_PYTHON" "$CHAT_REPO_DIR/src/chat_ui.py" \
    --host "$CHAT_HOST" \
    --port "$CHAT_PORT" \
    --log-file "$CHAT_LOG_FILE" \
    "$@"
