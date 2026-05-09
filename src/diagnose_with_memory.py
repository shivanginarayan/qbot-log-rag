import json
import sqlite3
from pathlib import Path

from diagnose import diagnose_issue


DB_PATH = "data/processed/error_memory.db"
CURRENT_HEALTH_PATH = "data/processed/live_topic_health.jsonl"


def load_latest_health_snapshot():
    path = Path(CURRENT_HEALTH_PATH)

    if not path.exists():
        return None

    lines = path.read_text().strip().splitlines()

    if not lines:
        return None

    return json.loads(lines[-1])


def summarize_context(snapshot):
    if not snapshot:
        return "No current topic health snapshot available."

    lines = []
    lines.append(f"Timestamp: {snapshot.get('timestamp')}")

    topics = snapshot.get("topics", {})

    for topic, data in topics.items():
        status = data.get("status")
        value = data.get("latest_value")
        lines.append(f"- {topic}: status={status}, value={value}")

    return "\n".join(lines)


def get_error_history(limit=5):
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

    errors = cur.fetchall()

    history = []

    for error in errors:
        error_key, node, severity, message, count, first_seen, last_seen = error

        cur.execute("""
            SELECT timestamp, context_before
            FROM error_occurrences
            WHERE error_key = ?
            ORDER BY timestamp DESC
            LIMIT 5
        """, (error_key,))

        occurrences = cur.fetchall()

        parsed_occurrences = []
        for timestamp, context_json in occurrences:
            try:
                context = json.loads(context_json)
            except Exception:
                context = []

            last_context = context[-1] if context else None

            parsed_occurrences.append({
                "timestamp": timestamp,
                "context_before": last_context
            })

        history.append({
            "error_key": error_key,
            "node": node,
            "severity": severity,
            "message": message,
            "count": count,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "occurrences": parsed_occurrences
        })

    conn.close()
    return history


def compare_current_to_past(current_snapshot, past_context):
    if not current_snapshot or not past_context:
        return "Not enough context to compare."

    current_topics = current_snapshot.get("topics", {})
    past_topics = past_context.get("topics", {})

    matches = []
    differences = []

    for topic, current_data in current_topics.items():
        past_data = past_topics.get(topic)

        if past_data is None:
            continue

        current_value = current_data.get("latest_value")
        past_value = past_data

        if current_value == past_value:
            matches.append(topic)
        else:
            differences.append(topic)

    if matches and not differences:
        return "Current topic state looks very similar to the previous occurrence."

    if matches and differences:
        return (
            f"Partially similar. Similar topics: {matches}. "
            f"Different topics: {differences}."
        )

    return "Current topic state does not look very similar to the stored previous context."


def diagnose_with_memory(user_query):
    print("\nCURRENT DIAGNOSIS")
    print("=" * 80)
    print(diagnose_issue(user_query))

    current_snapshot = load_latest_health_snapshot()

    print("\nCURRENT TOPIC CONTEXT")
    print("=" * 80)
    print(summarize_context(current_snapshot))

    history = get_error_history(limit=5)

    print("\nERROR MEMORY")
    print("=" * 80)

    if not history:
        print("No previous WARN/ERROR/FATAL events stored yet.")
        return

    for item in history:
        print("\n" + "-" * 80)
        print(f"Stored error: [{item['severity']}] {item['node']}: {item['message']}")
        print(f"Seen count: {item['count']}")
        print(f"First seen: {item['first_seen']}")
        print(f"Last seen: {item['last_seen']}")

        if item["count"] == 1:
            print("Status: This error has only been seen once so far.")
        else:
            print("Status: This error has occurred before.")

        latest_occurrence = item["occurrences"][0] if item["occurrences"] else None

        if latest_occurrence:
            print(f"Latest occurrence timestamp: {latest_occurrence['timestamp']}")

            comparison = compare_current_to_past(
                current_snapshot,
                latest_occurrence["context_before"]
            )

            print(f"Comparison with current state: {comparison}")

            print("\nWhat happened just before last occurrence:")

            context_before = latest_occurrence["context_before"]

            if context_before:
                print(summarize_context(context_before))
            else:
                print("No context was captured before this occurrence.")


if __name__ == "__main__":
    while True:
        query = input("\nAsk QBot diagnostic question (type 'exit' to quit): ")

        if query.lower() == "exit":
            break

        diagnose_with_memory(query)
