#!/usr/bin/env python3

import dbm
import json
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]

INDEX_PATH = str(
    REPO_DIR
    / "runtime_logs"
    / "task_intent_index"
)


def main():
    with dbm.open(
        INDEX_PATH,
        "r",
    ) as index:

        print(
            "Intent labels:",
            len(index),
        )

        for raw_key in index.keys():
            print()
            print("=" * 70)

            print(
                json.dumps(
                    json.loads(
                        index[
                            raw_key
                        ].decode(
                            "utf-8"
                        )
                    ),
                    indent=2,
                )
            )


if __name__ == "__main__":
    main()
