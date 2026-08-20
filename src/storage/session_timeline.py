import argparse
import math
import sqlite3
from datetime import datetime, timezone


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

ODOM_POSITION_CHANGE = 0.10
POSE_POSITION_CHANGE = 0.10

YAW_CHANGE_RAD = math.radians(10)

LINEAR_MOVING_THRESHOLD = 0.01
ANGULAR_MOVING_THRESHOLD = 0.05


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------

def ns_to_iso(timestamp_ns):
    if timestamp_ns is None:
        return "None"

    dt = datetime.fromtimestamp(
        timestamp_ns / 1_000_000_000,
        tz=timezone.utc,
    )

    return dt.isoformat(timespec="milliseconds")


def seconds_from(start_ns, timestamp_ns):
    if (
        start_ns is None
        or timestamp_ns is None
    ):
        return None

    return (
        timestamp_ns - start_ns
    ) / 1_000_000_000


def yaw_difference(a, b):
    return abs(
        math.atan2(
            math.sin(a - b),
            math.cos(a - b),
        )
    )


def position_difference(
    x1,
    y1,
    x2,
    y2,
):
    return math.hypot(
        x2 - x1,
        y2 - y1,
    )


def fmt(value, digits=3):
    if value is None:
        return "None"

    return f"{value:.{digits}f}"


# ---------------------------------------------------------
# Timeline event
# ---------------------------------------------------------

def add_event(
    timeline,
    timestamp_ns,
    category,
    message,
):
    if timestamp_ns is None:
        return

    timeline.append(
        {
            "time_ns": timestamp_ns,
            "category": category,
            "message": message,
        }
    )


# ---------------------------------------------------------
# Session metadata
# ---------------------------------------------------------

