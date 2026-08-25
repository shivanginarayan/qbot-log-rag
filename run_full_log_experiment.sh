#!/usr/bin/env bash

set -u


# ============================================================
# QBot Full Experiment Launcher
#
# Usage:
#
#   ./run_full_log_experiment.sh
#
# Starts:
#   - browser map-label UI
#   - browser RAG chat UI
#   - evidence logging
#   - rosbag
#   - live robot-log Q&A
#
# Commands:
#   /user
#   /developer
#   /status
#   /end
#   exit
#
# Cleanup policy:
#
#   We DO stop experiment-created:
#     - browser UI
#     - evidence loggers
#     - rosbag
#     - mapping/navigation
#     - Nav2
#     - AMCL
#     - Cartographer
#     - QBot ROS interface/support nodes
#
#   We DO NOT stop:
#
#     qbot_platform_driver_physical
#
#   That is treated as the persistent physical robot driver.
# ============================================================


# ============================================================
# PATHS
# ============================================================

REPO_DIR="$HOME/ENGR857_Narayan_Shivangi/project/qbot-log-rag"

RUNTIME_DIR="$REPO_DIR/runtime_logs"

CHAT_UI_PORT=8766


cd "$REPO_DIR" || exit 1


# ============================================================
# PYTHON ENVIRONMENT
# ============================================================

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi


# ============================================================
# ROS
# ============================================================

export ROS_DOMAIN_ID=57


echo
echo "Using ROS_DOMAIN_ID=$ROS_DOMAIN_ID"


# ============================================================
# BASIC HELPERS
# ============================================================

valid_positive_integer() {

    [[ "${1:-}" =~ ^[1-9][0-9]*$ ]]

}


# ============================================================
# KILL PIDS MATCHING ONE SAFE PATTERN
#
# Only processes owned by the current user are targeted.
#
# This automatically protects the root-owned persistent:
#
#   qbot_platform_driver_physical
# ============================================================

signal_user_processes_matching() {

    local signal_name="$1"

    local pattern="$2"

    local pids


    pids="$(
        pgrep \
            -u "$UID" \
            -f "$pattern" \
            2>/dev/null || true
    )"


    while read -r pid
    do

        if [ -z "$pid" ]; then
            continue
        fi


        if ! valid_positive_integer "$pid"; then
            continue
        fi


        # Never signal this launcher.

        if [ "$pid" = "$$" ]; then
            continue
        fi


        # Never signal the shell that launched us.

        if [ "$pid" = "$PPID" ]; then
            continue
        fi


        kill \
            "-$signal_name" \
            "$pid" \
            2>/dev/null || true


    done <<< "$pids"

}


# ============================================================
# PROJECT RUNTIME PROCESS PATTERNS
#
# These are the detached processes we have actually observed
# surviving previous experiments.
#
# IMPORTANT:
#
# qbot_platform_driver_physical is NOT listed.
# ============================================================

signal_project_runtime_nodes() {

    local signal_name="$1"


    # --------------------------------------------------------
    # QBot support/interface nodes
    # --------------------------------------------------------

    signal_user_processes_matching \
        "$signal_name" \
        'robot_navigation/install/qbot_platform/lib/qbot_platform/lidar([[:space:]]|$)'


    signal_user_processes_matching \
        "$signal_name" \
        'robot_navigation/install/qbot_platform/lib/qbot_platform/fixed_lidar_frame([[:space:]]|$)'


    signal_user_processes_matching \
        "$signal_name" \
        'robot_navigation/install/qbot_platform/lib/qbot_platform/wheel_odometry\.py([[:space:]]|$)'


    signal_user_processes_matching \
        "$signal_name" \
        'robot_navigation/install/qbot_platform/lib/qbot_platform/scan_wedge_filter\.py([[:space:]]|$)'


    signal_user_processes_matching \
        "$signal_name" \
        'robot_navigation/install/qbot_platform/lib/qbot_platform/adaptive_goal_tolerance\.py([[:space:]]|$)'


    signal_user_processes_matching \
        "$signal_name" \
        'robot_navigation/install/qbot_platform/lib/qbot_platform/qbot_platform_driver_interface([[:space:]]|$)'


    signal_user_processes_matching \
        "$signal_name" \
        'robot_navigation/install/qbot_platform/lib/qbot_platform/go_to_label\.py([[:space:]]|$)'


    # --------------------------------------------------------
    # Browser backend
    # --------------------------------------------------------

    signal_user_processes_matching \
        "$signal_name" \
        'robot_navigation/tools/map_label_gui\.py([[:space:]]|$)'


    # --------------------------------------------------------
    # Mapping/navigation launcher processes
    # --------------------------------------------------------

    signal_user_processes_matching \
        "$signal_name" \
        'run_qbot_navigation\.sh'


    signal_user_processes_matching \
        "$signal_name" \
        'run_qbot_mapping\.sh'


    signal_user_processes_matching \
        "$signal_name" \
        'qbot_platform_manual_map_launch'


    signal_user_processes_matching \
        "$signal_name" \
        'qbot_platform_map_nav_bringup_launch'


    # --------------------------------------------------------
    # Navigation stack
    # --------------------------------------------------------

    signal_user_processes_matching \
        "$signal_name" \
        'planner_server'


    signal_user_processes_matching \
        "$signal_name" \
        'controller_server'


    signal_user_processes_matching \
        "$signal_name" \
        'bt_navigator'


    signal_user_processes_matching \
        "$signal_name" \
        'behavior_server'


    signal_user_processes_matching \
        "$signal_name" \
        'waypoint_follower'


    signal_user_processes_matching \
        "$signal_name" \
        'velocity_smoother'


    signal_user_processes_matching \
        "$signal_name" \
        'map_server'


    signal_user_processes_matching \
        "$signal_name" \
        'lifecycle_manager'


    signal_user_processes_matching \
        "$signal_name" \
        'recoveries_server'


    # --------------------------------------------------------
    # Localization / mapping
    # --------------------------------------------------------

    signal_user_processes_matching \
        "$signal_name" \
        '(^|[[:space:]/])amcl([[:space:]]|$)'


    signal_user_processes_matching \
        "$signal_name" \
        'cartographer'

}


