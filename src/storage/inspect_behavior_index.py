import dbm
import json
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
INDEX_PATH = str(REPO_DIR / "runtime_logs" / "behavior_index")


with dbm.open(INDEX_PATH, "r") as index:
    print(f"Behavior keys: {len(index)}")
    print()

    for raw_key in index.keys():
        key = raw_key.decode("utf-8")
        record = json.loads(
            index[raw_key].decode("utf-8")
        )

        print("=" * 70)
        print(f"KEY: {key}")
        print()

        print("BEHAVIOR:")
        print(
            json.dumps(
                record["behavior"],
                indent=2,
            )
        )

        print()
        print(
            f"OCCURRENCES: "
            f"{len(record['occurrences'])}"
        )

        for i, occurrence in enumerate(
            record["occurrences"],
            start=1,
        ):
            print()
            print(
                f"Occurrence {i}:"
            )
            print(
                json.dumps(
                    occurrence,
                    indent=2,
                )
            )
