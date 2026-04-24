import json
from pathlib import Path


def load_logs(file_path: str):
    logs = []

    with open(file_path, "r", encoding="utf-8") as file:
        for line in file:
            logs.append(json.loads(line))

    return logs


def log_to_text(log):
    return (
        f"Time: {log['timestamp']}\n"
        f"Node: {log['node']}\n"
        f"Topic: {log['topic']}\n"
        f"Severity: {log['severity']}\n"
        f"Message: {log['message']}"
    )


if __name__ == "__main__":
    path = Path("data/mock_logs/qbot_mock_logs.jsonl")
    logs = load_logs(path)

    for log in logs:
        print(log_to_text(log))
        print("-" * 40)