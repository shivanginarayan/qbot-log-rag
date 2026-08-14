#!/usr/bin/env bash

set -e

NAV_DIR="$HOME/ENGR857_Narayan_Shivangi/project/navigation"
MAP_DIR="$NAV_DIR/maps/home_test_v1"
MAP="$MAP_DIR/home_test_v1.yaml"
LABELS="$MAP_DIR/home_test_v1_labels.json"

export ROS_DOMAIN_ID=57

echo "=========================================="
echo " QBot Navigation"
echo " ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
echo " Map: $MAP"
echo "=========================================="

source /opt/ros/humble/setup.bash
source "$HOME/ros2/install/setup.bash"
source "$NAV_DIR/install/setup.bash"

cleanup() {
    echo
    echo "Stopping QBot navigation..."
    kill "$NAV_PID" 2>/dev/null || true
    wait "$NAV_PID" 2>/dev/null || true
}

trap cleanup INT TERM EXIT

ros2 launch qbot_platform \
    qbot_platform_map_nav_bringup_launch.py \
    map:="$MAP" \
    labels_file:="$LABELS" \
    use_scan_filter:=true \
    use_breadcrumb_return:=false &

NAV_PID=$!

echo "Navigation started with PID $NAV_PID"
echo "Waiting for AMCL..."

until ros2 node list 2>/dev/null | grep -qx "/amcl"; do
    sleep 1
done

echo
echo "QBot navigation is ready."
echo
echo "Useful commands:"
echo
echo "  Global localization:"
echo "    ros2 service call /reinitialize_global_localization std_srvs/srv/Empty \"{}\""
echo
echo "  Go home:"
echo "    ros2 run qbot_platform go_to_label.py gohome --labels-file $LABELS"
echo
echo "  Current location:"
echo "    ros2 topic echo /amcl_pose --once"
echo
echo "Press Ctrl+C here to stop the navigation stack."
echo

wait "$NAV_PID"
