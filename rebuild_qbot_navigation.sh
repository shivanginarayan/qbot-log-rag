#!/usr/bin/env bash

set -eo pipefail

REBUILD_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REBUILD_NAV_DIR="$REBUILD_REPO_DIR/robot_navigation"
REBUILD_QBOT_SETUP="$HOME/ros2/install/setup.bash"

export ROS_DOMAIN_ID=57

if [ ! -f /opt/ros/humble/setup.bash ]; then
    echo "ERROR: ROS Humble setup not found: /opt/ros/humble/setup.bash"
    exit 1
fi

if [ ! -f "$REBUILD_QBOT_SETUP" ]; then
    echo "ERROR: QBot ROS workspace setup not found: $REBUILD_QBOT_SETUP"
    exit 1
fi

if [ ! -d "$REBUILD_NAV_DIR/src/qbot_platform" ]; then
    echo "ERROR: qbot_platform source not found: $REBUILD_NAV_DIR/src/qbot_platform"
    exit 1
fi

source /opt/ros/humble/setup.bash
source "$REBUILD_QBOT_SETUP"

cd "$REBUILD_NAV_DIR"
echo "Building qbot_platform in $REBUILD_NAV_DIR (ROS domain $ROS_DOMAIN_ID)..."
colcon build \
    --packages-select qbot_platform \
    "$@" \
    --cmake-args -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
touch "$REBUILD_NAV_DIR/install/.qbot_platform_source_stamp"
source "$REBUILD_NAV_DIR/install/setup.bash"

echo
echo "Build complete. Restart navigation to load the changes."
