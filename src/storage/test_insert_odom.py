import sqlite3
import sys
import time


if len(sys.argv) != 3:
    print(
        "Usage: python src/storage/test_insert_odom.py "
        "<path-to-robot.db> <session_id>"
    )
    sys.exit(1)

db_path = sys.argv[1]
session_id = sys.argv[2]

received_at_ns = time.time_ns()
ros_time_ns = received_at_ns - 10_000_000  # pretend 10 ms earlier

frame_id = "odom"
child_frame_id = "base_link"

x = 1.25
y = -0.30
z = 0.0

qx = 0.0
qy = 0.0
qz = 0.05
qw = 0.9987

yaw_rad = 0.10

linear_x = 0.15
linear_y = 0.0
linear_z = 0.0

angular_x = 0.0
angular_y = 0.0
angular_z = 0.02


conn = sqlite3.connect(db_path)

cursor = conn.execute(
    """
    INSERT INTO odom_samples (
        session_id,
        ros_time_ns,
        received_at_ns,
        frame_id,
        child_frame_id,
        x,
        y,
        z,
        qx,
        qy,
        qz,
        qw,
        yaw_rad,
        linear_x,
        linear_y,
        linear_z,
        angular_x,
        angular_y,
        angular_z
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
        session_id,
        ros_time_ns,
        received_at_ns,
        frame_id,
        child_frame_id,
        x,
        y,
        z,
        qx,
        qy,
        qz,
        qw,
        yaw_rad,
        linear_x,
        linear_y,
        linear_z,
        angular_x,
        angular_y,
        angular_z,
    ),
)

odom_id = cursor.lastrowid

conn.commit()
conn.close()

print(f"Inserted odom_id: {odom_id}")