def load_session(
    conn,
    session_id,
    timeline,
):
    row = conn.execute(
        """
        SELECT
            started_at_ns,
            started_at_iso,
            ended_at_ns,
            ended_at_iso,
            robot_id,
            ros_domain_id,
            map_name,
            status

        FROM sessions

        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"Session not found: {session_id}"
        )

    (
        started_at_ns,
        started_at_iso,
        ended_at_ns,
        ended_at_iso,
        robot_id,
        ros_domain_id,
        map_name,
        status,
    ) = row

    add_event(
        timeline,
        started_at_ns,
        "SESSION",
        (
            f"Session started | "
            f"robot={robot_id} | "
            f"ROS_DOMAIN_ID={ros_domain_id} | "
            f"map={map_name}"
        ),
    )

    if ended_at_ns is not None:
        add_event(
            timeline,
            ended_at_ns,
            "SESSION",
            f"Session ended | status={status}",
        )

    return started_at_ns


# ---------------------------------------------------------
# Navigation events
# ---------------------------------------------------------

def load_navigation_events(
    conn,
    session_id,
    timeline,
):
    rows = conn.execute(
        """
        SELECT
            e.event_time_ns,
            e.event_type,
            e.status_code,
            e.status_text,

            g.navigation_goal_id,
            g.target_x,
            g.target_y,
            g.target_yaw_rad

        FROM navigation_events AS e

        JOIN navigation_goals AS g
            ON e.navigation_goal_id
             = g.navigation_goal_id

        WHERE e.session_id = ?

        ORDER BY e.event_time_ns
        """,
        (session_id,),
    ).fetchall()

    for row in rows:
        (
            event_time_ns,
            event_type,
            status_code,
            status_text,
            goal_id,
            target_x,
            target_y,
            target_yaw,
        ) = row

        if event_type == "GOAL_REQUESTED":
            message = (
                f"Goal {goal_id} requested | "
                f"target=({target_x:.3f}, "
                f"{target_y:.3f}) | "
                f"yaw={target_yaw:.3f}"
            )

        elif event_type == "GOAL_ACCEPTED":
            message = (
                f"Goal {goal_id} accepted"
            )

        elif event_type == "GOAL_COMPLETED":
            message = (
                f"Goal {goal_id} completed | "
                f"status={status_text}"
            )

        else:
            message = (
                f"Goal {goal_id} | "
                f"{event_type} | "
                f"status={status_text}"
            )

        add_event(
            timeline,
            event_time_ns,
            "NAV",
            message,
        )


# ---------------------------------------------------------
# Navigation feedback
# ---------------------------------------------------------

def load_navigation_feedback(
    conn,
    session_id,
    timeline,
):
    rows = conn.execute(
        """
        SELECT
            received_at_ns,
            navigation_goal_id,

            current_x,
            current_y,
            current_yaw_rad,

            distance_remaining,
            navigation_time_sec,
            number_of_recoveries

        FROM navigation_feedback

        WHERE session_id = ?

        ORDER BY received_at_ns
        """,
        (session_id,),
    ).fetchall()

    for row in rows:
        (
            received_at_ns,
            goal_id,
            x,
            y,
            yaw,
            distance_remaining,
            navigation_time,
            recoveries,
        ) = row

        message = (
            f"Goal {goal_id} feedback | "
            f"pose=({fmt(x)}, {fmt(y)}) | "
            f"yaw={fmt(yaw)} | "
            f"remaining={fmt(distance_remaining)} m | "
            f"recoveries={recoveries}"
        )

        add_event(
            timeline,
            received_at_ns,
            "NAV_FEEDBACK",
            message,
        )


# ---------------------------------------------------------
# cmd_vel intervals
# ---------------------------------------------------------

def load_cmd_vel(
    conn,
    session_id,
    timeline,
):
    rows = conn.execute(
        """
        SELECT
            cmd_vel_id,
            started_at_ns,
            ended_at_ns,

            linear_x,
            linear_y,
            linear_z,

            angular_x,
            angular_y,
            angular_z,

            sample_count

        FROM cmd_vel_intervals

        WHERE session_id = ?

        ORDER BY started_at_ns
        """,
        (session_id,),
    ).fetchall()

    for row in rows:
        (
            cmd_id,
            start_ns,
            end_ns,

            linear_x,
            linear_y,
            linear_z,

            angular_x,
            angular_y,
            angular_z,

            sample_count,
        ) = row

        duration = 0.0

        if (
            start_ns is not None
            and end_ns is not None
        ):
            duration = (
                end_ns - start_ns
            ) / 1_000_000_000

        add_event(
            timeline,
            start_ns,
            "CMD_VEL",
            (
                f"Command {cmd_id} started | "
                f"linear_x={linear_x:.3f} | "
                f"angular_z={angular_z:.3f} | "
                f"duration={duration:.2f}s | "
                f"samples={sample_count}"
            ),
        )


# ---------------------------------------------------------
# LiDAR intervals
# ---------------------------------------------------------

def load_lidar(
    conn,
    session_id,
    timeline,
):
    rows = conn.execute(
        """
        SELECT
            lidar_id,
            started_at_ns,
            ended_at_ns,

            distance_band,
            front_band,
            left_band,
            right_band,
            rear_band,

            closest_distance,
            closest_angle,

            front_min,
            left_min,
            right_min,
            rear_min,

            closest_bin,
            front_bin,
            left_bin,
            right_bin,
            rear_bin,

            sample_count,
            previous_interval_id

        FROM lidar_summary_intervals

        WHERE session_id = ?

        ORDER BY started_at_ns
        """,
        (session_id,),
    ).fetchall()

    previous = None

    for row in rows:
        (
            lidar_id,
            start_ns,
            end_ns,

            overall_band,
            front_band,
            left_band,
            right_band,
            rear_band,

            closest,
            closest_angle,

            front,
            left,
            right,
            rear,

            closest_bin,
            front_bin,
            left_bin,
            right_bin,
            rear_bin,

            sample_count,
            previous_id,
        ) = row

        duration = 0.0

        if start_ns is not None and end_ns is not None:
            duration = (
                end_ns - start_ns
            ) / 1_000_000_000

        # Always show the first LiDAR state.
        important = previous is None

        reason = "initial state"

        if previous is not None:
            (
                prev_overall_band,
                prev_front_band,
                prev_left_band,
                prev_right_band,
                prev_rear_band,
                prev_closest,
            ) = previous

            # Overall obstacle severity changed.
            if overall_band != prev_overall_band:
                important = True
                reason = (
                    f"overall band changed "
                    f"{prev_overall_band}→{overall_band}"
                )

            # Front matters most for navigation.
            elif front_band != prev_front_band:
                important = True
                reason = (
                    f"front band changed "
                    f"{prev_front_band}→{front_band}"
                )

            # Any direction entering critical range matters.
            elif (
                left_band == "critical"
                and prev_left_band != "critical"
            ):
                important = True
                reason = "left became critical"

            elif (
                right_band == "critical"
                and prev_right_band != "critical"
            ):
                important = True
                reason = "right became critical"

            elif (
                rear_band == "critical"
                and prev_rear_band != "critical"
            ):
                important = True
                reason = "rear became critical"

            # Large closest-distance change.
            elif (
                closest is not None
                and prev_closest is not None
                and abs(
                    closest - prev_closest
                ) >= 0.20
            ):
                important = True
                reason = (
                    f"closest changed "
                    f"{prev_closest:.2f}→"
                    f"{closest:.2f} m"
                )

        if important:
            add_event(
                timeline,
                start_ns,
                "LIDAR",
                (
                    f"{reason} | "
                    f"closest={fmt(closest)} m | "
                    f"overall={overall_band} | "
                    f"front={front_band} | "
                    f"left={left_band} | "
                    f"right={right_band} | "
                    f"rear={rear_band} | "
                    f"duration={duration:.2f}s | "
                    f"samples={sample_count}"
                ),
            )

        previous = (
            overall_band,
            front_band,
            left_band,
            right_band,
            rear_band,
            closest,
        )

# ---------------------------------------------------------
# Odom meaningful changes
# ---------------------------------------------------------

def load_odom(
    conn,
    session_id,
    timeline,
):
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

        WHERE session_id = ?

        ORDER BY received_at_ns
        """,
        (session_id,),
    ).fetchall()

    if not rows:
        return

    last_saved = None
    previous_motion_state = None

    for row in rows:
        (
            timestamp_ns,
            x,
            y,
            yaw,
            linear_x,
            angular_z,
        ) = row

        linear_x = linear_x or 0.0
        angular_z = angular_z or 0.0

        moving = (
            abs(linear_x)
            >= LINEAR_MOVING_THRESHOLD
            or abs(angular_z)
            >= ANGULAR_MOVING_THRESHOLD
        )

        motion_state = (
            "MOVING"
            if moving
            else "STOPPED"
        )

        should_store = False
        reason = ""

        if last_saved is None:
            should_store = True
            reason = "initial"

        elif (
            previous_motion_state
            != motion_state
        ):
            should_store = True
            reason = (
                f"{previous_motion_state}"
                f"→{motion_state}"
            )

        else:
            (
                _,
                previous_x,
                previous_y,
                previous_yaw,
                _,
                _,
            ) = last_saved

            position_change = (
                position_difference(
                    previous_x,
                    previous_y,
                    x,
                    y,
                )
            )

            yaw_change = yaw_difference(
                previous_yaw,
                yaw,
            )

            if (
                position_change
                >= ODOM_POSITION_CHANGE
            ):
                should_store = True
                reason = (
                    f"moved "
                    f"{position_change:.2f} m"
                )

            elif (
                yaw_change
                >= YAW_CHANGE_RAD
            ):
                should_store = True
                reason = (
                    f"turned "
                    f"{math.degrees(yaw_change):.1f}°"
                )

        if should_store:
            add_event(
                timeline,
                timestamp_ns,
                "ODOM",
                (
                    f"{motion_state} | "
                    f"pose=({x:.3f}, {y:.3f}) | "
                    f"yaw={yaw:.3f} | "
                    f"linear_x={linear_x:.3f} | "
                    f"angular_z={angular_z:.3f} | "
                    f"{reason}"
                ),
            )

            last_saved = row

        previous_motion_state = (
            motion_state
        )


