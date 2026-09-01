#!/usr/bin/env bash
set -euo pipefail
REPO_DIR="$HOME/ENGR857_Narayan_Shivangi/project/qbot-log-rag"
source "$REPO_DIR/ros_domain_constants.sh"
cd "$REPO_DIR"
[ -f .venv/bin/activate ] && source .venv/bin/activate
export ROS_DOMAIN_ID="$QBOT_ROS_DOMAIN_ID"
exec python comparison_experiments/causal_explanation/live_causal_logger.py "$@"
