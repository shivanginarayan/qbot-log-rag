#!/bin/bash
if [ -n "$QBOT_SCRIPT_RUNNING" ]; then
    echo "Script already running. Exiting recursive launch."
    exit 1
fi

export QBOT_SCRIPT_RUNNING=1


#~/ENGR857_Narayan_Shivangi/start_qbot.sh follower
#~/ENGR857_Narayan_Shivangi/start_qbot.sh joystick

# Usage:
#   ./start_qbot.sh follower
#   ./start_qbot.sh joystick
#   ./start_qbot.sh gohome
#
# Default:
#   follower mode

MODE=${1:-follower}

ROS_WS=~/ENGR857_Narayan_Shivangi/ros2_ws
RAG_DIR=~/ENGR857_Narayan_Shivangi/project/qbot-log-rag
NAV_DIR=~/ENGR857_Narayan_Shivangi/project/navigation
LOG_DIR=$RAG_DIR/runtime_logs
NAV_LOG_DIR=$NAV_DIR/runtime_logs
STUDY_MAP_YAML=$NAV_DIR/maps/shivangi_map1/shivangi_map1.yaml
STUDY_LABELS_JSON=$NAV_DIR/maps/shivangi_map1/shivangi_map1_labels.json
RUN_TIMESTAMP=$(date -u +"%Y%m%d_%H%M%S")
GOHOME_RUN_DIR=$NAV_LOG_DIR/gohome_$RUN_TIMESTAMP
GOHOME_STATUS_LOG=$GOHOME_RUN_DIR/status.log

mkdir -p "$LOG_DIR"
mkdir -p "$RAG_DIR/data/processed"
mkdir -p "$NAV_LOG_DIR"

log_msg() {
    local message="$1"
    local timestamp
    timestamp=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    echo "[$timestamp] $message"
    if [ "$MODE" = "gohome" ]; then
        mkdir -p "$GOHOME_RUN_DIR"
        echo "[$timestamp] $message" >> "$GOHOME_STATUS_LOG"
    fi
}

# Save runtime mode so diagnose_with_memory.py knows if we are in follower or joystick mode
echo "$MODE" > "$RAG_DIR/data/processed/runtime_mode.txt"

log_msg "Starting QBot Diagnostic System..."
log_msg "Mode: $MODE"

# -----------------------------
# Clean old duplicate processes
# -----------------------------
log_msg "Cleaning old processes..."

pkill -f topic_health_collector.py 2>/dev/null
pkill -f error_memory_collector.py 2>/dev/null
pkill -f health_to_logs.py 2>/dev/null
pkill -f diagnose_with_memory.py 2>/dev/null
pkill -f "ros2 run teleop follower" 2>/dev/null
pkill -f "qbot_platform_manual_drive_launch.py" 2>/dev/null
pkill -f "qbot_platform_map_nav_bringup_launch.py" 2>/dev/null
pkill -f "go_to_label.py" 2>/dev/null
pkill -f "breadcrumb_return.py" 2>/dev/null

sleep 2

# -----------------------------
# Source ROS
# -----------------------------
cd "$ROS_WS" || exit 1

source /opt/ros/humble/setup.bash
source "$ROS_WS/install/setup.bash"
if [ -f "$NAV_DIR/install/setup.bash" ]; then
    source "$NAV_DIR/install/setup.bash"
fi

log_msg "ROS sourced."

wait_for_amcl_pose() {
    local timeout_sec=${1:-30}
    local start_time
    log_msg "Waiting for AMCL localization on /amcl_pose (timeout: ${timeout_sec}s)..."
    start_time=$(date +%s)

    while true; do
        if ros2 topic echo --once /amcl_pose >/dev/null 2>&1; then
            log_msg "AMCL pose received."
            return 0
        fi

        if [ $(( $(date +%s) - start_time )) -ge "$timeout_sec" ]; then
            break
        fi

        sleep 2
    done

    log_msg "Timed out waiting for /amcl_pose."
    return 1
}

gohome_cleanup() {
    echo ""
    log_msg "Stopping go-home navigation..."
    kill "$QBOT_PID" 2>/dev/null
    pkill -f "qbot_platform_map_nav_bringup_launch.py" 2>/dev/null
    pkill -f "go_to_label.py" 2>/dev/null
    pkill -f "breadcrumb_return.py" 2>/dev/null
    log_msg "Go-home logs saved in $GOHOME_RUN_DIR"
    exit "${1:-0}"
}

run_gohome_command() {
    local attempt=$1
    local attempt_log_prefix=$GOHOME_RUN_DIR/gohome_attempt_${attempt}

    log_msg "Running go-home command attempt $attempt."
    ros2 run qbot_platform go_to_label.py gohome --labels-file "$STUDY_LABELS_JSON" \
      > "${attempt_log_prefix}.out" 2> "${attempt_log_prefix}.err"
    return $?
}

