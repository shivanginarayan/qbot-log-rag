import sqlite3
import sys
import time


if len(sys.argv) != 3:
    print(
        "Usage: python src/storage/test_insert_pose.py "
        "<path-to-robot.db> <session_id>"
    )
    sys.exit(1)

db_path = sys.argv[1]
session_id = sys.argv[2]

received_at_ns = time.time_ns()

# Fake AMCL-like pose
ros_time_ns = received_at_ns - 5_000_000

frame_id = "map"

x = 3.355
y = -0.147
z = 0.0

qx = 0.0
qy = 0.0
qz = 0.047019
qw = 0.998894

yaw_rad = 0.094073

x_variance = 0.021315
y_variance = 0.020004
yaw_variance = 0.021816


conn = sqlite3.connect(db_path)

cursor = conn.execute(
    """
    INSERT INTO pose_samples (
        session_id,
        ros_time_ns,
        received_at_ns,
        frame_id,
        x,
        y,
        z,
        qx,
        qy,
        qz,
        qw,
        yaw_rad,
        x_variance,
        y_variance,
        yaw_variance
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """,
    (
        session_id,
        ros_time_ns,
        received_at_ns,
        frame_id,
        x,
        y,
        z,
        qx,
        qy,
        qz,
        qw,
        yaw_rad,
        x_variance,
        y_variance,
        yaw_variance,
    ),
)

pose_id = cursor.lastrowid

conn.commit()
conn.close()

print(f"Inserted pose_id: {pose_id}")
