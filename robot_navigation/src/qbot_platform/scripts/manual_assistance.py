#!/usr/bin/env python3
"""Collision-checked idle teleop and recovery-gated manual assistance."""

from __future__ import annotations

import json
import math
import threading
import time

from action_msgs.msg import GoalStatus
from builtin_interfaces.msg import Duration
from geometry_msgs.msg import Twist
from nav2_msgs.action import AssistedTeleop
from nav2_msgs.srv import ClearEntireCostmap
from nav_msgs.msg import Odometry
import rclpy
from rclpy.action import ActionClient, ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import Bool, String
from std_srvs.srv import Trigger

from qbot_platform.action import ManualAssistance


CONTROL_STATE_QOS = QoSProfile(
    depth=1,
    reliability=ReliabilityPolicy.RELIABLE,
    durability=DurabilityPolicy.TRANSIENT_LOCAL,
)


def yaw_from_quaternion(orientation) -> float:
    return math.atan2(
        2.0 * (orientation.w * orientation.z + orientation.x * orientation.y),
        1.0 - 2.0 * (orientation.y * orientation.y + orientation.z * orientation.z),
    )


def angle_difference(first: float, second: float) -> float:
    return math.atan2(math.sin(first - second), math.cos(first - second))


class ManualAssistanceServer(Node):
    """Own Nav2 AssistedTeleop without ever bypassing its collision checks."""

    TELEOP_ALLOWED_STATES = {"idle_ready", "localizing_manual"}
    TERMINAL_ACTION_STATES = {
        GoalStatus.STATUS_CANCELED,
        GoalStatus.STATUS_SUCCEEDED,
        GoalStatus.STATUS_ABORTED,
    }

    def __init__(self) -> None:
        super().__init__("manual_assistance")
        self.declare_parameter("lb_state_topic", "/controller/lb_held")
        self.declare_parameter("teleop_topic", "/cmd_vel_teleop")
        self.declare_parameter("navigation_state_topic", "/robot/navigation_control_state")
        self.declare_parameter("status_topic", "/robot/manual_assistance_status")
        self.declare_parameter("assisted_action", "/assisted_teleop")
        self.declare_parameter("odom_topic", "/odom")
        self.declare_parameter("translation_threshold", 0.03)
        self.declare_parameter("rotation_threshold", math.radians(3.0))

        self.callback_group = ReentrantCallbackGroup()
        self.lock = threading.RLock()
        self.lb_held = False
        self.odom_pose: tuple[float, float, float] | None = None
        self.navigation_state = "locked"
        self.help_active = False
        self.stop_generation = 0
        self.idle_goal_handle = None
        self.idle_send_pending = False
        self.translation_threshold = float(
            self.get_parameter("translation_threshold").value
        )
        self.rotation_threshold = float(self.get_parameter("rotation_threshold").value)

        lb_topic = str(self.get_parameter("lb_state_topic").value)
        teleop_topic = str(self.get_parameter("teleop_topic").value)
        state_topic = str(self.get_parameter("navigation_state_topic").value)
        status_topic = str(self.get_parameter("status_topic").value)
        action_name = str(self.get_parameter("assisted_action").value)
        odom_topic = str(self.get_parameter("odom_topic").value)

        self.teleop_pub = self.create_publisher(Twist, teleop_topic, 10)
        self.status_pub = self.create_publisher(String, status_topic, 10)
        self.assisted_client = ActionClient(
            self,
            AssistedTeleop,
            action_name,
            callback_group=self.callback_group,
        )
        self.local_clear = self.create_client(
            ClearEntireCostmap,
            "/local_costmap/clear_entirely_local_costmap",
            callback_group=self.callback_group,
        )
        self.global_clear = self.create_client(
            ClearEntireCostmap,
            "/global_costmap/clear_entirely_global_costmap",
            callback_group=self.callback_group,
        )
        self.create_subscription(
            Bool, lb_topic, self.lb_callback, 10, callback_group=self.callback_group
        )
        self.create_subscription(
            Odometry,
            odom_topic,
            self.odom_callback,
            20,
            callback_group=self.callback_group,
        )
        self.create_subscription(
            String,
            state_topic,
            self.navigation_state_callback,
            CONTROL_STATE_QOS,
            callback_group=self.callback_group,
        )
        self.stop_service = self.create_service(
            Trigger,
            "/manual_assistance/stop",
            self.stop_callback,
            callback_group=self.callback_group,
        )
        self.action_server = ActionServer(
            self,
            ManualAssistance,
            "manual_assistance",
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.callback_group,
        )
        self.idle_timer = self.create_timer(
            0.05, self.idle_teleop_tick, callback_group=self.callback_group
        )
        self.publish_state("idle_ready", "Controller assistance is standing by")

    def publish_state(self, state: str, message: str = "", reason: str = "") -> None:
        payload = {
            "state": state,
            "message": message,
            "reason": reason,
            "received_at": time.time(),
        }
        msg = String()
        msg.data = json.dumps(payload)
        self.status_pub.publish(msg)

    def lb_callback(self, message: Bool) -> None:
        with self.lock:
            self.lb_held = bool(message.data)
            navigation_state = self.navigation_state
        if navigation_state == "localizing_manual":
            if message.data:
                self.publish_state(
                    "localizing_manual_driving",
                    "Cartographer localization drive is active and collision checked.",
                )
            else:
                self.publish_state(
                    "localizing_manual",
                    "Hold LB and drive or turn through distinctive map features.",
                )

    def odom_callback(self, message: Odometry) -> None:
        pose = message.pose.pose
        with self.lock:
            self.odom_pose = (
                float(pose.position.x),
                float(pose.position.y),
                yaw_from_quaternion(pose.orientation),
            )

    def navigation_state_callback(self, message: String) -> None:
        state = message.data.strip()
        if not state:
            return
        with self.lock:
            self.navigation_state = state
        if state not in self.TELEOP_ALLOWED_STATES:
            self.stop_idle_assisted()
        elif state == "localizing_manual":
            self.publish_state(
                "localizing_manual",
                "Hold LB and drive or turn through distinctive map features.",
            )

    def goal_callback(self, _request) -> GoalResponse:
        with self.lock:
            return GoalResponse.REJECT if self.help_active else GoalResponse.ACCEPT

    def cancel_callback(self, _goal_handle) -> CancelResponse:
        return CancelResponse.ACCEPT

    def stop_callback(self, _request, response):
        with self.lock:
            self.stop_generation += 1
        self.publish_zero()
        try:
            self.stop_idle_assisted(strict=True)
        except RuntimeError as exc:
            response.success = False
            response.message = str(exc)
            return response
        response.success = True
        response.message = "Assisted teleoperation is stopped"
        return response

    def publish_zero(self) -> None:
        for _ in range(3):
            self.teleop_pub.publish(Twist())

    def _assisted_goal(self) -> AssistedTeleop.Goal:
        goal = AssistedTeleop.Goal()
        # Recovery assistance has no automatic operator timeout. Cancellation,
        # Stop, or qualified movement followed by LB release ends the action.
        goal.time_allowance = Duration(sec=24 * 60 * 60)
        return goal

    @staticmethod
    def _wait_future(future, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while not future.done() and time.monotonic() < deadline:
            time.sleep(0.02)
        return future.done()

    def start_assisted(self, timeout: float = 5.0):
        if not self.assisted_client.wait_for_server(timeout_sec=timeout):
            raise RuntimeError("Nav2 assisted_teleop action is unavailable")
        future = self.assisted_client.send_goal_async(self._assisted_goal())
        if not self._wait_future(future, timeout):
            raise RuntimeError("Timed out starting collision-checked assisted teleop")
        handle = future.result()
        if handle is None or not handle.accepted:
            raise RuntimeError("Nav2 rejected collision-checked assisted teleop")
        return handle

    def stop_assisted(self, handle, timeout: float = 3.0, *, strict: bool = False) -> bool:
        if handle is None:
            return True
        self.publish_zero()
        result_future = handle.get_result_async()

        def terminal_result_available() -> bool:
            if not self._wait_future(result_future, timeout):
                return False
            wrapped_result = result_future.result()
            return bool(
                wrapped_result is not None
                and wrapped_result.status in self.TERMINAL_ACTION_STATES
            )

        try:
            # Cancellation and result callbacks can cross in flight. Treat an
            # already-terminal goal as stopped instead of requiring it to be
            # listed in a new cancellation response.
            if result_future.done() and terminal_result_available():
                return True
            cancel_future = handle.cancel_goal_async()
            if not self._wait_future(cancel_future, timeout):
                raise RuntimeError("timed out waiting for cancellation acknowledgement")
            cancel_response = cancel_future.result()
            if cancel_response is None or not cancel_response.goals_canceling:
                if terminal_result_available():
                    return True
                raise RuntimeError(
                    "Nav2 neither accepted AssistedTeleop cancellation nor reported it terminal"
                )
            if terminal_result_available():
                return True
            raise RuntimeError("timed out confirming AssistedTeleop termination")
        except Exception as exc:
            if strict:
                raise RuntimeError(f"Could not confirm assisted teleop stop: {exc}") from exc
            self.get_logger().warning(f"Could not confirm assisted teleop stop: {exc}")
            return False

    def stop_idle_assisted(self, *, strict: bool = False) -> bool:
        with self.lock:
            handle = self.idle_goal_handle
            self.idle_goal_handle = None
            self.idle_send_pending = False
        if handle is not None:
            try:
                return self.stop_assisted(handle, strict=strict)
            except RuntimeError:
                # Keep the handle so Stop can retry instead of forgetting a
                # possibly still-active collision-checked teleop goal.
                with self.lock:
                    if self.idle_goal_handle is None:
                        self.idle_goal_handle = handle
                raise
        return True

    def _idle_goal_response(self, future) -> None:
        try:
            handle = future.result()
        except Exception as exc:
            self.get_logger().warning(f"Could not start idle assisted teleop: {exc}")
            handle = None
        with self.lock:
            self.idle_send_pending = False
            if (
                handle is not None
                and handle.accepted
                and self.lb_held
                and self.navigation_state in self.TELEOP_ALLOWED_STATES
                and not self.help_active
            ):
                self.idle_goal_handle = handle
                return
        if handle is not None and handle.accepted:
            self.stop_assisted(handle)

    def idle_teleop_tick(self) -> None:
        with self.lock:
            allowed = (
                self.navigation_state == "idle_ready"
                or self.navigation_state == "localizing_manual"
            )
            allowed = (
                allowed
                and not self.help_active
                and self.lb_held
            )
            handle = self.idle_goal_handle
            pending = self.idle_send_pending
        if not allowed:
            if handle is not None:
                self.stop_idle_assisted()
            return
        if handle is None and not pending and self.assisted_client.server_is_ready():
            with self.lock:
                self.idle_send_pending = True
            future = self.assisted_client.send_goal_async(self._assisted_goal())
            future.add_done_callback(self._idle_goal_response)

    def moved_enough(
        self, baseline: tuple[float, float, float] | None
    ) -> tuple[bool, float, float]:
        with self.lock:
            current = self.odom_pose
        if baseline is None or current is None:
            return False, 0.0, 0.0
        translation = math.hypot(current[0] - baseline[0], current[1] - baseline[1])
        rotation = abs(angle_difference(current[2], baseline[2]))
        return (
            translation >= self.translation_threshold
            or rotation >= self.rotation_threshold,
            translation,
            rotation,
        )

    def clear_costmaps(self) -> bool:
        cleared = True
        for name, client in (("local", self.local_clear), ("global", self.global_clear)):
            if not client.wait_for_service(timeout_sec=2.0):
                self.get_logger().warning(
                    f"{name} costmap clear service is unavailable; Nav2 will clear/replan"
                )
                cleared = False
                continue
            future = client.call_async(ClearEntireCostmap.Request())
            if not self._wait_future(future, 3.0):
                self.get_logger().warning(
                    f"Timed out clearing the {name} costmap; Nav2 will clear/replan"
                )
                cleared = False
                continue
            try:
                future.result()
            except Exception as exc:
                self.get_logger().warning(
                    f"Could not clear the {name} costmap; Nav2 will clear/replan: {exc}"
                )
                cleared = False
        return cleared

    def execute_callback(self, goal_handle):
        reason = goal_handle.request.reason or "Autonomous recovery could not proceed"
        result = ManualAssistance.Result()
        with self.lock:
            self.help_active = True
            generation = self.stop_generation
        self.stop_idle_assisted()
        self.publish_state(
            "help_requested",
            "Hold LB and drive the QBot into clear space; release LB after it moves.",
            reason,
        )

        assisted_handle = None
        last_lb = False
        baseline = None
        movement_armed = False
        try:
            while rclpy.ok():
                with self.lock:
                    lb_held = self.lb_held
                    stopped = self.stop_generation != generation
                if goal_handle.is_cancel_requested or stopped:
                    if assisted_handle is not None:
                        self.stop_assisted(assisted_handle)
                    self.publish_zero()
                    goal_handle.canceled()
                    result.completed = False
                    result.message = "Manual assistance was canceled"
                    return result

                if lb_held and not last_lb:
                    assisted_handle = self.start_assisted()
                    with self.lock:
                        baseline = self.odom_pose
                    movement_armed = False
                    self.publish_state(
                        "manual_driving",
                        "Collision-checked controller movement is active.",
                        reason,
                    )

                if lb_held and assisted_handle is not None and not movement_armed:
                    movement_armed, translation, rotation = self.moved_enough(baseline)
                    if movement_armed:
                        feedback = ManualAssistance.Feedback()
                        feedback.state = "movement_qualified"
                        goal_handle.publish_feedback(feedback)
                        self.get_logger().info(
                            f"Manual movement qualified: {translation:.3f} m, "
                            f"{math.degrees(rotation):.2f} deg"
                        )

                if not lb_held and last_lb and assisted_handle is not None:
                    self.stop_assisted(assisted_handle, strict=True)
                    assisted_handle = None
                    self.publish_zero()
                    if movement_armed:
                        self.publish_state(
                            "resuming", "Clearing costmaps and resuming the saved goal.", reason
                        )
                        cleared = self.clear_costmaps()
                        result.completed = True
                        result.message = (
                            "Qualified manual movement completed; costmaps cleared"
                            if cleared
                            else (
                                "Qualified manual movement completed; "
                                "Nav2 will clear while replanning"
                            )
                        )
                        goal_handle.succeed()
                        self.get_logger().info(
                            "Manual assistance completed; resuming the saved navigation goal."
                        )
                        return result
                    self.publish_state(
                        "help_requested",
                        "No qualified movement was detected; hold LB and try again.",
                        reason,
                    )

                last_lb = lb_held
                feedback = ManualAssistance.Feedback()
                feedback.state = (
                    "manual_driving" if assisted_handle is not None else "help_requested"
                )
                goal_handle.publish_feedback(feedback)
                time.sleep(0.05)
        except Exception as exc:
            if assisted_handle is not None:
                self.stop_assisted(assisted_handle)
            self.publish_zero()
            self.get_logger().error(
                f"Manual assistance failed while handling {reason!r}: {exc}"
            )
            goal_handle.abort()
            result.completed = False
            result.message = str(exc)
            return result
        finally:
            with self.lock:
                self.help_active = False
                navigation_state = self.navigation_state
            if navigation_state == "navigating":
                self.publish_state(
                    "navigating",
                    "Autonomous navigation is continuing with the saved goal.",
                )
            else:
                self.publish_state("idle_ready", "Manual assistance is standing by")


def main() -> int:
    rclpy.init()
    node = ManualAssistanceServer()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        node.publish_zero()
        node.stop_idle_assisted()
        node.action_server.destroy()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
