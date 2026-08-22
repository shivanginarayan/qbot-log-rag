#!/usr/bin/env python3

import argparse
import dbm
import hashlib
import json
import math
import sqlite3
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_DIR / "runtime_logs"
INDEX_PATH = str(RUNTIME_DIR / "behavior_index")


def canonical_json(data):
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
    )


def behavior_key(behavior):
    text = canonical_json(behavior)

    return hashlib.sha256(
        text.encode("utf-8")
    ).hexdigest()[:16]


def get_session_end(conn, session_id):
    row = conn.execute(
        """
        SELECT ended_at_ns
        FROM sessions
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()

    if not row:
        return None

    return row[0]


def get_row_range(
    conn,
    table,
    id_column,
    time_column,
    start_ns,
    end_ns,
):
    row = conn.execute(
        f"""
        SELECT
            MIN({id_column}),
            MAX({id_column}),
            COUNT(*)
        FROM {table}
        WHERE {time_column} >= ?
          AND {time_column} <= ?
        """,
        (start_ns, end_ns),
    ).fetchone()

    if not row or row[2] == 0:
        return None

    return {
        "first_id": row[0],
        "last_id": row[1],
        "count": row[2],
    }


def find_executed_navigations(
    conn,
    session_id,
):
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

    session_end = get_session_end(
        conn,
        session_id,
    )

    occurrences = []

    for i, row in enumerate(rows):
        (
            event_id,
            event_time_ns,
            event_type,
            map_name,
            label_id,
            label_name,
            task_type,
            status,
            payload_json,
        ) = row

        if event_type != "NAVIGATION_STARTED":
            continue

        if task_type != "navigate_to_location":
            continue

        start_ns = event_time_ns
        end_ns = None

        outcome = "unknown_interrupted"
        final_status = None

        label_key = (
            str(label_name or "")
            .strip()
            .casefold()
        )

        try:
            payload = (
                json.loads(payload_json)
                if payload_json
                else {}
            )
        except Exception:
            payload = {}

        for later in rows[i + 1:]:
            (
                later_id,
                later_time,
                later_type,
                later_map,
                later_label_id,
                later_label,
                later_task_type,
                later_status,
                later_payload,
            ) = later

            later_label_key = (
                str(later_label or "")
                .strip()
                .casefold()
            )

            if (
                later_type == "NAVIGATION_FINISHED"
                and later_task_type
                == "navigate_to_location"
                and later_label_key == label_key
            ):
                end_ns = later_time
                final_status = later_status

                if str(later_status) == "4":
                    outcome = "succeeded"
                elif str(later_status) == "5":
                    outcome = "canceled"
                elif str(later_status) == "6":
                    outcome = "failed"
                else:
                    outcome = "finished_unknown"

                break

            # Another executed navigation started
            # before this one completed.
            if (
                later_type == "NAVIGATION_STARTED"
                and later_task_type
                == "navigate_to_location"
            ):
                end_ns = later_time
                break

        if end_ns is None:
            end_ns = session_end or start_ns

        occurrences.append(
            {
                "event_id": event_id,
                "start_ns": start_ns,
                "end_ns": end_ns,

                "label_name": (
                    payload.get("name")
                    or label_name
                ),

                "map_name": (
                    payload.get("map")
                    or map_name
                ),

                "label_id": (
                    payload.get("label_id")
                    or label_id
                ),

                "world": payload.get("world"),
                "yaw": payload.get("yaw"),

                "outcome": outcome,
                "final_status": final_status,
            }
        )

    return occurrences


def get_odom_motion(
    conn,
    start_ns,
    end_ns,
):
    rows = conn.execute(
        """
        SELECT
            received_at_ns,
            x,
            y,
            yaw_rad
        FROM odom_samples
        WHERE received_at_ns >= ?
          AND received_at_ns <= ?
        ORDER BY received_at_ns
        """,
        (start_ns, end_ns),
    ).fetchall()

    if len(rows) < 2:
        return {
            "source": "wheel_odometry",
            "sample_count": len(rows),
            "distance_m": None,
            "net_displacement_m": None,
            "relative_dx_m": None,
            "relative_dy_m": None,
        }

    first = rows[0]
    last = rows[-1]

    first_x = float(first[1])
    first_y = float(first[2])
    first_yaw = float(first[3])

    last_x = float(last[1])
    last_y = float(last[2])

    dx = last_x - first_x
    dy = last_y - first_y

    net_displacement = math.hypot(
        dx,
        dy,
    )

    # Transform map/odom displacement into
    # robot-relative coordinates using start yaw.
    relative_dx = (
        math.cos(first_yaw) * dx
        + math.sin(first_yaw) * dy
    )

    relative_dy = (
        -math.sin(first_yaw) * dx
        + math.cos(first_yaw) * dy
    )

    total_distance = 0.0

    previous_x = first_x
    previous_y = first_y

    for row in rows[1:]:
        x = float(row[1])
        y = float(row[2])

        total_distance += math.hypot(
            x - previous_x,
            y - previous_y,
        )

        previous_x = x
        previous_y = y

    return {
        "source": "wheel_odometry",
        "sample_count": len(rows),
        "distance_m": total_distance,
        "net_displacement_m": net_displacement,
        "relative_dx_m": relative_dx,
        "relative_dy_m": relative_dy,
    }


def get_cmd_stats(
    conn,
    start_ns,
    end_ns,
):
    rows = conn.execute(
        """
        SELECT
            linear_x,
            linear_y,
            angular_z
        FROM cmd_vel_intervals
        WHERE started_at_ns >= ?
          AND started_at_ns <= ?
        ORDER BY started_at_ns
        """,
        (start_ns, end_ns),
    ).fetchall()

    if not rows:
        return {
            "interval_count": 0,
            "max_abs_linear_x": 0.0,
            "max_abs_angular_z": 0.0,
        }

    return {
        "interval_count": len(rows),

        "max_abs_linear_x": max(
            abs(float(row[0] or 0.0))
            for row in rows
        ),

        "max_abs_angular_z": max(
            abs(float(row[2] or 0.0))
            for row in rows
        ),
    }


def classify_behavior(
    odom,
    cmd,
):
    net = odom.get(
        "net_displacement_m"
    )

    relative_dx = odom.get(
        "relative_dx_m"
    )

    relative_dy = odom.get(
        "relative_dy_m"
    )

    commanded_translation = (
        cmd.get(
            "max_abs_linear_x",
            0.0,
        ) > 0.01
    )

    commanded_rotation = (
        cmd.get(
            "max_abs_angular_z",
            0.0,
        ) > 0.05
    )

    if net is None:
        motion_family = "unknown"

    elif net < 0.03:
        if commanded_translation:
            motion_family = (
                "translation_commanded_little_motion"
            )
        elif commanded_rotation:
            motion_family = "rotation"
        else:
            motion_family = "stationary"

    else:
        motion_family = "translation"

    relative_direction = "unknown"

    if (
        relative_dx is not None
        and relative_dy is not None
    ):
        if (
            abs(relative_dx)
            >= abs(relative_dy)
        ):
            if relative_dx > 0.03:
                relative_direction = "forward"
            elif relative_dx < -0.03:
                relative_direction = "backward"
        else:
            if relative_dy > 0.03:
                relative_direction = "left"
            elif relative_dy < -0.03:
                relative_direction = "right"

    behavior = {
        "action_family": "navigation",
        "motion_family": motion_family,
        # "relative_direction": relative_direction,
    }

    return behavior


def store_occurrence(
    behavior,
    occurrence,
):
    key = behavior_key(
        behavior
    )

    with dbm.open(
        INDEX_PATH,
        "c",
    ) as index:

        raw_key = key.encode(
            "utf-8"
        )

        if raw_key in index:
            record = json.loads(
                index[
                    raw_key
                ].decode("utf-8")
            )
        else:
            record = {
                "behavior_key": key,
                "behavior": behavior,
                "occurrences": [],
            }

        occurrence_id = occurrence[
            "occurrence_id"
        ]

        exists = any(
            old.get(
                "occurrence_id"
            ) == occurrence_id
            for old
            in record[
                "occurrences"
            ]
        )

        if not exists:
            record[
                "occurrences"
            ].append(
                occurrence
            )

        index[
            raw_key
        ] = json.dumps(
            record,
            indent=2,
        ).encode("utf-8")

    return key, not exists


def index_session(
    session_id,
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

    executed = (
        find_executed_navigations(
            conn,
            session_id,
        )
    )

    if not executed:
        print(
            "No executed navigation "
            "occurrences found."
        )

        conn.close()
        return

    for item in executed:
        start_ns = item[
            "start_ns"
        ]

        end_ns = item[
            "end_ns"
        ]

        odom = get_odom_motion(
            conn,
            start_ns,
            end_ns,
        )

        cmd = get_cmd_stats(
            conn,
            start_ns,
            end_ns,
        )

        behavior = classify_behavior(
            odom,
            cmd,
        )

        occurrence = {
            "occurrence_id":
                f"{session_id}:task_event:"
                f"{item['event_id']}",

            "session_id":
                session_id,

            "time_range": {
                "start_ns":
                    start_ns,
                "end_ns":
                    end_ns,
            },

            "task_context": {
                "map":
                    item.get(
                        "map_name"
                    ),

                "label_id":
                    item.get(
                        "label_id"
                    ),

                "label_name":
                    item.get(
                        "label_name"
                    ),

                "world":
                    item.get(
                        "world"
                    ),

                "yaw":
                    item.get(
                        "yaw"
                    ),
            },

            "outcome": {
                "status":
                    item[
                        "outcome"
                    ],

                "raw_status":
                    item[
                        "final_status"
                    ],
            },

            "observed_motion": odom,

            "command_summary": cmd,

            "sqlite_refs": {
                "task_events":
                    get_row_range(
                        conn,
                        "task_events",
                        "task_event_id",
                        "event_time_ns",
                        start_ns,
                        end_ns,
                    ),

                "odom_samples":
                    get_row_range(
                        conn,
                        "odom_samples",
                        "odom_id",
                        "received_at_ns",
                        start_ns,
                        end_ns,
                    ),

                "cmd_vel_intervals":
                    get_row_range(
                        conn,
                        "cmd_vel_intervals",
                        "cmd_vel_id",
                        "started_at_ns",
                        start_ns,
                        end_ns,
                    ),

                "lidar_summary_intervals":
                    get_row_range(
                        conn,
                        "lidar_summary_intervals",
                        "lidar_id",
                        "started_at_ns",
                        start_ns,
                        end_ns,
                    ),

                "pose_samples":
                    get_row_range(
                        conn,
                        "pose_samples",
                        "pose_id",
                        "received_at_ns",
                        start_ns,
                        end_ns,
                    ),
            },

            "source": {
                "sqlite_db":
                    str(db_path),

                "rosbag":
                    str(
                        RUNTIME_DIR
                        / f"session_{session_id}"
                        / "rosbag"
                    ),
            },
        }

        key, added = (
            store_occurrence(
                behavior,
                occurrence,
            )
        )

        print()
        print(
            f"Behavior key: {key}"
        )

        print(
            "Behavior:",
            json.dumps(
                behavior
            ),
        )

        print(
            "Label:",
            item.get(
                "label_name"
            ),
        )

        print(
            "Outcome:",
            item[
                "outcome"
            ],
        )

        print(
            "Net displacement:",
            odom.get(
                "net_displacement_m"
            ),
        )

        print(
            "Distance traveled:",
            odom.get(
                "distance_m"
            ),
        )

        print(
            "Occurrence:",
            occurrence[
                "occurrence_id"
            ],
        )

        if added:
            print(
                "Added to global "
                "behavior index."
            )
        else:
            print(
                "Occurrence already "
                "indexed."
            )

    conn.close()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--session-id",
        required=True,
    )

    args = parser.parse_args()

    index_session(
        args.session_id
    )


if __name__ == "__main__":
    main()
