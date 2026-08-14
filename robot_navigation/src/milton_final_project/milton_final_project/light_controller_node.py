import rclpy
from rclpy.node import Node
from std_msgs.msg import ColorRGBA
from std_msgs.msg import Float32MultiArray
from std_msgs.msg import String

from .status_qos import status_qos


class LightControllerNode(Node):
    def __init__(self):
        super().__init__('light_controller_node')

        self.declare_parameter('state_topic', '/robot/stage')
        self.declare_parameter('led_topic', '/qbot_led_strip')
        self.declare_parameter('qbot_led_topic', '/qbot_platform/led')
        self.declare_parameter('flash_period_sec', 0.5)

        state_topic = self.get_parameter('state_topic').value
        led_topic = self.get_parameter('led_topic').value
        qbot_led_topic = self.get_parameter('qbot_led_topic').value
        self.flash_period_sec = float(self.get_parameter('flash_period_sec').value)

        self.current_state = 'waiting'
        self.last_flash_toggle_at = self.now_seconds()
        self.flash_on = True

        self.color_pub = self.create_publisher(ColorRGBA, led_topic, 10)
        self.qbot_color_pub = self.create_publisher(Float32MultiArray, qbot_led_topic, 10)
        self.state_sub = self.create_subscription(
            String,
            state_topic,
            self.state_callback,
            status_qos(),
        )
        self.timer = self.create_timer(0.1, self.update_led)

        self.get_logger().info(f'Listening for robot stage on: {state_topic}')
        self.get_logger().info(f'Publishing ColorRGBA LEDs to: {led_topic}')
        self.get_logger().info(f'Publishing QBot LED arrays to: {qbot_led_topic}')
        self.get_logger().info('Light state changed to: waiting')

    def now_seconds(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def state_callback(self, msg: String):
        state = msg.data.strip().lower()
        if not state:
            return

        if state != self.current_state:
            self.current_state = state
            self.last_flash_toggle_at = self.now_seconds()
            self.flash_on = True
            self.get_logger().info(f'LED state changed to: {self.current_state}')
            self.update_led()

    def state_to_color(self):
        if self.current_state in {'navigation', 'returning'}:
            return (0.0, 1.0, 0.0)

        if self.current_state == 'confirmation':
            now = self.now_seconds()
            if now - self.last_flash_toggle_at >= self.flash_period_sec:
                self.flash_on = not self.flash_on
                self.last_flash_toggle_at = now
            return (0.0, 1.0, 0.0) if self.flash_on else (0.0, 0.0, 0.0)

        return (0.0, 0.0, 1.0)

    def publish_color(self, red: float, green: float, blue: float):
        msg = ColorRGBA()
        msg.r = red
        msg.g = green
        msg.b = blue
        msg.a = 1.0
        self.color_pub.publish(msg)

        qbot_msg = Float32MultiArray()
        qbot_msg.data = [red, green, blue]
        self.qbot_color_pub.publish(qbot_msg)

    def update_led(self):
        red, green, blue = self.state_to_color()
        self.publish_color(red, green, blue)


def main(args=None):
    rclpy.init(args=args)
    node = LightControllerNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()
        else:
            node.destroy_node()


if __name__ == '__main__':
    main()
