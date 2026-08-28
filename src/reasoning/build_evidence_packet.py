#!/usr/bin/env python3
import time
import argparse
import json
import math
import sqlite3
import statistics
from pathlib import Path
import urllib.error
import urllib.request
try:
    from .live_ros_status import (
        collect_ros_runtime,
    )

except ImportError:
    from live_ros_status import (
        collect_ros_runtime,
    )

REPO_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_DIR / "runtime_logs"


def table_columns(conn, table):
    return {
        row[1]: row[2]
        for row in conn.execute(
            f"PRAGMA table_info({table})"
        )
    }


def table_exists(conn, table):
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type='table'
          AND name=?
        """,
        (table,),
    ).fetchone()

    return row is not None


def fetch_window(
    conn,
    table,
    start_ns,
    end_ns,
):
    cols = table_columns(conn, table)

    if "event_time_ns" in cols:
        query = f"""
            SELECT *
            FROM {table}
            WHERE event_time_ns >= ?
              AND event_time_ns <= ?
            ORDER BY event_time_ns
        """
        return conn.execute(
            query,
            (start_ns, end_ns),
        ).fetchall(), list(cols.keys())

    if "received_at_ns" in cols:
        query = f"""
            SELECT *
            FROM {table}
            WHERE received_at_ns >= ?
              AND received_at_ns <= ?
            ORDER BY received_at_ns
        """
        return conn.execute(
            query,
            (start_ns, end_ns),
        ).fetchall(), list(cols.keys())

    if "started_at_ns" in cols:
        if "ended_at_ns" in cols:
            query = f"""
                SELECT *
                FROM {table}
                WHERE started_at_ns <= ?
                  AND (
                        ended_at_ns >= ?
                        OR ended_at_ns IS NULL
                  )
                ORDER BY started_at_ns
            """
            return conn.execute(
                query,
                (end_ns, start_ns),
            ).fetchall(), list(cols.keys())

        query = f"""
            SELECT *
            FROM {table}
            WHERE started_at_ns >= ?
              AND started_at_ns <= ?
            ORDER BY started_at_ns
        """

        return conn.execute(
            query,
            (start_ns, end_ns),
        ).fetchall(), list(cols.keys())

    return [], list(cols.keys())


def rows_as_dicts(rows, columns):
    return [
        dict(zip(columns, row))
        for row in rows
    ]


def summarize_task_events(
    conn,
    start_ns,
    end_ns,
):
    if not table_exists(
        conn,
        "task_events",
    ):
        return []

    rows, columns = fetch_window(
        conn,
        "task_events",
        start_ns,
        end_ns,
    )

    result = []

    for row in rows_as_dicts(
        rows,
        columns,
    ):
        item = {
            "event_time_ns":
                row.get("event_time_ns"),

            "event_type":
                row.get("event_type"),

            "map_name":
                row.get("map_name"),

            "label_id":
                row.get("label_id"),

            "label_name":
                row.get("label_name"),

            "task_type":
                row.get("task_type"),

            "status":
                row.get("status"),
        }

        raw_payload = row.get(
            "payload_json"
        )

        if raw_payload:
            try:
                item["payload"] = json.loads(
                    raw_payload
                )
            except Exception:
                item["payload_raw"] = (
                    raw_payload
                )

        result.append(item)

    return result


def summarize_odom(
    conn,
    start_ns,
    end_ns,
):
    if not table_exists(
        conn,
        "odom_samples",
    ):
        return None

    rows = conn.execute(
        """
        SELECT
            received_at_ns,
            x,
            y,
            yaw_rad,
            linear_x,
            angular_z
        FROM odom_samples
        WHERE received_at_ns >= ?
          AND received_at_ns <= ?
        ORDER BY received_at_ns
        """,
        (start_ns, end_ns),
    ).fetchall()

    if not rows:
        return {
            "source":
                "wheel_odometry",
            "sample_count": 0,
        }

    first = rows[0]
    last = rows[-1]

    dx = float(last[1]) - float(first[1])
    dy = float(last[2]) - float(first[2])

    net = math.hypot(
        dx,
        dy,
    )

    distance = 0.0

    px = float(first[1])
    py = float(first[2])

    for row in rows[1:]:
        x = float(row[1])
        y = float(row[2])

        distance += math.hypot(
            x - px,
            y - py,
        )

        px = x
        py = y

    linear_values = [
        abs(float(row[4]))
        for row in rows
        if row[4] is not None
    ]

    angular_values = [
        abs(float(row[5]))
        for row in rows
        if row[5] is not None
    ]

    return {
        "source":
            "wheel_odometry",

        "sample_count":
            len(rows),

        "first_pose": {
            "x": first[1],
            "y": first[2],
            "yaw_rad": first[3],
        },

        "last_pose": {
            "x": last[1],
            "y": last[2],
            "yaw_rad": last[3],
        },

        "estimated_net_displacement_m":
            net,

        "estimated_path_distance_m":
            distance,

        "max_abs_linear_velocity_mps":
            max(linear_values)
            if linear_values
            else None,

        "max_abs_angular_velocity_radps":
            max(angular_values)
            if angular_values
            else None,
    }


def summarize_cmd_vel(
    conn,
    start_ns,
    end_ns,
):
    if not table_exists(
        conn,
        "cmd_vel_intervals",
    ):
        return None

    rows, columns = fetch_window(
        conn,
        "cmd_vel_intervals",
        start_ns,
        end_ns,
    )

    records = rows_as_dicts(
        rows,
        columns,
    )

    if not records:
        return {
            "interval_count": 0,
            "translation_command_present":
                False,
            "rotation_command_present":
                False,
        }

    linear = [
        abs(
            float(
                row.get("linear_x")
                or 0.0
            )
        )
        for row in records
    ]

    angular = [
        abs(
            float(
                row.get("angular_z")
                or 0.0
            )
        )
        for row in records
    ]

    return {
        "interval_count":
            len(records),

        "max_abs_linear_x_mps":
            max(linear),

        "max_abs_angular_z_radps":
            max(angular),

        "translation_command_present":
            max(linear) > 0.01,

        "rotation_command_present":
            max(angular) > 0.05,
    }


def numeric_summary(values):
    values = [
        float(v)
        for v in values
        if v is not None
    ]

    if not values:
        return None

    return {
        "min": min(values),
        "median":
            statistics.median(values),
        "max": max(values),
        "mean":
            sum(values) / len(values),
    }


def summarize_lidar(
    conn,
    start_ns,
    end_ns,
):
    if not table_exists(
        conn,
        "lidar_summary_intervals",
    ):
        return None

    rows, columns = fetch_window(
        conn,
        "lidar_summary_intervals",
        start_ns,
        end_ns,
    )

    records = rows_as_dicts(
        rows,
        columns,
    )

    result = {
        "interval_count":
            len(records)
    }

    if not records:
        return result

    # Schema-independent:
    # summarize useful range/distance columns.
    useful_columns = []

    for column in columns:
        lower = column.lower()

        location_word = any(
            word in lower
            for word in [
                "closest",
                "front",
                "left",
                "right",
                "rear",
            ]
        )

        range_word = any(
            word in lower
            for word in [
                "min",
                "distance",
                "range",
            ]
        )

        if location_word and range_word:
            useful_columns.append(
                column
            )

    for column in useful_columns:
        summary = numeric_summary(
            row.get(column)
            for row in records
        )

        if summary is not None:
            result[column] = summary

    return result


def summarize_amcl(
    conn,
    start_ns,
    end_ns,
):
    if not table_exists(
        conn,
        "pose_samples",
    ):
        return None

    rows, columns = fetch_window(
        conn,
        "pose_samples",
        start_ns,
        end_ns,
    )

    records = rows_as_dicts(
        rows,
        columns,
    )

    if not records:
        return {
            "sample_count": 0
        }

    first = records[0]
    last = records[-1]

    def pose_from(row):
        result = {}

        for name in [
            "x",
            "y",
            "z",
            "yaw_rad",
            "yaw",
        ]:
            if name in row:
                result[name] = row[name]

        return result

    result = {
        "sample_count":
            len(records),

        "first_pose":
            pose_from(first),

        "last_pose":
            pose_from(last),
    }

    stale_values = [
        row.get("is_stale")
        for row in records
        if row.get("is_stale")
        is not None
    ]

    if stale_values:
        result[
            "stale_sample_count"
        ] = sum(
            int(bool(value))
            for value in stale_values
        )

    covariance_columns = [
        c for c in columns
        if "cov" in c.lower()
    ]

    for column in covariance_columns:
        summary = numeric_summary(
            row.get(column)
            for row in records
        )

        if summary:
            result[column] = summary

    return result


def build_packet(
    session_id,
    start_ns,
    end_ns,
):
    db_path = (
        RUNTIME_DIR
        / f"session_{session_id}"
        / "robot.db"
    )

    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found: {db_path}"
        )

    conn = sqlite3.connect(
        db_path
    )

    packet = {
        "session_id":
            session_id,

        "time_range": {
            "start_ns":
                int(start_ns),

            "end_ns":
                int(end_ns),

            "duration_s":
                (
                    int(end_ns)
                    - int(start_ns)
                )
                / 1e9,
        },

        "task_events":
            summarize_task_events(
                conn,
                start_ns,
                end_ns,
            ),

        "wheel_odometry":
            summarize_odom(
                conn,
                start_ns,
                end_ns,
            ),

        "velocity_commands":
            summarize_cmd_vel(
                conn,
                start_ns,
                end_ns,
            ),

        "lidar":
            summarize_lidar(
                conn,
                start_ns,
                end_ns,
            ),

        "localization":
            summarize_amcl(
                conn,
                start_ns,
                end_ns,
            ),

        "source": {
            "sqlite":
                str(db_path),

            "rosbag":
                str(
                    RUNTIME_DIR
                    / f"session_{session_id}"
                    / "rosbag"
                ),
        },

        "grounding_notes": [
            (
                "Wheel odometry is an estimate "
                "and is not guaranteed to equal "
                "physical chassis displacement."
            ),
            (
                "Navigation status represents "
                "the navigation system's result, "
                "not independent physical ground truth."
            ),
            (
                "Temporal correlation alone does "
                "not prove causality."
            ),
        ],
    }

    conn.close()

    return packet

def get_session_info(
    conn,
    session_id,
):
    row = conn.execute(
        """
        SELECT
            started_at_ns,
            ended_at_ns,
            status,
            map_name
        FROM sessions
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()

    if not row:
        return None

    return {
        "started_at_ns":
            row[0],

        "ended_at_ns":
            row[1],

        "status":
            row[2],

        "map_name":
            row[3],
    }


