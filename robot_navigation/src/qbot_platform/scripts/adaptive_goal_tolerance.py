#!/usr/bin/env python3
"""Adjust Nav2's XY goal tolerance from AMCL position covariance."""

from __future__ import annotations

from dataclasses import dataclass
import math
import time

try:
    from geometry_msgs.msg import PoseWithCovarianceStamped
    import rclpy
    from rcl_interfaces.msg import SetParametersResult
    from rcl_interfaces.srv import SetParameters
    from rclpy.node import Node
    from rclpy.parameter import Parameter
except ImportError as exc:  # Allow the policy to be unit-tested without ROS installed.
    PoseWithCovarianceStamped = None
    rclpy = None
    SetParametersResult = None
    SetParameters = None
    Parameter = None
    Node = object
    ROS_IMPORT_ERROR = exc
else:
    ROS_IMPORT_ERROR = None


@dataclass(frozen=True)
class ToleranceConfig:
    precise_xy_tolerance: float = 0.15
    normal_xy_tolerance: float = 0.20
    precise_enter_std_dev: float = 0.08
    precise_exit_std_dev: float = 0.12
    required_confident_samples: int = 3
    pose_timeout: float = 2.0

    def validate(self) -> None:
        if self.precise_xy_tolerance <= 0.0:
            raise ValueError("precise_xy_tolerance must be positive")
        if self.normal_xy_tolerance < self.precise_xy_tolerance:
            raise ValueError(
                "normal_xy_tolerance must be at least precise_xy_tolerance"
            )
        if self.precise_enter_std_dev < 0.0:
            raise ValueError("precise_enter_std_dev cannot be negative")
        if self.precise_exit_std_dev <= self.precise_enter_std_dev:
            raise ValueError(
                "precise_exit_std_dev must be greater than precise_enter_std_dev"
            )
        if self.required_confident_samples < 1:
            raise ValueError("required_confident_samples must be at least 1")
        if self.pose_timeout <= 0.0:
            raise ValueError("pose_timeout must be positive")


def position_uncertainty(covariance) -> float | None:
    """Return the largest X/Y standard deviation, or None for invalid data."""
    try:
        x_variance = float(covariance[0])
        y_variance = float(covariance[7])
    except (IndexError, TypeError, ValueError):
        return None
    if (
        not math.isfinite(x_variance)
        or not math.isfinite(y_variance)
        or x_variance < 0.0
        or y_variance < 0.0
    ):
        return None
    return max(math.sqrt(x_variance), math.sqrt(y_variance))


class AdaptiveTolerancePolicy:
    """Two-level tolerance policy with sample confirmation and hysteresis."""

    def __init__(self, config: ToleranceConfig, *, enabled: bool = True) -> None:
        config.validate()
        self.config = config
        self.enabled = bool(enabled)
        self.mode = "normal"
        self.confident_samples = 0
        self.last_pose_at: float | None = None
        self.last_uncertainty: float | None = None

    @property
    def tolerance(self) -> float:
        if self.enabled and self.mode == "precise":
            return self.config.precise_xy_tolerance
        return self.config.normal_xy_tolerance

    def set_enabled(self, enabled: bool) -> bool:
        previous_tolerance = self.tolerance
        self.enabled = bool(enabled)
        self.mode = "normal"
        self.confident_samples = 0
        self.last_uncertainty = None
        return self.tolerance != previous_tolerance

    def reconfigure(self, config: ToleranceConfig, *, enabled: bool) -> bool:
        config.validate()
        previous_tolerance = self.tolerance
        self.config = config
        self.enabled = bool(enabled)
        self.mode = "normal"
        self.confident_samples = 0
        self.last_uncertainty = None
        return self.tolerance != previous_tolerance

    def observe(self, covariance, now: float) -> bool:
        previous_mode = self.mode
        self.last_pose_at = float(now)
        self.last_uncertainty = position_uncertainty(covariance)

        if not self.enabled or self.last_uncertainty is None:
            self.mode = "normal"
            self.confident_samples = 0
            return self.mode != previous_mode

        if self.last_uncertainty <= self.config.precise_enter_std_dev:
            self.confident_samples += 1
            if self.confident_samples >= self.config.required_confident_samples:
                self.mode = "precise"
        else:
            # A sample in the hysteresis band keeps an already-precise mode,
            # but it breaks the consecutive-sample requirement to enter it.
            self.confident_samples = 0
            if self.last_uncertainty > self.config.precise_exit_std_dev:
                self.mode = "normal"
        return self.mode != previous_mode

    def check_stale(self, now: float) -> bool:
        if self.last_pose_at is None:
            return False
        if float(now) - self.last_pose_at <= self.config.pose_timeout:
            return False
        previous_mode = self.mode
        self.mode = "normal"
        self.confident_samples = 0
        self.last_uncertainty = None
        return self.mode != previous_mode


