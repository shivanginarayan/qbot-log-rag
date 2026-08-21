#!/usr/bin/env python3
"""Send a Nav2 goal using a saved map label."""

import argparse
import json
import math
import re
import sys
import time
from pathlib import Path

from action_msgs.msg import GoalStatus
from geometry_msgs.msg import Twist
from geometry_msgs.msg import PoseWithCovarianceStamped
import rclpy
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.utilities import remove_ros_args
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String
from std_srvs.srv import Empty


def workspace_root():
    for parent in Path(__file__).resolve().parents:
        if (parent / "maps").is_dir():
            return parent
    return Path("/home/nvidia/857_Final_Project_Code")


ROOT = workspace_root()
DEFAULT_LABELS_FILE = ROOT / "maps" / "lab_map_new_labels.json"
LAST_LABEL_FILE = ROOT / "maps" / "last_navigation_label.json"
FULL_SPIN_COMMAND = "__full_spin__"
RETURN_STAGING_COMMAND = "__return_staging__"
BREADCRUMB_RETURN_COMMAND = "__return_breadcrumbs__"
STOP_NAVIGATION_COMMAND = "__stop_navigation__"
LOCALIZE_COMMAND = "__localize__"
LOCALIZATION_LABEL = "AMCL localization"

ALIASES = {
    "dr zhang": "xiaorong zhang",
    "dr. zhang": "xiaorong zhang",
    "zhang": "xiaorong zhang",
    "313": "seic 313",
    "gohome": "home",
    "go home": "home",
}


def normalize(text):
    return re.sub(r"\s+", " ", text.strip().lower())


def yaw_to_quaternion(yaw):
    return math.sin(yaw / 2.0), math.cos(yaw / 2.0)


def quaternion_to_yaw(orientation):
    return math.atan2(
        2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
        1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z),
    )


