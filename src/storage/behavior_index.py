import argparse
import dbm
import hashlib
import json
import math
import os
import sqlite3
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_DIR / "runtime_logs"

# dbm may create one or more physical files depending on the Linux backend.
INDEX_PATH = str(RUNTIME_DIR / "behavior_index")


def normalize_angle(angle):
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def relative_direction(start_x, start_y, start_yaw, target_x, target_y):
    """
    Describe target direction relative to the robot at the beginning
    of the navigation action.

    This intentionally does NOT use absolute map directions such as
    +x or +y as the behavior identity.
    """

    dx = target_x - start_x
    dy = target_y - start_y

    distance = math.hypot(dx, dy)

    if distance < 0.05:
        return "no_significant_translation", distance

    # Convert map-frame displacement into robot-relative coordinates.
    forward = (
        math.cos(start_yaw) * dx
        + math.sin(start_yaw) * dy
    )

    lateral = (
        -math.sin(start_yaw) * dx
        + math.cos(start_yaw) * dy
    )

    angle = math.atan2(lateral, forward)

    # Generic directional categories.
    if -math.pi / 4 <= angle <= math.pi / 4:
        direction = "forward"

    elif math.pi / 4 < angle < 3 * math.pi / 4:
        direction = "left"

    elif -3 * math.pi / 4 < angle < -math.pi / 4:
        direction = "right"

    else:
        direction = "backward"

    return direction, distance


def make_behavior_key(behavior):
    canonical = json.dumps(
        behavior,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode("utf-8")
    ).hexdigest()[:16]


