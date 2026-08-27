#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Explaining-Autonomy-style comparison launcher
#
# Usage:
#
#   Interactive:
#     ./run_explaining_autonomy_experiment.sh
#
#   One question:
#     ./run_explaining_autonomy_experiment.sh \
#         --session-id 20260827_014022_8d00 \
#         --question "Why did localization fail?"
#
# This launcher:
#   - does NOT touch the main proposed system
#   - uses comparison_experiments/explaining_autonomy/
#   - auto-builds the /rosout RAG index if missing
#   - uses the same recorded session ID
# ============================================================

REPO_DIR="$HOME/ENGR857_Narayan_Shivangi/project/qbot-log-rag"
cd "$REPO_DIR"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

export ROS_DOMAIN_ID=57

SESSION_ID="latest"
QUESTION=""
TOP_K="12"
SHOW_RETRIEVAL=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --session-id)
            SESSION_ID="$2"
            shift 2
            ;;
        --question)
            QUESTION="$2"
            shift 2
            ;;
        --top-k)
            TOP_K="$2"
            shift 2
            ;;
        --show-retrieval)
            SHOW_RETRIEVAL=1
            shift
            ;;
        -h|--help)
            echo
            echo "Usage:"
            echo "  ./run_explaining_autonomy_experiment.sh"
            echo
            echo "  ./run_explaining_autonomy_experiment.sh \\"
            echo "      --session-id SESSION_ID \\"
            echo "      --question \"Why did localization fail?\""
            echo
            exit 0
            ;;
        *)
            echo "Unknown argument: $1"
            exit 2
            ;;
    esac
done

resolve_session() {
    if [ "$SESSION_ID" != "latest" ]; then
        printf '%s\n' "$SESSION_ID"
        return
    fi

    local latest
    latest="$(
        find runtime_logs -maxdepth 1 -type d -name 'session_*' \
            | sort \
            | tail -1 \
            | sed 's|.*/session_||'
    )"

    if [ -z "$latest" ]; then
        echo "No runtime_logs/session_* session was found." >&2
        exit 1
    fi

    printf '%s\n' "$latest"
}

ensure_nvidia_key() {
    if [ -n "${NVIDIA_API_KEY:-}" ]; then
        return
    fi

    echo
    read -rsp "Enter NVIDIA API key: " NVIDIA_API_KEY
    echo
    export NVIDIA_API_KEY
}

ensure_index() {
    local sid="$1"

    local index_path
    index_path="comparison_experiments/runtime/explaining_autonomy/${sid}_rosout_embeddings.json"

    if [ -f "$index_path" ]; then
        return
    fi

    local bag_dir
    bag_dir="comparison_experiments/runtime/rosout_bags/session_${sid}/rosout"

    if [ ! -d "$bag_dir" ]; then
        echo
        echo "No /rosout comparison recording exists for session:"
        echo "  $sid"
        echo
        echo "Expected:"
        echo "  $bag_dir"
        echo
        echo "Record /rosout during the robot run with ROS_DOMAIN_ID=57."
        exit 1
    fi

    echo
    echo "No /rosout RAG index exists yet."
    echo "Building it now..."
    echo

    ./comparison_experiments/run_comparison.sh \
        rosout-build \
        --session-id "$sid"
}

ask_one() {
    local sid="$1"
    local q="$2"

    ensure_nvidia_key
    ensure_index "$sid"

    local args=(
        ./comparison_experiments/run_comparison.sh
        rosout
        --session-id "$sid"
        --question "$q"
        --top-k "$TOP_K"
    )

    if [ "$SHOW_RETRIEVAL" -eq 1 ]; then
        args+=(--show-retrieval)
    fi

    "${args[@]}"
}

SID="$(resolve_session)"

if [ -n "$QUESTION" ]; then
    ask_one "$SID" "$QUESTION"
    exit 0
fi

echo
echo "============================================================"
echo "EXPLAINING-AUTONOMY-STYLE /ROSOUT RAG"
echo "============================================================"
echo
echo "Session:"
echo "  $SID"
echo
echo "Type a question and press ENTER."
echo "Commands:"
echo "  /session SESSION_ID   switch recorded session"
echo "  /retrieval on         show retrieved ROS logs"
echo "  /retrieval off        hide retrieved ROS logs"
echo "  exit                   quit"
echo

while true; do
    read -rp "rosout-rag> " q || break

    case "$q" in
        exit|quit|q)
            break
            ;;
        "/retrieval on")
            SHOW_RETRIEVAL=1
            echo "Retrieved-log display enabled."
            continue
            ;;
        "/retrieval off")
            SHOW_RETRIEVAL=0
            echo "Retrieved-log display disabled."
            continue
            ;;
        /session\ *)
            SID="${q#"/session "}"
            echo "Session changed to: $SID"
            continue
            ;;
        "")
            continue
            ;;
    esac

    ask_one "$SID" "$q"
    echo
done