def get_live_navigation_state(
    conn,
):
    """
    Determine what navigation is doing RIGHT NOW
    from recorded task events.

    Important:
    absence of FINISHED in a live session does NOT
    mean interrupted.
    """

    rows = conn.execute(
        """
        SELECT
            task_event_id,
            event_time_ns,
            event_type,
            map_name,
            label_id,
            label_name,
            task_type,
            status,
            payload_json
        FROM task_events
        ORDER BY event_time_ns
        """
    ).fetchall()

    if not rows:
        return {
            "state":
                "no_task_events_recorded"
        }

    latest_command = None

    for row in reversed(rows):

        if (
            row[2] == "NAVIGATION_COMMAND"
            and row[6]
            == "navigate_to_location"
        ):
            latest_command = row
            break

    if latest_command is None:

        latest_event = rows[-1]

        return {
            "state":
                "no_navigation_request_recorded",

            "latest_event": {
                "event_time_ns":
                    latest_event[1],

                "event_type":
                    latest_event[2],

                "label_name":
                    latest_event[5],

                "task_type":
                    latest_event[6],

                "status":
                    latest_event[7],
            },
        }

    (
        command_id,
        command_time,
        _,
        command_map,
        command_label_id,
        command_label,
        _,
        _,
        command_payload_json,
    ) = latest_command

    try:
        command_payload = (
            json.loads(
                command_payload_json
            )
            if command_payload_json
            else {}
        )
    except Exception:
        command_payload = {}

    started = None
    finished = None

    label_key = (
        str(command_label or "")
        .strip()
        .casefold()
    )

    command_index = None

    for i, row in enumerate(rows):
        if row[0] == command_id:
            command_index = i
            break

    if command_index is not None:

        for later in rows[
            command_index + 1:
        ]:

            (
                later_id,
                later_time,
                later_type,
                later_map,
                later_label_id,
                later_label,
                later_task,
                later_status,
                later_payload_json,
            ) = later

            # A newer navigation request means
            # this command is no longer the current one.
            if (
                later_type
                == "NAVIGATION_COMMAND"
                and later_task
                == "navigate_to_location"
            ):
                break

            later_label_key = (
                str(
                    later_label or ""
                )
                .strip()
                .casefold()
            )

            if (
                started is None
                and later_type
                == "NAVIGATION_STARTED"
                and later_task
                == "navigate_to_location"
                and later_label_key
                == label_key
            ):
                started = {
                    "event_id":
                        later_id,

                    "event_time_ns":
                        later_time,

                    "map_name":
                        later_map,

                    "label_id":
                        later_label_id,

                    "label_name":
                        later_label,

                    "status":
                        later_status,

                    "payload_json":
                        later_payload_json,
                }

            elif (
                started is not None
                and later_type
                == "NAVIGATION_FINISHED"
                and later_task
                == "navigate_to_location"
                and later_label_key
                == label_key
            ):
                finished = {
                    "event_id":
                        later_id,

                    "event_time_ns":
                        later_time,

                    "status":
                        later_status,

                    "payload_json":
                        later_payload_json,
                }

                break

    map_name = (
        (
            started.get(
                "map_name"
            )
            if started
            else None
        )
        or command_map
        or command_payload.get("map")
    )

    result = {
        "command_event_id":
            command_id,

        "command_time_ns":
            command_time,

        "map":
            map_name,

        "label_id":
            (
                (
                    started.get(
                        "label_id"
                    )
                    if started
                    else None
                )
                or command_label_id
            ),

        "label_name":
            command_label,

        "execution_start_ns":
            (
                started[
                    "event_time_ns"
                ]
                if started
                else None
            ),

        "finish_ns":
            (
                finished[
                    "event_time_ns"
                ]
                if finished
                else None
            ),

        "final_status":
            (
                finished[
                    "status"
                ]
                if finished
                else None
            ),
    }

    if finished is not None:

        status = str(
            finished.get(
                "status"
            )
        )

        if status == "4":
            outcome = "succeeded"

        elif status == "5":
            outcome = "canceled"

        elif status == "6":
            outcome = "failed"

        else:
            outcome = "finished_unknown"

        result[
            "state"
        ] = "navigation_finished"

        result[
            "outcome"
        ] = outcome

    elif started is not None:

        result[
            "state"
        ] = "navigation_in_progress"

        result[
            "outcome"
        ] = None

    else:

        # This is deliberately NOT called
        # no_execution_start_recorded.
        #
        # The session is live and the start
        # event could still arrive.
        result[
            "state"
        ] = "navigation_requested_waiting_for_start"

        result[
            "outcome"
        ] = None

    return result

