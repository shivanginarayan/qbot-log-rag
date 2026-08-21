import argparse
import json
import math
import urllib.request
from pathlib import Path


MODEL = "bge-m3"

REPO_DIR = Path(__file__).resolve().parents[2]

EMBEDDING_FILE = (
    REPO_DIR
    / "runtime_logs"
    / "behavior_embeddings.json"
)


def ollama_embed(text):
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
            "Content-Type": "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=120,
    ) as response:
        data = json.loads(
            response.read().decode("utf-8")
        )

    return data["embeddings"][0]


def normalize(vector):
    norm = math.sqrt(
        sum(x * x for x in vector)
    )

    if norm == 0:
        return vector

    return [
        x / norm
        for x in vector
    ]


def cosine_similarity(a, b):
    return sum(
        x * y
        for x, y in zip(a, b)
    )


def search(question, top_k=3):
    with open(
        EMBEDDING_FILE,
        "r",
        encoding="utf-8",
    ) as f:
        data = json.load(f)

    question_embedding = normalize(
        ollama_embed(question)
    )

    results = []

    for record in data["records"]:
        score = cosine_similarity(
            question_embedding,
            record["embedding"],
        )

        results.append(
            {
                "behavior_key":
                    record["behavior_key"],

                "score":
                    score,

                "embedding_text":
                    record["embedding_text"],
            }
        )

    results.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    return results[:top_k]


def main():
    parser = argparse.ArgumentParser()

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

    results = search(
        args.question,
        args.top_k,
    )

    print()
    print("Question:")
    print(args.question)
    print()

    print("Matches:")

    for i, result in enumerate(
        results,
        start=1,
    ):
        print()
        print(
            f"{i}. "
            f"{result['behavior_key']} "
            f"score={result['score']:.4f}"
        )

        print(
            result["embedding_text"]
        )


if __name__ == "__main__":
    main()
