import argparse
import math
import sqlite3
import time
import uuid

import rclpy

from rclpy.action import ActionClient
from rclpy.node import Node

from action_msgs.msg import GoalStatus
from nav2_msgs.action import NavigateToPose


FEEDBACK_INTERVAL_NS = 500_000_000
# 500 ms = structured feedback at max ~2 Hz


def yaw_to_quaternion(yaw):
    qz = math.sin(yaw / 2.0)
    qw = math.cos(yaw / 2.0)

    return 0.0, 0.0, qz, qw


def quaternion_to_yaw(qx, qy, qz, qw):
    siny_cosp = 2.0 * (
        qw * qz + qx * qy
    )

    cosy_cosp = 1.0 - 2.0 * (
        qy * qy + qz * qz
    )

    return math.atan2(
        siny_cosp,
        cosy_cosp,
    )


def duration_to_seconds(duration):
    if duration is None:
        return None

    return (
        float(duration.sec)
        + float(duration.nanosec) / 1_000_000_000
    )


def status_text(status):
    names = {
        GoalStatus.STATUS_UNKNOWN:
            "UNKNOWN",

        GoalStatus.STATUS_ACCEPTED:
            "ACCEPTED",

        GoalStatus.STATUS_EXECUTING:
            "EXECUTING",

        GoalStatus.STATUS_CANCELING:
            "CANCELING",

        GoalStatus.STATUS_SUCCEEDED:
            "SUCCEEDED",

        GoalStatus.STATUS_CANCELED:
            "CANCELED",

        GoalStatus.STATUS_ABORTED:
            "ABORTED",
    }

    return names.get(
        status,
        f"STATUS_{status}",
    )