# ---------------------------------------------------------
# AMCL meaningful changes
# ---------------------------------------------------------

def load_pose(
    conn,
    session_id,
    timeline,
):
    rows = conn.execute(
        """
        SELECT
            received_at_ns,
            is_stale,

            x,
            y,
            yaw_rad,

            x_variance,
            y_variance,
            yaw_variance

        FROM pose_samples

        WHERE session_id = ?

        ORDER BY received_at_ns
        """,
        (session_id,),
    ).fetchall()

    if not rows:
        return

    last_saved = None
    previous_stale = None

    for row in rows:
        (
            timestamp_ns,
            is_stale,
            x,
            y,
            yaw,
            x_variance,
            y_variance,
            yaw_variance,
        ) = row

        should_store = False
        reason = ""

        if last_saved is None:
            should_store = True
            reason = "initial"

        elif previous_stale != is_stale:
            should_store = True
            reason = (
                "freshness changed"
            )

        else:
            (
                _,
                _,
                previous_x,
                previous_y,
                previous_yaw,
                _,
                _,
                _,
            ) = last_saved

            position_change = (
                position_difference(
                    previous_x,
                    previous_y,
                    x,
                    y,
                )
            )

            yaw_change = yaw_difference(
                previous_yaw,
                yaw,
            )

            if (
                position_change
                >= POSE_POSITION_CHANGE
            ):
                should_store = True
                reason = (
                    f"belief moved "
                    f"{position_change:.2f} m"
                )

            elif (
                yaw_change
                >= YAW_CHANGE_RAD
            ):
                should_store = True
                reason = (
                    f"belief turned "
                    f"{math.degrees(yaw_change):.1f}°"
                )

        if should_store:
            freshness = (
                "STALE"
                if is_stale
                else "FRESH"
            )

            add_event(
                timeline,
                timestamp_ns,
                "AMCL",
                (
                    f"{freshness} | "
                    f"pose=({x:.3f}, {y:.3f}) | "
                    f"yaw={yaw:.3f} | "
                    f"var_x={fmt(x_variance, 4)} | "
                    f"var_y={fmt(y_variance, 4)} | "
                    f"{reason}"
                ),
            )

            last_saved = row

        previous_stale = is_stale


