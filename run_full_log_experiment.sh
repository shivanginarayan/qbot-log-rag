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
# ============================================================


# ============================================================
# PATHS
# ============================================================

REPO_DIR="$HOME/ENGR857_Narayan_Shivangi/project/qbot-log-rag"

RUNTIME_DIR="$REPO_DIR/runtime_logs"


cd "$REPO_DIR" || exit 1


# ============================================================
# PYTHON ENVIRONMENT
# ============================================================

if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi


# ============================================================
# ROS DOMAIN
# ============================================================

export ROS_DOMAIN_ID=57


echo
echo "Using ROS_DOMAIN_ID=$ROS_DOMAIN_ID"


# ============================================================
# ROBOT PROCESS GROUP DETECTION
#
# Only valid positive PGIDs are returned.
# PGID 0 is NEVER allowed.
# ============================================================

robot_process_pgids() {

    ps -eo pgid=,args= \
        | awk '
        /run_qbot_navigation\.sh/ ||
        /run_qbot_mapping\.sh/ ||
        /robot_navigation\/install\/qbot_platform/ ||
        /qbot_platform_manual_map_launch/ ||
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
# SAFE STALE CLEANUP
#
# We only clean:
#   - old browser server on port 8765
#   - old evidence logger processes
#   - old rosbag recorder
#
# We DO NOT kill arbitrary navigation process groups here.
# ============================================================

stop_stale_pid_matches() {

    local pattern="$1"
    local pids


    pids="$(
        pgrep -f "$pattern" \
            2>/dev/null || true
    )"


    while read -r pid
    do

        if [ -z "$pid" ]; then
            continue
        fi


        if [ "$pid" = "$$" ]; then
            continue
        fi


        if [ "$pid" = "$PPID" ]; then
            continue
        fi


        kill -INT "$pid" \
            2>/dev/null || true


    done <<< "$pids"
}


echo
echo "Checking for stale processes from a previous experiment..."


if fuser 8765/tcp \
    >/dev/null 2>&1
then

    echo "Stopping stale map-label browser server..."

    fuser -k 8765/tcp \
        >/dev/null 2>&1 || true

fi


stop_stale_pid_matches \
    'src/storage/(odom_logger|amcl_pose_logger|cmd_vel_logger|lidar_logger|task_event_logger)\.py'


stop_stale_pid_matches \
    'ros2 bag record'


sleep 1


echo "Stale logging/browser cleanup complete."


# ============================================================
# SNAPSHOT EXISTING ROBOT PROCESS GROUPS
#
# Anything already running now is protected.
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

EXPERIMENT_FINISHED=0

SESSION_ACTIVE=1

MEMORY_FINALIZED=0

AUDIENCE="user"


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
# SIGNAL ONLY ROBOT GROUPS CREATED DURING THIS RUN
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


        # Only positive integer process-group IDs.
        # Never PGID 0.

        if ! [[ "$pgid" =~ ^[1-9][0-9]*$ ]]; then
            continue
        fi


        # Never signal our launcher shell.

        if [ "$pgid" = "$our_pgid" ]; then
            continue
        fi


        # Protect anything that existed before this run.

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
# CLEANUP
# ============================================================

cleanup_processes() {

    echo
    echo "============================================================"
    echo "STOPPING EXPERIMENT PROCESSES"
    echo "============================================================"
    echo


    # --------------------------------------------------------
    # Evidence logger process group
    # --------------------------------------------------------

    if [ -n "${LOGGER_PID:-}" ]; then

        local logger_pgid


        logger_pgid="$(
            ps -o pgid= -p "$LOGGER_PID" \
                2>/dev/null \
                | tr -d ' '
        )"


        if [[ "$logger_pgid" =~ ^[1-9][0-9]*$ ]]; then

            echo \
                "Stopping evidence logger group: $logger_pgid"


            kill -INT \
                -- "-$logger_pgid" \
                2>/dev/null || true

        fi

    fi


    sleep 2


    # --------------------------------------------------------
    # Browser GUI process group
    # --------------------------------------------------------

    if [ -n "${GUI_PID:-}" ]; then

        local gui_pgid


        gui_pgid="$(
            ps -o pgid= -p "$GUI_PID" \
                2>/dev/null \
                | tr -d ' '
        )"


        if [[ "$gui_pgid" =~ ^[1-9][0-9]*$ ]]; then

            echo \
                "Stopping browser GUI group: $gui_pgid"


            kill -INT \
                -- "-$gui_pgid" \
                2>/dev/null || true

        fi

    fi


    sleep 1


    # --------------------------------------------------------
    # Detached mapping/navigation groups created after startup
    # --------------------------------------------------------

    echo
    echo "Stopping detached experiment ROS groups..."


    signal_new_robot_groups INT


    sleep 2


    signal_new_robot_groups TERM


    sleep 1


    signal_new_robot_groups KILL


    # --------------------------------------------------------
    # Session-specific logging fallback
    # --------------------------------------------------------

    if [ -n "${SESSION_ID:-}" ]; then

        pkill -INT -f \
            "src/storage/.*${SESSION_ID}" \
            2>/dev/null || true


        pkill -INT -f \
            "ros2 bag record.*${SESSION_ID}" \
            2>/dev/null || true

    fi


    # --------------------------------------------------------
    # Browser port
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
    # Refresh ROS graph
    # --------------------------------------------------------

    ROS_DOMAIN_ID=57 \
        ros2 daemon stop \
        >/dev/null 2>&1 || true


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

    fi


    exit 130

}


trap handle_interrupt INT TERM HUP


# ============================================================
# FINAL EXIT SAFETY
# ============================================================

final_exit_cleanup() {

    if [ "$EXPERIMENT_FINISHED" -eq 0 ]; then

        cleanup_processes

        close_session \
            2>/dev/null || true


        EXPERIMENT_FINISHED=1

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

    exit 1

fi


echo
echo "Evidence logging running."
echo
echo "Evidence log:"
echo "  $EVIDENCE_LOG"
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
import os
import sqlite3

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


if row:

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
# DETECT MAP FROM TASK EVENTS
# ============================================================

detect_session_map() {

    export QBOT_EXPERIMENT_SESSION_ID="$SESSION_ID"


    MAP_NAME="$(
python - <<'PY'
import json
import os
import sqlite3

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


    if [ -n "$MAP_NAME" ]; then

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

        echo \
            "Skipping map memory because map is unknown."

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
    echo "Logging and browser processes are stopped."
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