# ============================================================
# EVIDENCE LOGGER CLEANUP
# ============================================================

signal_evidence_processes() {

    local signal_name="$1"


    signal_user_processes_matching \
        "$signal_name" \
        'src/storage/odom_logger\.py'


    signal_user_processes_matching \
        "$signal_name" \
        'src/storage/amcl_pose_logger\.py'


    signal_user_processes_matching \
        "$signal_name" \
        'src/storage/cmd_vel_logger\.py'


    signal_user_processes_matching \
        "$signal_name" \
        'src/storage/lidar_logger\.py'


    signal_user_processes_matching \
        "$signal_name" \
        'src/storage/task_event_logger\.py'


    signal_user_processes_matching \
        "$signal_name" \
        'ros2 bag record'

}


# ============================================================
# FULL STALE CLEANUP
#
# Run BEFORE baseline snapshot.
#
# Otherwise leftovers from the last experiment could become
# protected baseline processes.
# ============================================================

cleanup_stale_experiment() {

    echo
    echo "============================================================"
    echo "CHECKING FOR STALE EXPERIMENT PROCESSES"
    echo "============================================================"
    echo


    # --------------------------------------------------------
    # Browser port
    # --------------------------------------------------------

    if fuser 8765/tcp \
        >/dev/null 2>&1
    then

        echo "Stopping stale browser server on port 8765..."


        fuser -k 8765/tcp \
            >/dev/null 2>&1 || true

    fi


    if fuser "$CHAT_UI_PORT/tcp" \
        >/dev/null 2>&1
    then

        echo "Stopping stale chat UI on port $CHAT_UI_PORT..."


        fuser -k "$CHAT_UI_PORT/tcp" \
            >/dev/null 2>&1 || true

    fi


    # --------------------------------------------------------
    # Graceful stop
    # --------------------------------------------------------

    echo "Stopping stale loggers / rosbag..."

    signal_evidence_processes INT


    echo "Stopping stale robot runtime nodes..."

    signal_project_runtime_nodes INT


    sleep 2


    # --------------------------------------------------------
    # TERM survivors
    # --------------------------------------------------------

    signal_evidence_processes TERM

    signal_project_runtime_nodes TERM


    sleep 2


    # --------------------------------------------------------
    # KILL final survivors
    # --------------------------------------------------------

    signal_evidence_processes KILL

    signal_project_runtime_nodes KILL


    sleep 1


    # --------------------------------------------------------
    # Browser fallback
    # --------------------------------------------------------

    if fuser 8765/tcp \
        >/dev/null 2>&1
    then

        fuser -k 8765/tcp \
            >/dev/null 2>&1 || true

    fi


    if fuser "$CHAT_UI_PORT/tcp" \
        >/dev/null 2>&1
    then

        fuser -k "$CHAT_UI_PORT/tcp" \
            >/dev/null 2>&1 || true

    fi


    # --------------------------------------------------------
    # Clear stale ROS CLI graph cache
    #
    # This does NOT stop ROS nodes.
    # --------------------------------------------------------

    ROS_DOMAIN_ID=57 \
        ros2 daemon stop \
        >/dev/null 2>&1 || true


    sleep 1


    ROS_DOMAIN_ID=57 \
        ros2 daemon start \
        >/dev/null 2>&1 || true


    echo
    echo "Stale experiment cleanup complete."

}


