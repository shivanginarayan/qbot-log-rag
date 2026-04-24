import json
import time
from datetime import datetime

import rclpy
from rclpy.node import Node

from geometry_msgs.msg import Twist, TwistStamped
from sensor_msgs.msg import LaserScan, BatteryState, Imu


class TopicHealthCollector(Node):
    def __init__(self):
        super().__init__("topic_health_collector")

        self.output_file = "data/processed/live_topic_health.jsonl"

        self.last_seen = {
            "/cmd_vel": None,
            "/scan": None,
            "/qbot_speed_feedback": None,
            "/qbot_battery": None,
            "/qbot_imu": None,
        }

        self.latest_values = {}

        self.create_subscription(Twist, "/cmd_vel", self.cmd_vel_callback, 10)
        self.create_subscription(LaserScan, "/scan", self.scan_callback, 10)
        self.create_subscription(TwistStamped, "/qbot_speed_feedback", self.speed_callback, 10)
        self.create_subscription(BatteryState, "/qbot_battery", self.battery_callback, 10)
        self.create_subscription(Imu, "/qbot_imu", self.imu_callback, 10)

        self.create_timer(2.0, self.write_health_snapshot)

        self.get_logger().info("Topic health collector started.")

    def now_text(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def mark_seen(self, topic):
        self.last_seen[topic] = time.time()

    def cmd_vel_callback(self, msg):
        self.mark_seen("/cmd_vel")
        self.latest_values["/cmd_vel"] = {
            "linear_x": msg.linear.x,
            "angular_z": msg.angular.z,
        }

    def scan_callback(self, msg):
        self.mark_seen("/scan")
        valid_ranges = [r for r in msg.ranges if r > 0.0]
        self.latest_values["/scan"] = {
            "num_ranges": len(msg.ranges),
            "min_range": min(valid_ranges) if valid_ranges else None,
        }

    def speed_callback(self, msg):
        self.mark_seen("/qbot_speed_feedback")
        self.latest_values["/qbot_speed_feedback"] = {
            "linear_x": msg.twist.linear.x,
            "angular_z": msg.twist.angular.z,
        }

    def battery_callback(self, msg):
        self.mark_seen("/qbot_battery")
        self.latest_values["/qbot_battery"] = {
            "percentage": msg.percentage,
            "voltage": msg.voltage,
        }

    def imu_callback(self, msg):
        self.mark_seen("/qbot_imu")
        self.latest_values["/qbot_imu"] = {
            "angular_velocity_z": msg.angular_velocity.z,
        }

    def topic_status(self, topic):
        last = self.last_seen.get(topic)

        if last is None:
            return "NO_MESSAGES_YET"

        age = time.time() - last

        if age > 3.0:
            return "STALE"

        return "ACTIVE"

    def write_health_snapshot(self):
        snapshot = {
            "timestamp": self.now_text(),
            "topics": {
                topic: {
                    "status": self.topic_status(topic),
                    "latest_value": self.latest_values.get(topic, {})
                }
                for topic in self.last_seen
            }
        }

        with open(self.output_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot) + "\n")

        print(json.dumps(snapshot, indent=2))


def main():
    rclpy.init()
    node = TopicHealthCollector()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