# ---------------------------------------------------------
# Print timeline
# ---------------------------------------------------------

def print_timeline(
    timeline,
    session_start_ns,
    session_id,
):
    timeline.sort(
        key=lambda event:
            event["time_ns"]
    )

    print()
    print("=" * 110)
    print(
        f"SESSION TIMELINE: "
        f"{session_id}"
    )
    print("=" * 110)
    print()

    for event in timeline:
        elapsed = seconds_from(
            session_start_ns,
            event["time_ns"],
        )

        print(
            f"+{elapsed:8.3f}s | "
            f"{event['category']:12} | "
            f"{event['message']}"
        )

    print()
    print("=" * 110)
    print(
        f"Timeline events: "
        f"{len(timeline)}"
    )
    print("=" * 110)


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--session-id",
        required=True,
        help="Session ID",
    )

    parser.add_argument(
        "--db",
        default=None,
        help=(
            "Optional explicit path "
            "to robot.db"
        ),
    )

    args = parser.parse_args()

    if args.db:
        db_path = args.db

    else:
        db_path = (
            "runtime_logs/"
            f"session_{args.session_id}/"
            "robot.db"
        )

    conn = sqlite3.connect(
        db_path
    )

    timeline = []

    session_start_ns = load_session(
        conn,
        args.session_id,
        timeline,
    )

    # Each loader reads one evidence source.
    load_navigation_events(
        conn,
        args.session_id,
        timeline,
    )

    load_navigation_feedback(
        conn,
        args.session_id,
        timeline,
    )

    load_cmd_vel(
        conn,
        args.session_id,
        timeline,
    )

    load_lidar(
        conn,
        args.session_id,
        timeline,
    )

    load_odom(
        conn,
        args.session_id,
        timeline,
    )

    load_pose(
        conn,
        args.session_id,
        timeline,
    )

    conn.close()

    print_timeline(
        timeline,
        session_start_ns,
        args.session_id,
    )


if __name__ == "__main__":
    main()
