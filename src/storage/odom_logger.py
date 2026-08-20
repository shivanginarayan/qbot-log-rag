import math
import sqlite3
import time

import rclpy
from rclpy.node import Node

from nav_msgs.msg import Odometry


def quaternion_to_yaw(qx, qy, qz, qw):
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)

    return math.atan2(siny_cosp, cosy_cosp)


class OdomLogger(Node):

    def __init__(self, db_path, session_id):
        super().__init__("odom_logger")

        self.db_path = db_path
        self.session_id = session_id

        self.conn = sqlite3.connect(self.db_path)

        self.subscription = self.create_subscription(
            Odometry,
            "/odom",
            self.odom_callback,
            10,
        )

        self.sample_count = 0
        self.last_stored_ns = 0

        # Store structured odometry at 10 Hz.
        self.store_interval_ns = 100_000_000

        self.get_logger().info(
            f"Logging /odom for session {self.session_id}"
        )

    def odom_callback(self, msg):
        received_at_ns = time.time_ns()

        if (
            self.last_stored_ns != 0
            and received_at_ns - self.last_stored_ns < self.store_interval_ns
        ):
            return

        ros_time_ns = (
            msg.header.stamp.sec * 1_000_000_000
            + msg.header.stamp.nanosec
        )

        pose = msg.pose.pose
        twist = msg.twist.twist

        x = pose.position.x
        y = pose.position.y
        z = pose.position.z

        qx = pose.orientation.x
        qy = pose.orientation.y
        qz = pose.orientation.z
        qw = pose.orientation.w

        yaw_rad = quaternion_to_yaw(
            qx,
            qy,
            qz,
            qw,
        )

        linear_x = twist.linear.x
        linear_y = twist.linear.y
        linear_z = twist.linear.z

        angular_x = twist.angular.x
        angular_y = twist.angular.y
        angular_z = twist.angular.z

        self.conn.execute(
            """
            INSERT INTO odom_samples (
                session_id,
                ros_time_ns,
                received_at_ns,
                frame_id,
                child_frame_id,
                x,
                y,
                z,
                qx,
                qy,
                qz,
                qw,
                yaw_rad,
                linear_x,
                linear_y,
                linear_z,
                angular_x,
                angular_y,
                angular_z
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.session_id,
                ros_time_ns,
                received_at_ns,
                msg.header.frame_id,
                msg.child_frame_id,
                x,
                y,
                z,
                qx,
                qy,
                qz,
                qw,
                yaw_rad,
                linear_x,
                linear_y,
                linear_z,
                angular_x,
                angular_y,
                angular_z,
            ),
        )

        self.conn.commit()
        self.last_stored_ns = received_at_ns

        self.sample_count += 1

        if self.sample_count % 50 == 0:
            self.get_logger().info(
                f"Stored {self.sample_count} odom samples"
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

    node = OdomLogger(
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