class NavigateToPoseLogger(Node):

    def __init__(
        self,
        db_path,
        session_id,
        x,
        y,
        yaw,
        frame_id,
    ):
        super().__init__(
            "navigate_to_pose_logger"
        )

        self.db_path = db_path
        self.session_id = session_id

        self.target_x = x
        self.target_y = y
        self.target_yaw = yaw
        self.frame_id = frame_id

        self.conn = sqlite3.connect(
            self.db_path
        )

        self.action_client = ActionClient(
            self,
            NavigateToPose,
            "/navigate_to_pose",
        )

        self.navigation_goal_id = None

        self.last_feedback_stored_ns = 0

    # --------------------------------------------------

    def create_goal_row(self):
        now_ns = time.time_ns()

        client_goal_id = uuid.uuid4().hex

        qx, qy, qz, qw = yaw_to_quaternion(
            self.target_yaw
        )

        cursor = self.conn.execute(
            """
            INSERT INTO navigation_goals (
                session_id,

                client_goal_id,
                action_goal_uuid,

                action_name,

                requested_at_ns,

                frame_id,

                target_x,
                target_y,
                target_z,

                target_qx,
                target_qy,
                target_qz,
                target_qw,

                target_yaw_rad,

                status_text
            )

            VALUES (
                ?, ?, ?,
                ?,
                ?,
                ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?,
                ?
            )
            """,
            (
                self.session_id,

                client_goal_id,
                None,

                "/navigate_to_pose",

                now_ns,

                self.frame_id,

                self.target_x,
                self.target_y,
                0.0,

                qx,
                qy,
                qz,
                qw,

                self.target_yaw,

                "REQUESTED",
            ),
        )

        self.navigation_goal_id = (
            cursor.lastrowid
        )

        self.conn.commit()

        self.add_event(
            "GOAL_REQUESTED",
            None,
            "REQUESTED",
        )

    # --------------------------------------------------

    def add_event(
        self,
        event_type,
        code=None,
        text=None,
    ):
        self.conn.execute(
            """
            INSERT INTO navigation_events (
                navigation_goal_id,
                session_id,

                event_time_ns,

                event_type,

                status_code,
                status_text
            )

            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                self.navigation_goal_id,
                self.session_id,

                time.time_ns(),

                event_type,

                code,
                text,
            ),
        )

        self.conn.commit()

    # --------------------------------------------------

    def feedback_callback(
        self,
        feedback_message,
    ):
        now_ns = time.time_ns()

        if (
            self.last_feedback_stored_ns != 0
            and
            now_ns
            - self.last_feedback_stored_ns
            < FEEDBACK_INTERVAL_NS
        ):
            return

        feedback = (
            feedback_message.feedback
        )

        pose = feedback.current_pose.pose

        yaw = quaternion_to_yaw(
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        )

        navigation_time = (
            duration_to_seconds(
                getattr(
                    feedback,
                    "navigation_time",
                    None,
                )
            )
        )

        estimated_time = (
            duration_to_seconds(
                getattr(
                    feedback,
                    "estimated_time_remaining",
                    None,
                )
            )
        )

        distance_remaining = getattr(
            feedback,
            "distance_remaining",
            None,
        )

        recoveries = getattr(
            feedback,
            "number_of_recoveries",
            None,
        )

        self.conn.execute(
            """
            INSERT INTO navigation_feedback (
                navigation_goal_id,
                session_id,

                received_at_ns,

                current_x,
                current_y,
                current_yaw_rad,

                navigation_time_sec,
                estimated_time_remaining_sec,

                distance_remaining,
                number_of_recoveries
            )

            VALUES (
                ?, ?,
                ?,
                ?, ?, ?,
                ?, ?,
                ?, ?
            )
            """,
            (
                self.navigation_goal_id,
                self.session_id,

                now_ns,

                pose.position.x,
                pose.position.y,
                yaw,

                navigation_time,
                estimated_time,

                distance_remaining,
                recoveries,
            ),
        )

        self.conn.commit()

        self.last_feedback_stored_ns = (
            now_ns
        )

    # --------------------------------------------------

    def run(self):
        self.create_goal_row()

        self.get_logger().info(
            "Waiting for "
            "/navigate_to_pose..."
        )

        if not self.action_client.wait_for_server(
            timeout_sec=10.0
        ):
            self.add_event(
                "ACTION_SERVER_UNAVAILABLE"
            )

            self.conn.execute(
                """
                UPDATE navigation_goals
                SET status_text = ?
                WHERE navigation_goal_id = ?
                """,
                (
                    "SERVER_UNAVAILABLE",
                    self.navigation_goal_id,
                ),
            )

            self.conn.commit()

            raise RuntimeError(
                "NavigateToPose action server "
                "not available."
            )

        goal = NavigateToPose.Goal()

        goal.pose.header.frame_id = (
            self.frame_id
        )

        goal.pose.header.stamp = (
            self.get_clock()
            .now()
            .to_msg()
        )

        goal.pose.pose.position.x = (
            self.target_x
        )

        goal.pose.pose.position.y = (
            self.target_y
        )

        goal.pose.pose.position.z = 0.0

        qx, qy, qz, qw = yaw_to_quaternion(
            self.target_yaw
        )

        goal.pose.pose.orientation.x = qx
        goal.pose.pose.orientation.y = qy
        goal.pose.pose.orientation.z = qz
        goal.pose.pose.orientation.w = qw

        self.get_logger().info(
            "Sending navigation goal: "
            f"x={self.target_x:.3f}, "
            f"y={self.target_y:.3f}, "
            f"yaw={self.target_yaw:.3f}"
        )

        send_future = (
            self.action_client.send_goal_async(
                goal,
                feedback_callback=
                    self.feedback_callback,
            )
        )

        rclpy.spin_until_future_complete(
            self,
            send_future,
        )

        goal_handle = send_future.result()

        # ----------------------------------------------
        # Goal rejected
        # ----------------------------------------------

        if (
            goal_handle is None
            or not goal_handle.accepted
        ):
            now_ns = time.time_ns()

            self.conn.execute(
                """
                UPDATE navigation_goals

                SET
                    completed_at_ns = ?,
                    status_text = ?

                WHERE navigation_goal_id = ?
                """,
                (
                    now_ns,
                    "REJECTED",
                    self.navigation_goal_id,
                ),
            )

            self.conn.commit()

            self.add_event(
                "GOAL_REJECTED",
                None,
                "REJECTED",
            )

            self.get_logger().info(
                "Navigation goal rejected."
            )

            return

        # ----------------------------------------------
        # Accepted
        # ----------------------------------------------

        accepted_ns = time.time_ns()

        action_uuid = "".join(
            f"{value:02x}"
            for value
            in goal_handle.goal_id.uuid
        )

        self.conn.execute(
            """
            UPDATE navigation_goals

            SET
                action_goal_uuid = ?,
                accepted_at_ns = ?,
                status_code = ?,
                status_text = ?

            WHERE navigation_goal_id = ?
            """,
            (
                action_uuid,
                accepted_ns,

                GoalStatus.STATUS_ACCEPTED,
                "ACCEPTED",

                self.navigation_goal_id,
            ),
        )

        self.conn.commit()

        self.add_event(
            "GOAL_ACCEPTED",
            GoalStatus.STATUS_ACCEPTED,
            "ACCEPTED",
        )

        self.get_logger().info(
            f"Goal accepted: {action_uuid}"
        )

        # ----------------------------------------------
        # Wait for result
        # ----------------------------------------------

        result_future = (
            goal_handle.get_result_async()
        )

        rclpy.spin_until_future_complete(
            self,
            result_future,
        )

        wrapped_result = (
            result_future.result()
        )

        completed_ns = time.time_ns()

        final_status = wrapped_result.status

        final_text = status_text(
            final_status
        )

        result = wrapped_result.result

        error_code = getattr(
            result,
            "error_code",
            None,
        )

        error_message = getattr(
            result,
            "error_msg",
            None,
        )

        self.conn.execute(
            """
            UPDATE navigation_goals

            SET
                completed_at_ns = ?,

                status_code = ?,
                status_text = ?,

                result_error_code = ?,
                result_error_message = ?

            WHERE navigation_goal_id = ?
            """,
            (
                completed_ns,

                final_status,
                final_text,

                error_code,
                error_message,

                self.navigation_goal_id,
            ),
        )

        self.conn.commit()

        self.add_event(
            "GOAL_COMPLETED",
            final_status,
            final_text,
        )

        self.get_logger().info(
            f"Navigation finished: "
            f"{final_text}"
        )

    # --------------------------------------------------

    def destroy_node(self):
        if self.conn:
            self.conn.commit()
            self.conn.close()

        super().destroy_node()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--db",
        required=True,
    )

    parser.add_argument(
        "--session-id",
        required=True,
    )

    parser.add_argument(
        "--x",
        type=float,
        required=True,
    )

    parser.add_argument(
        "--y",
        type=float,
        required=True,
    )

    parser.add_argument(
        "--yaw",
        type=float,
        default=0.0,
        help="Target yaw in radians",
    )

    parser.add_argument(
        "--frame",
        default="map",
    )

    args = parser.parse_args()

    rclpy.init()

    node = NavigateToPoseLogger(
        db_path=args.db,
        session_id=args.session_id,
        x=args.x,
        y=args.y,
        yaw=args.yaw,
        frame_id=args.frame,
    )

    try:
        node.run()

    except KeyboardInterrupt:
        node.get_logger().info(
            "Interrupted."
        )

    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
