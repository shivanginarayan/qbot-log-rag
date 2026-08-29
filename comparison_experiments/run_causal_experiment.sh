#!/usr/bin/env bash
set -euo pipefail
cd "$HOME/ENGR857_Narayan_Shivangi/project/qbot-log-rag"
[ -f .venv/bin/activate ] && source .venv/bin/activate
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-57}"
exec python comparison_experiments/causal_explanation/live_causal_logger.py "$@"