def normalize_angle(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def load_labels(path):
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    labels = data.get("labels", [])
    if not isinstance(labels, list):
        raise ValueError(f"{path} does not contain a labels list")
    return labels


def label_display(label):
    detail = label.get("detail")
    if detail:
        return f"{label.get('name', '<unnamed>')} ({detail})"
    return label.get("name", "<unnamed>")


def list_labels(labels):
    for label in labels:
        world = label.get("world") or {}
        x = world.get("x")
        y = world.get("y")
        if x is None or y is None:
            continue
        print(f"{label_display(label)} -> x={float(x):.3f}, y={float(y):.3f}")


def find_label(labels, query):
    wanted = ALIASES.get(normalize(query), normalize(query))

    if wanted == "home":
        for preferred_name in ("home", "robot_start", "start", "original", "origin"):
            for label in labels:
                if normalize(label.get("name", "")) == preferred_name:
                    return label

    candidates = []
    for label in labels:
        names = [
            label.get("name", ""),
            label.get("detail", ""),
            label.get("kind", ""),
        ]
        normalized_names = [normalize(name) for name in names if name]
        if wanted in normalized_names:
            return label
        if any(wanted in name for name in normalized_names):
            candidates.append(label)

    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        names = ", ".join(label_display(label) for label in candidates)
        raise ValueError(f"Multiple labels match {query!r}: {names}")
    raise ValueError(f"No saved label matches {query!r}")


def find_label_in_file(labels_file, query):
    """Reload a labels JSON file and resolve one query against its latest contents."""
    return find_label(load_labels(Path(labels_file)), query)


class LabelNavigator(Node):
    def __init__(self, action_name, status_topic, cmd_vel_topic="/cmd_vel_nav"):
        super().__init__("go_to_label")
        self.action_name = action_name
        self.status_topic = status_topic
        self.cmd_vel_topic = cmd_vel_topic
        self.client = ActionClient(self, NavigateToPose, action_name)
        self.global_localization_client = self.create_client(
            Empty,
            "/reinitialize_global_localization",
        )
        self.status_pub = self.create_publisher(String, status_topic, 10)
        self.cmd_vel_pub = self.create_publisher(Twist, cmd_vel_topic, 10)
        self.labels = []
        self.labels_file = None
        self.server_timeout_sec = 10.0
        self.active_goal_label = None
        self.active_goal_handle = None
        self.stop_requested = False
        self.cancel_request_in_flight = False
        self.localization_requested = False
        self.localization_in_progress = False
        self.localization_generation = 0
        self.localization_timer = None
        self.localization_end_time = 0.0
        self.localization_angular_speed = 0.30
        self.latest_pose = None
        self.latest_scan = None
        self.create_subscription(
            PoseWithCovarianceStamped,
            "/amcl_pose",
            self.pose_callback,
            10,
        )
        self.create_subscription(
            LaserScan,
            "/scan",
            self.scan_callback,
            qos_profile_sensor_data,
        )
        self.get_logger().info(
            f"Direct motion commands publish to {self.cmd_vel_topic}."
        )

    def pose_callback(self, msg):
        self.latest_pose = msg

    def scan_callback(self, msg):
        self.latest_scan = msg

    def go_to(self, label, timeout_sec):
        world = label.get("world") or {}
        x = float(world["x"])
        y = float(world["y"])
        yaw = float(label.get("yaw", 0.0))
        qz, qw = yaw_to_quaternion(yaw)

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        goal.pose.pose.position.z = 0.0
        goal.pose.pose.orientation.z = qz
        goal.pose.pose.orientation.w = qw

        self.get_logger().info(
            f"Waiting for Nav2 action server, then going to {label_display(label)} "
            f"at x={x:.3f}, y={y:.3f}, yaw={yaw:.3f}"
        )
        if not self.client.wait_for_server(timeout_sec=timeout_sec):
            message = f"Nav2 action server {self.action_name} is not available"
            self.publish_navigation_status(
                label,
                GoalStatus.STATUS_ABORTED,
                message=message,
            )
            raise RuntimeError(message)

        send_future = self.client.send_goal_async(goal)
        rclpy.spin_until_future_complete(self, send_future)
        try:
            goal_handle = send_future.result()
        except Exception as exc:
            self.publish_navigation_status(
                label,
                GoalStatus.STATUS_ABORTED,
                message=f"Could not submit goal: {exc}",
            )
            raise
        if goal_handle is None or not goal_handle.accepted:
            self.publish_navigation_status(
                label,
                GoalStatus.STATUS_ABORTED,
                message="Nav2 rejected the goal",
            )
            raise RuntimeError("Nav2 rejected the goal")
        self.active_goal_handle = goal_handle

        self.get_logger().info("Goal accepted. Waiting for result.")
        self.publish_navigation_status(
            label,
            GoalStatus.STATUS_EXECUTING,
            event="started",
        )
        # result_future = goal_handle.get_result_async()
        # rclpy.spin_until_future_complete(self, result_future)
        result_future = goal_handle.get_result_async()

        try:
            rclpy.spin_until_future_complete(self, result_future)
        except KeyboardInterrupt:
            self.get_logger().warning("Ctrl+C received. Cancelling active navigation goal.")
            cancel_future = goal_handle.cancel_goal_async()
            rclpy.spin_until_future_complete(self, cancel_future)

            self.stop_robot()
            self.publish_navigation_status(
                label,
                GoalStatus.STATUS_CANCELED,
                message="Navigation was interrupted",
            )
            raise
        try:
            result = result_future.result()
        except Exception as exc:
            self.publish_navigation_status(
                label,
                GoalStatus.STATUS_ABORTED,
                message=f"Nav2 result failed: {exc}",
            )
            raise
        if result is None:
            self.publish_navigation_status(
                label,
                GoalStatus.STATUS_ABORTED,
                message="Nav2 did not return a result",
            )
            raise RuntimeError("Nav2 did not return a result")
        self.publish_navigation_status(label, result.status)
        return result.status

    def listen_for_labels(self, labels_file, topic, timeout_sec):
        self.labels_file = Path(labels_file)
        self.labels = load_labels(self.labels_file)
        self.server_timeout_sec = timeout_sec

        self.get_logger().info(f"Waiting for Nav2 action server {self.action_name}.")
        if not self.client.wait_for_server(timeout_sec=timeout_sec):
            raise RuntimeError(f"Nav2 action server {self.action_name} is not available")

        self.create_subscription(String, topic, self.label_callback, 10)
        self.get_logger().info(
            f"Listening for label names on {topic}; reloading {self.labels_file} for each request."
        )

    def label_callback(self, msg):
        query = msg.data.strip()
        if not query:
            return
        normalized_query = normalize(query)
        if normalized_query == STOP_NAVIGATION_COMMAND:
            self.request_navigation_stop()
            return
        if normalized_query == LOCALIZE_COMMAND:
            self.request_localization()
            return
        if self.active_goal_label is not None:
            self.get_logger().warning(
                f"Ignoring {query!r}; already navigating to {self.active_goal_label}."
            )
            return

        label = None
        try:
            if normalized_query == BREADCRUMB_RETURN_COMMAND:
                self.get_logger().info("Ignoring breadcrumb return command.")
                return
            if normalized_query == FULL_SPIN_COMMAND:
                label = self.virtual_label("full_spin", "Full spin")
                self.active_goal_label = label_display(label)
                self.get_logger().info("Received full spin command.")
                self.publish_navigation_status(
                    label,
                    GoalStatus.STATUS_EXECUTING,
                    event="started",
                )
                status = self.execute_full_spin()
                self.active_goal_label = None
                self.publish_navigation_status(label, status)
                return
            if normalized_query == RETURN_STAGING_COMMAND:
                label = self.build_return_staging_label()
            else:
                if self.labels_file is not None:
                    label = find_label_in_file(self.labels_file, query)
                else:
                    label = find_label(self.labels, query)
            goal = self.build_goal(label)
        except Exception as exc:
            self.get_logger().error(str(exc))
            normalized_query = normalize(query)
            if normalized_query == FULL_SPIN_COMMAND:
                self.publish_navigation_status(
                    self.virtual_label("full_spin", "Full spin"),
                    GoalStatus.STATUS_ABORTED,
                    message=str(exc),
                )
            elif normalized_query == RETURN_STAGING_COMMAND:
                self.publish_navigation_status(
                    self.virtual_label("return_staging", "Return staging"),
                    GoalStatus.STATUS_ABORTED,
                    message=str(exc),
                )
            elif label is not None:
                self.publish_navigation_status(
                    label,
                    GoalStatus.STATUS_ABORTED,
                    message=str(exc),
                )
            return

        self.active_goal_label = label_display(label)
        self.active_goal_handle = None
        self.stop_requested = False
        self.cancel_request_in_flight = False
        self.get_logger().info(f"Received {query!r}; going to {self.active_goal_label}.")
        send_future = self.client.send_goal_async(goal)
        send_future.add_done_callback(lambda future: self.handle_goal_response(future, label))

    def request_navigation_stop(self):
        """Stop motion now and cancel an active or currently-submitting Nav2 goal."""
        localization_stopped = self.cancel_localization()
        self.stop_robot()
        if self.active_goal_label is None:
            self.stop_requested = False
            if localization_stopped:
                self.get_logger().info("Stop requested; AMCL localization was stopped.")
            else:
                self.get_logger().info("Stop requested; robot stopped with no active navigation goal.")
            return

        self.stop_requested = True
        if self.active_goal_handle is None:
            self.get_logger().warning(
                f"Stop requested while submitting {self.active_goal_label}; "
                "it will be cancelled immediately if Nav2 accepts it."
            )
            return

        self.cancel_active_goal()

    def cancel_active_goal(self):
        if self.active_goal_handle is None or self.cancel_request_in_flight:
            return
        self.cancel_request_in_flight = True
        self.get_logger().warning(f"Cancelling navigation to {self.active_goal_label}.")
        cancel_future = self.active_goal_handle.cancel_goal_async()
        cancel_future.add_done_callback(self.handle_cancel_response)

    def request_localization(self):
        """Cancel navigation if needed, then globally localize with a slow 360-degree spin."""
        if self.localization_requested or self.localization_in_progress:
            self.get_logger().warning("AMCL localization is already in progress.")
            return

        self.localization_requested = True
        if self.active_goal_label is not None:
            self.get_logger().warning(
                f"Stopping {self.active_goal_label} before starting AMCL localization."
            )
            self.stop_robot()
            self.stop_requested = True
            if self.active_goal_handle is not None:
                self.cancel_active_goal()
            return

        self.begin_global_localization()

    def begin_global_localization(self):
        if not self.localization_requested or self.active_goal_label is not None:
            return

        self.localization_requested = False
        self.localization_in_progress = True
        self.localization_generation += 1
        generation = self.localization_generation
        self.active_goal_label = LOCALIZATION_LABEL
        self.stop_robot()

        self.get_logger().info(
            "Requesting AMCL global localization. The robot will then rotate 360 degrees."
        )
        self.publish_navigation_status(
            self.virtual_label("localize", "AMCL global localization"),
            GoalStatus.STATUS_EXECUTING,
            event="started",
        )
        if not self.global_localization_client.service_is_ready():
            self.finish_localization(
                GoalStatus.STATUS_ABORTED,
                "/reinitialize_global_localization is not ready; verify AMCL is active",
            )
            return

        future = self.global_localization_client.call_async(Empty.Request())
        future.add_done_callback(
            lambda completed: self.handle_global_localization_response(
                completed,
                generation,
            )
        )

    def handle_global_localization_response(self, future, generation):
        if generation != self.localization_generation or not self.localization_in_progress:
            return
        try:
            future.result()
        except Exception as exc:
            self.finish_localization(
                GoalStatus.STATUS_ABORTED,
                f"AMCL global localization failed: {exc}",
            )
            return

        duration_sec = (2.0 * math.pi) / self.localization_angular_speed
        self.localization_end_time = time.monotonic() + duration_sec
        self.get_logger().info(
            f"AMCL particles reset globally; rotating at "
            f"{self.localization_angular_speed:.2f} rad/s for {duration_sec:.1f} seconds."
        )
        self.localization_timer = self.create_timer(
            0.1,
            lambda: self.localization_spin_tick(generation),
        )

    def localization_spin_tick(self, generation):
        if generation != self.localization_generation or not self.localization_in_progress:
            return
        if time.monotonic() >= self.localization_end_time:
            self.finish_localization(
                GoalStatus.STATUS_SUCCEEDED,
                "AMCL localization scan completed",
            )
            return

        twist = Twist()
        twist.angular.z = self.localization_angular_speed
        self.cmd_vel_pub.publish(twist)

    def cancel_localization(self):
        if not self.localization_requested and not self.localization_in_progress:
            return False
        self.localization_requested = False
        self.localization_in_progress = False
        self.localization_generation += 1
        if self.localization_timer is not None:
            self.destroy_timer(self.localization_timer)
            self.localization_timer = None
        if self.active_goal_label == LOCALIZATION_LABEL:
            self.active_goal_label = None
        self.stop_robot()
        self.publish_navigation_status(
            self.virtual_label("localize", "AMCL global localization"),
            GoalStatus.STATUS_CANCELED,
            message="Localization was stopped",
        )
        return True

    def finish_localization(self, status, message):
        if self.localization_timer is not None:
            self.destroy_timer(self.localization_timer)
            self.localization_timer = None
        self.localization_requested = False
        self.localization_in_progress = False
        if self.active_goal_label == LOCALIZATION_LABEL:
            self.active_goal_label = None
        self.stop_robot()
        log = self.get_logger().info if status == GoalStatus.STATUS_SUCCEEDED else self.get_logger().error
        log(message)
        self.publish_navigation_status(
            self.virtual_label("localize", "AMCL global localization"),
            status,
            message=message,
        )

    def handle_cancel_response(self, future):
        self.cancel_request_in_flight = False
        try:
            response = future.result()
            if response is None or not response.goals_canceling:
                self.get_logger().error("Nav2 did not accept the goal cancellation request.")
            else:
                self.get_logger().info("Nav2 accepted the goal cancellation request.")
        except Exception as exc:
            self.get_logger().error(f"Could not cancel the Nav2 goal: {exc}")
        finally:
            self.stop_robot()

    def build_goal(self, label):
        world = label.get("world") or {}
        x = float(world["x"])
        y = float(world["y"])
        yaw = float(label.get("yaw", 0.0))
        return self.build_goal_from_values(x, y, yaw)

    def build_goal_from_values(self, x, y, yaw):
        qz, qw = yaw_to_quaternion(yaw)

        goal = NavigateToPose.Goal()
        goal.pose.header.frame_id = "map"
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x = x
        goal.pose.pose.position.y = y
        goal.pose.pose.position.z = 0.0
        goal.pose.pose.orientation.z = qz
        goal.pose.pose.orientation.w = qw
        return goal

    def build_return_staging_label(self):
        pose_msg = self.wait_for_pose()
        scan_msg = self.wait_for_scan()
        pose = pose_msg.pose.pose
        x = pose.position.x
        y = pose.position.y
        yaw = quaternion_to_yaw(pose.orientation)

        target_x, target_y, target_yaw, score = self.find_open_staging_pose(
            x,
            y,
            yaw,
            scan_msg,
        )
        self.get_logger().info(
            "Return staging goal computed at "
            f"x={target_x:.3f}, y={target_y:.3f}, yaw={target_yaw:.3f}, score={score:.3f}"
        )
        return {
            "name": "return_staging",
            "kind": "navigation",
            "detail": "Return staging",
            "source": "dynamic_lidar",
            "world": {"x": target_x, "y": target_y},
            "yaw": target_yaw,
        }

    def execute_full_spin(self):
        angular_speed = 0.45
        duration_sec = (2.0 * math.pi) / angular_speed
        command_period_sec = 0.1
        twist = Twist()
        twist.angular.z = angular_speed

        self.get_logger().info(
            f"Starting full spin at {angular_speed:.2f} rad/s for {duration_sec:.1f} sec."
        )
        end_time = time.monotonic() + duration_sec
        try:
            while rclpy.ok() and time.monotonic() < end_time:
                self.cmd_vel_pub.publish(twist)
                time.sleep(command_period_sec)
            return GoalStatus.STATUS_SUCCEEDED
        finally:
            self.stop_robot()

    def stop_robot(self):
        stop = Twist()
        for _ in range(5):
            self.cmd_vel_pub.publish(stop)
            time.sleep(0.02)

    def wait_for_pose(self):
        if self.latest_pose is None:
            raise RuntimeError("Cannot compute return staging: no /amcl_pose received")
        return self.latest_pose

    def wait_for_scan(self):
        if self.latest_scan is None:
            raise RuntimeError("Cannot compute return staging: no /scan received")
        return self.latest_scan

    def find_open_staging_pose(self, x, y, yaw, scan):
        origin_angle = math.atan2(-y, -x)
        origin_angle_robot = normalize_angle(origin_angle - yaw)
        best = None
        current_origin_distance = math.hypot(x, y)

        for degrees in range(-180, 180, 15):
            scan_angle = math.radians(degrees)
            forward_min, forward_avg = self.scan_window_stats(
                scan,
                scan_angle,
                math.radians(16.0),
            )
            side_min, side_avg = self.scan_window_stats(
                scan,
                scan_angle,
                math.radians(38.0),
            )
            if forward_min is None or side_min is None:
                continue
            if forward_min < 0.85 or side_min < 0.60:
                continue

            distance_to_move = min(0.45, forward_min - 0.45)
            if distance_to_move < 0.25:
                continue

            angle_in_map = yaw + scan_angle
            target_x = x + distance_to_move * math.cos(angle_in_map)
            target_y = y + distance_to_move * math.sin(angle_in_map)
            target_origin_distance = math.hypot(target_x, target_y)
            if target_origin_distance > current_origin_distance + 0.25:
                continue

            diff_to_origin = abs(normalize_angle(scan_angle - origin_angle_robot))
            target_yaw = math.atan2(-target_y, -target_x)
            score = (
                min(forward_min, 2.5)
                + min(forward_avg, 2.0)
                + min(side_avg, 2.0)
                + 0.75 * math.cos(diff_to_origin)
                + (current_origin_distance - target_origin_distance)
                - 0.1 * abs(scan_angle)
            )

            if best is None or score > best[0]:
                best = (score, target_x, target_y, target_yaw, scan_angle, distance_to_move)

        if best is None:
            raise RuntimeError(
                "Cannot compute return staging: no safe lidar cone toward origin found"
            )

        score, target_x, target_y, target_yaw, scan_angle, distance_to_move = best
        self.get_logger().info(
            "Return staging selected "
            f"angle={scan_angle:.3f} rad, move={distance_to_move:.3f} m"
        )
        return target_x, target_y, target_yaw, score

    def scan_window_stats(self, scan, center_angle, half_width):
        distances = []
        for index, distance in enumerate(scan.ranges):
            if not math.isfinite(distance):
                continue
            if distance < scan.range_min or distance > scan.range_max:
                continue
            scan_angle = scan.angle_min + index * scan.angle_increment
            if abs(normalize_angle(scan_angle - center_angle)) <= half_width:
                distances.append(distance)

        if not distances:
            return None, None
        return min(distances), sum(distances) / len(distances)

    def virtual_label(self, name, detail):
        return {
            "name": name,
            "kind": "navigation",
            "detail": detail,
            "world": None,
        }

    def handle_goal_response(self, future, label):
        try:
            goal_handle = future.result()
        except Exception as exc:
            self.get_logger().error(f"Could not submit goal: {exc}")
            self.publish_navigation_status(
                label,
                GoalStatus.STATUS_ABORTED,
                message=f"Could not submit goal: {exc}",
            )
            self.active_goal_label = None
            self.active_goal_handle = None
            self.stop_requested = False
            self.cancel_request_in_flight = False
            self.begin_global_localization()
            return
        if goal_handle is None or not goal_handle.accepted:
            self.get_logger().error("Nav2 rejected the goal")
            self.publish_navigation_status(
                label,
                GoalStatus.STATUS_ABORTED,
                message="Nav2 rejected the goal",
            )
            self.active_goal_label = None
            self.active_goal_handle = None
            self.stop_requested = False
            self.cancel_request_in_flight = False
            self.begin_global_localization()
            return

        self.active_goal_handle = goal_handle
        self.get_logger().info("Goal accepted. Waiting for result.")
        self.publish_navigation_status(
            label,
            GoalStatus.STATUS_EXECUTING,
            event="started",
        )
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(lambda future: self.handle_result(future, label))
        if self.stop_requested:
            self.cancel_active_goal()

    def handle_result(self, future, label):
        try:
            result = future.result()
        except Exception as exc:
            self.get_logger().error(f"Nav2 result failed: {exc}")
            self.publish_navigation_status(
                label,
                GoalStatus.STATUS_ABORTED,
                message=f"Nav2 result failed: {exc}",
            )
            self.active_goal_label = None
            self.active_goal_handle = None
            self.stop_requested = False
            self.cancel_request_in_flight = False
            self.stop_robot()
            self.begin_global_localization()
            return
        if result is None:
            self.get_logger().error("Nav2 did not return a result")
            self.publish_navigation_status(
                label,
                GoalStatus.STATUS_ABORTED,
                message="Nav2 did not return a result",
            )
            self.active_goal_label = None
            self.active_goal_handle = None
            self.stop_requested = False
            self.cancel_request_in_flight = False
            self.stop_robot()
            self.begin_global_localization()
            return

        if should_save_last_label(label):
            save_last_label(label, result.status)
            self.get_logger().info(
                f"Navigation finished with status {result.status}. Saved {LAST_LABEL_FILE}."
            )
        else:
            self.get_logger().info(
                f"Navigation finished with status {result.status}. "
                f"Skipped saving {LAST_LABEL_FILE} for {label.get('name')} label."
            )
        was_stopped = self.stop_requested
        self.active_goal_label = None
        self.active_goal_handle = None
        self.stop_requested = False
        self.cancel_request_in_flight = False
        if was_stopped or result.status == GoalStatus.STATUS_CANCELED:
            self.stop_robot()
        self.publish_navigation_status(label, result.status)
        self.begin_global_localization()

    def publish_navigation_status(
        self,
        label,
        status,
        *,
        event="finished",
        message=None,
    ):
        payload = {
            "event": event,
            "label": label_display(label),
            "name": label.get("name"),
            "kind": label.get("kind"),
            "detail": label.get("detail"),
            "status": status,
        }
        if message:
            payload["message"] = message
        msg = String()
        msg.data = json.dumps(payload)
        self.status_pub.publish(msg)
        self.get_logger().info(f"Published navigation status to {self.status_topic}: {msg.data}")


def save_last_label(label, status):
    output = {
        "name": label.get("name"),
        "kind": label.get("kind"),
        "detail": label.get("detail"),
        "world": label.get("world"),
        "status": status,
    }
    LAST_LABEL_FILE.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")


def should_save_last_label(label):
    name = normalize(label.get("name", ""))
    return name not in {"origin", "return_staging", "full_spin"}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Send Nav2 to a label from maps/lab_map_new_labels.json."
    )
    parser.add_argument("label", nargs="?", help="Label name or alias")
    parser.add_argument("--list", action="store_true", help="List saved labels and exit")
    parser.add_argument(
        "--listen",
        action="store_true",
        help="Subscribe to labels explicitly; this is the default with no label argument",
    )
    parser.add_argument(
        "--topic",
        default="/label",
        help="std_msgs/String topic to listen to",
    )
    parser.add_argument(
        "--labels-file",
        default=str(DEFAULT_LABELS_FILE),
        help="Path to a *_labels.json file",
    )
    parser.add_argument(
        "--action-name",
        default="/navigate_to_pose",
        help="Nav2 NavigateToPose action name",
    )
    parser.add_argument(
        "--status-topic",
        default="/robot/navigation_status",
        help="std_msgs/String topic for completed navigation status",
    )
    parser.add_argument(
        "--cmd-vel-topic",
        default="/cmd_vel_nav",
        help=(
            "Twist input used for localization and full-spin commands; Nav2's "
            "velocity smoother consumes /cmd_vel_nav"
        ),
    )
    parser.add_argument(
        "--server-timeout",
        type=float,
        default=10.0,
        help="Seconds to wait for the Nav2 action server",
    )
    return parser.parse_args(remove_ros_args(args=sys.argv)[1:])


def main():
    args = parse_args()
    labels_file = Path(args.labels_file).expanduser()
    labels = load_labels(labels_file)

    if args.list:
        list_labels(labels)
        return 0

    rclpy.init()
    node = LabelNavigator(
        args.action_name,
        args.status_topic,
        args.cmd_vel_topic,
    )
    try:
        if args.listen or not args.label:
            node.listen_for_labels(labels_file, args.topic, args.server_timeout)
            rclpy.spin(node)
        else:
            label = find_label(labels, args.label)
            status = node.go_to(label, args.server_timeout)
            if should_save_last_label(label):
                save_last_label(label, status)
                node.get_logger().info(
                    f"Navigation finished with status {status}. Saved {LAST_LABEL_FILE}."
                )
            else:
                node.get_logger().info(
                    f"Navigation finished with status {status}. "
                    f"Skipped saving {LAST_LABEL_FILE} for origin label."
                )
            if status != GoalStatus.STATUS_SUCCEEDED:
                return 1
        return 0
    except Exception as exc:
        node.get_logger().error(str(exc))
        return 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
