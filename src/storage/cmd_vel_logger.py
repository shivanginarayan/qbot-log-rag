import sqlite3
import time

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import Twist


TOLERANCE = 1e-4


def same_command(a, b):
    return (
        abs(a["linear_x"] - b["linear_x"]) <= TOLERANCE
        and abs(a["linear_y"] - b["linear_y"]) <= TOLERANCE
        and abs(a["linear_z"] - b["linear_z"]) <= TOLERANCE
        and abs(a["angular_x"] - b["angular_x"]) <= TOLERANCE
        and abs(a["angular_y"] - b["angular_y"]) <= TOLERANCE
        and abs(a["angular_z"] - b["angular_z"]) <= TOLERANCE
    )


class CmdVelLogger(Node):

    def __init__(self, db_path, session_id):
        super().__init__("cmd_vel_logger")

        self.db_path = db_path
        self.session_id = session_id

        self.conn = sqlite3.connect(self.db_path, timeout=30)
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.conn.execute("PRAGMA foreign_keys = ON")

        self.subscription = self.create_subscription(
            Twist,
            "/cmd_vel",
            self.cmd_vel_callback,
            10,
        )

        self.current_command = None
        self.current_interval_id = None

        self.get_logger().info(
            f"Logging /cmd_vel intervals for session {self.session_id}"
        )

    def cmd_vel_callback(self, msg):
        now_ns = time.time_ns()

        new_command = {
            "linear_x": msg.linear.x,
            "linear_y": msg.linear.y,
            "linear_z": msg.linear.z,
            "angular_x": msg.angular.x,
            "angular_y": msg.angular.y,
            "angular_z": msg.angular.z,
        }

        # First command seen
        if self.current_command is None:
            self.current_command = new_command

            cursor = self.conn.execute(
                """
                INSERT INTO cmd_vel_intervals (
                    session_id,
                    started_at_ns,
                    ended_at_ns,

                    linear_x,
                    linear_y,
                    linear_z,

                    angular_x,
                    angular_y,
                    angular_z,

                    sample_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    self.session_id,
                    now_ns,
                    now_ns,

                    new_command["linear_x"],
                    new_command["linear_y"],
                    new_command["linear_z"],

                    new_command["angular_x"],
                    new_command["angular_y"],
                    new_command["angular_z"],

                    1,
                ),
            )

            self.current_interval_id = cursor.lastrowid
            self.conn.commit()

            return

        # Same command continues
        if same_command(self.current_command, new_command):
            self.conn.execute(
                """
                UPDATE cmd_vel_intervals
                SET ended_at_ns = ?,
                    sample_count = sample_count + 1
                WHERE cmd_vel_id = ?
                """,
                (
                    now_ns,
                    self.current_interval_id,
                ),
            )

            self.conn.commit()
            return

        # Command changed: start a new interval
        self.current_command = new_command

        cursor = self.conn.execute(
            """
            INSERT INTO cmd_vel_intervals (
                session_id,
                started_at_ns,
                ended_at_ns,

                linear_x,
                linear_y,
                linear_z,

                angular_x,
                angular_y,
                angular_z,

                sample_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.session_id,
                now_ns,
                now_ns,

                new_command["linear_x"],
                new_command["linear_y"],
                new_command["linear_z"],

                new_command["angular_x"],
                new_command["angular_y"],
                new_command["angular_z"],

                1,
            ),
        )

        self.current_interval_id = cursor.lastrowid

        self.conn.commit()

        self.get_logger().info(
            "Command changed: "
            f"linear_x={new_command['linear_x']:.3f}, "
            f"angular_z={new_command['angular_z']:.3f}"
        )

    def destroy_node(self):
        if self.conn:
            self.conn.commit()
            self.conn.close()

        super().destroy_node()


def main():
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--db",
        required=True,
        help="Path to session robot.db",
    )

    parser.add_argument(
        "--session-id",
        required=True,
        help="Session ID",
    )

    args = parser.parse_args()

    rclpy.init()

    node = CmdVelLogger(
        db_path=args.db,
        session_id=args.session_id,
    )

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
