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
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped, Twist
from nav_msgs.msg import Odometry
import rclpy
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
    qos_profile_sensor_data,
)
from rclpy.utilities import remove_ros_args
from sensor_msgs.msg import LaserScan
from std_msgs.msg import Bool, String
from std_srvs.srv import Empty, Trigger


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
LOCALIZATION_LABEL = "localization"
CONTROL_STATE_QOS = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)
NAVIGATION_STATUS_QOS = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)

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


def parse_label_command(value):
    """Parse legacy label strings and structured browser go commands."""
    text = str(value).strip()
    command = {"query": text, "label_id": None}
    if not text.startswith("{"):
        return command
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("Structured /label commands must be JSON objects")
    command.update(
        {
            "query": str(payload.get("name") or "").strip(),
            "label_id": str(payload.get("label_id") or "").strip() or None,
        }
    )
    if not command["query"] and not command["label_id"]:
        raise ValueError("Structured /label commands require label_id or name")
    return command


def find_label_by_id(labels, label_id):
    for label in labels:
        if str(label.get("id") or "") == str(label_id):
            return label
    raise ValueError(f"No saved label has id {label_id!r}")


def tracked_pose_stability(
    samples,
    now,
    *,
    minimum_samples=10,
    minimum_span=2.0,
    maximum_age=0.5,
    maximum_translation_spread=0.08,
    maximum_yaw_spread=math.radians(5.0),
):
    """Return (stable, detail) for timestamped (x, y, yaw) tracked poses."""
    if len(samples) < minimum_samples:
        return False, f"need {minimum_samples - len(samples)} more samples"
    window = samples[-max(minimum_samples, len(samples)):]
    span = float(window[-1][0]) - float(window[0][0])
    age = float(now) - float(window[-1][0])
    if span < minimum_span:
        return False, f"sample span is {span:.2f}s"
    if age > maximum_age:
        return False, f"newest pose is {age:.2f}s old"
    # "Spread" is the full separation between any two samples, not merely
    # each sample's distance from the mean. This keeps the configured 0.08 m
    # and 5 degree limits conservative and unambiguous.
    translation_spread = max(
        math.hypot(first[1] - second[1], first[2] - second[2])
        for index, first in enumerate(window)
        for second in window[index:]
    )
    yaw_spread = max(
        abs(normalize_angle(first[3] - second[3]))
        for index, first in enumerate(window)
        for second in window[index:]
    )
    stable = (
        translation_spread <= maximum_translation_spread
        and yaw_spread <= maximum_yaw_spread
    )
    detail = (
        f"translation spread {translation_spread:.3f} m, "
        f"yaw spread {math.degrees(yaw_spread):.2f} deg"
    )
    return stable, detail


def amcl_pose_confidence(
    message,
    received_at,
    now,
    *,
    maximum_age=2.0,
    maximum_position_std_dev=0.20,
    maximum_yaw_std_dev=math.radians(20.0),
):
    """Return (confident, detail) for one fresh AMCL covariance sample."""
    if message is None or received_at is None:
        return False, "no fresh /amcl_pose sample was received"
    age = float(now) - float(received_at)
    if age > maximum_age:
        return False, f"newest /amcl_pose is {age:.2f}s old"
    covariance = message.pose.covariance
    try:
        variances = (float(covariance[0]), float(covariance[7]), float(covariance[35]))
    except (IndexError, TypeError, ValueError):
        return False, "AMCL returned invalid covariance"
    if any(not math.isfinite(value) or value < 0.0 for value in variances):
        return False, "AMCL returned invalid covariance"
    position_std_dev = max(math.sqrt(variances[0]), math.sqrt(variances[1]))
    yaw_std_dev = math.sqrt(variances[2])
    detail = (
        f"position std dev {position_std_dev:.3f} m, "
        f"yaw std dev {math.degrees(yaw_std_dev):.1f} deg"
    )
    return (
        position_std_dev <= maximum_position_std_dev
        and yaw_std_dev <= maximum_yaw_std_dev,
        detail,
    )


