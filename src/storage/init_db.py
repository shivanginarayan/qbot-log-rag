import sqlite3


def initialize_database(db_path):
    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT PRIMARY KEY,

            started_at_ns INTEGER NOT NULL,
            started_at_iso TEXT NOT NULL,

            ended_at_ns INTEGER,
            ended_at_iso TEXT,

            robot_id TEXT NOT NULL,
            ros_domain_id INTEGER NOT NULL,

            map_name TEXT,
            map_yaml_path TEXT,

            git_commit TEXT,

            status TEXT NOT NULL,

            notes TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS pose_samples (
            pose_id INTEGER PRIMARY KEY AUTOINCREMENT,

            session_id TEXT NOT NULL,

            ros_time_ns INTEGER NOT NULL,
            received_at_ns INTEGER NOT NULL,
            is_stale INTEGER NOT NULL DEFAULT 0,

            frame_id TEXT,

            x REAL NOT NULL,
            y REAL NOT NULL,
            z REAL NOT NULL,

            qx REAL NOT NULL,
            qy REAL NOT NULL,
            qz REAL NOT NULL,
            qw REAL NOT NULL,

            yaw_rad REAL NOT NULL,

            x_variance REAL,
            y_variance REAL,
            yaw_variance REAL,

            FOREIGN KEY (session_id)
                REFERENCES sessions(session_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS odom_samples (
            odom_id INTEGER PRIMARY KEY AUTOINCREMENT,

            session_id TEXT NOT NULL,

            ros_time_ns INTEGER NOT NULL,
            received_at_ns INTEGER NOT NULL,

            frame_id TEXT,
            child_frame_id TEXT,

            x REAL NOT NULL,
            y REAL NOT NULL,
            z REAL NOT NULL,

            qx REAL NOT NULL,
            qy REAL NOT NULL,
            qz REAL NOT NULL,
            qw REAL NOT NULL,

            yaw_rad REAL NOT NULL,

            linear_x REAL,
            linear_y REAL,
            linear_z REAL,

            angular_x REAL,
            angular_y REAL,
            angular_z REAL,

            FOREIGN KEY (session_id)
                REFERENCES sessions(session_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cmd_vel_intervals (
            cmd_vel_id INTEGER PRIMARY KEY AUTOINCREMENT,

            session_id TEXT NOT NULL,

            started_at_ns INTEGER NOT NULL,
            ended_at_ns INTEGER,

            linear_x REAL NOT NULL,
            linear_y REAL NOT NULL,
            linear_z REAL NOT NULL,

            angular_x REAL NOT NULL,
            angular_y REAL NOT NULL,
            angular_z REAL NOT NULL,

            sample_count INTEGER NOT NULL DEFAULT 1,

            FOREIGN KEY (session_id)
                REFERENCES sessions(session_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS lidar_summary_intervals (
            lidar_id INTEGER PRIMARY KEY AUTOINCREMENT,

            session_id TEXT NOT NULL,

            started_at_ns INTEGER NOT NULL,
            ended_at_ns INTEGER,

            source_topic TEXT NOT NULL,

            closest_distance REAL,
            closest_angle REAL,

            front_min REAL,
            left_min REAL,
            right_min REAL,
            rear_min REAL,

            distance_band TEXT NOT NULL,
            front_band TEXT,
            left_band TEXT,
            right_band TEXT,
            rear_band TEXT,

            closest_bin INTEGER,
            front_bin INTEGER,
            left_bin INTEGER,
            right_bin INTEGER,
            rear_bin INTEGER,

            zero_count INTEGER NOT NULL DEFAULT 0,
            inf_count INTEGER NOT NULL DEFAULT 0,
            valid_count INTEGER NOT NULL DEFAULT 0,

            sample_count INTEGER NOT NULL DEFAULT 1,

            previous_interval_id INTEGER,

            FOREIGN KEY (session_id)
                REFERENCES sessions(session_id),

            FOREIGN KEY (previous_interval_id)
                REFERENCES lidar_summary_intervals(lidar_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS navigation_goals (
            navigation_goal_id INTEGER PRIMARY KEY AUTOINCREMENT,

            session_id TEXT NOT NULL,

            client_goal_id TEXT NOT NULL,
            action_goal_uuid TEXT,

            action_name TEXT NOT NULL,

            requested_at_ns INTEGER NOT NULL,
            accepted_at_ns INTEGER,
            completed_at_ns INTEGER,

            frame_id TEXT NOT NULL,

            target_x REAL NOT NULL,
            target_y REAL NOT NULL,
            target_z REAL NOT NULL,

            target_qx REAL NOT NULL,
            target_qy REAL NOT NULL,
            target_qz REAL NOT NULL,
            target_qw REAL NOT NULL,

            target_yaw_rad REAL NOT NULL,

            status_code INTEGER,
            status_text TEXT NOT NULL,

            result_error_code INTEGER,
            result_error_message TEXT,

            FOREIGN KEY (session_id)
                REFERENCES sessions(session_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS navigation_feedback (
            feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,

            navigation_goal_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,

            received_at_ns INTEGER NOT NULL,

            current_x REAL,
            current_y REAL,
            current_yaw_rad REAL,

            navigation_time_sec REAL,
            estimated_time_remaining_sec REAL,

            distance_remaining REAL,
            number_of_recoveries INTEGER,

            FOREIGN KEY (navigation_goal_id)
                REFERENCES navigation_goals(navigation_goal_id),

            FOREIGN KEY (session_id)
                REFERENCES sessions(session_id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS navigation_events (
            navigation_event_id INTEGER PRIMARY KEY AUTOINCREMENT,

            navigation_goal_id INTEGER NOT NULL,
            session_id TEXT NOT NULL,

            event_time_ns INTEGER NOT NULL,

            event_type TEXT NOT NULL,

            status_code INTEGER,
            status_text TEXT,

            FOREIGN KEY (navigation_goal_id)
                REFERENCES navigation_goals(navigation_goal_id),

            FOREIGN KEY (session_id)
                REFERENCES sessions(session_id)
        )
    """)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_events (
            task_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            event_time_ns INTEGER NOT NULL,
            source_topic TEXT NOT NULL,
            event_type TEXT NOT NULL,
            map_name TEXT,
            label_id TEXT,
            label_name TEXT,
            task_type TEXT,
            status TEXT,
            payload_json TEXT,
            FOREIGN KEY(session_id) REFERENCES sessions(session_id)
        )
        """
    )

    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_task_events_session_time
        ON task_events(session_id, event_time_ns)
        """
    )

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_navigation_goal_time
        ON navigation_goals(session_id, requested_at_ns)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_navigation_feedback_time
        ON navigation_feedback(navigation_goal_id, received_at_ns)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_navigation_event_time
        ON navigation_events(navigation_goal_id, event_time_ns)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_lidar_session_time
        ON lidar_summary_intervals(session_id, started_at_ns)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_lidar_band
        ON lidar_summary_intervals(session_id, distance_band)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_cmd_vel_interval_time
        ON cmd_vel_intervals(session_id, started_at_ns)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_odom_session_time
        ON odom_samples(session_id, ros_time_ns)
    """)

    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_pose_session_time
        ON pose_samples(session_id, ros_time_ns)
    """)

    conn.commit()
    conn.close()


if __name__ == "__main__":
    initialize_database("test_robot.db")
    print("Database initialized.")
