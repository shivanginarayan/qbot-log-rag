import json
import hashlib
import sqlite3
import time
from collections import deque
from datetime import datetime

import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import Log
from geometry_msgs.msg import Twist, TwistStamped
from sensor_msgs.msg import LaserScan, BatteryState, Imu


class ErrorMemoryCollector(Node):
    def __init__(self):
        super().__init__("error_memory_collector")

        self.db_path = "data/processed/error_memory.db"
        self.context_buffer = deque(maxlen=10)

        self.latest_values = {
            "/cmd_vel": None,
            "/scan": None,
            "/qbot_speed_feedback": None,
            "/qbot_battery": None,
            "/qbot_imu": None,
        }

        self.setup_db()

        self.create_subscription(Log, "/rosout", self.rosout_callback, 100)
        self.create_subscription(Twist, "/cmd_vel", self.cmd_vel_callback, 10)
        self.create_subscription(LaserScan, "/scan", self.scan_callback, 10)
        self.create_subscription(TwistStamped, "/qbot_speed_feedback", self.speed_callback, 10)
        self.create_subscription(BatteryState, "/qbot_battery", self.battery_callback, 10)
        self.create_subscription(Imu, "/qbot_imu", self.imu_callback, 10)

        self.create_timer(1.0, self.save_context_snapshot)

        self.get_logger().info("Error memory collector started.")

    def setup_db(self):
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS errors (
                error_key TEXT PRIMARY KEY,
                node TEXT,
                severity TEXT,
                message TEXT,
                count INTEGER,
                first_seen TEXT,
                last_seen TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS error_occurrences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_key TEXT,
                timestamp TEXT,
                node TEXT,
                severity TEXT,
                message TEXT,
                context_before TEXT
            )
        """)

        conn.commit()
        conn.close()

    def now_text(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def severity_name(self, level):
        if level >= 50:
            return "FATAL"
        if level >= 40:
            return "ERROR"
        if level >= 30:
            return "WARN"
        if level >= 20:
            return "INFO"
        return "DEBUG"

    def normalize_message(self, message):
        return " ".join(message.lower().strip().split())

    def make_error_key(self, node, severity, message):
        normalized = self.normalize_message(message)
        raw = f"{node}|{severity}|{normalized}"
        return hashlib.md5(raw.encode()).hexdigest()

    def cmd_vel_callback(self, msg):
        self.latest_values["/cmd_vel"] = {
            "linear_x": msg.linear.x,
            "angular_z": msg.angular.z
        }

    def scan_callback(self, msg):
        valid_ranges = [r for r in msg.ranges if r > 0.0]
        self.latest_values["/scan"] = {
            "num_ranges": len(msg.ranges),
            "min_range": min(valid_ranges) if valid_ranges else None
        }

    def speed_callback(self, msg):
        self.latest_values["/qbot_speed_feedback"] = {
            "linear_x": msg.twist.linear.x,
            "angular_z": msg.twist.angular.z
        }

    def battery_callback(self, msg):
        self.latest_values["/qbot_battery"] = {
            "percentage": msg.percentage,
            "voltage": msg.voltage
        }

    def imu_callback(self, msg):
        self.latest_values["/qbot_imu"] = {
            "angular_velocity_z": msg.angular_velocity.z
        }

    def save_context_snapshot(self):
        snapshot = {
            "timestamp": self.now_text(),
            "topics": self.latest_values.copy()
        }
        self.context_buffer.append(snapshot)

    def rosout_callback(self, msg):
        severity = self.severity_name(msg.level)

        if severity not in ["WARN", "ERROR", "FATAL"]:
            return

        timestamp = self.now_text()
        error_key = self.make_error_key(msg.name, severity, msg.msg)
        context_before = list(self.context_buffer)

        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()

        cur.execute("SELECT count FROM errors WHERE error_key = ?", (error_key,))
        row = cur.fetchone()

        if row is None:
            print(f"\nNEW ERROR: [{severity}] {msg.name}: {msg.msg}")

            cur.execute("""
                INSERT INTO errors
                (error_key, node, severity, message, count, first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                error_key,
                msg.name,
                severity,
                msg.msg,
                1,
                timestamp,
                timestamp
            ))
        else:
            new_count = row[0] + 1
            print(f"\nREPEATED ERROR #{new_count}: [{severity}] {msg.name}: {msg.msg}")

            cur.execute("""
                UPDATE errors
                SET count = ?, last_seen = ?
                WHERE error_key = ?
            """, (
                new_count,
                timestamp,
                error_key
            ))

        cur.execute("""
            INSERT INTO error_occurrences
            (error_key, timestamp, node, severity, message, context_before)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            error_key,
            timestamp,
            msg.name,
            severity,
            msg.msg,
            json.dumps(context_before)
        ))

        # Keep only last 5 occurrences for this same error
        cur.execute("""
            DELETE FROM error_occurrences
            WHERE error_key = ?
            AND id NOT IN (
                SELECT id FROM error_occurrences
                WHERE error_key = ?
                ORDER BY timestamp DESC
                LIMIT 5
            )
        """, (
            error_key,
            error_key
        ))

        conn.commit()
        conn.close()


def main():
    rclpy.init()
    node = ErrorMemoryCollector()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
