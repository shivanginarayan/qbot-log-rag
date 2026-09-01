#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$HOME/ENGR857_Narayan_Shivangi/project/qbot-log-rag"
source "$REPO_DIR/ros_domain_constants.sh"
cd "$REPO_DIR"

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

export ROS_DOMAIN_ID="$QBOT_ROS_DOMAIN_ID"

echo
echo "============================================================"
echo "EXPLAINING AUTONOMY — PERSISTENT /ROSOUT MEMORY"
echo "============================================================"
echo
echo "ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo
echo "This process continuously appends live /rosout messages"
echo "to the same persistent corpus that contains prior logs."
echo
echo "Ask questions from the UI or another terminal with:"
echo
echo '  ./comparison_experiments/run_comparison.sh rosout \'
echo '      --question "What is happening?"'
echo
echo "Press Ctrl+C to stop live accumulation."
echo

exec python \
    comparison_experiments/explaining_autonomy/live_rosout_index.py \
    "$@"
