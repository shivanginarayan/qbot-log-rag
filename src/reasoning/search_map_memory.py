#!/usr/bin/env python3

import argparse
import json
import math
import urllib.request
from pathlib import Path


MODEL = "bge-m3"

REPO_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_DIR / "runtime_logs"


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

    vector = data[
        "embeddings"
    ][0]

    norm = math.sqrt(
        sum(x * x for x in vector)
    )

    return [
        x / norm
        for x in vector
    ]


def similarity(a, b):
    return sum(
        x * y
        for x, y in zip(a, b)
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--map",
        required=True,
    )

    parser.add_argument(
        "--question",
        required=True,
    )

    parser.add_argument(
        "--top-k",
        type=int,
        default=3,
    )

    args = parser.parse_args()

    map_name = Path(
        args.map
    ).stem

    path = (
        RUNTIME_DIR
        / "map_indexes"
        / map_name
        / "label_embeddings.json"
    )

    with open(
        path,
        "r",
        encoding="utf-8",
    ) as f:
        data = json.load(f)

    query = embed(
        args.question
    )

    results = []

    for record in data["records"]:
        score = similarity(
            query,
            record["embedding"],
        )

        results.append(
            (
                score,
                record,
            )
        )

    results.sort(
        key=lambda item:
            item[0],
        reverse=True,
    )

    for score, record in results[
        :args.top_k
    ]:
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