if [ "$MODE" = "gohome" ]; then
    mkdir -p "$GOHOME_RUN_DIR"
    trap 'gohome_cleanup 130' INT TERM

    log_msg "Go-home mode selected."
    log_msg "Map yaml: $STUDY_MAP_YAML"
    log_msg "Labels file: $STUDY_LABELS_JSON"

    if [ ! -f "$STUDY_MAP_YAML" ]; then
        log_msg "Missing map file: $STUDY_MAP_YAML"
        exit 1
    fi

    if [ ! -f "$STUDY_LABELS_JSON" ]; then
        log_msg "Missing labels file: $STUDY_LABELS_JSON"
        exit 1
    fi

    log_msg "Launching Nav2 on shivangi_map1..."
    ros2 launch qbot_platform qbot_platform_map_nav_bringup_launch.py \
      map:="$STUDY_MAP_YAML" \
      labels_file:="$STUDY_LABELS_JSON" \
      use_breadcrumb_return:=false \
      > "$GOHOME_RUN_DIR/gohome_launch.out" 2> "$GOHOME_RUN_DIR/gohome_launch.err" &

    QBOT_PID=$!
    log_msg "Nav2 launch pid: $QBOT_PID"

    sleep 5

    if ! wait_for_amcl_pose 120; then
        log_msg "Go-home navigation failed: localization did not become ready."
        gohome_cleanup 1
    fi

    sleep 5

    log_msg "Sending robot to home..."
    exit_code=1
    for attempt in 1 2 3; do
        log_msg "Go-home attempt $attempt..."
        if run_gohome_command "$attempt"; then
            exit_code=0
            log_msg "Go-home attempt $attempt succeeded."
            break
        fi
        log_msg "Go-home attempt $attempt failed. Waiting 5 seconds before retrying..."
        sleep 5
    done

    if [ $exit_code -ne 0 ]; then
        log_msg "Go-home navigation failed."
    else
        log_msg "Go-home navigation command finished."
    fi
    gohome_cleanup "$exit_code"
fi

# -----------------------------
# Offline mode for local models
# -----------------------------
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

# -----------------------------
# Start QBot runtime
# This should start:
# /QBotPlatformDriver
# /Lidar
# /joysticCommands
# /scan
# -----------------------------
echo "Launching QBot platform..."

ros2 launch qbot_platform qbot_platform_manual_drive_launch.py \
  > "$LOG_DIR/qbot_launch.out" 2> "$LOG_DIR/qbot_launch.err" &

QBOT_PID=$!

sleep 7

# -----------------------------
# Mode selection
# -----------------------------
FOLLOWER_PID=""

if [ "$MODE" = "follower" ]; then
    echo "Follower mode selected."
    echo "Stopping joystick node because joystick conflicts with follower on /cmd_vel..."

    pkill -f joystic 2>/dev/null
    sleep 2

    echo "Starting LiDAR follower node..."

    ros2 run teleop follower \
      > "$LOG_DIR/follower.out" 2> "$LOG_DIR/follower.err" &

    FOLLOWER_PID=$!

elif [ "$MODE" = "joystick" ]; then
    echo "Joystick mode selected."
    echo "Keeping joystick node running."
    echo "Follower will NOT be started."

else
    echo "Invalid mode: $MODE"
    echo "Use one of:"
    echo "  ./start_qbot.sh follower"
    echo "  ./start_qbot.sh joystick"
    echo "  ./start_qbot.sh gohome"
    exit 1
fi

sleep 3

# -----------------------------
# Start RAG diagnostic system
# -----------------------------
cd "$RAG_DIR" || exit 1

source shivangi/bin/activate

echo "Python environment activated."

echo "Starting topic health collector..."
python src/topic_health_collector.py \
  > "$LOG_DIR/topic_health_collector.out" 2> "$LOG_DIR/topic_health_collector.err" &

TOPIC_PID=$!

echo "Starting error memory collector..."
python src/error_memory_collector.py \
  > "$LOG_DIR/error_memory_collector.out" 2> "$LOG_DIR/error_memory_collector.err" &

MEMORY_PID=$!

echo "Starting health-to-logs converter..."
python src/health_to_logs.py \
  > "$LOG_DIR/health_to_logs.out" 2> "$LOG_DIR/health_to_logs.err" &

LOG_CONVERTER_PID=$!

sleep 3

# -----------------------------
# Cleanup function
# -----------------------------
cleanup() {
    echo ""
    echo "Stopping QBot Diagnostic System..."

    kill $QBOT_PID 2>/dev/null
    kill $FOLLOWER_PID 2>/dev/null
    kill $TOPIC_PID 2>/dev/null
    kill $MEMORY_PID 2>/dev/null
    kill $LOG_CONVERTER_PID 2>/dev/null

    pkill -f topic_health_collector.py 2>/dev/null
    pkill -f error_memory_collector.py 2>/dev/null
    pkill -f health_to_logs.py 2>/dev/null
    pkill -f "ros2 run teleop follower" 2>/dev/null

    echo "Stopped."
    exit 0
}

trap cleanup SIGINT

# -----------------------------
# User-facing chat
# -----------------------------
clear

echo "=========================================="
echo " QBot Diagnostic Assistant Ready"
echo "=========================================="
echo ""
echo "Mode: $MODE"
echo ""
echo "Ask questions like:"
echo "  Why is the robot not moving?"
echo "  Did this error happen before?"
echo "  What happened before the failure?"
echo ""
echo "Press Ctrl+C to stop everything."
echo "=========================================="
echo ""

python src/diagnose_with_memory.py

cleanup