class LabelNavigator(Node):
    def __init__(
        self,
        action_name,
        status_topic,
        cmd_vel_topic="/cmd_vel_nav",
        *,
        localizer="amcl",
        normal_bt="",
    ):
        super().__init__("go_to_label")
        self.action_name = action_name
        self.status_topic = status_topic
        self.cmd_vel_topic = cmd_vel_topic
        self.localizer = str(localizer).casefold()
        if self.localizer not in {"amcl", "cartographer"}:
            raise ValueError("localizer must be amcl or cartographer")
        self.behavior_tree = str(normal_bt)
        self.client = ActionClient(self, NavigateToPose, action_name)
        self.global_localization_client = self.create_client(
            Empty,
            "/reinitialize_global_localization",
        )
        self.nomotion_update_client = self.create_client(
            Empty,
            "/request_nomotion_update",
        )
        self.status_pub = self.create_publisher(
            String, status_topic, NAVIGATION_STATUS_QOS
        )
        self.control_state_pub = self.create_publisher(
            String, "/robot/navigation_control_state", CONTROL_STATE_QOS
        )
        self.cmd_vel_pub = self.create_publisher(Twist, cmd_vel_topic, 10)
        self.manual_stop_client = self.create_client(
            Trigger, "/manual_assistance/stop"
        )
        self.labels = []
        self.labels_file = None
        self.server_timeout_sec = 10.0
        self.active_goal_label = None
        self.active_goal = None
        self.active_goal_handle = None
        self.stop_requested = False
        self.cancel_request_in_flight = False
        self.cancel_watchdog_timer = None
        self.localization_requested = False
        self.localization_in_progress = False
        self.localization_generation = 0
        self.localization_timer = None
        self.localization_end_time = 0.0
        self.amcl_reset_timeout = 4.0
        self.amcl_confidence_timeout = 2.0
        self.amcl_confidence_samples = []
        self.amcl_last_nomotion_request = 0.0
        self.localization_angular_speed = 0.30
        self.tracked_localization_timeout = 10.0
        self.tracked_pose_samples = []
        self.localization_phase = "idle"
        self.lb_held = False
        self.localization_last_lb = False
        self.latest_odom_pose = None
        self.localization_last_odom_pose = None
        self.localization_translation = 0.0
        self.localization_rotation = 0.0
        self.cartographer_translation_required = 0.25
        self.cartographer_rotation_required = math.radians(45.0)
        self.localized = False
        self.latest_pose = None
        self.latest_pose_received_at = None
        self.latest_scan = None
        self.create_subscription(
            PoseWithCovarianceStamped,
            "/amcl_pose",
            self.pose_callback,
            10,
        )
        self.create_subscription(
            PoseStamped,
            "/tracked_pose",
            self.tracked_pose_callback,
            10,
        )
        self.create_subscription(
            LaserScan,
            "/scan",
            self.scan_callback,
            qos_profile_sensor_data,
        )
        self.create_subscription(Bool, "/controller/lb_held", self.lb_callback, 10)
        self.create_subscription(Odometry, "/odom", self.odom_callback, 20)
        self.get_logger().info(
            f"Using {self.localizer} localization; direct scan commands publish to "
            f"{self.cmd_vel_topic}."
        )
        self.publish_control_state("locked")

    def pose_callback(self, msg):
        if self.localizer == "amcl":
            received_at = time.monotonic()
            self.latest_pose = msg
            self.latest_pose_received_at = received_at
            if (
                self.localization_in_progress
                and self.localization_phase == "amcl_settling"
            ):
                self.amcl_confidence_samples.append((received_at, msg))
                self.amcl_confidence_samples = self.amcl_confidence_samples[-10:]

    def tracked_pose_callback(self, msg):
        if self.localizer != "cartographer":
            return
        self.latest_pose = msg
        if self.localization_in_progress and self.localization_phase == "settling":
            pose = msg.pose
            received_at = time.monotonic()
            self.tracked_pose_samples.append(
                (
                    received_at,
                    float(pose.position.x),
                    float(pose.position.y),
                    quaternion_to_yaw(pose.orientation),
                )
            )
            # Cartographer publishes tracked poses at up to 200 Hz. Keeping a
            # fixed 200 samples capped the stability span near one second even
            # though tracked_pose_stability() requires two seconds. Retain a
            # monotonic three-second window instead, independent of topic rate.
            cutoff = received_at - 3.0
            self.tracked_pose_samples = [
                sample for sample in self.tracked_pose_samples if sample[0] >= cutoff
            ]

    def lb_callback(self, msg):
        self.lb_held = bool(msg.data)

    def odom_callback(self, msg):
        pose = msg.pose.pose
        current = (
            float(pose.position.x),
            float(pose.position.y),
            quaternion_to_yaw(pose.orientation),
        )
        self.latest_odom_pose = current
        if (
            self.localizer == "cartographer"
            and self.localization_in_progress
            and self.localization_phase == "manual"
            and self.lb_held
            and self.localization_last_odom_pose is not None
        ):
            previous = self.localization_last_odom_pose
            self.localization_translation += math.hypot(
                current[0] - previous[0], current[1] - previous[1]
            )
            self.localization_rotation += abs(
                normalize_angle(current[2] - previous[2])
            )
        self.localization_last_odom_pose = current

    def publish_control_state(self, state):
        message = String()
        message.data = state
        self.control_state_pub.publish(message)

    def stop_idle_assistance(self, callback, failure_callback=None):
        """Confirm idle AssistedTeleop stopped, then continue asynchronously."""
        self.publish_control_state("locked")
        if not self.manual_stop_client.service_is_ready():
            message = "/manual_assistance/stop is unavailable"
            self.get_logger().error(message)
            if failure_callback is not None:
                failure_callback(message)
            return
        future = self.manual_stop_client.call_async(Trigger.Request())

        def stopped(completed):
            try:
                response = completed.result()
                if response is None or not response.success:
                    raise RuntimeError(
                        response.message if response is not None else "empty response"
                    )
            except Exception as exc:
                message = f"Could not stop assisted teleoperation: {exc}"
                self.get_logger().error(message)
                if failure_callback is not None:
                    failure_callback(message)
                return
            callback()

        future.add_done_callback(stopped)

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
        raw_query = msg.data.strip()
        if not raw_query:
            return
        try:
            command = parse_label_command(raw_query)
        except Exception as exc:
            self.get_logger().error(f"Invalid /label command: {exc}")
            return
        query = command["query"] or command["label_id"]
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
                    labels = load_labels(self.labels_file)
                else:
                    labels = self.labels
                label = (
                    find_label_by_id(labels, command["label_id"])
                    if command["label_id"]
                    else find_label(labels, query)
                )
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
        self.active_goal = label
        self.active_goal_handle = None
        self.stop_requested = False
        self.cancel_request_in_flight = False
        self.get_logger().info(
            f"Received {query!r}; going to {self.active_goal_label}."
        )

        def submit_goal():
            if self.stop_requested:
                self.active_goal_label = None
                self.active_goal = None
                self.publish_control_state("idle_ready" if self.localized else "locked")
                return
            self.publish_control_state("navigating")
            send_future = self.client.send_goal_async(goal)
            send_future.add_done_callback(
                lambda future: self.handle_goal_response(future, label)
            )

        def goal_stop_failed(message):
            self.publish_navigation_status(
                label,
                GoalStatus.STATUS_ABORTED,
                message=message,
            )
            self.active_goal_label = None
            self.active_goal = None
            self.publish_control_state("idle_ready" if self.localized else "locked")

        self.stop_idle_assistance(submit_goal, goal_stop_failed)

    def request_navigation_stop(self):
        """Stop motion now and cancel an active or currently-submitting Nav2 goal."""
        self.publish_control_state("locked")
        if self.manual_stop_client.service_is_ready():
            self.manual_stop_client.call_async(Trigger.Request())
        localization_stopped = self.cancel_localization()
        self.stop_robot()
        if self.active_goal_label is None:
            self.stop_requested = False
            if localization_stopped:
                self.get_logger().info(
                    f"Stop requested; {self.localizer} localization was stopped."
                )
            else:
                message = "Robot stopped; no navigation goal is active."
                self.publish_navigation_status(
                    self.virtual_label("stop", "No active navigation goal"),
                    GoalStatus.STATUS_CANCELED,
                    message=message,
                )
                self.publish_control_state(
                    "idle_ready" if self.localized else "locked"
                )
                self.get_logger().info(message)
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
        goal_handle = self.active_goal_handle
        cancel_future = goal_handle.cancel_goal_async()
        cancel_future.add_done_callback(
            lambda future: self.handle_cancel_response(future, goal_handle)
        )
        self.stop_cancel_watchdog()
        self.cancel_watchdog_timer = self.create_timer(
            5.0,
            lambda: self.cancel_watchdog(goal_handle),
        )

    def stop_cancel_watchdog(self):
        timer = self.cancel_watchdog_timer
        self.cancel_watchdog_timer = None
        if timer is not None:
            self.destroy_timer(timer)

    def reconcile_missing_goal(self, message, goal_handle):
        """End stale local state when Nav2 no longer knows the active handle."""
        if self.active_goal_handle is not goal_handle:
            return
        label = self.active_goal or self.virtual_label(
            "navigation", self.active_goal_label or "Navigation goal"
        )
        self.stop_cancel_watchdog()
        self.stop_robot()
        self.publish_navigation_status(
            label,
            GoalStatus.STATUS_CANCELED,
            message=message,
        )
        self.active_goal_label = None
        self.active_goal = None
        self.active_goal_handle = None
        self.stop_requested = False
        self.cancel_request_in_flight = False
        self.publish_control_state("idle_ready" if self.localized else "locked")
        self.begin_global_localization()

    def cancel_watchdog(self, goal_handle):
        """Bound how long Stop can remain waiting for an action result."""
        if self.active_goal_handle is not goal_handle or not self.stop_requested:
            self.stop_cancel_watchdog()
            return
        self.get_logger().error(
            "Nav2 did not report a terminal result within 5 seconds of Stop."
        )
        self.reconcile_missing_goal(
            "Stop timed out waiting for Nav2; local navigation state was reset.",
            goal_handle,
        )

    def request_localization(self):
        """Cancel navigation if needed, then run the selected localization workflow."""
        if self.localization_requested or self.localization_in_progress:
            self.get_logger().warning("Localization is already in progress.")
            return

        self.localization_requested = True
        if self.active_goal_label is not None:
            self.get_logger().warning(
                f"Stopping {self.active_goal_label} before starting {self.localizer} localization."
            )
            self.stop_robot()
            self.stop_requested = True
            if self.active_goal_handle is not None:
                self.cancel_active_goal()
            return

        def localization_stop_failed(message):
            self.localization_requested = False
            self.finish_localization(GoalStatus.STATUS_ABORTED, message)

        self.stop_idle_assistance(
            self.begin_global_localization,
            localization_stop_failed,
        )

    def begin_global_localization(self):
        if not self.localization_requested or self.active_goal_label is not None:
            return

        self.localization_requested = False
        self.localization_in_progress = True
        self.localized = False
        self.tracked_pose_samples = []
        self.amcl_confidence_samples = []
        self.localization_phase = "starting"
        self.localization_generation += 1
        generation = self.localization_generation
        self.active_goal_label = LOCALIZATION_LABEL
        self.stop_robot()

        if self.localizer == "amcl":
            # Discard any startup/prior-localization pose. Completion must be
            # justified by covariance received after this global reset.
            self.latest_pose = None
            self.latest_pose_received_at = None

        detail = (
            "AMCL global localization"
            if self.localizer == "amcl"
            else "Cartographer controller localization"
        )
        if self.localizer == "amcl":
            self.get_logger().info(f"Starting {detail} with a 360-degree rotation.")
        else:
            self.get_logger().info(
                "Starting Cartographer controller localization. Hold LB and drive or turn "
                "through distinctive map features, then release LB to evaluate the pose."
            )
        self.publish_navigation_status(
            self.virtual_label("localize", detail),
            GoalStatus.STATUS_EXECUTING,
            event="started",
        )
        if self.localizer == "cartographer":
            self.start_cartographer_manual_scan()
            self.localization_timer = self.create_timer(
                0.1, lambda: self.localization_timer_callback(generation)
            )
            return

        if not self.global_localization_client.wait_for_service(timeout_sec=2.0):
            self.finish_localization(
                GoalStatus.STATUS_ABORTED,
                "/reinitialize_global_localization did not become ready within 2 seconds; "
                "verify AMCL is active",
            )
            return

        self.localization_phase = "amcl_resetting"
        self.localization_end_time = time.monotonic() + self.amcl_reset_timeout
        self.localization_timer = self.create_timer(
            0.1,
            lambda: self.localization_timer_callback(generation),
        )
        try:
            future = self.global_localization_client.call_async(Empty.Request())
        except Exception as exc:
            self.finish_localization(
                GoalStatus.STATUS_ABORTED,
                f"Could not request AMCL global localization: {exc}",
            )
            return
        future.add_done_callback(
            lambda completed: self.handle_global_localization_response(
                completed,
                generation,
            )
        )

    def handle_global_localization_response(self, future, generation):
        if (
            generation != self.localization_generation
            or not self.localization_in_progress
            or self.localization_phase != "amcl_resetting"
        ):
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
        self.localization_phase = "amcl_spinning"
        self.localization_end_time = time.monotonic() + duration_sec
        self.get_logger().info(
            f"AMCL particles reset globally; rotating at "
            f"{self.localization_angular_speed:.2f} rad/s for {duration_sec:.1f} seconds."
        )

    def start_cartographer_manual_scan(self, message=None):
        self.localization_phase = "manual"
        self.localization_last_lb = self.lb_held
        self.localization_last_odom_pose = self.latest_odom_pose
        self.localization_translation = 0.0
        self.localization_rotation = 0.0
        self.tracked_pose_samples = []
        self.publish_control_state("localizing_manual")
        if message:
            self.get_logger().warning(message)
        self.get_logger().info(
            "Cartographer needs controller motion: hold LB, move at least 0.25 m or "
            "turn at least 45 degrees, then release LB."
        )

    def localization_spin_tick(self, generation):
        if generation != self.localization_generation or not self.localization_in_progress:
            return
        now = time.monotonic()
        if self.localizer == "cartographer":
            if self.localization_phase == "manual":
                movement_qualified = (
                    self.localization_translation
                    >= self.cartographer_translation_required
                    or self.localization_rotation >= self.cartographer_rotation_required
                )
                if self.localization_last_lb and not self.lb_held:
                    if not movement_qualified:
                        self.get_logger().warning(
                            "Cartographer localization needs more controller movement "
                            f"({self.localization_translation:.2f} m, "
                            f"{math.degrees(self.localization_rotation):.1f} deg so far)."
                        )
                    else:
                        self.publish_control_state("locked")
                        self.stop_robot()
                        self.localization_phase = "settling"
                        self.tracked_pose_samples = []
                        self.localization_end_time = (
                            now + self.tracked_localization_timeout
                        )
                        self.get_logger().info(
                            "Controller scan completed; evaluating tracked-pose stability."
                        )
                self.localization_last_lb = self.lb_held
                return
            if self.localization_phase == "settling":
                stable, detail = tracked_pose_stability(
                    self.tracked_pose_samples, now
                )
                if stable:
                    self.finish_localization(
                        GoalStatus.STATUS_SUCCEEDED,
                        f"Cartographer tracked pose is stable: {detail}",
                    )
                    return
                if now >= self.localization_end_time:
                    self.start_cartographer_manual_scan(
                        "Tracked pose is not stable yet "
                        f"({detail}). Drive through more map features and release LB to retry."
                    )
                return
            return
        if self.localization_phase == "amcl_resetting":
            if now >= self.localization_end_time:
                self.finish_localization(
                    GoalStatus.STATUS_ABORTED,
                    "AMCL global localization did not respond within "
                    f"{self.amcl_reset_timeout:.0f} seconds; run Localize again.",
                )
            return
        if self.localization_phase != "amcl_spinning":
            if self.localization_phase != "amcl_settling":
                return

            if (
                now - self.amcl_last_nomotion_request >= 0.25
                and self.nomotion_update_client.service_is_ready()
            ):
                self.amcl_last_nomotion_request = now
                self.nomotion_update_client.call_async(Empty.Request())

            samples = self.amcl_confidence_samples[-3:]
            if len(samples) == 3 and samples[-1][0] - samples[0][0] >= 0.4:
                checks = [
                    amcl_pose_confidence(message, received_at, now)
                    for received_at, message in samples
                ]
                if all(confident for confident, _detail in checks):
                    self.finish_localization(
                        GoalStatus.STATUS_SUCCEEDED,
                        "AMCL localization settled with three consecutive confident "
                        f"poses: {checks[-1][1]}",
                    )
                    return

            if now >= self.localization_end_time:
                if samples:
                    _confident, detail = amcl_pose_confidence(
                        samples[-1][1], samples[-1][0], now
                    )
                    sample_detail = (
                        f"{len(samples)} recent confidence sample(s); {detail}"
                    )
                else:
                    sample_detail = "no fresh AMCL poses arrived after stopping"
                self.finish_localization(
                    GoalStatus.STATUS_ABORTED,
                    "AMCL stopped rotating but did not produce three consecutive "
                    f"confident poses ({sample_detail}). Move to a more distinctive "
                    "area or set an initial pose, then run Localize again.",
                )
            return

        if now >= self.localization_end_time:
            self.stop_robot()
            self.localization_phase = "amcl_settling"
            self.amcl_confidence_samples = []
            self.amcl_last_nomotion_request = 0.0
            self.localization_end_time = now + self.amcl_confidence_timeout
            self.get_logger().info(
                "AMCL scan completed; checking three fresh confidence samples."
            )
            return

        twist = Twist()
        twist.angular.z = self.localization_angular_speed
        self.cmd_vel_pub.publish(twist)

    def localization_timer_callback(self, generation):
        """Keep an unexpected localization callback error from killing this node."""
        try:
            self.localization_spin_tick(generation)
        except Exception as exc:
            if (
                generation != self.localization_generation
                or not self.localization_in_progress
            ):
                return
            message = f"Localization stopped after an internal error: {exc}"
            self.finish_localization(GoalStatus.STATUS_ABORTED, message)

    def cancel_localization(self):
        if not self.localization_requested and not self.localization_in_progress:
            return False
        self.localization_requested = False
        self.localization_in_progress = False
        self.localization_phase = "idle"
        self.amcl_confidence_samples = []
        self.localization_generation += 1
        if self.localization_timer is not None:
            self.destroy_timer(self.localization_timer)
            self.localization_timer = None
        if self.active_goal_label == LOCALIZATION_LABEL:
            self.active_goal_label = None
        self.localized = False
        self.stop_robot()
        self.publish_navigation_status(
            self.virtual_label("localize", f"{self.localizer} localization"),
            GoalStatus.STATUS_CANCELED,
            message="Localization was stopped",
        )
        self.publish_control_state("locked")
        return True

    def finish_localization(self, status, message):
        if self.localization_timer is not None:
            self.destroy_timer(self.localization_timer)
            self.localization_timer = None
        self.localization_requested = False
        self.localization_in_progress = False
        self.localization_phase = "idle"
        self.amcl_confidence_samples = []
        if self.active_goal_label == LOCALIZATION_LABEL:
            self.active_goal_label = None
        self.localized = status == GoalStatus.STATUS_SUCCEEDED
        self.stop_robot()
        self.publish_navigation_status(
            self.virtual_label("localize", f"{self.localizer} localization"),
            status,
            message=message,
        )
        self.publish_control_state("idle_ready" if self.localized else "locked")
        # ROS Humble caches log severity by source call site. Do not dynamically
        # invoke INFO and ERROR from one line: repeating localization with a
        # different outcome otherwise raises and terminates go_to_label.
        if self.localized:
            self.get_logger().info(message)
        else:
            self.get_logger().error(message)

    def handle_cancel_response(self, future, goal_handle):
        if self.active_goal_handle is not goal_handle:
            return
        self.cancel_request_in_flight = False
        try:
            response = future.result()
            if response is None or not response.goals_canceling:
                message = (
                    "Nav2 reports that this goal is no longer active; "
                    "local navigation state was reconciled."
                )
                self.get_logger().warning(message)
                self.reconcile_missing_goal(message, goal_handle)
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
        if self.behavior_tree:
            goal.behavior_tree = self.behavior_tree
        return goal

    def build_return_staging_label(self):
        pose_msg = self.wait_for_pose()
        scan_msg = self.wait_for_scan()
        pose = pose_msg.pose.pose if hasattr(pose_msg.pose, "pose") else pose_msg.pose
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
            topic = "/amcl_pose" if self.localizer == "amcl" else "/tracked_pose"
            raise RuntimeError(f"Cannot compute return staging: no {topic} received")
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
            self.active_goal = None
            self.active_goal_handle = None
            self.stop_requested = False
            self.cancel_request_in_flight = False
            self.publish_control_state("idle_ready" if self.localized else "locked")
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
            self.active_goal = None
            self.active_goal_handle = None
            self.stop_requested = False
            self.cancel_request_in_flight = False
            self.publish_control_state("idle_ready" if self.localized else "locked")
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
        result_future.add_done_callback(
            lambda future: self.handle_result(future, label, goal_handle)
        )
        if self.stop_requested:
            self.cancel_active_goal()

    def handle_result(self, future, label, goal_handle):
        if self.active_goal_handle is not goal_handle:
            self.get_logger().warning("Ignoring a late result for an inactive Nav2 goal.")
            return
        self.stop_cancel_watchdog()
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
            self.active_goal = None
            self.active_goal_handle = None
            self.stop_requested = False
            self.cancel_request_in_flight = False
            self.stop_robot()
            self.publish_control_state("idle_ready" if self.localized else "locked")
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
            self.active_goal = None
            self.active_goal_handle = None
            self.stop_requested = False
            self.cancel_request_in_flight = False
            self.stop_robot()
            self.publish_control_state("idle_ready" if self.localized else "locked")
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
        self.active_goal = None
        self.active_goal_handle = None
        self.stop_requested = False
        self.cancel_request_in_flight = False
        if was_stopped or result.status == GoalStatus.STATUS_CANCELED:
            self.stop_robot()
        self.publish_navigation_status(label, result.status)
        self.publish_control_state("idle_ready" if self.localized else "locked")
        self.begin_global_localization()

    # def publish_navigation_status(
    #     self,
    #     label,
    #     status,
    #     *,
    #     event="finished",
    #     message=None,
    # ):
    #     payload = {
    #         "event": event,
    #         "label": label_display(label),
    #         "name": label.get("name"),
    #         "kind": label.get("kind"),
    #         "detail": label.get("detail"),
    #         "status": status,
    #     }
    #     if message:
    #         payload["message"] = message
    #     msg = String()
    #     msg.data = json.dumps(payload)
    #     self.status_pub.publish(msg)
    #     self.get_logger().info(f"Published navigation status to {self.status_topic}: {msg.data}")

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
            "label_id": label.get("id"),
            "kind": label.get("kind"),
            "detail": label.get("detail"),
            "world": label.get("world"),
            "yaw": label.get("yaw"),
            "map": (
                self.labels_file.stem.replace("_labels", "")
                if getattr(self, "labels_file", None) is not None
                else None
            ),
            "status": status,
            "localizer": self.localizer,
            "manual_state": (
                "navigating"
                if event == "started" and label.get("name") != "localize"
                else ("idle_ready" if self.localized else "locked")
            ),
        }

        if message:
            payload["message"] = message

        msg = String()
        msg.data = json.dumps(payload)

        self.status_pub.publish(msg)

        self.get_logger().info(
            f"Published navigation status to {self.status_topic}: {msg.data}"
        )


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
    parser.add_argument(
        "--localizer",
        choices=("amcl", "cartographer"),
        default="amcl",
        help="Pose source and localization procedure used by the running stack",
    )
    parser.add_argument(
        "--normal-bt",
        default="",
        help="Behavior tree XML for normal goals",
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
        localizer=args.localizer,
        normal_bt=args.normal_bt,
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
