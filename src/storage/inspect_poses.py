import sqlite3
import sys


if len(sys.argv) != 2:
    print("Usage: python src/storage/inspect_poses.py <path-to-robot.db>")
    sys.exit(1)

db_path = sys.argv[1]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    """
    SELECT *
    FROM pose_samples
    ORDER BY ros_time_ns
    """
).fetchall()

conn.close()

print(f"Pose samples: {len(rows)}")
print("=" * 60)

for row in rows:
    print(f"pose_id: {row['pose_id']}")
    print(f"session_id: {row['session_id']}")
    print(f"ros_time_ns: {row['ros_time_ns']}")
    print(f"received_at_ns: {row['received_at_ns']}")
    print(f"frame_id: {row['frame_id']}")
    print(f"x: {row['x']}")
    print(f"y: {row['y']}")
    print(f"z: {row['z']}")
    print(f"yaw_rad: {row['yaw_rad']}")
    print(f"x_variance: {row['x_variance']}")
    print(f"y_variance: {row['y_variance']}")
    print(f"yaw_variance: {row['yaw_variance']}")
    print("-" * 60)
