import dbm
import json
import math
import urllib.request
from pathlib import Path


MODEL = "bge-m3"

REPO_DIR = Path(__file__).resolve().parents[2]

BEHAVIOR_INDEX = str(
    REPO_DIR / "runtime_logs" / "behavior_index"
)

OUTPUT_FILE = (
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


def build_embedding_text(record):
    behavior = record["behavior"]

    action = behavior.get(
        "action_family",
        "unknown",
    )

    motion = behavior.get(
        "motion_family",
        "unknown",
    )

    direction = behavior.get(
        "relative_direction",
        "unknown",
    )

    occurrence_count = len(
        record.get("occurrences", [])
    )

    return f"""
Robot behavior.

Action family: {action}.
Motion family: {motion}.
Relative direction: {direction}.

This describes a robot behavior involving {action},
with {motion} motion in the {direction} direction
relative to the robot's starting orientation.

Possible descriptions include:
move {direction},
go {direction},
drive {direction},
travel {direction},
robot movement,
navigation movement,
navigation toward a goal.

Available evidence may include:
navigation goals,
navigation feedback,
odometry,
velocity commands,
LiDAR,
localization,
timestamps,
and rosbag evidence.

This behavior has {occurrence_count} recorded occurrence(s).
""".strip()


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


def main():
    records = []

    with dbm.open(
        BEHAVIOR_INDEX,
        "r",
    ) as index:

        for raw_key in index.keys():
            record = json.loads(
                index[raw_key].decode(
                    "utf-8"
                )
            )

            text = build_embedding_text(
                record
            )

            print(
                "Embedding behavior:",
                record["behavior_key"],
            )

            vector = normalize(
                ollama_embed(text)
            )

            records.append(
                {
                    "behavior_key":
                        record[
                            "behavior_key"
                        ],

                    "embedding_text":
                        text,

                    "embedding":
                        vector,
                }
            )

    with open(
        OUTPUT_FILE,
        "w",
        encoding="utf-8",
    ) as f:
        json.dump(
            {
                "model": MODEL,
                "records": records,
            },
            f,
        )

    print()
    print(
        f"Saved {len(records)} behavior embeddings"
    )

    print(
        f"Output: {OUTPUT_FILE}"
    )


if __name__ == "__main__":
    main()
