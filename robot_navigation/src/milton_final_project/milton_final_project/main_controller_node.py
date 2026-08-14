from concurrent.futures import ThreadPoolExecutor
import json

from action_msgs.msg import GoalStatus
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .robot_interpreter import RobotInterpreter
from .seic_directory import SeicDirectory
from .status_qos import status_qos


class MainControllerNode(Node):
    def __init__(self):
        super().__init__('main_controller_node')

        self.declare_parameter('user_input_topic', '/wayfinding/user_input')
        self.declare_parameter('message_topic', '/robot/message')
        self.declare_parameter('display_status_topic', '/face/status_message')
        self.declare_parameter('expression_topic', '/face/expression')
        self.declare_parameter('stage_topic', '/robot/stage')
        self.declare_parameter('destination_label_topic', '/label')
        self.declare_parameter('navigation_status_topic', '/robot/navigation_status')
        self.declare_parameter('return_label', '__return_breadcrumbs__')
        self.declare_parameter('return_spin_label', '__full_spin__')
        self.declare_parameter('return_staging_label', '__return_staging__')
        self.declare_parameter('use_return_spin', False)
        self.declare_parameter('use_return_staging', False)
        self.declare_parameter('arrival_pause_sec', 10.0)
        self.declare_parameter('response_duration_sec', 10.0)
        self.declare_parameter('confirmation_timeout_sec', 60.0)
        self.declare_parameter('navigation_timeout_sec', 20.0)
        self.declare_parameter(
            'waiting_message',
            'I am the SEIC navigation robot. Please enter the person or room you are trying to find.',
        )

        self.response_duration_sec = float(
            self.get_parameter('response_duration_sec').value
        )
        self.confirmation_timeout_sec = float(
            self.get_parameter('confirmation_timeout_sec').value
        )
        self.navigation_timeout_sec = float(
            self.get_parameter('navigation_timeout_sec').value
        )
        self.arrival_pause_sec = float(
            self.get_parameter('arrival_pause_sec').value
        )
        self.waiting_message = self.get_parameter('waiting_message').value
        self.return_label = self.get_parameter('return_label').value
        self.return_spin_label = self.get_parameter('return_spin_label').value
        self.return_staging_label = self.get_parameter('return_staging_label').value
        self.use_return_spin = bool(self.get_parameter('use_return_spin').value)
        self.use_return_staging = bool(self.get_parameter('use_return_staging').value)

        self.stage = 'waiting'
        self.pending_future = None
        self.pending_destination_label = None
        self.state_timeout_at = None
        self.last_status_publish_at = None
        self.last_stage = None
        self.assistant_pool = ThreadPoolExecutor(max_workers=1)
        self.interpreter = RobotInterpreter()
        self.directory = SeicDirectory()
        self.status_qos = status_qos()

        user_input_topic = self.get_parameter('user_input_topic').value
        self.user_input_sub = self.create_subscription(
            String,
            user_input_topic,
            self.user_input_callback,
            10,
        )
        self.message_pub = self.create_publisher(
            String,
            self.get_parameter('message_topic').value,
            10,
        )
        self.display_status_pub = self.create_publisher(
            String,
            self.get_parameter('display_status_topic').value,
            10,
        )
        self.expression_pub = self.create_publisher(
            String,
            self.get_parameter('expression_topic').value,
            10,
        )
        self.stage_pub = self.create_publisher(
            String,
            self.get_parameter('stage_topic').value,
            self.status_qos,
        )
        self.destination_label_pub = self.create_publisher(
            String,
            self.get_parameter('destination_label_topic').value,
            10,
        )
        self.navigation_status_sub = self.create_subscription(
            String,
            self.get_parameter('navigation_status_topic').value,
            self.navigation_status_callback,
            10,
        )

        self.timer = self.create_timer(0.1, self.update)
        self.startup_timer = self.create_timer(1.0, self.publish_startup_state)
        self.get_logger().info(f'Main controller listening on: {user_input_topic}')

    def publish_string(self, publisher, text: str):
        msg = String()
        msg.data = text
        publisher.publish(msg)

    def publish_expression(self, expression: str):
        self.publish_string(self.expression_pub, expression)

    def publish_message(self, message: str):
        self.publish_string(self.message_pub, message)

    def publish_display_status(self, message: str):
        self.publish_string(self.display_status_pub, message)

    def publish_stage(self, stage: str, force: bool = False):
        normalized_stage = stage.strip().lower() or 'waiting'
        self.stage = normalized_stage
        if not force and normalized_stage == self.last_stage:
            return

        self.publish_string(self.stage_pub, normalized_stage)
        self.last_status_publish_at = self.now_seconds()

        if normalized_stage != self.last_stage:
            self.last_stage = normalized_stage
            self.get_logger().info(f'Main controller stage changed to: {normalized_stage}')

    def publish_startup_state(self):
        self.startup_timer.cancel()
        self.publish_stage('waiting')
        self.publish_expression('neutral')
        self.publish_message(self.waiting_message)

    def reset_to_waiting(self):
        self.pending_destination_label = None
        self.state_timeout_at = None
        self.publish_stage('waiting')
        self.publish_expression('neutral')
        self.publish_message(self.waiting_message)

    def handle_destination_arrival(self):
        self.publish_stage('arrived')
        self.publish_expression('happy')
        self.publish_message('Thank you for using my services!')
        self.state_timeout_at = self.now_seconds() + self.arrival_pause_sec

    def start_return_to_origin(self):
        self.publish_stage('returning')
        self.publish_expression('neutral')
        self.publish_message('Returning to my starting point.')
        self.state_timeout_at = None
        self.publish_string(self.destination_label_pub, self.return_label)

    def start_return_staging(self):
        self.publish_stage('return_staging')
        self.publish_expression('neutral')
        self.publish_message('Moving to a clearer spot before returning.')
        self.state_timeout_at = None
        self.publish_string(self.destination_label_pub, self.return_staging_label)

    def start_return_spin(self):
        self.publish_stage('return_spin')
        self.publish_expression('neutral')
        self.publish_message('Spinning once to scan for a clearer path.')
        self.state_timeout_at = None
        self.publish_string(self.destination_label_pub, self.return_spin_label)

    def start_return_after_spin(self):
        if self.use_return_staging:
            self.start_return_staging()
        else:
            self.start_return_to_origin()

    def handle_navigation_failure(self, status: int):
        self.pending_destination_label = None
        self.publish_stage('waiting')
        self.publish_expression('confused')
        if status == GoalStatus.STATUS_CANCELED:
            self.publish_message('Navigation was canceled.')
        else:
            self.publish_message('I could not reach the destination.')
        self.state_timeout_at = self.now_seconds() + self.response_duration_sec

    def navigation_status_callback(self, msg: String):
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            self.get_logger().warning(f'Navigation status decode failed: {exc!r}')
            return

        status = int(payload.get('status', GoalStatus.STATUS_UNKNOWN))
        if self.stage == 'navigation':
            if status == GoalStatus.STATUS_SUCCEEDED:
                self.handle_destination_arrival()
            else:
                self.handle_navigation_failure(status)
            return

        if self.stage == 'returning':
            if status == GoalStatus.STATUS_SUCCEEDED:
                self.reset_to_waiting()
            else:
                self.handle_navigation_failure(status)
            return

        if self.stage == 'return_staging':
            if status == GoalStatus.STATUS_SUCCEEDED:
                self.start_return_to_origin()
            else:
                self.get_logger().warning(
                    f'Return staging failed with status {status}; trying origin directly.'
                )
                self.start_return_to_origin()
            return

        if self.stage == 'return_spin':
            if status != GoalStatus.STATUS_SUCCEEDED:
                self.get_logger().warning(
                    f'Return spin failed with status {status}; continuing return anyway.'
                )
            self.start_return_after_spin()

    def user_input_callback(self, msg: String):
        prompt_type, user_text = self.parse_user_input(msg.data)
        user_text = user_text.strip()

        if not user_text:
            self.reset_to_waiting()
            return

        if self.stage in {
            'navigation',
            'arrived',
            'return_spin',
            'return_staging',
            'returning',
        }:
            self.reset_to_waiting()
            return

        if prompt_type == 'confirmation' or self.stage == 'confirmation':
            self.handle_confirmation_response(user_text)
            return

        self.handle_destination_request(user_text)

    def parse_user_input(self, data: str):
        if '|' not in data:
            return 'destination', data
        prompt_type, user_text = data.split('|', 1)
        return prompt_type.strip().lower(), user_text

    def handle_destination_request(self, destination: str):
        if self.interpreter.is_conversation_end(destination):
            ending = self.interpreter.ending_response(destination)
            self.publish_expression(ending['expression'])
            self.publish_message(ending['message'])
            self.state_timeout_at = self.now_seconds() + self.response_duration_sec
            return

        if self.pending_future is not None and not self.pending_future.done():
            self.publish_expression('confused')
            self.publish_message('I am still processing the last request.')
            return

        self.publish_stage('lookup')
        self.publish_expression('confused')
        self.publish_display_status(f'Looking up {destination} in the SEIC directory.')
        self.pending_future = self.assistant_pool.submit(
            self.lookup_destination,
            destination,
        )

    def lookup_destination(self, destination: str):
        target = self.interpreter.extract_target(destination)
        match = self.directory.find_best_match(target or destination)
        base_message = self.directory.build_response(match)
        expression = self.directory.expression_for_match(match)
        if match.entry is None:
            return {
                'message': base_message,
                'expression': expression,
                'stage': 'waiting',
                'destination_label': None,
            }

        destination_label = (
            match.entry.location if match.entry.kind == 'person' else match.entry.title
        )
        message = (
            f'{base_message} Do you need help getting to {destination_label}? '
            'Please type yes or no.'
        )
        return {
            'message': message,
            'expression': expression,
            'stage': 'confirmation',
            'destination_label': destination_label,
        }

    def handle_lookup_reply(self, reply):
        self.pending_destination_label = reply['destination_label']
        self.publish_expression(reply['expression'])
        self.publish_message(reply['message'])
        self.publish_stage(reply['stage'])

        if reply['stage'] == 'confirmation':
            self.state_timeout_at = self.now_seconds() + self.confirmation_timeout_sec
        else:
            self.state_timeout_at = self.now_seconds() + self.response_duration_sec

    def handle_confirmation_response(self, response: str):
        normalized = response.strip().lower()
        yes_tokens = {'yes', 'y', 'yeah', 'yep', 'sure', 'ok', 'okay'}
        no_tokens = {'no', 'n', 'nope', 'nah'}

        if normalized in yes_tokens:
            if self.pending_destination_label:
                self.publish_string(
                    self.destination_label_pub,
                    self.pending_destination_label,
                )
            self.publish_stage('navigation')
            self.publish_expression('happy')
            self.publish_message('Going to navigation mode.')
            self.state_timeout_at = None
            return

        if normalized in no_tokens:
            self.pending_destination_label = None
            self.publish_stage('waiting')
            self.publish_expression('neutral')
            self.publish_message(
                'Okay. If you need anything else, ask me about another room or person.'
            )
            self.state_timeout_at = self.now_seconds() + self.response_duration_sec
            return

        destination_label = self.pending_destination_label or 'that location'
        self.publish_stage('confirmation')
        self.publish_expression('confused')
        self.publish_message(
            f'Please answer yes or no. Do you need help getting to {destination_label}?'
        )
        self.state_timeout_at = self.now_seconds() + self.confirmation_timeout_sec

    def now_seconds(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def update(self):
        now = self.now_seconds()
        if (
            self.last_status_publish_at is None
            or now - self.last_status_publish_at >= 1.0
        ):
            self.publish_stage(self.stage, force=True)

        if self.pending_future is not None and self.pending_future.done():
            try:
                self.handle_lookup_reply(self.pending_future.result())
            except Exception as exc:
                self.get_logger().warning(f'Destination lookup failed: {exc!r}')
                self.publish_stage('waiting')
                self.publish_expression('confused')
                self.publish_message(
                    'Sorry, I had trouble thinking of a reply just now.'
                )
                self.state_timeout_at = self.now_seconds() + self.response_duration_sec
            finally:
                self.pending_future = None

        if self.state_timeout_at is not None and now >= self.state_timeout_at:
            if self.stage == 'arrived':
                if self.use_return_spin:
                    self.start_return_spin()
                else:
                    self.start_return_after_spin()
                return
            self.reset_to_waiting()

    def destroy_node(self):
        self.assistant_pool.shutdown(wait=False)
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = MainControllerNode()

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
