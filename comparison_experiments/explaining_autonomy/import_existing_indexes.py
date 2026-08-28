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


from explaining_autonomy.persistent_memory import (
    upsert_records,
)


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--session-id",
        action="append",
        default=[],
        help=(
            "Import only this session. Can be repeated. "
            "If omitted, import every existing *_rosout_embeddings.json."
        ),
    )

    args = parser.parse_args()

    root = (
        COMPARISON_ROOT
        / "runtime"
        / "explaining_autonomy"
    )

    if args.session_id:
        paths = [
            root
            / f"{session_id}_rosout_embeddings.json"
            for session_id
            in args.session_id
        ]

    else:
        paths = sorted(
            root.glob(
                "*_rosout_embeddings.json"
            )
        )

    total_added = 0

    for path in paths:
        if not path.exists():
            print(
                "Missing:",
                path,
            )
            continue

        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

        session_id = data.get(
            "session_id"
        )

        records = []

        for record in data.get(
            "records",
            [],
        ):
            item = dict(
                record
            )

            item[
                "session_id"
            ] = (
                item.get(
                    "session_id"
                )
                or session_id
            )

            records.append(
                item
            )

        stats = upsert_records(
            records
        )

        total_added += stats[
            "added"
        ]

        print(
            f"{path.name}: "
            f"added={stats['added']} "
            f"total={stats['total']} "
            f"sessions={stats['session_count']}"
        )

    print()
    print(
        "TOTAL NEW RECORDS ADDED:",
        total_added,
    )


if __name__ == "__main__":
    main()
