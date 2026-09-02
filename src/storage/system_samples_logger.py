#!/usr/bin/env python3

import json
import math
import socket
import sqlite3
import time

import rclpy
from geometry_msgs.msg import TwistStamped
from rclpy.node import Node
from sensor_msgs.msg import BatteryState, JointState


STORE_INTERVAL_NS = 100_000_000


class SystemSamplesLogger(Node):
    def __init__(self, db_path, session_id):
        super().__init__("system_samples_logger")

        self.db_path = db_path
        self.session_id = session_id
        self.conn = sqlite3.connect(self.db_path, timeout=30)
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.last_stored_ns = {}

        self.create_subscription(
            BatteryState, "/qbot_battery", self.battery_callback, 10
        )
        self.create_subscription(
            TwistStamped, "/qbot_speed_feedback", self.speed_callback, 10
        )
        self.create_subscription(
            JointState, "/qbot_joint", self.joint_callback, 10
        )
        self.create_timer(2.0, self.network_callback)

        self.get_logger().info(
            f"Logging system samples for session {self.session_id}"
        )

    def store(self, category, metric_name, value_numeric=None,
              value_text=None, unit=None, source=None, payload=None,
              interval_ns=STORE_INTERVAL_NS):
        now_ns = time.time_ns()
        last_ns = self.last_stored_ns.get(metric_name)
        if last_ns is not None and now_ns - last_ns < interval_ns:
            return

        payload_json = json.dumps(payload, sort_keys=True) if payload else None
        self.conn.execute(
            """
            INSERT INTO system_samples (
                session_id, event_time_ns, category, metric_name,
                value_numeric, value_text, unit, source, payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.session_id, now_ns, category, metric_name,
                value_numeric, value_text, unit, source, payload_json,
            ),
        )
        self.conn.commit()
        self.last_stored_ns[metric_name] = now_ns

    def battery_callback(self, msg):
        if math.isfinite(msg.voltage):
            self.store(
                "battery", "battery_voltage", value_numeric=msg.voltage,
                unit="V", source="/qbot_battery",
            )
        if math.isfinite(msg.percentage):
            self.store(
                "battery", "battery_percentage", value_numeric=msg.percentage,
                unit="percent", source="/qbot_battery",
            )

    def speed_callback(self, msg):
        self.store(
            "motion_feedback", "feedback_linear_x",
            value_numeric=msg.twist.linear.x, unit="m/s",
            source="/qbot_speed_feedback",
        )
        self.store(
            "motion_feedback", "feedback_angular_z",
            value_numeric=msg.twist.angular.z, unit="rad/s",
            source="/qbot_speed_feedback",
        )

    def joint_callback(self, msg):
        for index, value in enumerate(msg.velocity[:2]):
            if math.isfinite(value):
                self.store(
                    "motor_feedback", f"motor_{index}_velocity",
                    value_numeric=value, unit="rad/s", source="/qbot_joint",
                )
        for index, value in enumerate(msg.effort[:2]):
            if math.isfinite(value):
                self.store(
                    "motor_feedback", f"motor_{index}_current",
                    value_numeric=value, unit="A", source="/qbot_joint",
                )

    def network_callback(self):
        try:
            ip_address = socket.gethostbyname(socket.gethostname())
        except OSError:
            return

        self.store(
            "network", "robot_ip", value_text=ip_address, source="hostname",
            interval_ns=2_000_000_000,
        )

    def destroy_node(self):
        if self.conn:
            self.conn.commit()
            self.conn.close()
        super().destroy_node()


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", required=True)
    parser.add_argument("--session-id", required=True)
    args = parser.parse_args()

    rclpy.init()
    node = SystemSamplesLogger(args.db, args.session_id)
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
