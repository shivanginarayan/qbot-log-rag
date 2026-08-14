from threading import Thread
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from .robot_interpreter import RobotInterpreter
from .seic_directory import SeicDirectory


class WayfindingInputNode(Node):
    def __init__(self):
        super().__init__('wayfinding_input_node')

        self.expression_pub = self.create_publisher(String, '/face/expression', 10)
        self.message_pub = self.create_publisher(String, '/face/message', 10)
        self.light_state_pub = self.create_publisher(String, '/robot/light_state', 10)
        self.user_input_pub = self.create_publisher(String, '/wayfinding/user_input', 10)
        self.running = True
        self.response_duration_sec = 10.0
        self.interpreter = RobotInterpreter()
        self.directory = SeicDirectory()

        self.publish_message(
            "Hi, I'm the navigation robot that helps you find a location "
            'or room.',
        )
        self.publish_expression('neutral')
        self.publish_light_state('waiting')

        self.input_thread = Thread(target=self.read_loop, daemon=True)
        self.input_thread.start()
        self.get_logger().info('Wayfinding input ready. Type a destination in this terminal.')

    def publish_expression(self, expression: str):
        msg = String()
        msg.data = expression
        self.expression_pub.publish(msg)

    def publish_message(self, text: str):
        msg = String()
        msg.data = text
        self.message_pub.publish(msg)

    def publish_light_state(self, state: str):
        msg = String()
        msg.data = state
        self.light_state_pub.publish(msg)

    def publish_user_input(self, prompt_type: str, text: str):
        msg = String()
        msg.data = f'{prompt_type}|{text}'
        self.user_input_pub.publish(msg)

    def read_loop(self):
        while rclpy.ok() and self.running:
            try:
                destination = input('Where would you like to go? ').strip()
            except EOFError:
                break
            except KeyboardInterrupt:
                rclpy.shutdown()
                break

            self.publish_user_input('destination', destination)

            if not destination:
                self.publish_expression('neutral')
                self.publish_message(
                    "Hi, I'm the navigation robot that helps you find a "
                    'location or room.',
                )
                self.publish_light_state('waiting')
                continue

            if self.interpreter.is_conversation_end(destination):
                ending = self.interpreter.ending_response(destination)
                self.publish_expression(ending['expression'])
                self.publish_message(ending['message'])
                time.sleep(2.0)
                self.publish_expression('neutral')
                self.publish_message(
                    "Hi, I'm the navigation robot that helps you find a location or room."
                )
                self.publish_light_state('waiting')
                continue

            target = self.interpreter.extract_target(destination)
            match = self.directory.find_best_match(target or destination)
            self.publish_expression(self.directory.expression_for_match(match))
            self.publish_message(self.directory.build_response(match))

            if match.entry is None:
                continue

            destination_label = (
                match.entry.location if match.entry.kind == 'person' else match.entry.title
            )
            self.publish_message(
                f'{self.directory.build_response(match)} Do you need help '
                f'getting to {destination_label}?'
            )
            self.publish_light_state('confirmation')

            try:
                answer = input('Do you need help getting there? (yes/no) ').strip().lower()
            except EOFError:
                break
            except KeyboardInterrupt:
                rclpy.shutdown()
                break

            self.publish_user_input('confirmation', answer)

            if answer in {'yes', 'y', 'yeah', 'yep', 'sure', 'ok', 'okay'}:
                self.publish_expression('happy')
                self.publish_message(
                    f"Let's go. Going to navigation mode for {destination_label}."
                )
                self.publish_light_state('navigation')
                time.sleep(self.response_duration_sec)
                self.publish_expression('neutral')
                self.publish_message(
                    "Hi, I'm the navigation robot that helps you find a location or room."
                )
                self.publish_light_state('waiting')
                continue

            self.publish_expression('neutral')
            self.publish_message(
                'Okay. If you need anything else, ask me about another room or person.'
            )
            self.publish_light_state('waiting')
            time.sleep(2.0)
            self.publish_expression('neutral')
            self.publish_message(
                "Hi, I'm the navigation robot that helps you find a location or room."
            )
            self.publish_light_state('waiting')

    def destroy_node(self):
        self.running = False
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = WayfindingInputNode()

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
