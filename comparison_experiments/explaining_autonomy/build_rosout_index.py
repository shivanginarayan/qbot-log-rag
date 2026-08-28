#!/usr/bin/env python3

import argparse
import json
import sys
from pathlib import Path


HERE = Path(__file__).resolve()
COMPARISON_ROOT = HERE.parents[1]

if str(COMPARISON_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(COMPARISON_ROOT),
    )


from common.embedding_client import (
    embed,
    MAX_CHARS_PER_CHUNK,
)

from common.session_utils import (
    repo_root,
    resolve_session_id,
)

from explaining_autonomy.rosout_reader import (
    read_rosout_records,
)

from explaining_autonomy.persistent_memory import (
    upsert_records,
)


def index_path_for_session(
    session_id,
):
    root = (
        COMPARISON_ROOT
        / "runtime"
        / "explaining_autonomy"
    )

    root.mkdir(
        parents=True,
        exist_ok=True,
    )

    return (
        root
        / "{}_rosout_embeddings.json".format(
            session_id
        )
    )


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--session-id",
        default="latest",
    )

    parser.add_argument(
        "--no-persistent-memory",
        action="store_true",
        help=(
            "Build only the per-session index and do not "
            "add this session to cumulative /rosout memory."
        ),
    )

    args = parser.parse_args()

    session_id = resolve_session_id(
        args.session_id
    )

    bag_dir = (
        repo_root()
        / "comparison_experiments"
        / "runtime"
        / "rosout_bags"
        / "session_{}".format(
            session_id
        )
        / "rosout"
    )

    if not bag_dir.exists():
        raise RuntimeError(
            "No comparison /rosout recording found for "
            "session {}: {}".format(
                session_id,
                bag_dir,
            )
        )

    data = read_rosout_records(
        bag_dir
    )

    print()
    print(
        "ROSOUT RECORDS:",
        data["record_count"],
    )

    print(
        "SKIPPED ADJACENT DUPLICATES:",
        data[
            "skipped_adjacent_duplicates"
        ],
    )

    indexed = []

    for i, record in enumerate(
        data["records"]
    ):
        text = record["text"]
        text_length = len(text)

        if (
            text_length
            > MAX_CHARS_PER_CHUNK
        ):
            chunk_count = (
                text_length
                + MAX_CHARS_PER_CHUNK
                - 1
            ) // MAX_CHARS_PER_CHUNK

            print(
                "Long ROS log record {}: {} chars -> {} chunks".format(
                    i,
                    text_length,
                    chunk_count,
                )
            )

        try:
            vector = embed(
                text
            )

        except Exception as exc:
            print()
            print(
                "Embedding failed at ROSOUT record:",
                i,
            )
            print(
                "Node:",
                record.get("name"),
            )
            print(
                "Message chars:",
                len(
                    record.get(
                        "message",
                        "",
                    )
                ),
            )
            print(
                "Text preview:",
                text[:500],
            )

            raise RuntimeError(
                "Could not embed ROSOUT record {}: {}".format(
                    i,
                    exc,
                )
            ) from exc

        indexed.append(
            {
                "record_id":
                    i,

                "session_id":
                    session_id,

                **record,

                "embedding":
                    vector,
            }
        )

        if (
            (i + 1) % 100
            == 0
        ):
            print(
                "Embedded {} / {}".format(
                    i + 1,
                    data["record_count"],
                )
            )

    output = {
        "session_id":
            session_id,

        "source":
            "/rosout",

        "dedup_rule":
            (
                "skip immediately repeated identical "
                "log records"
            ),

        "long_record_embedding":
            (
                "records longer than {} characters are "
                "chunked and mean-pooled"
            ).format(
                MAX_CHARS_PER_CHUNK
            ),

        "skipped_adjacent_duplicates":
            data[
                "skipped_adjacent_duplicates"
            ],

        "records":
            indexed,
    }

    path = index_path_for_session(
        session_id
    )

    path.write_text(
        json.dumps(
            output
        ),
        encoding="utf-8",
    )

    print()
    print(
        "Saved:",
        path,
    )

    print(
        "Indexed records:",
        len(indexed),
    )

    if not args.no_persistent_memory:
        stats = upsert_records(
            indexed
        )

        print()
        print(
            "PERSISTENT /ROSOUT MEMORY"
        )

        print(
            "Added:",
            stats[
                "added"
            ],
        )

        print(
            "Total records:",
            stats[
                "total"
            ],
        )

        print(
            "Sessions:",
            stats[
                "session_count"
            ],
        )


if __name__ == "__main__":
    main()
