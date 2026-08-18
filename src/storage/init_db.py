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

    conn.commit()
    conn.close()


if __name__ == "__main__":
    initialize_database("test_robot.db")
    print("Database initialized.")
