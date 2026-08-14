import json

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .status_qos import status_qos


class WaitingPersonGreeterNode(Node):
    def __init__(self):
        super().__init__('waiting_person_greeter_node')

        self.declare_parameter('person_target_topic', '/yolo/person_target')
        self.declare_parameter('state_topic', '/robot/stage')
        self.declare_parameter('user_input_topic', '/wayfinding/user_input')
        self.declare_parameter('expression_topic', '/face/expression')
        self.declare_parameter('message_topic', '/robot/message')
        self.declare_parameter('person_timeout_sec', 0.8)
        self.declare_parameter('idle_search_delay_sec', 90.0)
        self.declare_parameter('stable_detection_sec', 0.2)
        self.declare_parameter('greeting_cooldown_sec', 12.0)
        self.declare_parameter(
            'greeting_message',
            'Hello there. I can help you find a room or person.',
        )
        self.declare_parameter('greeting_expression', 'happy')

        person_target_topic = self.get_parameter('person_target_topic').value
        state_topic = self.get_parameter('state_topic').value
        user_input_topic = self.get_parameter('user_input_topic').value
        expression_topic = self.get_parameter('expression_topic').value
        message_topic = self.get_parameter('message_topic').value

        self.person_timeout_sec = float(self.get_parameter('person_timeout_sec').value)
        self.idle_search_delay_sec = float(
            self.get_parameter('idle_search_delay_sec').value
        )
        self.stable_detection_sec = float(
            self.get_parameter('stable_detection_sec').value
        )
        self.greeting_cooldown_sec = float(
            self.get_parameter('greeting_cooldown_sec').value
        )
        self.greeting_message = self.get_parameter('greeting_message').value
        self.greeting_expression = self.get_parameter('greeting_expression').value

        self.current_state = 'waiting'
        self.latest_person_target = None
        self.latest_person_time = None
        self.person_seen_since = None
        self.last_greet_time = None
        self.last_user_input_time = self.get_clock().now()

        self.person_target_sub = self.create_subscription(
            String,
            person_target_topic,
            self.person_target_callback,
            10,
        )
        self.state_sub = self.create_subscription(
            String,
            state_topic,
            self.state_callback,
            status_qos(),
        )
        self.user_input_sub = self.create_subscription(
            String,
            user_input_topic,
            self.user_input_callback,
            10,
        )
        self.expression_pub = self.create_publisher(String, expression_topic, 10)
        self.message_pub = self.create_publisher(String, message_topic, 10)

        self.timer = self.create_timer(0.1, self.control_loop)
        self.get_logger().info(f'Subscribed to person target topic: {person_target_topic}')
        self.get_logger().info(f'Subscribed to state topic: {state_topic}')
        self.get_logger().info(f'Subscribed to user input topic: {user_input_topic}')
        self.get_logger().info('Camera-only greeter ready; no cmd_vel commands will be published.')

    def state_callback(self, msg: String):
        self.current_state = msg.data.strip() or 'waiting'
        if self.current_state != 'waiting':
            self.person_seen_since = None
            self.latest_person_target = None
            self.latest_person_time = None

    def user_input_callback(self, msg: String):
        if msg.data.strip():
            self.last_user_input_time = self.get_clock().now()
            self.person_seen_since = None

    def person_target_callback(self, msg: String):
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warning('Ignoring invalid person target payload.')
            return

        self.latest_person_target = payload
        self.latest_person_time = self.get_clock().now()
        if payload.get('seen', False):
            if self.person_seen_since is None:
                self.person_seen_since = self.latest_person_time
        else:
            self.person_seen_since = None

    def payload_is_fresh(self, payload, payload_time, timeout_sec: float) -> bool:
        if payload is None or payload_time is None:
            return False
        age_sec = (self.get_clock().now() - payload_time).nanoseconds / 1e9
        return age_sec <= timeout_sec

    def greeting_ready(self) -> bool:
        if self.last_greet_time is None:
            return True
        elapsed = (self.get_clock().now() - self.last_greet_time).nanoseconds / 1e9
        return elapsed >= self.greeting_cooldown_sec

    def idle_search_ready(self) -> bool:
        if self.current_state != 'waiting':
            return False

        idle_sec = (
            self.get_clock().now() - self.last_user_input_time
        ).nanoseconds / 1e9
        return idle_sec >= self.idle_search_delay_sec

    def publish_greeting(self):
        expression = String()
        expression.data = self.greeting_expression
        self.expression_pub.publish(expression)

        message = String()
        message.data = self.greeting_message
        self.message_pub.publish(message)
        self.last_greet_time = self.get_clock().now()

    def current_person_target(self):
        if not self.payload_is_fresh(
            self.latest_person_target,
            self.latest_person_time,
            self.person_timeout_sec,
        ):
            return None
        if not self.latest_person_target.get('seen', False):
            return None
        return self.latest_person_target

    def control_loop(self):
        if self.current_state != 'waiting':
            return

        if not self.idle_search_ready():
            self.person_seen_since = None
            return

        person_target = self.current_person_target()
        if person_target is not None:
            if self.person_seen_since is None:
                self.person_seen_since = self.get_clock().now()

            stable_sec = (
                self.get_clock().now() - self.person_seen_since
            ).nanoseconds / 1e9

            if stable_sec < self.stable_detection_sec:
                return

            if self.greeting_ready():
                self.publish_greeting()
            return

        self.person_seen_since = None


def main(args=None):
    rclpy.init(args=args)
    node = WaitingPersonGreeterNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
