#!/usr/bin/env python3

import argparse
import dbm
import json
import math
import urllib.request
from pathlib import Path


MODEL = "bge-m3"

REPO_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_DIR / "runtime_logs"


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

    return data["embeddings"][0]


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
    label = record["label"]

    tasks = record.get(
        "tasks",
        {},
    )

    task_descriptions = []

    for task_name, task_data in tasks.items():
        occurrences = task_data.get(
            "occurrences",
            [],
        )

        outcomes = {}

        for occurrence in occurrences:
            status = occurrence.get(
                "outcome",
                {},
            ).get(
                "status",
                "unknown",
            )

            outcomes[status] = (
                outcomes.get(status, 0)
                + 1
            )

        outcome_text = ", ".join(
            f"{count} {status}"
            for status, count
            in outcomes.items()
        )

        task_descriptions.append(
            f"""
Task: {task_name}.
Recorded occurrences: {len(occurrences)}.
Recorded outcomes: {outcome_text or 'unknown'}.
""".strip()
        )

    world = label.get("world")

    location_text = ""

    if isinstance(world, dict):
        location_text = (
            f"World coordinates are "
            f"x={world.get('x')}, "
            f"y={world.get('y')}."
        )

    return f"""
Robot map-specific memory.

Map: {record.get('map')}.
Location label: {label.get('name')}.
Label kind: {label.get('kind')}.
Description: {label.get('detail') or ''}.

{location_text}

This entry represents robot tasks associated
with the saved map location called
"{label.get('name')}".

Users may refer to this location by its label,
by a shortened version of the name,
or by a natural-language description.

{chr(10).join(task_descriptions)}
""".strip()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--map",
        required=True,
    )

    args = parser.parse_args()

    map_name = Path(
        args.map
    ).stem

    map_dir = (
        RUNTIME_DIR
        / "map_indexes"
        / map_name
    )

    index_path = str(
        map_dir / "label_index"
    )

    output_path = (
        map_dir
        / "label_embeddings.json"
    )

    records = []

    with dbm.open(
        index_path,
        "r",
    ) as index:

        for raw_key in index.keys():
            record = json.loads(
                index[raw_key].decode(
                    "utf-8"
                )
            )

            text = build_text(
                record
            )

            print(
                "Embedding:",
                record["label"]["name"],
            )

            vector = normalize(
                ollama_embed(text)
            )

            records.append(
                {
                    "map":
                        map_name,

                    "label_key":
                        raw_key.decode(
                            "utf-8"
                        ),

                    "label_name":
                        record[
                            "label"
                        ]["name"],

                    "embedding_text":
                        text,

                    "embedding":
                        vector,
                }
            )

    with open(
        output_path,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            {
                "model": MODEL,
                "map": map_name,
                "records": records,
            },
            f,
        )

    print()
    print(
        f"Saved {len(records)} "
        f"map embeddings"
    )
    print(
        f"Output: {output_path}"
    )


if __name__ == "__main__":
    main()
