#!/usr/bin/env bash

# Source this file so the exported ROS environment remains in your terminal:
#   source ./setup_qbot_terminal.sh

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    echo "This script must be sourced, not executed:"
    echo "  source ./setup_qbot_terminal.sh"
    exit 2
fi

QBOT_ENV_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
QBOT_ENV_NAV_DIR="$QBOT_ENV_REPO_DIR/robot_navigation"
QBOT_ENV_DRIVER_SETUP="$HOME/ros2/install/setup.bash"

if [ ! -f /opt/ros/humble/setup.bash ]; then
    echo "ERROR: ROS Humble setup not found: /opt/ros/humble/setup.bash"
    return 1
fi

if [ ! -f "$QBOT_ENV_DRIVER_SETUP" ]; then
    echo "ERROR: QBot ROS workspace setup not found: $QBOT_ENV_DRIVER_SETUP"
    return 1
fi

if [ ! -f "$QBOT_ENV_NAV_DIR/install/setup.bash" ]; then
    echo "ERROR: Navigation workspace is not built. Run:"
    echo "  ./rebuild_qbot_navigation.sh"
    return 1
fi

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-63}"
source /opt/ros/humble/setup.bash
source "$QBOT_ENV_DRIVER_SETUP"
source "$QBOT_ENV_NAV_DIR/install/setup.bash"
cd "$QBOT_ENV_REPO_DIR"

echo "QBot terminal ready."
echo "Repository:    $QBOT_ENV_REPO_DIR"
echo "ROS_DOMAIN_ID: $ROS_DOMAIN_ID"

unset QBOT_ENV_REPO_DIR QBOT_ENV_NAV_DIR QBOT_ENV_DRIVER_SETUP
