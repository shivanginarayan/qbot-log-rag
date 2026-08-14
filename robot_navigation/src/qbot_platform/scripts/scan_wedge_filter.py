#!/usr/bin/env python3
"""Filter fixed LaserScan wedge regions and publish a cleaned scan topic."""

from copy import deepcopy
import json
import math
from pathlib import Path

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import LaserScan

try:
    import yaml
except ImportError:
    yaml = None


def angle_diff_degrees(a, b):
    diff = a - b
    while diff > 180.0:
        diff -= 360.0
    while diff < -180.0:
        diff += 360.0
    return diff


def point_in_wedge(angle_deg, distance, wedge):
    return (
        wedge["min_range"] <= distance <= wedge["max_range"]
        and abs(angle_diff_degrees(angle_deg, wedge["angle_deg"])) <= wedge["width_deg"] / 2.0
    )


def normalize_wedges(raw_wedges):
    wedges = []
    if not isinstance(raw_wedges, list):
        return wedges

    for raw in raw_wedges:
        try:
            wedge = {
                "angle_deg": float(raw["angle_deg"]),
                "width_deg": float(raw["width_deg"]),
                "min_range": float(raw["min_range"]),
                "max_range": float(raw["max_range"]),
            }
        except (KeyError, TypeError, ValueError):
            continue

        if wedge["width_deg"] <= 0.0:
            continue
        if wedge["max_range"] <= wedge["min_range"]:
            continue
        wedges.append(wedge)
    return wedges


def load_filter_file(path):
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        if yaml is None:
            raise RuntimeError("YAML filter files require python3-yaml")
        data = yaml.safe_load(text)
    if data is None:
        data = {}
    return normalize_wedges(data.get("wedges", []))


class ScanWedgeFilter(Node):
    def __init__(self):
        super().__init__("scan_wedge_filter")
        self.declare_parameter("input_topic", "/scan")
        self.declare_parameter("output_topic", "/scan_filtered")
        self.declare_parameter(
            "filter_file",
            "/home/nvidia/857_Final_Project_Code/filters/scan_wedge_filter.json",
        )
        self.declare_parameter("reload_filter_sec", 1.0)

        self.input_topic = self.get_parameter("input_topic").value
        self.output_topic = self.get_parameter("output_topic").value
        self.filter_file = Path(self.get_parameter("filter_file").value)
        self.reload_filter_sec = float(self.get_parameter("reload_filter_sec").value)

        self.wedges = []
        self.filter_mtime = None
        self.last_error = None

        self.load_filter_if_changed(force=True)
        self.publisher = self.create_publisher(LaserScan, self.output_topic, 10)
        self.subscription = self.create_subscription(
            LaserScan,
            self.input_topic,
            self.scan_callback,
            10,
        )
        self.reload_timer = self.create_timer(self.reload_filter_sec, self.load_filter_if_changed)
        self.get_logger().info(
            f"Filtering {self.input_topic} -> {self.output_topic} using {self.filter_file}"
        )

    def load_filter_if_changed(self, force=False):
        try:
            stat = self.filter_file.stat()
        except OSError:
            if force or self.last_error != "missing":
                self.get_logger().warn(
                    f"Filter file not found: {self.filter_file}. Passing scans through unchanged."
                )
            self.wedges = []
            self.filter_mtime = None
            self.last_error = "missing"
            return

        if not force and self.filter_mtime == stat.st_mtime:
            return

        try:
            self.wedges = load_filter_file(self.filter_file)
        except Exception as exc:
            self.get_logger().warn(
                f"Could not load filter file {self.filter_file}: {exc}. "
                "Passing scans through unchanged."
            )
            self.wedges = []
            self.filter_mtime = stat.st_mtime
            self.last_error = str(exc)
            return

        self.filter_mtime = stat.st_mtime
        self.last_error = None
        self.get_logger().info(f"Loaded {len(self.wedges)} scan filter wedges.")

    def scan_callback(self, msg):
        filtered = deepcopy(msg)
        if not self.wedges:
            self.publisher.publish(filtered)
            return

        ranges = list(filtered.ranges)
        for index, distance in enumerate(ranges):
            if not math.isfinite(distance):
                continue
            if distance < msg.range_min or distance > msg.range_max:
                continue
            angle_rad = msg.angle_min + index * msg.angle_increment
            angle_deg = math.degrees(angle_rad)
            if any(point_in_wedge(angle_deg, distance, wedge) for wedge in self.wedges):
                ranges[index] = math.inf

        filtered.ranges = ranges
        self.publisher.publish(filtered)


def main():
    rclpy.init()
    node = ScanWedgeFilter()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
