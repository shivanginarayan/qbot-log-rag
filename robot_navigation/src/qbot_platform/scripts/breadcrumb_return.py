#!/usr/bin/env python3
"""Record outbound AMCL breadcrumbs and replay them backward to return home."""

import json
import math
import sys
import time
from pathlib import Path

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseWithCovarianceStamped
from geometry_msgs.msg import Twist
import rclpy
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from std_msgs.msg import String


RETURN_COMMAND = "__return_breadcrumbs__"
ORIGIN_NAME = "origin"


def workspace_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "maps").is_dir():
            return parent
    return Path("/home/nvidia/857_Final_Project_Code")


def normalize(text):
    return " ".join(text.strip().lower().split())


def yaw_to_quaternion(yaw):
    return math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def quaternion_to_yaw(orientation):
    return math.atan2(
        2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
        1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z),
    )


def pose_to_waypoint(pose_msg):
    pose = pose_msg.pose.pose
    return {
        "x": float(pose.position.x),
        "y": float(pose.position.y),
        "yaw": float(quaternion_to_yaw(pose.orientation)),
    }


def distance(a, b):
    return math.hypot(a["x"] - b["x"], a["y"] - b["y"])


def normalize_angle(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


class BreadcrumbReturnNode(Node):
    def __init__(self):
        super().__init__("breadcrumb_return")
        self.declare_parameter("label_topic", "/label")
        self.declare_parameter("navigation_status_topic", "/robot/navigation_status")
        self.declare_parameter("amcl_pose_topic", "/amcl_pose")
        self.declare_parameter("action_name", "/navigate_to_pose")
        self.declare_parameter(
            "path_file",
            str(workspace_root() / "maps" / "last_navigation_path.json"),
        )
        self.declare_parameter("waypoint_spacing_m", 0.65)
        self.declare_parameter("return_segment_spacing_m", 0.25)
        self.declare_parameter("min_return_waypoint_spacing_m", 0.18)
        self.declare_parameter("goal_tolerance_skip_m", 0.15)
        self.declare_parameter("turn_in_place_before_waypoint", True)
        self.declare_parameter("turn_angular_speed_rad_s", 0.30)
        self.declare_parameter("turn_min_angle_rad", 0.55)

        self.path_file = Path(self.get_parameter("path_file").value)
        self.waypoint_spacing_m = float(self.get_parameter("waypoint_spacing_m").value)
        self.return_segment_spacing_m = float(
            self.get_parameter("return_segment_spacing_m").value
        )
        self.min_return_waypoint_spacing_m = float(
            self.get_parameter("min_return_waypoint_spacing_m").value
        )
        self.goal_tolerance_skip_m = float(
            self.get_parameter("goal_tolerance_skip_m").value
        )
        self.turn_in_place_before_waypoint = bool(
            self.get_parameter("turn_in_place_before_waypoint").value
        )
        self.turn_angular_speed_rad_s = float(
            self.get_parameter("turn_angular_speed_rad_s").value
        )
        self.turn_min_angle_rad = float(
            self.get_parameter("turn_min_angle_rad").value
        )

        self.status_pub = self.create_publisher(
            String,
            self.get_parameter("navigation_status_topic").value,
            10,
        )
        self.cmd_vel_pub = self.create_publisher(Twist, "/cmd_vel", 10)
        self.client = ActionClient(
            self,
            NavigateToPose,
            self.get_parameter("action_name").value,
        )

        self.latest_pose = None
        self.recording = False
        self.recording_label = None
        self.path = []
        self.return_queue = []
        self.return_active = False

        self.create_subscription(
            String,
            self.get_parameter("label_topic").value,
            self.label_callback,
            10,
        )
        self.create_subscription(
            String,
            self.get_parameter("navigation_status_topic").value,
            self.navigation_status_callback,
            10,
        )
        self.create_subscription(
            PoseWithCovarianceStamped,
            self.get_parameter("amcl_pose_topic").value,
            self.pose_callback,
            10,
        )
        self.get_logger().info("Breadcrumb return node ready.")

    def label_callback(self, msg):
        label = msg.data.strip()
        normalized = normalize(label)
        if not label:
            return
        if normalized == RETURN_COMMAND:
            self.start_return()
            return
        if normalized.startswith("__") or normalized == ORIGIN_NAME:
            return
        self.start_recording(label)

    def navigation_status_callback(self, msg):
        if not self.recording:
            return
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        name = normalize(str(payload.get("name") or ""))
        if name.startswith("__") or name in {ORIGIN_NAME, "return_breadcrumbs"}:
            return
        self.recording = False
        self.save_path(status=int(payload.get("status", GoalStatus.STATUS_UNKNOWN)))
        self.get_logger().info(
            f"Stopped recording {len(self.path)} breadcrumbs for {self.recording_label}."
        )

    def pose_callback(self, msg):
        self.latest_pose = msg
        if not self.recording:
            return
        waypoint = pose_to_waypoint(msg)
        if self.should_append_waypoint(waypoint):
            self.path.append(waypoint)
            self.save_path(status=GoalStatus.STATUS_EXECUTING)

    def start_recording(self, label):
        self.recording = True
        self.recording_label = label
        self.path = []
        if self.latest_pose is not None:
            self.path.append(pose_to_waypoint(self.latest_pose))
        self.save_path(status=GoalStatus.STATUS_EXECUTING)
        self.get_logger().info(f"Started breadcrumb recording for {label}.")

    def should_append_waypoint(self, waypoint):
        if not self.path:
            return True
        return distance(self.path[-1], waypoint) >= self.waypoint_spacing_m

    def start_return(self):
        if self.return_active:
            self.get_logger().warning("Ignoring breadcrumb return; already returning.")
            return
        self.recording = False
        path = self.load_path()
        if len(path) < 2:
            self.get_logger().warning("No usable breadcrumb path; reporting return failure.")
            self.publish_navigation_status(GoalStatus.STATUS_ABORTED)
            return

        current = pose_to_waypoint(self.latest_pose) if self.latest_pose else path[-1]
        self.return_queue = self.build_return_queue(path, current)
        if not self.return_queue:
            self.get_logger().warning("Breadcrumb return queue was empty.")
            self.publish_navigation_status(GoalStatus.STATUS_ABORTED)
            return

        self.return_active = True
        self.get_logger().info(
            f"Starting breadcrumb return with {len(self.return_queue)} waypoints."
        )
        self.send_next_goal()

    def build_return_queue(self, path, current):
        queue = []
        last_added = current
        for waypoint in reversed(path[:-1]):
            if distance(current, waypoint) < self.goal_tolerance_skip_m:
                continue
            for dense_waypoint in self.interpolate_segment(last_added, waypoint):
                if distance(current, dense_waypoint) < self.goal_tolerance_skip_m:
                    continue
                if distance(last_added, dense_waypoint) < self.min_return_waypoint_spacing_m:
                    continue
                queue.append(dense_waypoint)
                last_added = dense_waypoint
            if distance(last_added, waypoint) < self.min_return_waypoint_spacing_m:
                continue
            queue.append(dict(waypoint))
            last_added = waypoint

        origin = {"x": 0.0, "y": 0.0, "yaw": 0.0}
        if not queue or distance(queue[-1], origin) > self.goal_tolerance_skip_m:
            for dense_waypoint in self.interpolate_segment(last_added, origin):
                if distance(last_added, dense_waypoint) >= self.min_return_waypoint_spacing_m:
                    queue.append(dense_waypoint)
                    last_added = dense_waypoint
            if distance(last_added, origin) > self.goal_tolerance_skip_m:
                queue.append(origin)

        for index, waypoint in enumerate(queue):
            next_waypoint = queue[index + 1] if index + 1 < len(queue) else origin
            waypoint["yaw"] = math.atan2(
                next_waypoint["y"] - waypoint["y"],
                next_waypoint["x"] - waypoint["x"],
            )
        return queue

    def interpolate_segment(self, start, end):
        segment_length = distance(start, end)
        if segment_length <= self.return_segment_spacing_m:
            return []
        steps = int(segment_length / self.return_segment_spacing_m)
        waypoints = []
        for step in range(1, steps):
            ratio = step / steps
            waypoints.append(
                {
                    "x": start["x"] + (end["x"] - start["x"]) * ratio,
                    "y": start["y"] + (end["y"] - start["y"]) * ratio,
                    "yaw": 0.0,
                }
            )
        return waypoints

    def send_next_goal(self):
        if not self.return_queue:
            self.return_active = False
            self.publish_navigation_status(GoalStatus.STATUS_SUCCEEDED)
            self.get_logger().info("Breadcrumb return finished.")
            return

        waypoint = self.return_queue.pop(0)
        self.turn_toward_waypoint(waypoint)
        goal = self.build_goal(waypoint)
        self.get_logger().info(
            f"Returning via breadcrumb x={waypoint['x']:.3f}, y={waypoint['y']:.3f}."
        )
        if not self.client.wait_for_server(timeout_sec=2.0):
            self.return_active = False
            self.publish_navigation_status(GoalStatus.STATUS_ABORTED)
            return
        future = self.client.send_goal_async(goal)
        future.add_done_callback(self.handle_goal_response)

    def handle_goal_response(self, future):
        goal_handle = future.result()
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().warning("Breadcrumb waypoint rejected; trying next one.")
            self.send_next_goal()
            return
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self.handle_goal_result)

    def handle_goal_result(self, future):
        result = future.result()
        status = result.status if result is not None else GoalStatus.STATUS_ABORTED
        if status != GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().warning(
                f"Breadcrumb waypoint failed with status {status}; trying next one."
            )
        self.send_next_goal()

    def build_goal(self, waypoint):
        qz, qw = yaw_to_quaternion(float(waypoint.get("yaw", 0.0)))
        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = float(waypoint["x"])
        goal.pose.pose.position.y = float(waypoint["y"])
        goal.pose.pose.position.z = 0.0
        goal.pose.pose.orientation.z = qz
        goal.pose.pose.orientation.w = qw
        return goal

    def turn_toward_waypoint(self, waypoint):
        if not self.turn_in_place_before_waypoint or self.latest_pose is None:
            return

        current = pose_to_waypoint(self.latest_pose)
        if distance(current, waypoint) < 0.05:
            return

        target_yaw = math.atan2(waypoint["y"] - current["y"], waypoint["x"] - current["x"])
        yaw_error = normalize_angle(target_yaw - current["yaw"])
        if abs(yaw_error) < self.turn_min_angle_rad:
            return

        angular_speed = max(0.1, abs(self.turn_angular_speed_rad_s))
        duration_sec = abs(yaw_error) / angular_speed
        twist = Twist()
        twist.angular.z = math.copysign(angular_speed, yaw_error)

        self.get_logger().info(
            "Turning in place before breadcrumb: "
            f"yaw_error={yaw_error:.3f}, duration={duration_sec:.2f}s."
        )
        end_time = time.monotonic() + duration_sec
        try:
            while rclpy.ok() and time.monotonic() < end_time:
                self.cmd_vel_pub.publish(twist)
                time.sleep(0.1)
        finally:
            self.stop_robot()

    def stop_robot(self):
        stop = Twist()
        for _ in range(5):
            self.cmd_vel_pub.publish(stop)
            time.sleep(0.02)

    def save_path(self, status):
        data = {
            "label": self.recording_label,
            "status": status,
            "waypoint_spacing_m": self.waypoint_spacing_m,
            "breadcrumbs": self.path,
        }
        self.path_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def load_path(self):
        if not self.path_file.exists():
            return self.path
        try:
            data = json.loads(self.path_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return self.path
        breadcrumbs = data.get("breadcrumbs", [])
        if not isinstance(breadcrumbs, list):
            return self.path
        return [
            {
                "x": float(item["x"]),
                "y": float(item["y"]),
                "yaw": float(item.get("yaw", 0.0)),
            }
            for item in breadcrumbs
            if isinstance(item, dict) and "x" in item and "y" in item
        ]

    def publish_navigation_status(self, status):
        payload = {
            "event": "finished",
            "label": "origin (Breadcrumb return)",
            "name": ORIGIN_NAME,
            "kind": "navigation",
            "detail": "Breadcrumb return",
            "status": status,
        }
        msg = String()
        msg.data = json.dumps(payload)
        self.status_pub.publish(msg)
        self.get_logger().info(f"Published breadcrumb return status: {msg.data}")


def main(args=None):
    rclpy.init(args=args)
    node = BreadcrumbReturnNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main(sys.argv)
