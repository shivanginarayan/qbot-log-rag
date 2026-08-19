import sqlite3
import sys


if len(sys.argv) != 2:
    print("Usage: python src/storage/inspect_tables.py <path-to-robot.db>")
    sys.exit(1)

db_path = sys.argv[1]

conn = sqlite3.connect(db_path)

rows = conn.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
    ORDER BY name
""").fetchall()

conn.close()

print("Tables:")
for row in rows:
    print(f"  - {row[0]}")
