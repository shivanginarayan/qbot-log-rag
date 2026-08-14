import shutil
import subprocess

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class SpeechNode(Node):
    def __init__(self):
        super().__init__('speech_node')

        self.declare_parameter('message_topic', '/robot/message')
        self.declare_parameter('display_status_topic', '/face/status_message')
        self.declare_parameter('speech_command', '')
        self.declare_parameter('voice_rate', 150)
        self.declare_parameter('interrupt_previous', True)
        self.declare_parameter('wait_for_completion', True)
        self.declare_parameter('repeat_suppression_sec', 2.0)

        message_topic = self.get_parameter('message_topic').value
        display_status_topic = self.get_parameter('display_status_topic').value
        self.voice_rate = int(self.get_parameter('voice_rate').value)
        self.interrupt_previous = bool(
            self.get_parameter('interrupt_previous').value
        )
        self.wait_for_completion = bool(
            self.get_parameter('wait_for_completion').value
        )
        self.repeat_suppression_sec = float(
            self.get_parameter('repeat_suppression_sec').value
        )
        self.speech_command = self.resolve_speech_command(
            self.get_parameter('speech_command').value
        )
        self.speech_process = None
        self.last_spoken_text = None
        self.last_spoken_at = None

        self.message_subscription = self.create_subscription(
            String,
            message_topic,
            self.message_callback,
            10,
        )
        self.display_status_subscription = self.create_subscription(
            String,
            display_status_topic,
            self.message_callback,
            10,
        )
        self.get_logger().info(
            f'Speech node listening on: {message_topic}, {display_status_topic}'
        )
        if self.speech_command:
            self.get_logger().info(f'Speaking with: {self.speech_command}')
        else:
            self.get_logger().warning(
                'No text-to-speech command found. Install speech-dispatcher or espeak.'
            )

    def resolve_speech_command(self, configured_command: str):
        configured_command = configured_command.strip()
        if configured_command:
            if shutil.which(configured_command):
                return configured_command
            self.get_logger().warning(
                f'Speech command {configured_command!r} was not found.'
            )

        for command in ('spd-say', 'espeak', 'espeak-ng'):
            if shutil.which(command):
                return command

        return None

    def message_callback(self, msg: String):
        text = msg.data.strip()
        if text:
            if self.is_recent_repeat(text):
                return

            self.last_spoken_text = text
            self.last_spoken_at = self.get_clock().now()
            self.get_logger().info(f'Message received: {text}')
            self.speak(text)

    def is_recent_repeat(self, text: str) -> bool:
        if text != self.last_spoken_text or self.last_spoken_at is None:
            return False

        elapsed = (self.get_clock().now() - self.last_spoken_at).nanoseconds / 1e9
        return elapsed <= self.repeat_suppression_sec

    def build_speech_command(self, text: str):
        if self.speech_command == 'spd-say':
            command = [
                self.speech_command,
                '--rate',
                str(self.voice_rate),
            ]
            if self.wait_for_completion:
                command.append('--wait')
            command.append(text)
            return command

        if self.speech_command in ('espeak', 'espeak-ng'):
            return [
                self.speech_command,
                '-s',
                str(self.voice_rate),
                text,
            ]

        return [self.speech_command, text]

    def stop_previous_speech(self):
        if self.speech_command == 'spd-say':
            subprocess.run(
                [self.speech_command, '--cancel'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )

        if self.speech_process is None:
            return

        if self.speech_process.poll() is None:
            self.speech_process.terminate()

        self.speech_process = None

    def speak(self, text: str):
        if not self.speech_command:
            return

        if self.interrupt_previous:
            self.stop_previous_speech()

        try:
            self.speech_process = subprocess.Popen(
                self.build_speech_command(text),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            self.get_logger().warning(f'Failed to speak text: {exc}')

    def destroy_node(self):
        self.stop_previous_speech()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = SpeechNode()

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