class AdaptiveGoalTolerance(Node):
    """ROS adapter that applies AdaptiveTolerancePolicy to controller_server."""

    IMMUTABLE_PARAMETERS = {"pose_topic", "controller_node", "goal_checker_id"}

    def __init__(self) -> None:
        super().__init__("adaptive_goal_tolerance")
        self.declare_parameter("enabled", True)
        self.declare_parameter("pose_topic", "/amcl_pose")
        self.declare_parameter("controller_node", "/controller_server")
        self.declare_parameter("goal_checker_id", "general_goal_checker")
        self.declare_parameter("precise_xy_tolerance", 0.15)
        self.declare_parameter("normal_xy_tolerance", 0.20)
        self.declare_parameter("precise_enter_std_dev", 0.08)
        self.declare_parameter("precise_exit_std_dev", 0.12)
        self.declare_parameter("required_confident_samples", 3)
        self.declare_parameter("pose_timeout", 2.0)
        self.declare_parameter("update_interval", 1.0)

        self.enabled = bool(self.get_parameter("enabled").value)
        self.config = self._config_from_parameters()
        self.update_interval = float(self.get_parameter("update_interval").value)
        if self.update_interval <= 0.0:
            raise ValueError("update_interval must be positive")

        self.pose_topic = str(self.get_parameter("pose_topic").value)
        self.controller_node = str(self.get_parameter("controller_node").value)
        self.goal_checker_id = str(self.get_parameter("goal_checker_id").value)
        if not self.pose_topic or not self.controller_node or not self.goal_checker_id:
            raise ValueError(
                "pose_topic, controller_node, and goal_checker_id cannot be empty"
            )

        self.policy = AdaptiveTolerancePolicy(self.config, enabled=self.enabled)
        self.desired_tolerance = self.policy.tolerance
        self.applied_tolerance: float | None = None
        self.update_pending = False
        self.last_update_attempt = -math.inf
        self.last_error = ""
        self.last_error_at = -math.inf

        parameter_service = f"{self.controller_node.rstrip('/')}/set_parameters"
        self.parameter_client = self.create_client(SetParameters, parameter_service)
        self.subscription = self.create_subscription(
            PoseWithCovarianceStamped,
            self.pose_topic,
            self.pose_callback,
            10,
        )
        self.timer = self.create_timer(0.25, self.timer_callback)
        self.parameter_callback_handle = self.add_on_set_parameters_callback(
            self.parameter_callback
        )

        if self.enabled:
            startup_message = (
                "Adaptive goal tolerance enabled: "
                f"precise={self.config.precise_xy_tolerance:.2f} m at "
                f"<={self.config.precise_enter_std_dev:.2f} m uncertainty; "
                f"normal={self.config.normal_xy_tolerance:.2f} m"
            )
        else:
            startup_message = (
                "Adaptive goal tolerance disabled; using fixed normal tolerance "
                f"{self.config.normal_xy_tolerance:.2f} m"
            )
        self.get_logger().info(startup_message)

    def _config_from_parameters(self, overrides: dict | None = None) -> ToleranceConfig:
        values = {
            "precise_xy_tolerance": self.get_parameter(
                "precise_xy_tolerance"
            ).value,
            "normal_xy_tolerance": self.get_parameter("normal_xy_tolerance").value,
            "precise_enter_std_dev": self.get_parameter(
                "precise_enter_std_dev"
            ).value,
            "precise_exit_std_dev": self.get_parameter(
                "precise_exit_std_dev"
            ).value,
            "required_confident_samples": self.get_parameter(
                "required_confident_samples"
            ).value,
            "pose_timeout": self.get_parameter("pose_timeout").value,
        }
        values.update(overrides or {})
        config = ToleranceConfig(
            precise_xy_tolerance=float(values["precise_xy_tolerance"]),
            normal_xy_tolerance=float(values["normal_xy_tolerance"]),
            precise_enter_std_dev=float(values["precise_enter_std_dev"]),
            precise_exit_std_dev=float(values["precise_exit_std_dev"]),
            required_confident_samples=int(values["required_confident_samples"]),
            pose_timeout=float(values["pose_timeout"]),
        )
        config.validate()
        return config

    def pose_callback(self, message) -> None:
        previous_mode = self.policy.mode
        changed = self.policy.observe(message.pose.covariance, time.monotonic())
        self.desired_tolerance = self.policy.tolerance
        if changed:
            if self.policy.mode == "precise":
                self.get_logger().info(
                    "AMCL confidence is high "
                    f"(position std dev {self.policy.last_uncertainty:.3f} m); "
                    f"requesting {self.desired_tolerance:.2f} m XY goal tolerance"
                )
            elif previous_mode == "precise":
                detail = (
                    "invalid covariance"
                    if self.policy.last_uncertainty is None
                    else f"position std dev {self.policy.last_uncertainty:.3f} m"
                )
                self.get_logger().info(
                    f"AMCL confidence dropped ({detail}); requesting "
                    f"{self.desired_tolerance:.2f} m XY goal tolerance"
                )
            self._maybe_apply_tolerance(force=self.policy.mode == "normal")

    def timer_callback(self) -> None:
        became_stale = self.policy.check_stale(time.monotonic())
        if became_stale:
            self.desired_tolerance = self.policy.tolerance
            self.get_logger().warning(
                f"AMCL pose is stale; requesting normal {self.desired_tolerance:.2f} m "
                "XY goal tolerance"
            )
        self._maybe_apply_tolerance(force=became_stale)

    def parameter_callback(self, parameters):
        result = SetParametersResult()
        result.successful = False
        result.reason = ""
        overrides = {}
        enabled = self.enabled
        update_interval = self.update_interval

        for parameter in parameters:
            if parameter.name in self.IMMUTABLE_PARAMETERS:
                result.reason = (
                    f"{parameter.name} requires restarting adaptive_goal_tolerance"
                )
                return result
            if parameter.name == "enabled":
                enabled = bool(parameter.value)
            elif parameter.name == "update_interval":
                update_interval = float(parameter.value)
            elif parameter.name in ToleranceConfig.__dataclass_fields__:
                overrides[parameter.name] = parameter.value

        try:
            if update_interval <= 0.0:
                raise ValueError("update_interval must be positive")
            config = self._config_from_parameters(overrides)
        except (TypeError, ValueError) as exc:
            result.reason = str(exc)
            return result

        was_enabled = self.enabled
        self.enabled = enabled
        self.config = config
        self.update_interval = update_interval
        self.policy.reconfigure(config, enabled=enabled)
        self.desired_tolerance = self.policy.tolerance
        if was_enabled and not enabled:
            self.get_logger().warning(
                "Adaptive goal tolerance disabled at runtime; restoring "
                f"{self.desired_tolerance:.2f} m"
            )
        elif not was_enabled and enabled:
            self.get_logger().info(
                "Adaptive goal tolerance enabled at runtime; waiting for three "
                "fresh high-confidence AMCL poses"
            )
        self._maybe_apply_tolerance(force=not enabled)
        result.successful = True
        return result

    @property
    def controller_parameter_name(self) -> str:
        return f"{self.goal_checker_id}.xy_goal_tolerance"

    def _maybe_apply_tolerance(self, *, force: bool = False) -> None:
        if self.update_pending:
            return
        if (
            not force
            and self.applied_tolerance is not None
            and math.isclose(self.applied_tolerance, self.desired_tolerance)
        ):
            return
        now = time.monotonic()
        if not force and now - self.last_update_attempt < self.update_interval:
            return
        if not self.parameter_client.service_is_ready():
            self._log_update_error(
                f"Waiting for {self.controller_node} parameter service"
            )
            return

        target = self.desired_tolerance
        self.last_update_attempt = now
        self.update_pending = True
        request = SetParameters.Request()
        request.parameters = [
            Parameter(
                self.controller_parameter_name,
                Parameter.Type.DOUBLE,
                target,
            ).to_parameter_msg()
        ]
        future = self.parameter_client.call_async(request)
        future.add_done_callback(
            lambda completed, requested=target: self._parameter_update_done(
                completed,
                requested,
            )
        )

    def _parameter_update_done(self, future, requested: float) -> None:
        self.update_pending = False
        try:
            response = future.result()
            results = getattr(response, "results", [])
            if not results or not results[0].successful:
                reason = results[0].reason if results else "empty service response"
                raise RuntimeError(reason or "controller rejected the parameter")
        except Exception as exc:
            self._log_update_error(
                f"Could not set {self.controller_parameter_name}: {exc}"
            )
        else:
            self.applied_tolerance = requested
            self.last_error = ""
            self.get_logger().info(
                f"Nav2 XY goal tolerance is now {requested:.2f} m"
            )

        if not math.isclose(requested, self.desired_tolerance):
            # In particular, ensure a disable request wins if a previous
            # precise update was already in flight.
            self.last_update_attempt = -math.inf
            self._maybe_apply_tolerance(force=not self.enabled)

    def _log_update_error(self, message: str) -> None:
        now = time.monotonic()
        if message != self.last_error or now - self.last_error_at >= 10.0:
            self.get_logger().warning(message)
            self.last_error = message
            self.last_error_at = now

    def restore_normal_tolerance(self, timeout: float = 1.0) -> bool:
        """Best-effort restoration used when this node alone is shut down."""
        if (
            rclpy is None
            or not rclpy.ok()
            or not self.parameter_client.service_is_ready()
        ):
            return False
        request = SetParameters.Request()
        request.parameters = [
            Parameter(
                self.controller_parameter_name,
                Parameter.Type.DOUBLE,
                self.config.normal_xy_tolerance,
            ).to_parameter_msg()
        ]
        future = self.parameter_client.call_async(request)
        try:
            rclpy.spin_until_future_complete(self, future, timeout_sec=timeout)
            response = future.result()
            results = getattr(response, "results", [])
            return bool(results and results[0].successful)
        except Exception:
            return False


def main() -> int:
    if rclpy is None:
        raise RuntimeError(f"ROS Python dependencies are unavailable: {ROS_IMPORT_ERROR}")
    rclpy.init()
    node = AdaptiveGoalTolerance()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.restore_normal_tolerance()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
