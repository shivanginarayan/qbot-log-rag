import argparse
import math
import sqlite3
import time

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan


# ---------------------------------------------------------
# Distance configuration
# ---------------------------------------------------------

CRITICAL_DISTANCE = 0.35
NEAR_DISTANCE = 0.75
CAUTION_DISTANCE = 1.50

DISTANCE_BIN_SIZE = 0.10

# A bin must be crossed by an extra 2 cm before
# we consider it a real change.
BIN_HYSTERESIS = 0.02


# ---------------------------------------------------------
# Distance helpers
# ---------------------------------------------------------

def distance_band(distance):
    if distance is None:
        return "no_valid_return"

    if distance < CRITICAL_DISTANCE:
        return "critical"

    if distance < NEAR_DISTANCE:
        return "near"

    if distance < CAUTION_DISTANCE:
        return "caution"

    return "clear"


def raw_distance_bin(distance):
    if distance is None:
        return None

    return int(distance / DISTANCE_BIN_SIZE)


def stable_distance_bin(previous_bin, distance):
    """
    Keep the previous bin while the reading is close
    to the boundary.

    Example:

        previous bin = 11
        nominal range = 1.10 - 1.20 m

        reading 1.205 -> stay in bin 11
        reading 1.215 -> stay in bin 11
        reading 1.225 -> move to bin 12
    """

    if distance is None:
        return None

    new_bin = raw_distance_bin(distance)

    if previous_bin is None:
        return new_bin

    if new_bin == previous_bin:
        return previous_bin

    lower_boundary = previous_bin * DISTANCE_BIN_SIZE
    upper_boundary = (previous_bin + 1) * DISTANCE_BIN_SIZE

    # Moving farther away
    if new_bin > previous_bin:
        if distance >= upper_boundary + BIN_HYSTERESIS:
            return new_bin

        return previous_bin

    # Moving closer
    if new_bin < previous_bin:
        if distance < lower_boundary - BIN_HYSTERESIS:
            return new_bin

        return previous_bin

    return previous_bin


def sector_min(values, range_min, range_max):
    valid = [
        value
        for value in values
        if math.isfinite(value)
        and value > 0.0
        and value >= range_min
        and value <= range_max
    ]

    if not valid:
        return None

    return min(valid)


# ---------------------------------------------------------
# LiDAR logger
# ---------------------------------------------------------

