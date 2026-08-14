import json
import math

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan
from std_msgs.msg import String


class LidarPersonTrackerNode(Node):
    def __init__(self):
        super().__init__('lidar_person_tracker_node')

        self.declare_parameter('scan_topic', '/scan')
        self.declare_parameter('motion_topic', '/lidar/motion_target')
        self.declare_parameter('state_topic', '/robot/light_state')
        self.declare_parameter('min_range_m', 0.25)
        self.declare_parameter('max_range_m', 5.0)
        self.declare_parameter('motion_delta_m', 0.18)
        self.declare_parameter('window_size', 15)
        self.declare_parameter('min_motion_hits', 4)

        self.min_range_m = float(self.get_parameter('min_range_m').value)
        self.max_range_m = float(self.get_parameter('max_range_m').value)
        self.motion_delta_m = float(self.get_parameter('motion_delta_m').value)
        self.window_size = int(self.get_parameter('window_size').value)
        self.min_motion_hits = int(self.get_parameter('min_motion_hits').value)

        scan_topic = self.get_parameter('scan_topic').value
        motion_topic = self.get_parameter('motion_topic').value
        state_topic = self.get_parameter('state_topic').value

        self.previous_ranges = None
        self.previous_angle_min = None
        self.previous_angle_increment = None
        self.current_state = 'waiting'

        self.scan_sub = self.create_subscription(
            LaserScan,
            scan_topic,
            self.scan_callback,
            10,
        )
        self.state_sub = self.create_subscription(
            String,
            state_topic,
            self.state_callback,
            10,
        )
        self.motion_pub = self.create_publisher(String, motion_topic, 10)

        self.get_logger().info(f'Subscribed to scan topic: {scan_topic}')
        self.get_logger().info(f'Subscribed to state topic: {state_topic}')
        self.get_logger().info(f'Publishing motion cues to: {motion_topic}')

    def publish_motion(self, payload):
        msg = String()
        msg.data = json.dumps(payload)
        self.motion_pub.publish(msg)

    def valid_range(self, value: float) -> bool:
        return math.isfinite(value) and self.min_range_m <= value <= self.max_range_m

    def state_callback(self, msg: String):
        next_state = msg.data.strip() or 'waiting'
        if next_state == self.current_state:
            return

        self.current_state = next_state
        if self.current_state != 'waiting':
            self.previous_ranges = None
            self.previous_angle_min = None
            self.previous_angle_increment = None
            self.publish_motion({'seen': False, 'reason': 'tracking_disabled'})

    def scan_callback(self, msg: LaserScan):
        if self.current_state != 'waiting':
            return

        current_ranges = list(msg.ranges)
        if self.previous_ranges is None:
            self.previous_ranges = current_ranges
            self.previous_angle_min = msg.angle_min
            self.previous_angle_increment = msg.angle_increment
            self.publish_motion({'seen': False, 'reason': 'warmup'})
            return

        if (
            len(current_ranges) != len(self.previous_ranges)
            or msg.angle_min != self.previous_angle_min
            or msg.angle_increment != self.previous_angle_increment
        ):
            self.previous_ranges = current_ranges
            self.previous_angle_min = msg.angle_min
            self.previous_angle_increment = msg.angle_increment
            self.publish_motion({'seen': False, 'reason': 'scan_layout_changed'})
            return

        motion_hits = []
        for index, current in enumerate(current_ranges):
            previous = self.previous_ranges[index]
            if not self.valid_range(current) or not self.valid_range(previous):
                continue

            delta = abs(current - previous)
            if delta < self.motion_delta_m:
                continue

            angle = msg.angle_min + (index * msg.angle_increment)
            motion_hits.append(
                {
                    'index': index,
                    'angle_rad': angle,
                    'angle_deg': math.degrees(angle),
                    'range_m': current,
                    'delta_m': delta,
                }
            )

        self.previous_ranges = current_ranges

        if not motion_hits:
            self.publish_motion({'seen': False, 'reason': 'no_motion'})
            return

        best_cluster = self.find_best_cluster(motion_hits)
        if best_cluster is None:
            self.publish_motion({'seen': False, 'reason': 'insufficient_motion'})
            return

        self.publish_motion(best_cluster)

    def find_best_cluster(self, motion_hits):
        if not motion_hits:
            return None

        best_cluster = None
        for start in range(len(motion_hits)):
            cluster = [motion_hits[start]]
            for end in range(start + 1, len(motion_hits)):
                if motion_hits[end]['index'] - cluster[-1]['index'] > self.window_size:
                    break
                cluster.append(motion_hits[end])

            if len(cluster) < self.min_motion_hits:
                continue

            avg_angle_rad = sum(item['angle_rad'] for item in cluster) / len(cluster)
            avg_range_m = sum(item['range_m'] for item in cluster) / len(cluster)
            avg_delta_m = sum(item['delta_m'] for item in cluster) / len(cluster)
            score = len(cluster) * avg_delta_m

            payload = {
                'seen': True,
                'source': 'lidar_motion',
                'angle_rad': avg_angle_rad,
                'angle_deg': math.degrees(avg_angle_rad),
                'range_m': avg_range_m,
                'motion_hits': len(cluster),
                'avg_delta_m': avg_delta_m,
                'score': score,
            }
            if best_cluster is None or payload['score'] > best_cluster['score']:
                best_cluster = payload

        if best_cluster is None:
            return None

        best_cluster.pop('score', None)
        return best_cluster


def main(args=None):
    rclpy.init(args=args)
    node = LidarPersonTrackerNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