def get_navigation_runtime_status():
    """
    Read the map-labeler's live navigation status.

    This is runtime state, not historical evidence.
    Failure to reach the endpoint should not prevent
    SQLite evidence retrieval.
    """

    url = (
        "http://localhost:8765"
        "/api/navigation/status"
    )

    try:

        request = urllib.request.Request(
            url,
            method="GET",
        )

        with urllib.request.urlopen(
            request,
            timeout=2.0,
        ) as response:

            payload = json.loads(
                response.read().decode(
                    "utf-8"
                )
            )

        if not isinstance(
            payload,
            dict,
        ):
            return None

        return {
            "available":
                True,

            "state":
                payload.get(
                    "state"
                ),

            "active_map":
                payload.get(
                    "active_map"
                ),

            "ready":
                payload.get(
                    "ready"
                ),

            "message":
                payload.get(
                    "message"
                ),

            "ros_domain_id":
                payload.get(
                    "ros_domain_id"
                ),

            "localization_state":
                payload.get(
                    "localization_state"
                ),

            "localization_required":
                payload.get(
                    "localization_required"
                ),

            "localized":
                payload.get(
                    "localized"
                ),

            "localization_message":
                payload.get(
                    "localization_message"
                ),
        }

    except Exception as exc:

        return {
            "available":
                False,

            "error":
                str(exc),
        }


