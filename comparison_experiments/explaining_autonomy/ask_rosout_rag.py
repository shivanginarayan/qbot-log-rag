#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
COMPARISON_ROOT = HERE.parents[1]
if str(COMPARISON_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPARISON_ROOT))

from common.embedding_client import embed, cosine
from common.nvidia_client import call_nemotron
from common.session_utils import resolve_session_id
from explaining_autonomy.build_rosout_index import index_path_for_session

def load_index(session_id):
    path = index_path_for_session(session_id)
    if not path.exists():
        raise RuntimeError(
            f"No /rosout index for session {session_id}. "
            "Run rosout-build first."
        )
    return json.loads(path.read_text(encoding="utf-8"))

def retrieve(question, data, top_k=12):
    q = embed(question)
    scored = []
    for record in data.get("records", []):
        scored.append({
            "score": cosine(q, record["embedding"]),
            **record,
        })
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:top_k]

def build_prompt(question, session_id, hits):
    context = [{
        "timestamp_ns": h.get("timestamp_ns"),
        "node": h.get("name"),
        "level": h.get("level"),
        "message": h.get("message"),
        "similarity": round(h.get("score", 0.0), 4),
    } for h in hits]

    return f"""
You are answering a question about a robot navigation session.

You are given ROS textual log messages retrieved semantically from /rosout.
The comparison system removes only immediately repeated identical logs,
embeds the remaining messages, retrieves the most relevant logs, and gives
those logs to you.

Use only the retrieved logs below.
Do not assume hidden task structure, behavior memory, structured lifecycles,
or causal relationships that are not stated in the logs.
If the logs are insufficient, say so. Do not invent causes.

SESSION:
{session_id}

USER QUESTION:
{question}

RETRIEVED ROS LOGS:
{json.dumps(context, indent=2)}

Answer directly.
""".strip()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default="latest")
    parser.add_argument("--question", required=True)
    parser.add_argument("--top-k", type=int, default=12)
    parser.add_argument("--show-retrieval", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

    session_id = resolve_session_id(args.session_id)
    data = load_index(session_id)
    hits = retrieve(args.question, data, args.top_k)

    print()
    print("SYSTEM: explaining_autonomy_rosout_rag")
    print("SESSION:", session_id)
    print("INDEXED ROSOUT RECORDS:", len(data.get("records", [])))
    print("RETRIEVED:", len(hits))

    if args.show_retrieval:
        print()
        print("RETRIEVED ROS LOGS")
        print("=" * 70)
        for hit in hits:
            print(
                f"{hit.get('score', 0.0):.4f} | "
                f"{hit.get('name')} | {hit.get('message')}"
            )

    if args.no_llm:
        return

    answer = call_nemotron(
        build_prompt(args.question, session_id, hits)
    )

    print()
    print("ANSWER")
    print("=" * 70)
    print(answer)

if __name__ == "__main__":
    main()
