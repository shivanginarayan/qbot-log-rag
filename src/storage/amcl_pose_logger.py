import math
import sqlite3
import time

import rclpy
from rclpy.node import Node

from rclpy.qos import (
    QoSProfile,
    ReliabilityPolicy,
    DurabilityPolicy,
    HistoryPolicy,
)

from geometry_msgs.msg import PoseWithCovarianceStamped


def quaternion_to_yaw(qx, qy, qz, qw):
    siny_cosp = 2.0 * (qw * qz + qx * qy)
    cosy_cosp = 1.0 - 2.0 * (qy * qy + qz * qz)

    return math.atan2(siny_cosp, cosy_cosp)


class AmclPoseLogger(Node):

    def __init__(self, db_path, session_id):
        super().__init__("amcl_pose_logger")

        self.db_path = db_path
        self.session_id = session_id

        self.conn = sqlite3.connect(self.db_path, timeout=30)
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.conn.execute("PRAGMA foreign_keys = ON")

        pose_qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
            history=HistoryPolicy.KEEP_LAST,
            depth=10,
        )

        self.subscription = self.create_subscription(
            PoseWithCovarianceStamped,
            "/amcl_pose",
            self.pose_callback,
            pose_qos,
        )

        self.sample_count = 0

        self.get_logger().info(
            f"Logging /amcl_pose for session {self.session_id}"
        )

    def pose_callback(self, msg):
        received_at_ns = time.time_ns()

        ros_time_ns = (
            msg.header.stamp.sec * 1_000_000_000
            + msg.header.stamp.nanosec
        )
        ros_now_ns = self.get_clock().now().nanoseconds
        message_age_ns = ros_now_ns - ros_time_ns

        STALE_THRESHOLD_NS = 1_000_000_000  # 1 second

        is_stale = 1 if message_age_ns > STALE_THRESHOLD_NS else 0

        pose = msg.pose.pose
        covariance = msg.pose.covariance

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

        x_variance = covariance[0]
        y_variance = covariance[7]
        yaw_variance = covariance[35]

        self.conn.execute(
            """
            INSERT INTO pose_samples (
                session_id,
                ros_time_ns,
                received_at_ns,
                is_stale,
                frame_id,
                x,
                y,
                z,
                qx,
                qy,
                qz,
                qw,
                yaw_rad,
                x_variance,
                y_variance,
                yaw_variance
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.session_id,
                ros_time_ns,
                received_at_ns,
                is_stale,
                msg.header.frame_id,
                x,
                y,
                z,
                qx,
                qy,
                qz,
                qw,
                yaw_rad,
                x_variance,
                y_variance,
                yaw_variance,
            ),
        )

        self.conn.commit()

        self.sample_count += 1

        if is_stale:
            self.get_logger().warning(
                f"Stored stale/retained AMCL pose "
                f"(age={message_age_ns / 1_000_000_000:.2f}s)"
            )

        if self.sample_count % 10 == 0:
            self.get_logger().info(
                f"Stored {self.sample_count} AMCL pose samples"
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

    node = AmclPoseLogger(
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
