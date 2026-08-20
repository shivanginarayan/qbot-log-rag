import argparse
import os
import sqlite3
import subprocess
import requests


MODEL = "nvidia/nemotron-3-super-120b-a12b"

SYSTEM_PROMPT = """
You are explaining the behavior of a mobile robot using only the
evidence supplied from its recorded session.

Rules:
1. Use only the supplied evidence.
2. Do not invent sensor readings, events, intentions, or causes.
3. Distinguish observed facts, reasonable inference, and insufficient evidence.
4. Temporal order alone does not prove causation.
5. If evidence sources disagree, mention it.
6. If evidence is insufficient, say what is missing.
7. Answer the user's question directly.
"""


def get_timeline(session_id):
    result = subprocess.run(
        [
            "python",
            "src/storage/session_timeline.py",
            "--session-id",
            session_id,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


def get_database_summary(session_id):
    db = f"runtime_logs/session_{session_id}/robot.db"
    conn = sqlite3.connect(db)

    tables = [
        "pose_samples",
        "odom_samples",
        "cmd_vel_intervals",
        "lidar_summary_intervals",
        "navigation_goals",
        "navigation_feedback",
        "navigation_events",
    ]

    summary = {}

    for table in tables:
        try:
            summary[table] = conn.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        except sqlite3.OperationalError:
            summary[table] = 0

    conn.close()
    return summary


def ask_llm(api_key, session_id, evidence, question):
    url = "https://integrate.api.nvidia.com/v1/chat/completions"

    prompt = f"""
ROBOT SESSION:
{session_id}

DATABASE CONTENT COUNTS:
{get_database_summary(session_id)}

SESSION EVIDENCE:
----------------
{evidence}
----------------

USER QUESTION:
{question}

Answer only from the supplied evidence.
"""

    payload = {
        "model": MODEL,
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 1.0,
        "top_p": 0.95,
        "max_tokens": 2048,
        "stream": False,
        "chat_template_kwargs": {
            "enable_thinking": True
        },
        "reasoning_budget": 4096,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        timeout=120,
    )

    response.raise_for_status()

    data = response.json()

    return data["choices"][0]["message"]["content"]


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--session-id",
        required=True,
    )

    args = parser.parse_args()

    api_key = os.environ.get("NVIDIA_API_KEY")

    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY is not set."
        )

    print("Loading session evidence...")

    evidence = get_timeline(
        args.session_id
    )

    print()
    print(f"Session {args.session_id} loaded.")
    print("Ask questions about the robot.")
    print("Type 'exit' to stop.")
    print()

    while True:
        question = input("Question> ").strip()

        if question.lower() in {"exit", "quit"}:
            break

        if not question:
            continue

        print()
        print("Answer:")

        try:
            answer = ask_llm(
                api_key,
                args.session_id,
                evidence,
                question,
            )

            print(answer)

        except Exception as exc:
            print(f"LLM request failed: {exc}")

        print()


if __name__ == "__main__":
    main()