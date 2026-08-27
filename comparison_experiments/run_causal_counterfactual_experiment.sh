#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# Adapted causal/counterfactual comparison launcher
#
# Usage:
#
#   Interactive:
#     ./run_causal_counterfactual_experiment.sh
#
#   One question:
#     ./run_causal_counterfactual_experiment.sh \
#         --session-id 20260827_014022_8d00 \
#         --role user \
#         --question "Why did localization fail?"
#
# This launcher:
#   - does NOT touch the main proposed system
#   - uses comparison_experiments/causal_counterfactual/
#   - reads the selected session's robot.db
# ============================================================

REPO_DIR="$HOME/ENGR857_Narayan_Shivangi/project/qbot-log-rag"
cd "$REPO_DIR"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

export ROS_DOMAIN_ID=57

SESSION_ID="latest"
QUESTION=""
ROLE="user"
SHOW_MODEL=0

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
        --role)
            ROLE="$2"
            shift 2
            ;;
        --show-model)
            SHOW_MODEL=1
            shift
            ;;
        -h|--help)
            echo
            echo "Usage:"
            echo "  ./run_causal_counterfactual_experiment.sh"
            echo
            echo "  ./run_causal_counterfactual_experiment.sh \\"
            echo "      --session-id SESSION_ID \\"
            echo "      --role user \\"
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

if [ "$ROLE" != "user" ] && [ "$ROLE" != "engineer" ]; then
    echo "Role must be: user or engineer"
    exit 2
fi

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

check_session_db() {
    local sid="$1"
    local db="runtime_logs/session_${sid}/robot.db"

    if [ ! -f "$db" ]; then
        echo
        echo "robot.db was not found for session:"
        echo "  $sid"
        echo
        echo "Expected:"
        echo "  $db"
        exit 1
    fi
}

ask_one() {
    local sid="$1"
    local q="$2"
    local role="$3"

    ensure_nvidia_key
    check_session_db "$sid"

    local args=(
        ./comparison_experiments/run_comparison.sh
        causal
        --session-id "$sid"
        --role "$role"
        --question "$q"
    )

    if [ "$SHOW_MODEL" -eq 1 ]; then
        args+=(--show-model)
    fi

    "${args[@]}"
}

SID="$(resolve_session)"

if [ -n "$QUESTION" ]; then
    ask_one "$SID" "$QUESTION" "$ROLE"
    exit 0
fi

echo
echo "============================================================"
echo "ADAPTED CAUSAL / COUNTERFACTUAL BASELINE"
echo "============================================================"
echo
echo "Session:"
echo "  $SID"
echo
echo "Role:"
echo "  $ROLE"
echo
echo "Type a question and press ENTER."
echo "Commands:"
echo "  /user                 user-facing explanation"
echo "  /engineer             engineer-facing explanation"
echo "  /session SESSION_ID   switch recorded session"
echo "  /model on             show causal model"
echo "  /model off            hide causal model"
echo "  exit                   quit"
echo

while true; do
    read -rp "causal> " q || break

    case "$q" in
        exit|quit|q)
            break
            ;;
        /user)
            ROLE="user"
            echo "Role changed to user."
            continue
            ;;
        /engineer)
            ROLE="engineer"
            echo "Role changed to engineer."
            continue
            ;;
        "/model on")
            SHOW_MODEL=1
            echo "Model display enabled."
            continue
            ;;
        "/model off")
            SHOW_MODEL=0
            echo "Model display disabled."
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

    ask_one "$SID" "$q" "$ROLE"
    echo
done
