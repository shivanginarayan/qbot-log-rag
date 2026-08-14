#!/usr/bin/env python3

import math

import rclpy
from geometry_msgs.msg import Quaternion, TransformStamped
from nav_msgs.msg import Odometry
from rclpy.node import Node
from sensor_msgs.msg import Imu
from sensor_msgs.msg import JointState
from tf2_ros import TransformBroadcaster


def yaw_to_quaternion(yaw: float) -> Quaternion:
    q = Quaternion()
    half = yaw * 0.5
    q.z = math.sin(half)
    q.w = math.cos(half)
    return q


class WheelOdometry(Node):
    def __init__(self):
        super().__init__("wheel_odometry")

        # Matches the physical parameters used in qbot_platform_driver_interface.cpp.
        self.declare_parameter("joint_topic", "/qbot_joint")
        self.declare_parameter("imu_topic", "/qbot_imu")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("odom_frame_id", "odom")
        self.declare_parameter("base_frame_id", "base_link")
        self.declare_parameter("left_index", 0)
        self.declare_parameter("right_index", 1)
        self.declare_parameter("wheel_radius", 3.5 * 0.0254 / 2.0)
        self.declare_parameter("wheel_separation", 0.3928)
        self.declare_parameter("linear_scale_correction", 1.0)
        self.declare_parameter("angular_scale_correction", 1.0)
        self.declare_parameter("use_imu_yaw", True)
        self.declare_parameter("imu_angular_velocity_scale", 1.0)
        self.declare_parameter("imu_angular_velocity_sign", 1.0)
        self.declare_parameter("max_integration_dt", 0.2)
        self.declare_parameter("report_interval_sec", 2.0)
        self.declare_parameter(
            "pose_covariance_diagonal",
            [0.001, 0.001, 0.001, 0.001, 0.001, 0.01],
        )
        self.declare_parameter(
            "twist_covariance_diagonal",
            [0.001, 0.001, 0.001, 0.001, 0.001, 0.01],
        )

        self.joint_topic = self.get_parameter("joint_topic").value
        self.imu_topic = self.get_parameter("imu_topic").value
        self.odom_topic = self.get_parameter("odom_topic").value
        self.odom_frame_id = self.get_parameter("odom_frame_id").value
        self.base_frame_id = self.get_parameter("base_frame_id").value
        self.left_index = int(self.get_parameter("left_index").value)
        self.right_index = int(self.get_parameter("right_index").value)
        self.wheel_radius = float(self.get_parameter("wheel_radius").value)
        self.wheel_separation = float(self.get_parameter("wheel_separation").value)
        self.linear_scale_correction = float(self.get_parameter("linear_scale_correction").value)
        self.angular_scale_correction = float(self.get_parameter("angular_scale_correction").value)
        self.use_imu_yaw = bool(self.get_parameter("use_imu_yaw").value)
        self.imu_angular_velocity_scale = float(
            self.get_parameter("imu_angular_velocity_scale").value
        )
        self.imu_angular_velocity_sign = float(self.get_parameter("imu_angular_velocity_sign").value)
        self.max_integration_dt = float(self.get_parameter("max_integration_dt").value)
        self.report_interval_sec = float(self.get_parameter("report_interval_sec").value)
        self.pose_covariance = list(self.get_parameter("pose_covariance_diagonal").value)
        self.twist_covariance = list(self.get_parameter("twist_covariance_diagonal").value)

        self.odom_pub = self.create_publisher(Odometry, self.odom_topic, 20)
        self.tf_broadcaster = TransformBroadcaster(self)
        self.joint_sub = self.create_subscription(JointState, self.joint_topic, self._joint_cb, 50)
        self.imu_sub = self.create_subscription(Imu, self.imu_topic, self._imu_cb, 50)

        self.x = 0.0
        self.y = 0.0
        self.yaw = 0.0
        self.last_left = None
        self.last_right = None
        self.last_stamp = None
        self.imu_yaw = 0.0
        self.last_imu_stamp = None
        self.last_imu_yaw_for_odom = 0.0
        self.last_report_time = None
        self.total_distance = 0.0
        self.total_encoder_yaw = 0.0
        self.total_fused_yaw = 0.0

        self.get_logger().info(
            "wheel_odometry started: "
            f"use_imu_yaw={self.use_imu_yaw}, "
            f"linear_scale_correction={self.linear_scale_correction:.4f}, "
            f"angular_scale_correction={self.angular_scale_correction:.4f}, "
            f"imu_angular_velocity_scale={self.imu_angular_velocity_scale:.4f}, "
            f"imu_angular_velocity_sign={self.imu_angular_velocity_sign:.1f}"
        )

    @staticmethod
    def _stamp_to_sec(stamp) -> float:
        return float(stamp.sec) + float(stamp.nanosec) / 1e9

    def _imu_cb(self, msg: Imu):
        if not self.use_imu_yaw:
            return

        if msg.header.stamp.sec == 0 and msg.header.stamp.nanosec == 0:
            return

        if self.last_imu_stamp is None:
            self.last_imu_stamp = msg.header.stamp
            return

        dt = self._stamp_to_sec(msg.header.stamp) - self._stamp_to_sec(self.last_imu_stamp)
        self.last_imu_stamp = msg.header.stamp
        if dt <= 0.0 or dt > self.max_integration_dt:
            return

        angular_z = (
            float(msg.angular_velocity.z)
            * self.imu_angular_velocity_scale
            * self.imu_angular_velocity_sign
        )
        self.imu_yaw = math.atan2(
            math.sin(self.imu_yaw + angular_z * dt),
            math.cos(self.imu_yaw + angular_z * dt),
        )

    def _maybe_report(self, stamp, linear_x: float, angular_z: float):
        now_sec = self._stamp_to_sec(stamp)
        if self.last_report_time is None:
            self.last_report_time = now_sec
            return
        if (now_sec - self.last_report_time) < self.report_interval_sec:
            return

        yaw_error = math.atan2(
            math.sin(self.total_fused_yaw - self.total_encoder_yaw),
            math.cos(self.total_fused_yaw - self.total_encoder_yaw),
        )
        self.get_logger().info(
            "odom summary: "
            f"x={self.x:.3f} y={self.y:.3f} yaw={self.yaw:.3f} "
            f"distance={self.total_distance:.3f} "
            f"encoder_yaw={self.total_encoder_yaw:.3f} fused_yaw={self.total_fused_yaw:.3f} "
            f"yaw_error={yaw_error:.3f} vx={linear_x:.3f} wz={angular_z:.3f}"
        )
        self.last_report_time = now_sec

    def _joint_cb(self, msg: JointState):
        if len(msg.position) <= max(self.left_index, self.right_index):
            return

        left_pos = float(msg.position[self.left_index])
        right_pos = float(msg.position[self.right_index])

        if self.last_left is None or self.last_right is None:
            self.last_left = left_pos
            self.last_right = right_pos
            self.last_stamp = msg.header.stamp
            self.last_imu_yaw_for_odom = self.imu_yaw
            return

        d_left = (left_pos - self.last_left) * self.wheel_radius
        d_right = (right_pos - self.last_right) * self.wheel_radius
        d_center = 0.5 * (d_left + d_right) * self.linear_scale_correction
        d_theta_encoder = (
            (d_right - d_left) / self.wheel_separation * self.angular_scale_correction
        )
        d_theta = d_theta_encoder
        if self.use_imu_yaw:
            d_theta = math.atan2(
                math.sin(self.imu_yaw - self.last_imu_yaw_for_odom),
                math.cos(self.imu_yaw - self.last_imu_yaw_for_odom),
            )

        self.x += d_center * math.cos(self.yaw + 0.5 * d_theta)
        self.y += d_center * math.sin(self.yaw + 0.5 * d_theta)
        self.yaw = math.atan2(math.sin(self.yaw + d_theta), math.cos(self.yaw + d_theta))
        self.total_distance += abs(d_center)
        self.total_encoder_yaw = math.atan2(
            math.sin(self.total_encoder_yaw + d_theta_encoder),
            math.cos(self.total_encoder_yaw + d_theta_encoder),
        )
        self.total_fused_yaw = math.atan2(
            math.sin(self.total_fused_yaw + d_theta),
            math.cos(self.total_fused_yaw + d_theta),
        )

        linear_x = 0.0
        angular_z = 0.0
        if self.last_stamp is not None:
            dt = self._stamp_to_sec(msg.header.stamp) - self._stamp_to_sec(self.last_stamp)
            if dt > 0.0:
                linear_x = d_center / dt
                angular_z = d_theta / dt

        quat = yaw_to_quaternion(self.yaw)

        odom = Odometry()
        odom.header.stamp = msg.header.stamp
        odom.header.frame_id = self.odom_frame_id
        odom.child_frame_id = self.base_frame_id
        odom.pose.pose.position.x = self.x
        odom.pose.pose.position.y = self.y
        odom.pose.pose.orientation = quat
        odom.twist.twist.linear.x = linear_x
        odom.twist.twist.angular.z = angular_z
        odom.pose.covariance[0] = self.pose_covariance[0]
        odom.pose.covariance[7] = self.pose_covariance[1]
        odom.pose.covariance[14] = self.pose_covariance[2]
        odom.pose.covariance[21] = self.pose_covariance[3]
        odom.pose.covariance[28] = self.pose_covariance[4]
        odom.pose.covariance[35] = self.pose_covariance[5]
        odom.twist.covariance[0] = self.twist_covariance[0]
        odom.twist.covariance[7] = self.twist_covariance[1]
        odom.twist.covariance[14] = self.twist_covariance[2]
        odom.twist.covariance[21] = self.twist_covariance[3]
        odom.twist.covariance[28] = self.twist_covariance[4]
        odom.twist.covariance[35] = self.twist_covariance[5]
        self.odom_pub.publish(odom)

        tf_msg = TransformStamped()
        tf_msg.header.stamp = msg.header.stamp
        tf_msg.header.frame_id = self.odom_frame_id
        tf_msg.child_frame_id = self.base_frame_id
        tf_msg.transform.translation.x = self.x
        tf_msg.transform.translation.y = self.y
        tf_msg.transform.rotation = quat
        self.tf_broadcaster.sendTransform(tf_msg)
        self._maybe_report(msg.header.stamp, linear_x, angular_z)

        self.last_left = left_pos
        self.last_right = right_pos
        self.last_stamp = msg.header.stamp
        self.last_imu_yaw_for_odom = self.imu_yaw


def main():
    rclpy.init()
    node = WheelOdometry()
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
