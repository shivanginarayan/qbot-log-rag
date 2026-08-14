#!/usr/bin/env python3
"""Small helper for publishing QBot LED strip colors."""

from rclpy.node import Node
from std_msgs.msg import ColorRGBA


class LEDController:
    OFF = (0.0, 0.0, 0.0)
    BLUE = (0.0, 0.0, 1.0)
    YELLOW = (1.0, 1.0, 0.0)
    RED = (1.0, 0.0, 0.0)
    GREEN = (0.0, 1.0, 0.0)

    def __init__(self, node: Node, led_topic: str = "/qbot_led_strip"):
        self.node = node
        self.led_pub = node.create_publisher(ColorRGBA, led_topic, 10)
        self.current_color = self.OFF
        self.current_msg = None
        self.flash_timer = None
        self.flash_color = self.OFF
        self.flash_on = False
        self.republish_timer = node.create_timer(0.2, self._republish_current)
        self.node.get_logger().info(f"LED controller publishing to {led_topic}")

    def _publish_color(self, color: tuple, brightness: float = 1.0):
        msg = ColorRGBA()
        msg.r = float(color[0]) * brightness
        msg.g = float(color[1]) * brightness
        msg.b = float(color[2]) * brightness
        msg.a = 1.0
        self.current_msg = msg
        self.led_pub.publish(msg)
        self.current_color = color

    def _republish_current(self):
        if self.current_msg is not None:
            self.led_pub.publish(self.current_msg)

    def set_color(self, color: tuple, brightness: float = 1.0):
        self.stop_flash()
        self._publish_color(color, brightness)

    def off(self):
        self.set_color(self.OFF)
        self.node.get_logger().info("LED: off")

    def blue(self):
        self.set_color(self.BLUE)
        self.node.get_logger().info("LED: blue")

    def blue_flash(self, flash_freq: float = 2.0):
        self.start_flash(self.BLUE, flash_freq)
        self.node.get_logger().info(f"LED: blue flash at {flash_freq:.1f} Hz")

    def yellow(self):
        self.set_color(self.YELLOW)
        self.node.get_logger().info("LED: yellow idle")

    def red(self):
        self.set_color(self.RED)
        self.node.get_logger().info("LED: red error")

    def green(self):
        self.set_color(self.GREEN)
        self.node.get_logger().info("LED: green")

    def start_flash(self, color: tuple, flash_freq: float = 2.0):
        self.stop_flash()
        half_period = 0.5 / max(0.1, float(flash_freq))
        self.flash_color = color
        self.flash_on = True
        self._publish_color(self.flash_color)
        self.flash_timer = self.node.create_timer(half_period, self._flash_step)

    def _flash_step(self):
        self.flash_on = not self.flash_on
        self._publish_color(self.flash_color if self.flash_on else self.OFF)

    def stop_flash(self):
        if self.flash_timer is not None:
            self.flash_timer.cancel()
            self.node.destroy_timer(self.flash_timer)
            self.flash_timer = None
        self.flash_on = False

    def cleanup(self):
        self.stop_flash()
        self.off()


def main():
    import time

    import rclpy

    rclpy.init()
    node = Node("led_test_node")
    led = LEDController(node)

    try:
        led.blue()
        time.sleep(2.0)
        led.blue_flash(2.0)
        end_time = time.monotonic() + 5.0
        while time.monotonic() < end_time:
            rclpy.spin_once(node, timeout_sec=0.1)
        led.yellow()
        time.sleep(2.0)
        led.off()
    except KeyboardInterrupt:
        pass
    finally:
        led.cleanup()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
