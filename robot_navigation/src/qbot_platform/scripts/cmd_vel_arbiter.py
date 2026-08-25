#!/usr/bin/env python3
"""Priority and timeout arbitration for autonomous and Nav2 behavior twists."""

from __future__ import annotations

from dataclasses import dataclass
import time

from geometry_msgs.msg import Twist
import rclpy
from rclpy.node import Node


@dataclass
class TwistSource:
    """Last command and receipt time for one velocity source."""

    message: Twist | None = None
    received_at: float = float("-inf")


class CmdVelArbiter(Node):
    """Give short-lived Nav2 behavior commands priority over path following."""

    def __init__(self) -> None:
        super().__init__("cmd_vel_arbiter")
        self.declare_parameter("navigation_topic", "/cmd_vel_auto")
        self.declare_parameter("behavior_topic", "/cmd_vel_behavior")
        self.declare_parameter("output_topic", "/cmd_vel")
        self.declare_parameter("navigation_timeout", 0.5)
        self.declare_parameter("behavior_timeout", 0.3)
        self.declare_parameter("publish_frequency", 20.0)

        navigation_topic = str(self.get_parameter("navigation_topic").value)
        behavior_topic = str(self.get_parameter("behavior_topic").value)
        output_topic = str(self.get_parameter("output_topic").value)
        self.navigation_timeout = float(
            self.get_parameter("navigation_timeout").value
        )
        self.behavior_timeout = float(self.get_parameter("behavior_timeout").value)
        publish_frequency = float(self.get_parameter("publish_frequency").value)
        if self.navigation_timeout <= 0.0 or self.behavior_timeout <= 0.0:
            raise ValueError("cmd_vel source timeouts must be positive")
        if publish_frequency <= 0.0:
            raise ValueError("cmd_vel publish_frequency must be positive")

        self.navigation = TwistSource()
        self.behavior = TwistSource()
        self.active_source = "stopped"
        self.output = self.create_publisher(Twist, output_topic, 10)
        self.create_subscription(
            Twist, navigation_topic, self.navigation_callback, 10
        )
        self.create_subscription(Twist, behavior_topic, self.behavior_callback, 10)
        self.create_timer(1.0 / publish_frequency, self.publish_selected)
        self.get_logger().info(
            f"Arbitrating {behavior_topic} over {navigation_topic}; output is "
            f"{output_topic}."
        )

    def navigation_callback(self, message: Twist) -> None:
        """Record the latest smoothed autonomous command."""
        self.navigation.message = message
        self.navigation.received_at = time.monotonic()

    def behavior_callback(self, message: Twist) -> None:
        """Record the latest collision-checked Nav2 behavior command."""
        self.behavior.message = message
        self.behavior.received_at = time.monotonic()

    def selected_command(self, now: float) -> tuple[str, Twist]:
        """Return the highest-priority command that has not timed out."""
        if (
            self.behavior.message is not None
            and now - self.behavior.received_at <= self.behavior_timeout
        ):
            source = "behavior"
            message = self.behavior.message
        elif (
            self.navigation.message is not None
            and now - self.navigation.received_at <= self.navigation_timeout
        ):
            source = "navigation"
            message = self.navigation.message
        else:
            source = "stopped"
            message = Twist()
        return source, message

    def publish_selected(self) -> None:
        """Publish the highest-priority command that has not timed out."""
        source, message = self.selected_command(time.monotonic())

        if source != self.active_source:
            self.get_logger().info(f"cmd_vel source changed to {source}.")
            self.active_source = source
        self.output.publish(message)


def main(args=None) -> None:
    rclpy.init(args=args)
    node = CmdVelArbiter()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.output.publish(Twist())
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
