#!/usr/bin/env bash

set -eo pipefail

RUN_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUN_NAV_DIR="$RUN_REPO_DIR/robot_navigation"
RUN_MAP_DIR="$RUN_NAV_DIR/maps"
RUN_QBOT_SETUP="$HOME/ros2/install/setup.bash"
RUN_MAP=""
RUN_LABELS=""
RUN_SCAN_FILTER="$RUN_NAV_DIR/filters/scan_wedge_filter.json"
RUN_USE_ADAPTIVE_GOAL_TOLERANCE=true
RUN_GOAL_TOLERANCE_DESCRIPTION="adaptive"
RUN_BUILD_STAMP="$RUN_NAV_DIR/install/.qbot_platform_source_stamp"

usage() {
    echo "Usage: $0 --map MAP.yaml [--labels LABELS.json] [--scan-filter-file FILTER.json] [--fixed-goal-tolerance]"
    echo
    echo "The map is required. If --labels is omitted, <map_stem>_labels.json is used."
    echo "Maps available in $RUN_MAP_DIR:"
    local candidate
    for candidate in "$RUN_MAP_DIR"/*.yaml; do
        [ -e "$candidate" ] || continue
        case "$candidate" in
            *.labels.yaml) continue ;;
        esac
        echo "  $(basename "$candidate")"
    done
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --map)
            [ "$#" -ge 2 ] || { echo "ERROR: --map requires a path"; usage; exit 2; }
            RUN_MAP="$2"
            shift 2
            ;;
        --labels)
            [ "$#" -ge 2 ] || { echo "ERROR: --labels requires a path"; usage; exit 2; }
            RUN_LABELS="$2"
            shift 2
            ;;
        --scan-filter-file)
            [ "$#" -ge 2 ] || { echo "ERROR: --scan-filter-file requires a path"; usage; exit 2; }
            RUN_SCAN_FILTER="$2"
            shift 2
            ;;
        --fixed-goal-tolerance)
            RUN_USE_ADAPTIVE_GOAL_TOLERANCE=false
            shift
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

if [ -z "$RUN_MAP" ]; then
    echo "ERROR: --map is required."
    usage
    exit 2
fi

if [ "$RUN_USE_ADAPTIVE_GOAL_TOLERANCE" = false ]; then
    RUN_GOAL_TOLERANCE_DESCRIPTION="fixed at YAML value"
fi

case "$RUN_MAP" in
    *.yaml) ;;
    *) echo "ERROR: --map must point to a .yaml file: $RUN_MAP"; exit 2 ;;
esac

if [ -z "$RUN_LABELS" ]; then
    RUN_LABELS="${RUN_MAP%.yaml}_labels.json"
fi

if [ ! -d "$RUN_NAV_DIR/src/qbot_platform" ]; then
    echo "ERROR: qbot_platform source not found: $RUN_NAV_DIR/src/qbot_platform"
    exit 1
fi
if [ ! -f "$RUN_MAP" ]; then
    echo "ERROR: map not found: $RUN_MAP"
    exit 1
fi
if [ ! -f "$RUN_LABELS" ]; then
    echo "ERROR: labels file not found: $RUN_LABELS"
    exit 1
fi
if [ ! -f "$RUN_SCAN_FILTER" ]; then
    echo "ERROR: scan filter file not found: $RUN_SCAN_FILTER"
    exit 1
fi
if [ ! -f /opt/ros/humble/setup.bash ]; then
    echo "ERROR: ROS Humble setup not found: /opt/ros/humble/setup.bash"
    exit 1
fi
if [ ! -f "$RUN_QBOT_SETUP" ]; then
    echo "ERROR: QBot ROS workspace setup not found: $RUN_QBOT_SETUP"
    exit 1
fi

RUN_MAP="$(realpath "$RUN_MAP")"
RUN_LABELS="$(realpath "$RUN_LABELS")"
RUN_SCAN_FILTER="$(realpath "$RUN_SCAN_FILTER")"
export ROS_DOMAIN_ID=63

echo "=========================================="
echo " QBot Navigation"
echo "=========================================="
echo "Repository:    $RUN_REPO_DIR"
echo "Navigation WS: $RUN_NAV_DIR"
echo "ROS_DOMAIN_ID: $ROS_DOMAIN_ID"
echo "Map:           $RUN_MAP"
echo "Labels:        $RUN_LABELS"
echo "Scan filter:   $RUN_SCAN_FILTER"
echo "Goal tolerance: $RUN_GOAL_TOLERANCE_DESCRIPTION"
echo "=========================================="

source /opt/ros/humble/setup.bash
source "$RUN_QBOT_SETUP"

RUN_NEEDS_BUILD=false
if [ ! -f "$RUN_NAV_DIR/install/setup.bash" ] || [ ! -f "$RUN_BUILD_STAMP" ]; then
    RUN_NEEDS_BUILD=true
elif find "$RUN_NAV_DIR/src/qbot_platform" -type f ! -path '*/__pycache__/*' -newer "$RUN_BUILD_STAMP" -print -quit | grep -q .; then
    RUN_NEEDS_BUILD=true
fi

if [ "$RUN_NEEDS_BUILD" = true ]; then
    echo
    echo "qbot_platform is missing or out of date. Building it now..."
    cd "$RUN_NAV_DIR"
    colcon build \
        --packages-select qbot_platform \
        --cmake-args -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
    touch "$RUN_BUILD_STAMP"
fi

source "$RUN_NAV_DIR/install/setup.bash"
cd "$RUN_REPO_DIR"

RUN_NAV_PID=""
cleanup() {
    if [ -n "$RUN_NAV_PID" ]; then
        echo
        echo "Stopping QBot navigation..."
        kill "$RUN_NAV_PID" 2>/dev/null || true
        wait "$RUN_NAV_PID" 2>/dev/null || true
        RUN_NAV_PID=""
    fi
}
trap cleanup INT TERM EXIT

echo "Starting QBot navigation..."
ros2 launch qbot_platform \
    qbot_platform_map_nav_bringup_launch.py \
    map:="$RUN_MAP" \
    labels_file:="$RUN_LABELS" \
    scan_filter_file:="$RUN_SCAN_FILTER" \
    use_scan_filter:=true \
    use_adaptive_goal_tolerance:="$RUN_USE_ADAPTIVE_GOAL_TOLERANCE" \
    use_breadcrumb_return:=false &

RUN_NAV_PID=$!
echo "Navigation process started with PID: $RUN_NAV_PID"
echo "Waiting for AMCL..."

until ros2 node list 2>/dev/null | grep -qx "/amcl"; do
    if ! kill -0 "$RUN_NAV_PID" 2>/dev/null; then
        echo "ERROR: navigation exited before AMCL started."
        wait "$RUN_NAV_PID" || true
        RUN_NAV_PID=""
        exit 1
    fi
    sleep 1
done

echo
echo "=========================================="
echo " QBot navigation is starting on the ROS graph"
echo " The website will notify you when Nav2 is ready"
echo "=========================================="
echo "Press Ctrl+C here to stop the navigation stack."

set +e
wait "$RUN_NAV_PID"
RUN_EXIT_CODE=$?
set -e
RUN_NAV_PID=""
exit "$RUN_EXIT_CODE"
