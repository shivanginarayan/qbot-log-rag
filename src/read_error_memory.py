import json
import sqlite3


DB_PATH = "data/processed/error_memory.db"


def print_error_summary():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT error_key, node, severity, message, count, first_seen, last_seen
        FROM errors
        ORDER BY last_seen DESC
    """)

    errors = cur.fetchall()

    if not errors:
        print("No errors stored yet.")
        conn.close()
        return

    for error in errors:
        error_key, node, severity, message, count, first_seen, last_seen = error

        print("\n" + "=" * 80)
        print(f"Error Key: {error_key}")
        print(f"Node: {node}")
        print(f"Severity: {severity}")
        print(f"Message: {message}")
        print(f"Count: {count}")
        print(f"First Seen: {first_seen}")
        print(f"Last Seen: {last_seen}")

        cur.execute("""
            SELECT timestamp, context_before
            FROM error_occurrences
            WHERE error_key = ?
            ORDER BY timestamp DESC
            LIMIT 5
        """, (error_key,))

        occurrences = cur.fetchall()

        print("\nLast occurrences and context before error:")

        for timestamp, context_json in occurrences:
            print(f"\nOccurrence at: {timestamp}")

            context = json.loads(context_json)

            if not context:
                print("  No context captured before this error.")
                continue

            last_context = context[-1]

            print("  Topic state just before error:")

            for topic, value in last_context["topics"].items():
                print(f"  - {topic}: {value}")

    conn.close()


if __name__ == "__main__":
    print_error_summary()
