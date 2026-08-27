#!/usr/bin/env bash

set -e

if [ -z "$1" ]; then
    echo "Usage:"
    echo "  ./src/storage/record_rosbag.sh <SESSION_ID>"
    exit 1
fi

SESSION_ID="$1"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

SESSION_DIR="$REPO_DIR/runtime_logs/session_${SESSION_ID}"

BAG_DIR="$SESSION_DIR/rosbag"

if [ ! -d "$SESSION_DIR" ]; then
    echo "ERROR: session directory does not exist:"
    echo "$SESSION_DIR"
    exit 1
fi

if [ -e "$BAG_DIR" ]; then
    echo "ERROR: rosbag output already exists:"
    echo "$BAG_DIR"
    echo "Use a fresh session or remove that directory before recording."
    exit 1
fi

source /opt/ros/humble/setup.bash

if [ -f "$HOME/ros2/install/setup.bash" ]; then
    source "$HOME/ros2/install/setup.bash"
fi

if [ -f "$REPO_DIR/robot_navigation/install/setup.bash" ]; then
    source "$REPO_DIR/robot_navigation/install/setup.bash"
fi

export ROS_DOMAIN_ID=63

echo
echo "Recording raw ROS evidence"
echo "Session: $SESSION_ID"
echo "Output:  $BAG_DIR"
echo
echo "Press Ctrl+C to stop recording cleanly."
echo

ros2 bag record \
    -o "$BAG_DIR" \
    /scan \
    /scan_filtered \
    /odom \
    /amcl_pose \
    /cmd_vel \
    /tf \
    /tf_static \
    /controller/lb_held \
    /cmd_vel_teleop \
    /cmd_vel_behavior \
    /cmd_vel_auto \
    /robot/navigation_control_state \
    /robot/manual_assistance_status
