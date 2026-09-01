#!/usr/bin/env bash

set -eo pipefail

LABELER_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$LABELER_REPO_DIR/ros_domain_constants.sh"
LABELER_NAV_DIR="$LABELER_REPO_DIR/robot_navigation"
LABELER_QBOT_SETUP="$HOME/ros2/install/setup.bash"
LABELER_HOST="${QBOT_LABELER_HOST:-0.0.0.0}"
LABELER_PORT="${QBOT_LABELER_PORT:-8765}"

export ROS_DOMAIN_ID="$QBOT_ROS_DOMAIN_ID"

if [ ! -f /opt/ros/humble/setup.bash ]; then
    echo "ERROR: ROS Humble setup not found: /opt/ros/humble/setup.bash"
    exit 1
fi

if [ ! -f "$LABELER_QBOT_SETUP" ]; then
    echo "ERROR: QBot ROS workspace setup not found: $LABELER_QBOT_SETUP"
    exit 1
fi

source /opt/ros/humble/setup.bash
source "$LABELER_QBOT_SETUP"
if [ -f "$LABELER_NAV_DIR/install/setup.bash" ]; then
    source "$LABELER_NAV_DIR/install/setup.bash"
else
    echo "Navigation workspace is not built yet. Use Start Navigation or Rebuild in the website."
fi

echo "Starting QBot map labeler on ROS domain $ROS_DOMAIN_ID..."
echo "Open: http://ROBOT_IP:$LABELER_PORT"

exec python3 "$LABELER_NAV_DIR/tools/map_label_gui.py" \
    --host "$LABELER_HOST" \
    --port "$LABELER_PORT" \
    --ros-domain-id "$ROS_DOMAIN_ID" \
    "$@"
