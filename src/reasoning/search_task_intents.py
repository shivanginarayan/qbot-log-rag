#!/usr/bin/env python3

import argparse
import json
import math
import urllib.request
from pathlib import Path


MODEL = "bge-m3"

REPO_DIR = Path(__file__).resolve().parents[2]

EMBEDDINGS = (
    REPO_DIR
    / "runtime_logs"
    / "task_intent_embeddings.json"
)


def normalize(vector):
    norm = math.sqrt(
        sum(
            value * value
            for value in vector
        )
    )

    if not norm:
        return vector

    return [
        value / norm
        for value in vector
    ]


def embed(text):
    payload = json.dumps(
        {
            "model": MODEL,
            "input": text,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "http://localhost:11434/api/embed",
        data=payload,
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=120,
    ) as response:
        data = json.loads(
            response.read().decode(
                "utf-8"
            )
        )

    return normalize(
        data["embeddings"][0]
    )


def cosine(a, b):
    return sum(
        x * y
        for x, y in zip(a, b)
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--question",
        required=True,
    )

    args = parser.parse_args()

    data = json.loads(
        EMBEDDINGS.read_text(
            encoding="utf-8"
        )
    )

    query = embed(
        args.question
    )

    results = []

    for record in data[
        "records"
    ]:
        results.append(
            (
                cosine(
                    query,
                    record[
                        "embedding"
                    ],
                ),
                record,
            )
        )

    results.sort(
        key=lambda item:
            item[0],
        reverse=True,
    )

    for score, record in (
        results[:3]
    ):
        print()
        print(
            f"{record['label_name']} "
            f"score={score:.4f}"
        )

        print(
            record[
                "embedding_text"
            ]
        )


if __name__ == "__main__":
    main()