def get_id_range(
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


def get_command_stats(conn, start_ns, end_ns):
    rows = conn.execute(
        """
        SELECT
            linear_x,
            linear_y,
            angular_z,
            sample_count
        FROM cmd_vel_intervals
        WHERE started_at_ns <= ?
          AND COALESCE(ended_at_ns, started_at_ns) >= ?
        """,
        (end_ns, start_ns),
    ).fetchall()

    if not rows:
        return None

    total_samples = sum(max(row[3], 1) for row in rows)

    weighted_linear_x = sum(
        row[0] * max(row[3], 1)
        for row in rows
    ) / total_samples

    max_abs_linear_x = max(
        abs(row[0])
        for row in rows
    )

    max_abs_angular_z = max(
        abs(row[2])
        for row in rows
    )

    return {
        "mean_commanded_linear_x": weighted_linear_x,
        "max_abs_commanded_linear_x": max_abs_linear_x,
        "max_abs_commanded_angular_z": max_abs_angular_z,
    }


def build_occurrence(
    conn,
    session_id,
    db_path,
    goal,
):
    (
        goal_id,
        requested_at_ns,
        completed_at_ns,
        target_x,
        target_y,
        target_yaw,
        status_text,
        result_error_code,
        result_error_message,
    ) = goal

    if completed_at_ns is None:
        completed_at_ns = requested_at_ns

    # NavigateToPose feedback is in the navigation/map frame,
    # so it is appropriate for comparing with the map-frame target.
    feedback = conn.execute(
        """
        SELECT
            feedback_id,
            received_at_ns,
            current_x,
            current_y,
            current_yaw_rad
        FROM navigation_feedback
        WHERE navigation_goal_id = ?
        ORDER BY received_at_ns ASC
        """,
        (goal_id,),
    ).fetchall()

    if feedback:
        first_feedback = feedback[0]
        last_feedback = feedback[-1]

        start_x = first_feedback[2]
        start_y = first_feedback[3]
        start_yaw = first_feedback[4]

        last_x = last_feedback[2]
        last_y = last_feedback[3]
        last_yaw = last_feedback[4]

        direction, requested_distance = relative_direction(
            start_x,
            start_y,
            start_yaw,
            target_x,
            target_y,
        )

        observed_feedback_displacement = math.hypot(
            last_x - start_x,
            last_y - start_y,
        )

    else:
        start_x = None
        start_y = None
        start_yaw = None
        last_x = None
        last_y = None
        last_yaw = None
        requested_distance = None
        observed_feedback_displacement = None

        # We cannot safely determine robot-relative direction
        # without a starting pose.
        direction = "unknown"

    # Behavior identity describes WHAT WAS REQUESTED,
    # not whether it succeeded or failed.
    #
    # Therefore success/failure is deliberately NOT part of the key.
    behavior = {
        "action_family": "navigation",
        "motion_family": "translation",
        "relative_direction": direction,
    }

    behavior_key = make_behavior_key(behavior)

    refs = {
        "navigation_goals": {
            "first_id": goal_id,
            "last_id": goal_id,
            "count": 1,
        },

        "navigation_feedback": get_id_range(
            conn,
            "navigation_feedback",
            "feedback_id",
            "received_at_ns",
            requested_at_ns,
            completed_at_ns,
        ),

        "odom_samples": get_id_range(
            conn,
            "odom_samples",
            "odom_id",
            "received_at_ns",
            requested_at_ns,
            completed_at_ns,
        ),

        "cmd_vel_intervals": get_id_range(
            conn,
            "cmd_vel_intervals",
            "cmd_vel_id",
            "started_at_ns",
            requested_at_ns,
            completed_at_ns,
        ),

        "lidar_summary_intervals": get_id_range(
            conn,
            "lidar_summary_intervals",
            "lidar_id",
            "started_at_ns",
            requested_at_ns,
            completed_at_ns,
        ),
    }

    occurrence = {
        "occurrence_id": f"{session_id}:navigation_goal:{goal_id}",

        # Session is provenance, not the lookup key.
        "session_id": session_id,

        "time_range": {
            "start_ns": requested_at_ns,
            "end_ns": completed_at_ns,
        },

        "source": {
            "sqlite_db": str(db_path),
            "rosbag": str(
                RUNTIME_DIR
                / f"session_{session_id}"
                / "rosbag"
            ),
        },

        "sqlite_refs": refs,

        "requested": {
            "target_x": target_x,
            "target_y": target_y,
            "target_yaw": target_yaw,
            "relative_direction": direction,
            "requested_distance_m": requested_distance,
        },

        "observed": {
            "first_feedback_pose": (
                {
                    "x": start_x,
                    "y": start_y,
                    "yaw": start_yaw,
                }
                if start_x is not None
                else None
            ),

            "last_feedback_pose": (
                {
                    "x": last_x,
                    "y": last_y,
                    "yaw": last_yaw,
                }
                if last_x is not None
                else None
            ),

            # This is deliberately labelled feedback displacement,
            # not exact physical travel distance.
            "feedback_displacement_m":
                observed_feedback_displacement,

            "command_stats":
                get_command_stats(
                    conn,
                    requested_at_ns,
                    completed_at_ns,
                ),
        },

        # Outcome is stored with occurrence, NOT behavior identity.
        "outcome": {
            "navigation_status": status_text,
            "result_error_code": result_error_code,
            "result_error_message": result_error_message,
        },
    }

    return behavior_key, behavior, occurrence


def store_occurrence(
    behavior_key,
    behavior,
    occurrence,
):
    with dbm.open(INDEX_PATH, "c") as index:
        key = behavior_key.encode("utf-8")

        if key in index:
            record = json.loads(
                index[key].decode("utf-8")
            )
        else:
            record = {
                "behavior_key": behavior_key,
                "behavior": behavior,
                "occurrences": [],
            }

        occurrence_id = occurrence["occurrence_id"]

        # Makes the script safe to run twice on the same session.
        already_exists = any(
            item["occurrence_id"] == occurrence_id
            for item in record["occurrences"]
        )

        if not already_exists:
            record["occurrences"].append(
                occurrence
            )

        index[key] = json.dumps(
            record,
            indent=2,
        ).encode("utf-8")

    return not already_exists


def index_session(session_id):
    db_path = (
        RUNTIME_DIR
        / f"session_{session_id}"
        / "robot.db"
    )

    if not db_path.exists():
        raise FileNotFoundError(
            f"Database does not exist: {db_path}"
        )

    conn = sqlite3.connect(db_path)

    goals = conn.execute(
        """
        SELECT
            navigation_goal_id,
            requested_at_ns,
            completed_at_ns,
            target_x,
            target_y,
            target_yaw_rad,
            status_text,
            result_error_code,
            result_error_message
        FROM navigation_goals
        WHERE accepted_at_ns IS NOT NULL
        ORDER BY requested_at_ns
        """
    ).fetchall()

    if not goals:
        print("No navigation goals found.")
        conn.close()
        return

    for goal in goals:
        behavior_key, behavior, occurrence = (
            build_occurrence(
                conn,
                session_id,
                db_path,
                goal,
            )
        )

        added = store_occurrence(
            behavior_key,
            behavior,
            occurrence,
        )

        print()
        print(f"Behavior key: {behavior_key}")
        print(
            "Behavior:",
            json.dumps(behavior),
        )
        print(
            "Occurrence:",
            occurrence["occurrence_id"],
        )

        if added:
            print("Added to global behavior index.")
        else:
            print(
                "Occurrence already indexed. "
                "No duplicate added."
            )

    conn.close()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--session-id",
        required=True,
    )

    args = parser.parse_args()

    index_session(args.session_id)


if __name__ == "__main__":
    main()
