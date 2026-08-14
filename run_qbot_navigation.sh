#!/usr/bin/env bash

set -e

# ------------------------------------------------------------
# Paths
# ------------------------------------------------------------

# Directory containing this script = qbot-log-rag repository
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Navigation ROS2 workspace stored inside this repository
NAV_DIR="$REPO_DIR/robot_navigation"

MAP_DIR="$NAV_DIR/maps/home_test_v1"
MAP="$MAP_DIR/home_test_v1.yaml"
LABELS="$MAP_DIR/home_test_v1_labels.json"

export ROS_DOMAIN_ID=57


# ------------------------------------------------------------
# Display configuration
# ------------------------------------------------------------

echo "=========================================="
echo " QBot Navigation"
echo "=========================================="
echo "Repository:    $REPO_DIR"
echo "Navigation WS: $NAV_DIR"
echo "ROS_DOMAIN_ID: $ROS_DOMAIN_ID"
echo "Map:           $MAP"
echo "Labels:        $LABELS"
echo "=========================================="


# ------------------------------------------------------------
# Check required files
# ------------------------------------------------------------

if [ ! -d "$NAV_DIR/src/qbot_platform" ]; then
    echo "ERROR: qbot_platform source not found:"
    echo "  $NAV_DIR/src/qbot_platform"
    exit 1
fi

if [ ! -f "$MAP" ]; then
    echo "ERROR: map not found:"
    echo "  $MAP"
    exit 1
fi

if [ ! -f "$LABELS" ]; then
    echo "ERROR: labels file not found:"
    echo "  $LABELS"
    exit 1
fi


# ------------------------------------------------------------
# Source ROS2
# ------------------------------------------------------------

source /opt/ros/humble/setup.bash

# QBot/Quanser ROS workspace installed on the robot
if [ -f "$HOME/ros2/install/setup.bash" ]; then
    source "$HOME/ros2/install/setup.bash"
else
    echo "ERROR: QBot ROS2 workspace not found:"
    echo "  $HOME/ros2/install/setup.bash"
    exit 1
fi


# ------------------------------------------------------------
# Build navigation workspace if this is a fresh clone
# ------------------------------------------------------------

if [ ! -f "$NAV_DIR/install/setup.bash" ]; then
    echo
    echo "Navigation workspace has not been built yet."
    echo "Building qbot_platform..."
    echo

    cd "$NAV_DIR"

    colcon build --packages-select qbot_platform

    echo
    echo "Navigation workspace built successfully."
fi


# ------------------------------------------------------------
# Source our navigation workspace
# ------------------------------------------------------------

source "$NAV_DIR/install/setup.bash"


# ------------------------------------------------------------
# Cleanup
# ------------------------------------------------------------

NAV_PID=""

cleanup() {
    echo
    echo "Stopping QBot navigation..."

    if [ -n "$NAV_PID" ]; then
        kill "$NAV_PID" 2>/dev/null || true
        wait "$NAV_PID" 2>/dev/null || true
    fi
}

trap cleanup INT TERM EXIT


# ------------------------------------------------------------
# Launch navigation
# ------------------------------------------------------------

echo
echo "Starting QBot navigation..."
echo

ros2 launch qbot_platform \
    qbot_platform_map_nav_bringup_launch.py \
    map:="$MAP" \
    labels_file:="$LABELS" \
    use_scan_filter:=true \
    use_breadcrumb_return:=false &

NAV_PID=$!


# ------------------------------------------------------------
# Wait for AMCL
# ------------------------------------------------------------

echo "Navigation process PID: $NAV_PID"
echo "Waiting for AMCL..."

until ros2 node list 2>/dev/null | grep -qx "/amcl"; do

    if ! kill -0 "$NAV_PID" 2>/dev/null; then
        echo
        echo "ERROR: navigation process exited before AMCL started."
        exit 1
    fi

    sleep 1
done


# ------------------------------------------------------------
# Ready
# ------------------------------------------------------------

echo
echo "=========================================="
echo " QBot navigation is ready"
echo "=========================================="
echo
echo "Global localization:"
echo
echo '  ros2 service call /reinitialize_global_localization std_srvs/srv/Empty "{}"'
echo
echo "Go home:"
echo
echo "  ros2 run qbot_platform go_to_label.py gohome \\"
echo "    --labels-file \"$LABELS\""
echo
echo "Current location:"
echo
echo "  ros2 topic echo /amcl_pose --once"
echo
echo "Press Ctrl+C here to stop the navigation stack."
echo

wait "$NAV_PID"