import json
import sqlite3
from pathlib import Path
from rule_diagnoser import apply_rules


DB_PATH = "data/processed/error_memory.db"
CURRENT_HEALTH_PATH = "data/processed/live_topic_health.jsonl"
MODE_PATH = "data/processed/runtime_mode.txt"


def load_latest_health_snapshot():
    path = Path(CURRENT_HEALTH_PATH)

    if not path.exists():
        return None

    lines = path.read_text().strip().splitlines()

    if not lines:
        return None

    return json.loads(lines[-1])


def load_mode():
    path = Path(MODE_PATH)

    if path.exists():
        return path.read_text().strip()

    return "follower"


def get_error_history(limit=1):
    if not Path(DB_PATH).exists():
        return []

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        SELECT error_key, node, severity, message, count, first_seen, last_seen
        FROM errors
        ORDER BY last_seen DESC
        LIMIT ?
    """, (limit,))

    rows = cur.fetchall()
    conn.close()

    return rows


def diagnose_with_memory(user_query):
    current_snapshot = load_latest_health_snapshot()
    mode = load_mode()

    findings = apply_rules(
        retrieved_logs=[],
        current_context=current_snapshot,
        mode=mode,
        user_query=user_query
    )

    print("\nQBot Answer")
    print("=" * 50)

    for finding in findings:
        print(f"Issue: {finding['issue']}")
        print(f"Reason: {finding['cause']}")
        print(f"What to do: {finding['action']}")
        print()

    print("Simple explanation")
    print("-" * 50)

    for finding in findings:
        print(f"Reason: {finding['cause']}")
        print(f"Next step: {finding['action']}")
        print()

    history = get_error_history(limit=1)

    if history:
        latest = history[0]
        print("Memory")
        print("-" * 50)
        print(f"Most recent stored ROS warning/error: [{latest[2]}] {latest[1]}")
        print(f"Seen count: {latest[4]}")


if __name__ == "__main__":
    while True:
        query = input("\nAsk QBot diagnostic question (type 'exit' to quit): ")

        if query.lower() == "exit":
            break

        if not query.strip():
            continue

        diagnose_with_memory(query)