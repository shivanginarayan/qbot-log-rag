#!/usr/bin/env python3

import argparse
import json
import sqlite3
import time

import rclpy
from rclpy.node import Node
from std_msgs.msg import String


class TaskEventLogger(Node):
    def __init__(self, db_path, session_id):
        super().__init__("task_event_logger")

        self.db_path = db_path
        self.session_id = session_id

        self.conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            timeout=30,
        )
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        self.conn.execute("PRAGMA foreign_keys = ON")

        self.label_sub = self.create_subscription(
            String,
            "/label",
            self.label_callback,
            10,
        )

        self.nav_status_sub = self.create_subscription(
            String,
            "/robot/navigation_status",
            self.navigation_status_callback,
            10,
        )

        self.get_logger().info(
            f"Logging task events for session {session_id}"
        )

    def insert_event(
        self,
        *,
        source_topic,
        event_type,
        map_name=None,
        label_id=None,
        label_name=None,
        task_type=None,
        status=None,
        payload=None,
    ):
        event_time_ns = time.time_ns()

        payload_json = None

        if payload is not None:
            payload_json = json.dumps(
                payload,
                sort_keys=True,
            )

        self.conn.execute(
            """
            INSERT INTO task_events (
                session_id,
                event_time_ns,
                source_topic,
                event_type,
                map_name,
                label_id,
                label_name,
                task_type,
                status,
                payload_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.session_id,
                event_time_ns,
                source_topic,
                event_type,
                map_name,
                label_id,
                label_name,
                task_type,
                status,
                payload_json,
            ),
        )

        self.conn.commit()

    def label_callback(self, msg):
        label = msg.data.strip()

        if label == "__stop_navigation__":
            event_type = "STOP_COMMAND"
            task_type = "stop_navigation"

        elif label == "__localize__":
            event_type = "LOCALIZE_COMMAND"
            task_type = "localization"

        else:
            event_type = "NAVIGATION_COMMAND"
            task_type = "navigate_to_location"

        self.insert_event(
            source_topic="/label",
            event_type=event_type,
            label_name=label,
            task_type=task_type,
            payload={
                "data": label
            },
        )

        self.get_logger().info(
            f"{event_type}: {label}"
        )

    def navigation_status_callback(self, msg):
        raw = msg.data

        try:
            payload = json.loads(raw)

            if not isinstance(payload, dict):
                raise ValueError(
                    "navigation status is not a JSON object"
                )

        except Exception:
            self.insert_event(
                source_topic="/robot/navigation_status",
                event_type="NAVIGATION_STATUS_RAW",
                payload={
                    "raw": raw
                },
            )

            self.get_logger().warning(
                "Stored non-JSON navigation status"
            )
            return

        event = str(
            payload.get("event")
            or "unknown"
        ).strip().lower()

        status = payload.get("status")

        label_name = (
            payload.get("label")
            or payload.get("name")
        )

        if event in {"started", "running"}:
            event_type = "NAVIGATION_STARTED"

        elif event == "finished":
            event_type = "NAVIGATION_FINISHED"

        else:
            event_type = "NAVIGATION_STATUS"

        task_type = (
            "localization"
            if payload.get("name") == "localize"
            else "navigate_to_location"
        )

        self.insert_event(
            source_topic="/robot/navigation_status",
            event_type=event_type,
            map_name=payload.get("map"),
            label_id=payload.get("label_id"),
            label_name=label_name,
            task_type=task_type,
            status=(
                str(status)
                if status is not None
                else None
            ),
            payload=payload,
        )

        self.get_logger().info(
            f"{event_type}: "
            f"label={label_name} "
            f"status={status}"
        )

    def close(self):
        try:
            self.conn.commit()
            self.conn.close()
        except Exception:
            pass


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

    args = parser.parse_args()

    rclpy.init()

    node = TaskEventLogger(
        args.db,
        args.session_id,
    )

    try:
        rclpy.spin(node)

    except KeyboardInterrupt:
        pass

    finally:
        node.close()

        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
