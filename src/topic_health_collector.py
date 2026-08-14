import json
import time
import math
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

        all_valid_points = []
        front_valid_points = []

        min_valid_range = 0.15
        max_valid_range = 5.0

        # Wider front sector for demo:
        # 0 to 0.80 rad OR 5.48 to 6.28 rad
        # roughly +/- 45 degrees around front
        front_left_limit_rad = 0.80
        front_right_limit_rad = 5.48

        for i, r in enumerate(msg.ranges):
            if (
                r >= min_valid_range
                and r <= max_valid_range
                and not math.isinf(r)
                and not math.isnan(r)
            ):
                angle_rad = msg.angle_min + i * msg.angle_increment
                angle_deg = angle_rad * 180.0 / math.pi

                point = (r, i, angle_rad, angle_deg)
                all_valid_points.append(point)

                if angle_rad <= front_left_limit_rad or angle_rad >= front_right_limit_rad:
                    front_valid_points.append(point)

        if all_valid_points:
            global_min_range, global_min_index, global_min_angle_rad, global_min_angle_deg = min(
                all_valid_points,
                key=lambda x: x[0]
            )
        else:
            global_min_range = None
            global_min_index = None
            global_min_angle_rad = None
            global_min_angle_deg = None

        if front_valid_points:
            front_min_range, front_min_index, front_min_angle_rad, front_min_angle_deg = min(
                front_valid_points,
                key=lambda x: x[0]
            )
        else:
            front_min_range = None
            front_min_index = None
            front_min_angle_rad = None
            front_min_angle_deg = None

        obstacle_close = False
        if front_min_range is not None and front_min_range < 0.30:
            obstacle_close = True

        self.latest_values["/scan"] = {
            "num_ranges": len(msg.ranges),

            "min_range": front_min_range,
            "min_range_index": front_min_index,
            "min_angle_rad": front_min_angle_rad,
            "min_angle_deg": front_min_angle_deg,

            "global_min_range": global_min_range,
            "global_min_range_index": global_min_index,
            "global_min_angle_rad": global_min_angle_rad,
            "global_min_angle_deg": global_min_angle_deg,

            "angle_min": msg.angle_min,
            "angle_max": msg.angle_max,
            "angle_increment": msg.angle_increment,

            "front_sector_rad": "0 to 0.80 OR 5.48 to 6.28",
            "front_sector_deg": "+/- 45 degrees around assumed front",

            "obstacle_close": obstacle_close,
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