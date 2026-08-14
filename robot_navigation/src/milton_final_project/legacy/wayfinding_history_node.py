from datetime import datetime, timezone
from pathlib import Path

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class WayfindingHistoryNode(Node):
    def __init__(self):
        super().__init__('wayfinding_history_node')

        default_log_dir = Path(__file__).resolve().parent
        self.declare_parameter('log_dir', str(default_log_dir))
        self.log_dir = Path(self.get_parameter('log_dir').value).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / 'wayfinding_input_history.csv'

        self.subscription = self.create_subscription(
            String,
            '/wayfinding/user_input',
            self.handle_user_input,
            10,
        )
        self.ensure_log_header()
        self.get_logger().info(
            f'Wayfinding history node is recording input to {self.log_file}'
        )

    def ensure_log_header(self):
        if self.log_file.exists():
            return

        self.log_file.write_text('timestamp,prompt_type,user_input\n', encoding='utf-8')

    def handle_user_input(self, msg: String):
        prompt_type, user_input = self.parse_message(msg.data)
        timestamp = datetime.now(timezone.utc).isoformat()
        sanitized_input = user_input.replace('"', '""')

        with self.log_file.open('a', encoding='utf-8') as log_handle:
            log_handle.write(f'{timestamp},{prompt_type},"{sanitized_input}"\n')

        self.get_logger().info(
            f'Recorded {prompt_type} input: {user_input or "<empty>"}'
        )

    @staticmethod
    def parse_message(data: str):
        if '|' not in data:
            return 'unknown', data

        prompt_type, user_input = data.split('|', 1)
        return prompt_type, user_input


def main(args=None):
    rclpy.init(args=args)
    node = WayfindingHistoryNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
