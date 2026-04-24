import json


def convert_snapshot_to_logs(snapshot):
    logs = []

    timestamp = snapshot["timestamp"]

    for topic, data in snapshot["topics"].items():
        status = data["status"]
        value = data["latest_value"]

        if status == "NO_MESSAGES_YET":
            message = f"{topic} has not published any messages yet."
            severity = "WARN"

        elif status == "STALE":
            message = f"{topic} is not updating (stale)."
            severity = "ERROR"

        else:
            message = f"{topic} is active with data {value}"
            severity = "INFO"

        log = {
            "timestamp": timestamp,
            "node": topic,
            "topic": topic,
            "severity": severity,
            "message": message
        }

        logs.append(log)

    return logs


def process_file(input_file, output_file):
    with open(input_file, "r") as f:
        lines = f.readlines()

    all_logs = []

    for line in lines:
        snapshot = json.loads(line)
        logs = convert_snapshot_to_logs(snapshot)
        all_logs.extend(logs)

    with open(output_file, "w") as f:
        for log in all_logs:
            f.write(json.dumps(log) + "\n")


if __name__ == "__main__":
    process_file(
        "data/processed/live_topic_health.jsonl",
        "data/processed/converted_logs.jsonl"
    )
