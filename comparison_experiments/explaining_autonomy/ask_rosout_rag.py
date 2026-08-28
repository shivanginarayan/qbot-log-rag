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
from explaining_autonomy.persistent_memory import load_memory


def retrieve(
    question,
    data,
    top_k=12,
    mmr_lambda=0.5,
):
    """
    Retrieve from the single persistent cumulative /rosout corpus.

    Selection:
      semantic relevance -> MMR diversity -> chronological order
    """

    q = embed(question)

    candidates = []

    for record in data.get("records", []):
        query_similarity = cosine(
            q,
            record["embedding"],
        )

        candidates.append({
            "score": query_similarity,
            "query_similarity": query_similarity,
            **record,
        })

    if not candidates:
        return []

    top_k = max(
        1,
        min(
            int(top_k),
            len(candidates),
        ),
    )

    mmr_lambda = max(
        0.0,
        min(
            1.0,
            float(mmr_lambda),
        ),
    )

    remaining = sorted(
        candidates,
        key=lambda item: item["query_similarity"],
        reverse=True,
    )

    selected = [remaining.pop(0)]
    selected[0]["mmr_score"] = selected[0]["query_similarity"]

    while remaining and len(selected) < top_k:
        best_index = None
        best_mmr = None

        for index, candidate in enumerate(remaining):
            max_redundancy = max(
                cosine(
                    candidate["embedding"],
                    chosen["embedding"],
                )
                for chosen in selected
            )

            mmr_score = (
                mmr_lambda * candidate["query_similarity"]
                - (1.0 - mmr_lambda) * max_redundancy
            )

            if best_mmr is None or mmr_score > best_mmr:
                best_mmr = mmr_score
                best_index = index

        chosen = remaining.pop(best_index)
        chosen["mmr_score"] = best_mmr
        selected.append(chosen)

    # Present selected evidence in time order.
    selected.sort(
        key=lambda item: (
            int(item.get("timestamp_ns") or 0),
            str(item.get("session_id") or ""),
        )
    )

    return selected


def build_prompt(
    question,
    hits,
):
    context = [
        {
            "session_id": hit.get("session_id"),
            "timestamp_ns": hit.get("timestamp_ns"),
            "node": hit.get("name"),
            "level": hit.get("level"),
            "message": hit.get("message"),
            "similarity": round(
                hit.get("query_similarity", 0.0),
                4,
            ),
            "mmr_score": round(
                hit.get("mmr_score", 0.0),
                4,
            ),
        }
        for hit in hits
    ]

    return f"""
You are answering a question about robot navigation using an
Explaining-Autonomy-style /rosout RAG system.

There is one persistent knowledge base containing textual ROS logs
accumulated over time. It may contain logs from earlier robot runs as
well as logs being added from the current live run.

The system:
- removes immediately repeated identical logs,
- embeds remaining /rosout messages,
- uses MMR to retrieve relevant but non-redundant messages,
- sorts selected evidence chronologically,
- and gives those selected logs to you.

Use only the retrieved logs below.

Important:
- session_id is metadata only; it is not a retrieval boundary;
- do not invent hidden task structure, structured lifecycles, sensor
  evidence, or causal relationships not stated in the logs;
- an older log is not proof of the robot's current state;
- if a question asks about "now" and the retrieved logs do not establish
  the current state, say so;
- if the logs are insufficient, say so;
- temporal order alone is not proof of causation.

USER QUESTION:
{question}

RETRIEVED ROS LOGS:
{json.dumps(context, indent=2)}

Answer directly.
""".strip()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--question",
        required=True,
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=12,
    )

    parser.add_argument(
        "--mmr-lambda",
        type=float,
        default=0.5,
    )

    parser.add_argument(
        "--show-retrieval",
        action="store_true",
    )

    parser.add_argument(
        "--no-llm",
        action="store_true",
    )

    args = parser.parse_args()

    data = load_memory()

    hits = retrieve(
        args.question,
        data,
        args.top_k,
        args.mmr_lambda,
    )

    print()
    print(
        "SYSTEM:",
        "explaining_autonomy_persistent_rosout_rag",
    )
    print(
        "CORPUS:",
        "single persistent cumulative /rosout memory",
    )
    print(
        "INDEXED ROSOUT RECORDS:",
        len(data.get("records", [])),
    )
    print(
        "SESSIONS REPRESENTED:",
        len(data.get("session_ids", [])),
    )
    print(
        "RETRIEVED:",
        len(hits),
    )

    if args.show_retrieval:
        print()
        print("RETRIEVED ROS LOGS")
        print("=" * 70)

        for hit in hits:
            print(
                f"query={hit.get('query_similarity', 0.0):.4f} | "
                f"mmr={hit.get('mmr_score', 0.0):.4f} | "
                f"session={hit.get('session_id')} | "
                f"t={hit.get('timestamp_ns')} | "
                f"{hit.get('name')} | "
                f"{hit.get('message')}"
            )

    if args.no_llm:
        return

    if not hits:
        print()
        print(
            "No /rosout evidence is available in the persistent corpus."
        )
        return

    answer = call_nemotron(
        build_prompt(
            args.question,
            hits,
        )
    )

    print()
    print("ANSWER")
    print("=" * 70)
    print(answer)


if __name__ == "__main__":
    main()