cleanup_stale_experiment


# ============================================================
# ROBOT PROCESS GROUP DETECTION
#
# Used as an additional cleanup mechanism for process groups
# created AFTER this experiment begins.
# ============================================================

robot_process_pgids() {

    ps -eo pgid=,args= \
        | awk '
        /run_qbot_navigation\.sh/ ||
        /run_qbot_mapping\.sh/ ||
        /robot_navigation\/install\/qbot_platform/ ||
        /qbot_platform_manual_map_launch/ ||
        /qbot_platform_map_nav_bringup_launch/ ||
        /qbot_platform.*launch/ ||
        /cartographer/ ||
        /nav2_/ ||
        /planner_server/ ||
        /controller_server/ ||
        /bt_navigator/ ||
        /behavior_server/ ||
        /waypoint_follower/ ||
        /velocity_smoother/ ||
        /map_server/ ||
        /amcl/ ||
        /lifecycle_manager/ ||
        /recoveries_server/
        {
            print $1
        }
        ' \
        | awk '$1 ~ /^[1-9][0-9]*$/' \
        | sort -nu

}


# ============================================================
# BASELINE PROCESS GROUPS
#
# Anything still running after stale cleanup is deliberately
# protected by process-group cleanup.
# ============================================================

BASELINE_PGIDS="$(
    robot_process_pgids
)"


echo
echo "Existing robot process groups before experiment:"
echo


if [ -n "$BASELINE_PGIDS" ]; then

    echo "$BASELINE_PGIDS" \
        | sed 's/^/  /'

else

    echo "  none"

fi


# ============================================================
# SESSION ID
# ============================================================

SESSION_ID="$(
python - <<'PY'
from datetime import datetime
import secrets

stamp = datetime.now().strftime(
    "%Y%m%d_%H%M%S"
)

suffix = secrets.token_hex(2)

print(
    f"{stamp}_{suffix}"
)
PY
)"


SESSION_DIR="$RUNTIME_DIR/session_${SESSION_ID}"


mkdir -p "$SESSION_DIR"


GUI_LOG="$SESSION_DIR/map_labeler_console.log"

EVIDENCE_LOG="$SESSION_DIR/evidence_logging_console.log"

CHAT_UI_LOG="$SESSION_DIR/session_chat_ui_console.log"


MAP_NAME=""


export QBOT_EXPERIMENT_SESSION_ID="$SESSION_ID"


echo
echo "============================================================"
echo "QBOT EXPERIMENT"
echo "============================================================"
echo
echo "Session:"
echo "  $SESSION_ID"
echo
echo "Session directory:"
echo "  $SESSION_DIR"
echo


# ============================================================
# CREATE DATABASE + SESSION ROW
# ============================================================

python - <<'PY'
import os
import sqlite3
import subprocess
import sys
import time

from datetime import datetime, timezone
from pathlib import Path


repo = Path.cwd()


sys.path.insert(
    0,
    str(
        repo
        / "src"
        / "storage"
    ),
)


from init_db import initialize_database


session_id = os.environ[
    "QBOT_EXPERIMENT_SESSION_ID"
]


session_dir = (
    repo
    / "runtime_logs"
    / f"session_{session_id}"
)


db_path = (
    session_dir
    / "robot.db"
)


initialize_database(
    str(db_path)
)


try:

    git_commit = (
        subprocess.check_output(
            [
                "git",
                "rev-parse",
                "HEAD",
            ],
            cwd=repo,
            text=True,
        )
        .strip()
    )

except Exception:

    git_commit = None


conn = sqlite3.connect(
    db_path
)


