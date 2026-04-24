import json
from datetime import datetime
import rclpy
from rclpy.node import Node
from rcl_interfaces.msg import Log


class RosoutCollector(Node):
    def __init__(self):
        super().__init__("rosout_collector")

        self.output_file = "data/processed/live_rosout_logs.jsonl"

        self.subscription = self.create_subscription(
            Log,
            "/rosout",
            self.rosout_callback,
            10
        )

        self.get_logger().info("ROSOUT collector started.")

    def rosout_callback(self, msg):
        log_record = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "node": msg.name,
            "topic": "/rosout",
            "severity": str(msg.level),
            "message": msg.msg
        }

        with open(self.output_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_record) + "\n")

        print(log_record)


def main():
    rclpy.init()
    node = RosoutCollector()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
