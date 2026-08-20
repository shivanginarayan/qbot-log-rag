import sqlite3
import sys


if len(sys.argv) != 2:
    print("Usage: python src/storage/inspect_session.py <path-to-robot.db>")
    sys.exit(1)

db_path = sys.argv[1]

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

row = conn.execute(
    "SELECT * FROM sessions LIMIT 1"
).fetchone()

conn.close()

if row is None:
    print("No session found.")
    sys.exit(0)

print("\nSession record")
print("=" * 50)

for key in row.keys():
    print(f"{key}: {row[key]}")