conn.execute(
    """
    INSERT INTO sessions (
        session_id,
        started_at_ns,
        started_at_iso,
        robot_id,
        ros_domain_id,
        map_name,
        git_commit,
        status,
        notes
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
        session_id,
        time.time_ns(),
        datetime.now(
            timezone.utc
        ).isoformat(),
        "qbot",
        57,
        None,
        git_commit,
        "running",
        "Created by run_full_log_experiment.sh",
    ),
)


conn.commit()

conn.close()


print(
    f"Created session: {session_id}"
)

print(
    f"Database: {db_path}"
)
PY


if [ "$?" -ne 0 ]; then

    echo
    echo "Could not initialize session."

    exit 1

fi


# ============================================================
# STATE
# ============================================================

GUI_PID=""

LOGGER_PID=""

CHAT_UI_PID=""

EXPERIMENT_FINISHED=0

SESSION_ACTIVE=1

MEMORY_FINALIZED=0

AUDIENCE="user"


# ============================================================
# STOP RAG CHAT UI
#
# The chat UI remains available after /end so the completed
# session can still be queried. It stops when this launcher exits.
# ============================================================

stop_chat_ui() {

    if [ -z "${CHAT_UI_PID:-}" ]; then
        return
    fi


    local chat_pgid


    chat_pgid="$(
        ps -o pgid= -p "$CHAT_UI_PID" \
            2>/dev/null \
            | tr -d ' '
    )"


    if valid_positive_integer "$chat_pgid"; then

        echo
        echo "Stopping browser RAG chat UI..."


        kill -TERM \
            -- "-$chat_pgid" \
            2>/dev/null || true

    else

        kill -TERM \
            "$CHAT_UI_PID" \
            2>/dev/null || true

    fi


    local attempts=0


    while kill -0 "$CHAT_UI_PID" \
        2>/dev/null
    do

        attempts=$((attempts + 1))


        if [ "$attempts" -ge 20 ]; then
            break
        fi


        sleep 0.1

    done


    if kill -0 "$CHAT_UI_PID" \
        2>/dev/null
    then

        if valid_positive_integer "$chat_pgid"; then

            kill -KILL \
                -- "-$chat_pgid" \
                2>/dev/null || true

        else

            kill -KILL \
                "$CHAT_UI_PID" \
                2>/dev/null || true

        fi

    fi


    wait "$CHAT_UI_PID" \
        2>/dev/null || true


    CHAT_UI_PID=""

}


# ============================================================
# BASELINE CHECK
# ============================================================

pgid_is_baseline() {

    local target="$1"


    if [ -z "$target" ]; then
        return 0
    fi


    echo "$BASELINE_PGIDS" \
        | grep -qx "$target"

}


# ============================================================
# SIGNAL ONLY NEW ROBOT PROCESS GROUPS
# ============================================================

signal_new_robot_groups() {

    local signal_name="$1"

    local current_pgids

    local our_pgid


    current_pgids="$(
        robot_process_pgids
    )"


    our_pgid="$(
        ps -o pgid= -p $$ \
            2>/dev/null \
            | tr -d ' '
    )"


    while read -r pgid
    do

        if [ -z "$pgid" ]; then
            continue
        fi


        if ! valid_positive_integer "$pgid"; then
            continue
        fi


        if [ "$pgid" = "$our_pgid" ]; then
            continue
        fi


        if pgid_is_baseline "$pgid"; then
            continue
        fi


        echo \
            "  sending $signal_name to experiment process group $pgid"


        kill \
            "-$signal_name" \
            -- "-$pgid" \
            2>/dev/null || true


    done <<< "$current_pgids"

}


# ============================================================
# SHOW WHAT ROBOT PROCESSES REMAIN
# ============================================================

show_remaining_robot_processes() {

    echo
    echo "Robot-related processes remaining:"
    echo


    ps -eo pid,ppid,user,pgid,sid,args \
        | grep -E \
        'qbot_platform|run_qbot|cartographer|nav2|planner_server|controller_server|bt_navigator|behavior_server|map_server|amcl|lidar|wheel_odometry|scan_wedge_filter|adaptive_goal_tolerance|ros2 bag|odom_logger|task_event_logger' \
        | grep -v grep \
        || true

}


# ============================================================
# CLEANUP CURRENT EXPERIMENT
# ============================================================

cleanup_processes() {

    echo
    echo "============================================================"
    echo "STOPPING EXPERIMENT PROCESSES"
    echo "============================================================"
    echo


    # --------------------------------------------------------
    # 1. Evidence logger launcher process group
    # --------------------------------------------------------

    if [ -n "${LOGGER_PID:-}" ]; then

        local logger_pgid


        logger_pgid="$(
            ps -o pgid= -p "$LOGGER_PID" \
                2>/dev/null \
                | tr -d ' '
        )"


        if valid_positive_integer "$logger_pgid"; then

            echo \
                "Stopping evidence logger group: $logger_pgid"


            kill -INT \
                -- "-$logger_pgid" \
                2>/dev/null || true

        fi

    fi


    # --------------------------------------------------------
    # 2. Browser process group
    # --------------------------------------------------------

    if [ -n "${GUI_PID:-}" ]; then

        local gui_pgid


        gui_pgid="$(
            ps -o pgid= -p "$GUI_PID" \
                2>/dev/null \
                | tr -d ' '
        )"


        if valid_positive_integer "$gui_pgid"; then

            echo \
                "Stopping browser GUI group: $gui_pgid"


            kill -INT \
                -- "-$gui_pgid" \
                2>/dev/null || true

        fi

    fi


    # --------------------------------------------------------
    # 3. Explicit detached process cleanup
    #
    # This is the layer that handles processes adopted by PID 1.
    # --------------------------------------------------------

    echo
    echo "Stopping detached QBot/runtime processes..."


    signal_evidence_processes INT

    signal_project_runtime_nodes INT


    # --------------------------------------------------------
    # 4. Additional process-group cleanup
    # --------------------------------------------------------

    signal_new_robot_groups INT


    sleep 3


    # --------------------------------------------------------
    # 5. TERM survivors
    # --------------------------------------------------------

    echo
    echo "Terminating surviving experiment processes..."


    signal_evidence_processes TERM

    signal_project_runtime_nodes TERM

    signal_new_robot_groups TERM


    sleep 2


    # --------------------------------------------------------
    # 6. KILL final survivors
    # --------------------------------------------------------

    echo
    echo "Force-stopping final survivors..."


    signal_evidence_processes KILL

    signal_project_runtime_nodes KILL

    signal_new_robot_groups KILL


    sleep 1


    # --------------------------------------------------------
    # 7. Browser port
    # --------------------------------------------------------

    if fuser 8765/tcp \
        >/dev/null 2>&1
    then

        echo
        echo "Releasing browser port 8765..."


        fuser -k 8765/tcp \
            >/dev/null 2>&1 || true

    fi


    # --------------------------------------------------------
    # 8. Refresh ROS discovery
    #
    # This does not kill ROS nodes.
    # The actual nodes were stopped above.
    # --------------------------------------------------------

    echo
    echo "Refreshing ROS 2 daemon..."


    ROS_DOMAIN_ID=57 \
        ros2 daemon stop \
        >/dev/null 2>&1 || true


    sleep 1


    ROS_DOMAIN_ID=57 \
        ros2 daemon start \
        >/dev/null 2>&1 || true


    sleep 1


    # --------------------------------------------------------
    # 9. Display survivors
    # --------------------------------------------------------

    show_remaining_robot_processes


    echo
    echo "Experiment process cleanup complete."

}


# ============================================================
# CLOSE SESSION
# ============================================================

close_session() {

    export QBOT_EXPERIMENT_SESSION_ID="$SESSION_ID"


    python - <<'PY'
import os
import sqlite3
import time

from datetime import datetime, timezone
from pathlib import Path


repo = Path.cwd()


session_id = os.environ[
    "QBOT_EXPERIMENT_SESSION_ID"
]


db_path = (
    repo
    / "runtime_logs"
    / f"session_{session_id}"
    / "robot.db"
)


if not db_path.exists():

    raise SystemExit


conn = sqlite3.connect(
    db_path
)


conn.execute(
    """
    UPDATE sessions
    SET
        ended_at_ns = ?,
        ended_at_iso = ?,
        status = ?
    WHERE session_id = ?
    """,
    (
        time.time_ns(),
        datetime.now(
            timezone.utc
        ).isoformat(),
        "completed",
        session_id,
    ),
)


conn.commit()

conn.close()


print(
    f"Closed session: {session_id}"
)
PY

}


# ============================================================
# CTRL+C
# ============================================================

handle_interrupt() {

    echo
    echo "Ctrl+C received."
    echo "Closing experiment..."


    if [ "$EXPERIMENT_FINISHED" -eq 0 ]; then

        cleanup_processes

        close_session

        EXPERIMENT_FINISHED=1

        SESSION_ACTIVE=0

    fi


    echo
    echo "Experiment stopped."


    exit 130

}


trap handle_interrupt INT TERM HUP


# ============================================================
# FINAL EXIT SAFETY
# ============================================================

final_exit_cleanup() {

    stop_chat_ui

    if [ "$EXPERIMENT_FINISHED" -eq 0 ]; then

        echo
        echo "Final launcher cleanup..."


        cleanup_processes


        close_session \
            2>/dev/null || true


        EXPERIMENT_FINISHED=1

        SESSION_ACTIVE=0

    fi

}


trap final_exit_cleanup EXIT


# ============================================================
# START BROWSER UI
# ============================================================

echo
echo "Starting browser map labeler..."


setsid \
    ./run_qbot_map_labeler.sh \
    >"$GUI_LOG" 2>&1 &


GUI_PID=$!


sleep 3


if ! kill -0 "$GUI_PID" \
    2>/dev/null
then

    echo
    echo "Map labeler exited unexpectedly."
    echo
    echo "See:"
    echo "  $GUI_LOG"


    close_session

    EXPERIMENT_FINISHED=1

    exit 1

fi


ROBOT_IP="$(
    hostname -I \
        | awk '{print $1}'
)"


echo
echo "Map labeler running."
echo
echo "Open browser UI:"
echo
echo "  http://${ROBOT_IP}:8765"
echo
echo "GUI log:"
echo "  $GUI_LOG"
echo


# ============================================================
# START EVIDENCE LOGGING
# ============================================================

echo
echo "Starting evidence logging..."


setsid \
    ./src/storage/start_evidence_logging.sh \
    "$SESSION_ID" \
    >"$EVIDENCE_LOG" 2>&1 &


LOGGER_PID=$!


sleep 3


if ! kill -0 "$LOGGER_PID" \
    2>/dev/null
then

    echo
    echo "Evidence logger exited unexpectedly."
    echo
    echo "See:"
    echo "  $EVIDENCE_LOG"


    cleanup_processes

    close_session

    EXPERIMENT_FINISHED=1

    SESSION_ACTIVE=0

    exit 1

fi


echo
echo "Evidence logging running."
echo
echo "Evidence log:"
echo "  $EVIDENCE_LOG"
echo


# ============================================================
# START RAG CHAT UI
# ============================================================

echo
echo "Starting browser RAG chat UI..."


setsid \
    ./session_chat_ui/run_ui.sh \
    --port "$CHAT_UI_PORT" \
    --session-id "$SESSION_ID" \
    </dev/null \
    >"$CHAT_UI_LOG" 2>&1 &


CHAT_UI_PID=$!

CHAT_UI_READY=0


for _ in {1..30}
do

    if ! kill -0 "$CHAT_UI_PID" \
        2>/dev/null
    then
        break
    fi


    if curl \
        --fail \
        --silent \
        --show-error \
        --max-time 2 \
        "http://127.0.0.1:${CHAT_UI_PORT}/" \
        >/dev/null 2>&1
    then

        CHAT_UI_READY=1

        break

    fi


    sleep 0.5

done


if [ "$CHAT_UI_READY" -ne 1 ]; then

    echo
    echo "Browser RAG chat UI did not start."
    echo
    echo "See:"
    echo "  $CHAT_UI_LOG"


    cleanup_processes

    close_session

    EXPERIMENT_FINISHED=1

    SESSION_ACTIVE=0

    exit 1

fi


echo
echo "Browser RAG chat UI running."
echo
echo "Open on this QBot to enter the NVIDIA API key securely:"
echo "  http://localhost:${CHAT_UI_PORT}"
echo
echo "After the key is configured, the chat is also available at:"
echo "  http://${ROBOT_IP}:${CHAT_UI_PORT}"
echo
echo "Chat UI log:"
echo "  $CHAT_UI_LOG"
echo


# ============================================================
# LIVE SESSION
# ============================================================

echo
echo "============================================================"
echo "QBOT LIVE SESSION"
echo "============================================================"
echo
echo "Browser UI:"
echo "  http://${ROBOT_IP}:8765"
echo
echo "RAG chat UI:"
echo "  http://localhost:${CHAT_UI_PORT}"
echo
echo "Evidence logging:"
echo "  ACTIVE"
echo
echo "Session:"
echo "  $SESSION_ID"
echo
echo "You can now use the browser normally:"
echo
echo "  - create/save maps"
echo "  - create labels"
echo "  - start navigation"
echo "  - localize"
echo "  - navigate"
echo
echo "You can ask questions in this terminal at any time."
echo
echo "Commands:"
echo
echo "  /user       user-facing answers"
echo "  /developer  technical answers"
echo "  /status     show latest recorded status"
echo "  /end        stop robot/logging and finalize memory"
echo "  exit        end everything and leave"
echo
echo "============================================================"
echo


# ============================================================
# NVIDIA KEY
# ============================================================

ensure_nvidia_key() {

    if [ -n "${NVIDIA_API_KEY:-}" ]; then
        return
    fi


    echo
    echo "NVIDIA_API_KEY is not currently set."
    echo


    read -rsp \
        "Enter NVIDIA API key: " \
        NVIDIA_API_KEY


    echo


    export NVIDIA_API_KEY

}


# ============================================================
# LIVE STATUS
# ============================================================

show_live_status() {

    export QBOT_EXPERIMENT_SESSION_ID="$SESSION_ID"


    python - <<'PY'
import json
import os
import sqlite3
import urllib.request

from pathlib import Path


repo = Path.cwd()


session_id = os.environ[
    "QBOT_EXPERIMENT_SESSION_ID"
]


db = (
    repo
    / "runtime_logs"
    / f"session_{session_id}"
    / "robot.db"
)


conn = sqlite3.connect(
    db
)


row = conn.execute(
    """
    SELECT
        event_time_ns,
        event_type,
        map_name,
        label_name,
        task_type,
        status
    FROM task_events
    ORDER BY event_time_ns DESC
    LIMIT 1
    """
).fetchone()


print()
print(
    "Current session:",
    session_id
)


try:

    with urllib.request.urlopen(
        "http://localhost:8765/api/navigation/status",
        timeout=2,
    ) as response:

        runtime = json.loads(
            response.read().decode(
                "utf-8"
            )
        )


    print()
    print("Navigation runtime:")

    print(
        "  state:",
        runtime.get("state"),
    )

    print(
        "  active map:",
        runtime.get("active_map"),
    )

    print(
        "  ready:",
        runtime.get("ready"),
    )

    print(
        "  localization state:",
        runtime.get(
            "localization_state"
        ),
    )

    print(
        "  localized:",
        runtime.get("localized"),
    )

except Exception as exc:

    print()
    print(
        "Navigation runtime unavailable:",
        exc,
    )


if row:

    print()
    print(
        "Latest task event:",
        {
            "type":
                row[1],

            "map":
                row[2],

            "label":
                row[3],

            "task":
                row[4],

            "status":
                row[5],
        },
    )

else:

    print()
    print(
        "No task events recorded yet."
    )


print()
print("Evidence counts:")


for table in [
    "task_events",
    "odom_samples",
    "cmd_vel_intervals",
    "lidar_summary_intervals",
    "pose_samples",
]:

    try:

        count = conn.execute(
            f"SELECT COUNT(*) "
            f"FROM {table}"
        ).fetchone()[0]

    except Exception:

        count = None


    print(
        f"  {table:26s} {count}"
    )


conn.close()
PY

}


# ============================================================
# DETECT MAP
#
# First preference:
#   current browser/navigation runtime
#
# Second preference:
#   task-event history
# ============================================================

detect_session_map() {

    export QBOT_EXPERIMENT_SESSION_ID="$SESSION_ID"


    MAP_NAME="$(
python - <<'PY'
import json
import os
import sqlite3
import urllib.request

from pathlib import Path


repo = Path.cwd()


session_id = os.environ[
    "QBOT_EXPERIMENT_SESSION_ID"
]


# ------------------------------------------------------------
# Preferred: live browser/navigation runtime
# ------------------------------------------------------------

try:

    with urllib.request.urlopen(
        "http://localhost:8765/api/navigation/status",
        timeout=2,
    ) as response:

        payload = json.loads(
            response.read().decode(
                "utf-8"
            )
        )


    active_map = payload.get(
        "active_map"
    )


    if active_map:

        print(
            str(active_map).strip()
        )

        raise SystemExit

except SystemExit:

    raise

except Exception:

    pass


# ------------------------------------------------------------
# Fallback: SQLite task events
# ------------------------------------------------------------

db = (
    repo
    / "runtime_logs"
    / f"session_{session_id}"
    / "robot.db"
)


conn = sqlite3.connect(
    db
)


rows = conn.execute(
    """
    SELECT
        map_name,
        payload_json
    FROM task_events
    ORDER BY event_time_ns DESC
    """
).fetchall()


conn.close()


for map_name, payload_json in rows:

    if map_name:

        print(
            str(map_name).strip()
        )

        raise SystemExit


    if payload_json:

        try:

            payload = json.loads(
                payload_json
            )

        except Exception:

            continue


        candidate = payload.get(
            "map"
        )


        if candidate:

            print(
                str(candidate).strip()
            )

            raise SystemExit
PY
)"


    # Normalize:
    #
    # map1234.pgm -> map1234

    if [ -n "$MAP_NAME" ]; then

        MAP_NAME="$(
            basename "$MAP_NAME"
        )"

        MAP_NAME="${MAP_NAME%.pgm}"

        MAP_NAME="${MAP_NAME%.yaml}"

        MAP_NAME="${MAP_NAME%_labels.json}"


        echo
        echo "Detected map:"
        echo "  $MAP_NAME"


        export QBOT_EXPERIMENT_MAP_NAME="$MAP_NAME"


        python - <<'PY'
import os
import sqlite3

from pathlib import Path


repo = Path.cwd()


session_id = os.environ[
    "QBOT_EXPERIMENT_SESSION_ID"
]


map_name = os.environ[
    "QBOT_EXPERIMENT_MAP_NAME"
]


db = (
    repo
    / "runtime_logs"
    / f"session_{session_id}"
    / "robot.db"
)


conn = sqlite3.connect(
    db
)


conn.execute(
    """
    UPDATE sessions
    SET map_name = ?
    WHERE session_id = ?
    """,
    (
        map_name,
        session_id,
    ),
)


conn.commit()

conn.close()
PY


    else

        echo
        echo "No map name found in this session."

    fi

}


# ============================================================
# FINALIZE MEMORIES
# ============================================================

finalize_memories() {

    if [ "$MEMORY_FINALIZED" -eq 1 ]; then
        return
    fi


    echo
    echo "============================================================"
    echo "FINALIZING SESSION MEMORY"
    echo "============================================================"


    detect_session_map


    echo
    echo "Building task-intent memory..."


    if [ -n "$MAP_NAME" ]; then

        python \
            src/storage/task_intent_index.py \
            --session-id "$SESSION_ID" \
            --map "$MAP_NAME" \
            || true

    else

        python \
            src/storage/task_intent_index.py \
            --session-id "$SESSION_ID" \
            || true

    fi


    echo
    echo "Building map memory..."


    if [ -n "$MAP_NAME" ]; then

        python \
            src/storage/map_behavior_index.py \
            --session-id "$SESSION_ID" \
            --map "$MAP_NAME" \
            || true

    else

        echo
        echo "Skipping map memory because map is unknown."

    fi


    echo
    echo "Building global behavior memory..."


    python \
        src/storage/index_task_behaviors.py \
        --session-id "$SESSION_ID" \
        || true


    echo
    echo "Building embeddings..."


    if compgen -G \
        "$RUNTIME_DIR/task_intent_index*" \
        >/dev/null
    then

        python \
            src/reasoning/build_task_intent_embeddings.py \
            || true

    fi


    if compgen -G \
        "$RUNTIME_DIR/behavior_index*" \
        >/dev/null
    then

        python \
            src/reasoning/build_behavior_embeddings.py \
            || true

    fi


    if [ -n "$MAP_NAME" ]; then

        local map_index_dir


        map_index_dir="$RUNTIME_DIR/map_indexes/$MAP_NAME"


        if compgen -G \
            "$map_index_dir/label_index*" \
            >/dev/null
        then

            python \
                src/reasoning/build_map_embeddings.py \
                --map "$MAP_NAME" \
                || true

        fi

    fi


    MEMORY_FINALIZED=1


    echo
    echo "Session memory finalized."

}


# ============================================================
# END LIVE SESSION
# ============================================================

end_live_session() {

    if [ "$SESSION_ACTIVE" -eq 0 ]; then

        echo
        echo "Robot session is already stopped."

        return

    fi


    echo
    echo "============================================================"
    echo "ENDING LIVE ROBOT SESSION"
    echo "============================================================"


    # Detect map BEFORE killing browser runtime.

    detect_session_map


    cleanup_processes


    close_session


    EXPERIMENT_FINISHED=1

    SESSION_ACTIVE=0


    trap - INT TERM HUP


    finalize_memories


    echo
    echo "============================================================"
    echo "ROBOT SESSION ENDED"
    echo "============================================================"
    echo
    echo "Logging and experiment robot processes are stopped."
    echo
    echo "The persistent physical QBot driver was left running."
    echo
    echo "Q&A remains available."
    echo

}


# ============================================================
# CHAT LOOP
# ============================================================

while true
do

    echo


    read -rp \
        "robot-log> " \
        QUESTION


    if [ -z "$QUESTION" ]; then
        continue
    fi


    case "$QUESTION" in

        /user)

            AUDIENCE="user"

            echo
            echo "Audience changed to user."

            continue
            ;;


        /developer)

            AUDIENCE="developer"

            echo
            echo "Audience changed to developer."

            continue
            ;;


        /status)

            show_live_status

            continue
            ;;


        /end)

            end_live_session

            continue
            ;;


        exit|quit|q)

            if [ "$SESSION_ACTIVE" -eq 1 ]; then

                end_live_session

            fi


            break
            ;;

    esac


    ensure_nvidia_key


    echo


    if [ "$SESSION_ACTIVE" -eq 1 ]; then

        python \
            src/reasoning/ask_robot.py \
            --session-id "$SESSION_ID" \
            --audience "$AUDIENCE" \
            --question "$QUESTION"

    else

        if [ -n "$MAP_NAME" ]; then

            python \
                src/reasoning/ask_robot.py \
                --session-id "$SESSION_ID" \
                --map "$MAP_NAME" \
                --audience "$AUDIENCE" \
                --question "$QUESTION"

        else

            python \
                src/reasoning/ask_robot.py \
                --session-id "$SESSION_ID" \
                --audience "$AUDIENCE" \
                --question "$QUESTION"

        fi

    fi

done


echo
echo "============================================================"
echo "QBOT SESSION CLOSED"
echo "============================================================"
echo
echo "Session:"
echo "  $SESSION_ID"
echo
echo "Evidence:"
echo "  $SESSION_DIR"
echo
