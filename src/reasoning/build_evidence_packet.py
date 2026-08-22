#!/usr/bin/env python3

import argparse
import json
import math
import sqlite3
import statistics
from pathlib import Path


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
                  AND ended_at_ns >= ?
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
