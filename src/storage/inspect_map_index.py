#!/usr/bin/env python3

import argparse
import dbm
import json
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_DIR / "runtime_logs"


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--map",
        required=True,
    )

    args = parser.parse_args()

    map_name = Path(args.map).stem

    index_path = str(
        RUNTIME_DIR
        / "map_indexes"
        / map_name
        / "label_index"
    )

    with dbm.open(
        index_path,
        "r",
    ) as index:

        print(
            f"Map: {map_name}"
        )
        print(
            f"Labels: {len(index)}"
        )
        print()

        for raw_key in index.keys():
            record = json.loads(
                index[raw_key].decode(
                    "utf-8"
                )
            )

            print("=" * 70)
            print(
                json.dumps(
                    record,
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
