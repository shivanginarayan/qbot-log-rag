#!/usr/bin/env bash

set -eo pipefail

MAPPING_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MAPPING_NAV_DIR="$MAPPING_REPO_DIR/robot_navigation"
MAPPING_QBOT_SETUP="$HOME/ros2/install/setup.bash"
MAPPING_SCAN_FILTER="$MAPPING_NAV_DIR/filters/scan_wedge_filter.json"
MAPPING_RESOLUTION="0.01"
MAPPING_PUBLISH_PERIOD="1.0"
MAPPING_LABEL_TOPIC="/mapping/drop_label"
MAPPING_LABEL_BUTTON_BIT="1"
MAPPING_BUILD_STAMP="$MAPPING_NAV_DIR/install/.qbot_platform_source_stamp"

usage() {
    echo "Usage: $0 [--scan-filter-file FILTER.json] [--resolution METERS] [--publish-period SECONDS] [--label-topic TOPIC] [--label-button-bit BIT]"
    echo
    echo "Starts physical QBot manual Cartographer mapping with the gamepad controller."
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --scan-filter-file)
            [ "$#" -ge 2 ] || { echo "ERROR: --scan-filter-file requires a path"; usage; exit 2; }
            MAPPING_SCAN_FILTER="$2"
            shift 2
            ;;
        --resolution)
            [ "$#" -ge 2 ] || { echo "ERROR: --resolution requires a value"; usage; exit 2; }
            MAPPING_RESOLUTION="$2"
            shift 2
            ;;
        --publish-period)
            [ "$#" -ge 2 ] || { echo "ERROR: --publish-period requires a value"; usage; exit 2; }
            MAPPING_PUBLISH_PERIOD="$2"
            shift 2
            ;;
        --label-topic)
            [ "$#" -ge 2 ] || { echo "ERROR: --label-topic requires a value"; usage; exit 2; }
            MAPPING_LABEL_TOPIC="$2"
            shift 2
            ;;
        --label-button-bit)
            [ "$#" -ge 2 ] || { echo "ERROR: --label-button-bit requires a value"; usage; exit 2; }
            MAPPING_LABEL_BUTTON_BIT="$2"
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "ERROR: Unknown argument: $1"
            usage
            exit 2
            ;;
    esac
done

case "$MAPPING_LABEL_BUTTON_BIT" in
    ''|*[!0-9]*)
        echo "ERROR: --label-button-bit must be an integer between 0 and 31"
        exit 2
        ;;
esac
if [ "$MAPPING_LABEL_BUTTON_BIT" -gt 31 ]; then
    echo "ERROR: --label-button-bit must be between 0 and 31"
    exit 2
fi
if [ ! -f /opt/ros/humble/setup.bash ]; then
    echo "ERROR: ROS Humble setup not found: /opt/ros/humble/setup.bash"
    exit 1
fi
if [ ! -f "$MAPPING_QBOT_SETUP" ]; then
    echo "ERROR: QBot ROS workspace setup not found: $MAPPING_QBOT_SETUP"
    exit 1
fi
if [ ! -d "$MAPPING_NAV_DIR/src/qbot_platform" ]; then
    echo "ERROR: qbot_platform source not found: $MAPPING_NAV_DIR/src/qbot_platform"
    exit 1
fi
if [ ! -f "$MAPPING_SCAN_FILTER" ]; then
    echo "ERROR: scan filter file not found: $MAPPING_SCAN_FILTER"
    exit 1
fi

MAPPING_SCAN_FILTER="$(realpath "$MAPPING_SCAN_FILTER")"
export ROS_DOMAIN_ID=57

source /opt/ros/humble/setup.bash
source "$MAPPING_QBOT_SETUP"

MAPPING_NEEDS_BUILD=false
if [ ! -f "$MAPPING_NAV_DIR/install/setup.bash" ] || [ ! -f "$MAPPING_BUILD_STAMP" ]; then
    MAPPING_NEEDS_BUILD=true
elif find "$MAPPING_NAV_DIR/src/qbot_platform" -type f ! -path '*/__pycache__/*' -newer "$MAPPING_BUILD_STAMP" -print -quit | grep -q .; then
    MAPPING_NEEDS_BUILD=true
fi

if [ "$MAPPING_NEEDS_BUILD" = true ]; then
    echo "qbot_platform is missing or out of date. Building it now..."
    cd "$MAPPING_NAV_DIR"
    colcon build \
        --packages-select qbot_platform \
        --cmake-args -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
    touch "$MAPPING_BUILD_STAMP"
fi
source "$MAPPING_NAV_DIR/install/setup.bash"
cd "$MAPPING_REPO_DIR"

echo "=========================================="
echo " QBot Manual Mapping"
echo "=========================================="
echo "ROS_DOMAIN_ID: $ROS_DOMAIN_ID"
echo "Resolution:    $MAPPING_RESOLUTION m/pixel"
echo "Map publish:   every $MAPPING_PUBLISH_PERIOD sec"
echo "Scan filter:   $MAPPING_SCAN_FILTER"
echo "Controller:    hold LB to enable motion"
echo "Drop label:    release LB, then press B (button bit $MAPPING_LABEL_BUTTON_BIT)"
echo "=========================================="

MAPPING_PID=""
cleanup() {
    if [ -n "$MAPPING_PID" ]; then
        echo
        echo "Stopping QBot mapping..."
        kill "$MAPPING_PID" 2>/dev/null || true
        wait "$MAPPING_PID" 2>/dev/null || true
        MAPPING_PID=""
    fi
}
trap cleanup INT TERM EXIT

ros2 launch qbot_platform qbot_platform_manual_map_launch.py \
    resolution:="$MAPPING_RESOLUTION" \
    publish_period_sec:="$MAPPING_PUBLISH_PERIOD" \
    scan_filter_file:="$MAPPING_SCAN_FILTER" \
    mapping_label_topic:="$MAPPING_LABEL_TOPIC" \
    mapping_label_button_bit:="$MAPPING_LABEL_BUTTON_BIT" \
    use_scan_filter:=true &

MAPPING_PID=$!
echo "Mapping process started with PID: $MAPPING_PID"
echo "Drive manually with the QBot gamepad. Release LB to stop motion."
echo "With LB released, press B once to drop label1, label2, and so on."
echo "Use Finish & Save or Cancel Mapping in the website."

set +e
wait "$MAPPING_PID"
MAPPING_EXIT_CODE=$?
set -e
MAPPING_PID=""
exit "$MAPPING_EXIT_CODE"