class LidarLogger(Node):

    def __init__(self, db_path, session_id, topic):
        super().__init__("lidar_logger")

        self.db_path = db_path
        self.session_id = session_id
        self.topic = topic

        self.conn = sqlite3.connect(self.db_path)

        self.current_summary = None
        self.current_interval_id = None

        self.subscription = self.create_subscription(
            LaserScan,
            self.topic,
            self.scan_callback,
            10,
        )

        self.get_logger().info(
            f"Logging LiDAR summaries from {self.topic} "
            f"for session {self.session_id}"
        )

    # -----------------------------------------------------

    def scan_callback(self, msg):
        now_ns = time.time_ns()

        ranges = list(msg.ranges)

        zero_count = sum(
            1
            for value in ranges
            if value == 0.0
        )

        inf_count = sum(
            1
            for value in ranges
            if math.isinf(value)
        )

        valid_indices = [
            i
            for i, value in enumerate(ranges)
            if math.isfinite(value)
            and value > 0.0
            and value >= msg.range_min
            and value <= msg.range_max
        ]

        valid_count = len(valid_indices)

        # -------------------------------------------------
        # Closest point
        # -------------------------------------------------

        if valid_indices:
            closest_index = min(
                valid_indices,
                key=lambda i: ranges[i],
            )

            closest_distance = ranges[closest_index]

            closest_angle = (
                msg.angle_min
                + closest_index * msg.angle_increment
            )

        else:
            closest_distance = None
            closest_angle = None

        # -------------------------------------------------
        # Divide scan into four sectors
        # -------------------------------------------------

        front = []
        left = []
        right = []
        rear = []

        for i, value in enumerate(ranges):

            angle = (
                msg.angle_min
                + i * msg.angle_increment
            )

            # Normalize angle to [-pi, pi]
            angle = math.atan2(
                math.sin(angle),
                math.cos(angle),
            )

            # Front = +/- 45 degrees
            if -math.pi / 4 <= angle <= math.pi / 4:
                front.append(value)

            # Left
            elif math.pi / 4 < angle < 3 * math.pi / 4:
                left.append(value)

            # Right
            elif -3 * math.pi / 4 < angle < -math.pi / 4:
                right.append(value)

            # Rear
            else:
                rear.append(value)

        front_min = sector_min(
            front,
            msg.range_min,
            msg.range_max,
        )

        left_min = sector_min(
            left,
            msg.range_min,
            msg.range_max,
        )

        right_min = sector_min(
            right,
            msg.range_min,
            msg.range_max,
        )

        rear_min = sector_min(
            rear,
            msg.range_min,
            msg.range_max,
        )

        # -------------------------------------------------
        # First scan: no previous bins exist
        # -------------------------------------------------

        if self.current_summary is None:

            closest_bin = raw_distance_bin(
                closest_distance
            )

            front_bin = raw_distance_bin(
                front_min
            )

            left_bin = raw_distance_bin(
                left_min
            )

            right_bin = raw_distance_bin(
                right_min
            )

            rear_bin = raw_distance_bin(
                rear_min
            )

        # -------------------------------------------------
        # Later scans: use hysteresis
        # -------------------------------------------------

        else:

            closest_bin = stable_distance_bin(
                self.current_summary["closest_bin"],
                closest_distance,
            )

            front_bin = stable_distance_bin(
                self.current_summary["front_bin"],
                front_min,
            )

            left_bin = stable_distance_bin(
                self.current_summary["left_bin"],
                left_min,
            )

            right_bin = stable_distance_bin(
                self.current_summary["right_bin"],
                right_min,
            )

            rear_bin = stable_distance_bin(
                self.current_summary["rear_bin"],
                rear_min,
            )

        # -------------------------------------------------
        # Construct structured summary
        # -------------------------------------------------

        summary = {
            "closest_distance": closest_distance,
            "closest_angle": closest_angle,

            "front_min": front_min,
            "left_min": left_min,
            "right_min": right_min,
            "rear_min": rear_min,

            "distance_band":
                distance_band(closest_distance),

            "front_band":
                distance_band(front_min),

            "left_band":
                distance_band(left_min),

            "right_band":
                distance_band(right_min),

            "rear_band":
                distance_band(rear_min),

            "closest_bin": closest_bin,
            "front_bin": front_bin,
            "left_bin": left_bin,
            "right_bin": right_bin,
            "rear_bin": rear_bin,

            "zero_count": zero_count,
            "inf_count": inf_count,
            "valid_count": valid_count,
        }

        # -------------------------------------------------
        # First interval
        # -------------------------------------------------

        if self.current_summary is None:

            self.start_interval(
                now_ns,
                summary,
                previous_interval_id=None,
            )

            return

        # -------------------------------------------------
        # Determine whether meaningful state changed
        # -------------------------------------------------

        same_state = (
            self.current_summary["closest_bin"]
            == summary["closest_bin"]

            and self.current_summary["front_bin"]
            == summary["front_bin"]

            and self.current_summary["left_bin"]
            == summary["left_bin"]

            and self.current_summary["right_bin"]
            == summary["right_bin"]

            and self.current_summary["rear_bin"]
            == summary["rear_bin"]

            and self.current_summary["distance_band"]
            == summary["distance_band"]

            and self.current_summary["front_band"]
            == summary["front_band"]

            and self.current_summary["left_band"]
            == summary["left_band"]

            and self.current_summary["right_band"]
            == summary["right_band"]

            and self.current_summary["rear_band"]
            == summary["rear_band"]
        )

        # -------------------------------------------------
        # Same state -> extend interval
        # -------------------------------------------------

        if same_state:

            self.conn.execute(
                """
                UPDATE lidar_summary_intervals

                SET
                    ended_at_ns = ?,

                    sample_count =
                        sample_count + 1,

                    closest_distance = ?,
                    closest_angle = ?,

                    front_min = ?,
                    left_min = ?,
                    right_min = ?,
                    rear_min = ?,

                    zero_count = ?,
                    inf_count = ?,
                    valid_count = ?

                WHERE lidar_id = ?
                """,
                (
                    now_ns,

                    summary["closest_distance"],
                    summary["closest_angle"],

                    summary["front_min"],
                    summary["left_min"],
                    summary["right_min"],
                    summary["rear_min"],

                    summary["zero_count"],
                    summary["inf_count"],
                    summary["valid_count"],

                    self.current_interval_id,
                ),
            )

            self.conn.commit()

            # Keep latest raw values while preserving
            # stable bins.
            self.current_summary = summary

            return

        # -------------------------------------------------
        # Meaningful state changed -> new interval
        # -------------------------------------------------

        previous_id = self.current_interval_id

        self.start_interval(
            now_ns,
            summary,
            previous_interval_id=previous_id,
        )

        self.get_logger().info(
            "LiDAR state changed | "
            f"band={summary['distance_band']} | "
            f"closest={summary['closest_distance']:.3f} | "
            f"bins="
            f"{summary['closest_bin']}/"
            f"{summary['front_bin']}/"
            f"{summary['left_bin']}/"
            f"{summary['right_bin']}/"
            f"{summary['rear_bin']}"
        )

    # -----------------------------------------------------

    def start_interval(
        self,
        now_ns,
        summary,
        previous_interval_id,
    ):

        cursor = self.conn.execute(
            """
            INSERT INTO lidar_summary_intervals (
                session_id,

                started_at_ns,
                ended_at_ns,

                source_topic,

                closest_distance,
                closest_angle,

                front_min,
                left_min,
                right_min,
                rear_min,

                distance_band,
                front_band,
                left_band,
                right_band,
                rear_band,

                closest_bin,
                front_bin,
                left_bin,
                right_bin,
                rear_bin,

                zero_count,
                inf_count,
                valid_count,

                sample_count,

                previous_interval_id
            )

            VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?
            )
            """,
            (
                self.session_id,

                now_ns,
                now_ns,

                self.topic,

                summary["closest_distance"],
                summary["closest_angle"],

                summary["front_min"],
                summary["left_min"],
                summary["right_min"],
                summary["rear_min"],

                summary["distance_band"],
                summary["front_band"],
                summary["left_band"],
                summary["right_band"],
                summary["rear_band"],

                summary["closest_bin"],
                summary["front_bin"],
                summary["left_bin"],
                summary["right_bin"],
                summary["rear_bin"],

                summary["zero_count"],
                summary["inf_count"],
                summary["valid_count"],

                1,

                previous_interval_id,
            ),
        )

        self.current_interval_id = (
            cursor.lastrowid
        )

        self.current_summary = summary

        self.conn.commit()

    # -----------------------------------------------------

    def destroy_node(self):

        if self.conn:
            self.conn.commit()
            self.conn.close()

        super().destroy_node()


# ---------------------------------------------------------
# Main
# ---------------------------------------------------------

def main():

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--db",
        required=True,
    )

    parser.add_argument(
        "--session-id",
        required=True,
    )

    parser.add_argument(
        "--topic",
        default="/scan_filtered",
    )

    args = parser.parse_args()

    rclpy.init()

    node = LidarLogger(
        db_path=args.db,
        session_id=args.session_id,
        topic=args.topic,
    )

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:

        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()