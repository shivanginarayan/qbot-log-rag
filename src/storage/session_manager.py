from init_db import initialize_database
import os
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from ros_domain_config import get_ros_domain_id


class SessionManager:
    def __init__(
        self,
        base_log_dir="runtime_logs",
        ROS_DOMAIN_ID=None,
        map_name="home_test_v1",
        map_yaml_path=None,
        notes=None,
    ):
        self.base_log_dir = base_log_dir
        self.ros_domain_id = (
            get_ros_domain_id() if ROS_DOMAIN_ID is None else ROS_DOMAIN_ID
        )
        self.map_name = map_name
        self.map_yaml_path = map_yaml_path
        self.notes = notes

        self.session_id = None
        self.session_dir = None
        self.db_path = None
        self.started_at_ns = None
        self.started_at_iso = None

    def _now(self):
        now_ns = time.time_ns()
        now_iso = datetime.now().astimezone().isoformat()
        return now_ns, now_iso

    def _git_commit(self):
        try:
            return subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except Exception:
            return None

    def _initialize_database(self):
        initialize_database(self.db_path)

    def start_session(self):
        self.started_at_ns, self.started_at_iso = self._now()

        human_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        random_suffix = uuid.uuid4().hex[:4]

        self.session_id = f"{human_time}_{random_suffix}"

        self.session_dir = os.path.join(
            self.base_log_dir,
            f"session_{self.session_id}",
        )

        os.makedirs(self.session_dir, exist_ok=False)

        self.db_path = os.path.join(
            self.session_dir,
            "robot.db",
        )

        initialize_database(self.db_path)

        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute(
            """
            INSERT INTO sessions (
                session_id,
                started_at_ns,
                started_at_iso,
                robot_id,
                ros_domain_id,
                map_name,
                map_yaml_path,
                git_commit,
                status,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.session_id,
                self.started_at_ns,
                self.started_at_iso,
                socket.gethostname(),
                self.ros_domain_id,
                self.map_name,
                self.map_yaml_path,
                self._git_commit(),
                "running",
                self.notes,
            ),
        )

        conn.commit()
        conn.close()

        print(f"Session started: {self.session_id}")
        print(f"Session directory: {self.session_dir}")
        print(f"Database: {self.db_path}")

        return self.session_id

    def close_session(self, status="completed"):
        if self.db_path is None:
            raise RuntimeError("No session has been started.")

        ended_at_ns, ended_at_iso = self._now()

        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA foreign_keys = ON")

        conn.execute(
            """
            UPDATE sessions
            SET ended_at_ns = ?,
                ended_at_iso = ?,
                status = ?
            WHERE session_id = ?
            """,
            (
                ended_at_ns,
                ended_at_iso,
                status,
                self.session_id,
            ),
        )

        conn.commit()
        conn.close()

        print(f"Session closed: {self.session_id}")
        print(f"Status: {status}")

def main():
    manager = SessionManager()

    session_id = manager.start_session()

    try:
        input("Press Enter to close session...\n")
    except KeyboardInterrupt:
        print()

    manager.close_session(
        status="completed"
    )


if __name__ == "__main__":
    main()
