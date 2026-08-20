import sqlite3
import sys


if len(sys.argv) != 2:
    print("Usage: python src/storage/inspect_odom.py <path-to-robot.db>")
    sys.exit(1)

db_path = sys.argv[1]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    """
    SELECT *
    FROM odom_samples
    ORDER BY ros_time_ns
    """
).fetchall()

conn.close()

print(f"Odom samples: {len(rows)}")
print("=" * 60)

for row in rows:
    print(f"odom_id: {row['odom_id']}")
    print(f"session_id: {row['session_id']}")
    print(f"frame_id: {row['frame_id']}")
    print(f"child_frame_id: {row['child_frame_id']}")
    print(f"x: {row['x']}")
    print(f"y: {row['y']}")
    print(f"yaw_rad: {row['yaw_rad']}")
    print(f"linear_x: {row['linear_x']}")
    print(f"angular_z: {row['angular_z']}")
    print("-" * 60)