def build_live_packet(
    session_id,
    lookback_s=30.0,
):
    """
    Build evidence representing what is happening
    in the current session NOW.

    If navigation is active/requested, evidence starts
    at the command time so the whole current task is visible.

    Otherwise use a short recent window.
    """

    db_path = (
        RUNTIME_DIR
        / f"session_{session_id}"
        / "robot.db"
    )

    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found: {db_path}"
        )

    conn = sqlite3.connect(
        db_path,
        timeout=5.0,
    )

    session = get_session_info(
        conn,
        session_id,
    )

    if session is None:
        conn.close()

        raise ValueError(
            f"Session not found: {session_id}"
        )

    live_state = (
        get_live_navigation_state(
            conn
        )
    )

    runtime_status = (
        get_navigation_runtime_status()
    )

    ros_runtime = (
        collect_ros_runtime()
    )

    now_ns = time.time_ns()

    session_start = int(
        session[
            "started_at_ns"
        ]
    )

    command_time = (
        live_state.get(
            "command_time_ns"
        )
    )

    state = live_state.get(
        "state"
    )

    if (
        state in {
            "navigation_requested_waiting_for_start",
            "navigation_in_progress",
        }
        and command_time is not None
    ):

        start_ns = int(
            command_time
        )

    else:

        lookback_ns = int(
            lookback_s * 1e9
        )

        start_ns = max(
            session_start,
            now_ns - lookback_ns,
        )

    end_ns = now_ns

    conn.close()

    packet = build_packet(
        session_id,
        start_ns,
        end_ns,
    )

    # --------------------------------------------------------
    # Runtime map from browser/navigation backend
    # --------------------------------------------------------

    runtime_map = None

    if (
        runtime_status
        and runtime_status.get(
            "available"
        )
    ):
        runtime_map = (
            runtime_status.get(
                "active_map"
            )
        )

    # --------------------------------------------------------
    # Map recorded in SQLite/task evidence
    # --------------------------------------------------------

    recorded_map = (
        live_state.get(
            "map"
        )
        or session.get(
            "map_name"
        )
    )

    # Runtime information is preferred for
    # questions about the CURRENT robot state.
    current_map = (
        runtime_map
        or recorded_map
    )

    packet[
        "live_session"
    ] = {
        "is_live":
            session[
                "ended_at_ns"
            ] is None,

        "session_status":
            session[
                "status"
            ],

        "map":
            current_map,

        "ros_runtime":
            ros_runtime,

        "map_sources": {
            "runtime_navigation_status":
                runtime_map,

            "recorded_task_events_or_session":
                recorded_map,
        },

        "navigation_runtime":
            runtime_status,

        "current_navigation":
            live_state,

        "evidence_generated_at_ns":
            now_ns,
    }

    packet[
        "grounding_notes"
    ].append(
        (
            "This packet may represent an active "
            "session. Missing completion events "
            "must not be interpreted as failure "
            "or interruption while the session "
            "is still running."
        )
    )

    packet[
        "grounding_notes"
    ].append(
        (
            "For current-map questions, the live "
            "navigation runtime active_map is preferred "
            "over historical map-memory retrieval."
        )
    )

    return packet

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--session-id",
        required=True,
    )

    parser.add_argument(
        "--start-ns",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--end-ns",
        required=True,
        type=int,
    )

    parser.add_argument(
        "--output",
    )

    args = parser.parse_args()

    packet = build_packet(
        args.session_id,
        args.start_ns,
        args.end_ns,
    )

    text = json.dumps(
        packet,
        indent=2,
    )

    print(text)

    if args.output:
        Path(
            args.output
        ).write_text(
            text + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
