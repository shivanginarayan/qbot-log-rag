#!/usr/bin/env bash
set -e

if [ -z "$1" ]; then
    echo "Usage:"
    echo "  ./src/storage/start_evidence_logging.sh <SESSION_ID>"
    exit 1
fi

SESSION_ID="$1"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SESSION_DIR="$REPO_DIR/runtime_logs/session_${SESSION_ID}"
DB_PATH="$SESSION_DIR/robot.db"
BAG_DIR="$SESSION_DIR/rosbag"

if [ ! -d "$SESSION_DIR" ]; then
    echo "ERROR: session directory does not exist:"
    echo "$SESSION_DIR"
    exit 1
fi

if [ ! -f "$DB_PATH" ]; then
    echo "ERROR: robot.db does not exist:"
    echo "$DB_PATH"
    exit 1
fi

if [ -e "$BAG_DIR" ]; then
    echo "ERROR: rosbag output already exists:"
    echo "$BAG_DIR"
    echo "Use a fresh session ID."
    exit 1
fi

source /opt/ros/humble/setup.bash

if [ -f "$HOME/ros2/install/setup.bash" ]; then
    source "$HOME/ros2/install/setup.bash"
fi

if [ -f "$REPO_DIR/robot_navigation/install/setup.bash" ]; then
    source "$REPO_DIR/robot_navigation/install/setup.bash"
fi

if [ -f "$REPO_DIR/.venv/bin/activate" ]; then
    source "$REPO_DIR/.venv/bin/activate"
fi

export ROS_DOMAIN_ID=57

cd "$REPO_DIR"

echo
echo "Starting evidence logging"
echo "Session ID: $SESSION_ID"
echo "Database:   $DB_PATH"
echo "Rosbag:     $BAG_DIR"
echo
echo "Press Ctrl+C once to stop all loggers."
echo

PIDS=()

cleanup() {
    echo
    echo "Stopping evidence loggers..."

    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            kill -INT "$pid" 2>/dev/null || true
        fi
    done

    wait || true

    echo "All evidence loggers stopped."
}

trap cleanup INT TERM EXIT


python src/storage/odom_logger.py \
    --db "$DB_PATH" \
    --session-id "$SESSION_ID" &
PIDS+=($!)

python src/storage/amcl_pose_logger.py \
    --db "$DB_PATH" \
    --session-id "$SESSION_ID" &
PIDS+=($!)

python src/storage/cmd_vel_logger.py \
    --db "$DB_PATH" \
    --session-id "$SESSION_ID" &
PIDS+=($!)

python src/storage/lidar_logger.py \
    --db "$DB_PATH" \
    --session-id "$SESSION_ID" &
PIDS+=($!)

ros2 bag record \
    -o "$BAG_DIR" \
    /scan \
    /scan_filtered \
    /odom \
    /amcl_pose \
    /cmd_vel \
    /tf \
    /tf_static &
PIDS+=($!)

wait
