#!/usr/bin/env python3

import dbm
import json
import math
import urllib.request
from pathlib import Path


MODEL = "bge-m3"

REPO_DIR = Path(__file__).resolve().parents[2]

INDEX_PATH = str(
    REPO_DIR
    / "runtime_logs"
    / "task_intent_index"
)

OUTPUT_PATH = (
    REPO_DIR
    / "runtime_logs"
    / "task_intent_embeddings.json"
)


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

    return data[
        "embeddings"
    ][0]


def normalize(vector):
    norm = math.sqrt(
        sum(
            value * value
            for value in vector
        )
    )

    if norm == 0:
        return vector

    return [
        value / norm
        for value in vector
    ]


def build_text(record):
    occurrences = record.get(
        "occurrences",
        [],
    )

    outcomes = {}

    for occurrence in occurrences:
        outcome = occurrence.get(
            "outcome",
            "unknown",
        )

        outcomes[outcome] = (
            outcomes.get(
                outcome,
                0,
            )
            + 1
        )

    outcome_text = ", ".join(
        f"{count} {name}"
        for name, count
        in outcomes.items()
    )

    label = record.get(
        "label_name",
        "",
    )

    return f"""
Robot requested-task memory.

Destination label: {label}.
Task type: navigate_to_location.

This memory represents user or system requests
for the robot to navigate to the saved destination
called "{label}".

It includes requests that executed successfully,
requests that failed, requests that began but did
not finish, and requests for which no execution
start was recorded.

Natural-language descriptions may include:
go to {label},
navigate to {label},
drive to {label},
move to {label},
why didn't the robot go to {label},
why did navigation to {label} not start,
what happened when {label} was requested.

Recorded requests: {len(occurrences)}.
Recorded outcomes: {outcome_text or "unknown"}.
""".strip()


def main():
    records = []

    with dbm.open(
        INDEX_PATH,
        "r",
    ) as index:

        for raw_key in index.keys():
            record = json.loads(
                index[
                    raw_key
                ].decode(
                    "utf-8"
                )
            )

            text = build_text(
                record
            )

            print(
                "Embedding intent:",
                record[
                    "label_name"
                ],
            )

            vector = normalize(
                embed(text)
            )

            records.append(
                {
                    "label_key":
                        record[
                            "label_key"
                        ],

                    "label_name":
                        record[
                            "label_name"
                        ],

                    "embedding_text":
                        text,

                    "embedding":
                        vector,
                }
            )

    OUTPUT_PATH.write_text(
        json.dumps(
            {
                "model": MODEL,
                "records": records,
            }
        ),
        encoding="utf-8",
    )

    print()
    print(
        f"Saved {len(records)} "
        f"task-intent embeddings"
    )

    print(
        f"Output: {OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()
