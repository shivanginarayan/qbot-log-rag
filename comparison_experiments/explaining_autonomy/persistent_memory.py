#!/usr/bin/env python3

import json
import threading
import time
from pathlib import Path


HERE = Path(__file__).resolve()
COMPARISON_ROOT = HERE.parents[1]

_MEMORY_LOCK = threading.Lock()


def memory_path():
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
        / "persistent_rosout_memory.json"
    )


def _empty_memory():
    return {
        "source":
            "/rosout",

        "mode":
            "persistent_cumulative",

        "updated_at_ns":
            time.time_ns(),

        "records":
            [],
    }


def load_memory():
    path = memory_path()

    if not path.exists():
        return _empty_memory()

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )

    except Exception:
        return _empty_memory()

    if not isinstance(
        data,
        dict,
    ):
        return _empty_memory()

    if not isinstance(
        data.get(
            "records"
        ),
        list,
    ):
        data[
            "records"
        ] = []

    return data


def _record_key(
    record,
):
    return (
        str(
            record.get(
                "session_id"
            )
            or ""
        ),
        int(
            record.get(
                "timestamp_ns"
            )
            or 0
        ),
        str(
            record.get(
                "name"
            )
            or ""
        ),
        str(
            record.get(
                "message"
            )
            or ""
        ),
        str(
            record.get(
                "file"
            )
            or ""
        ),
        str(
            record.get(
                "function"
            )
            or ""
        ),
        str(
            record.get(
                "line"
            )
            or ""
        ),
    )


def _write_atomic(
    data,
):
    path = memory_path()

    temp = path.with_suffix(
        path.suffix + ".tmp"
    )

    temp.write_text(
        json.dumps(
            data
        ),
        encoding="utf-8",
    )

    temp.replace(
        path
    )


def upsert_records(
    records,
):
    """
    Add new /rosout records to the cumulative memory.

    Duplicate records are ignored using:
        session_id + timestamp + node + message + source location
    """

    with _MEMORY_LOCK:
        data = load_memory()

        existing = data.get(
            "records",
            [],
        )

        seen = {
            _record_key(
                record
            )
            for record
            in existing
        }

        added = 0

        for record in records:
            key = _record_key(
                record
            )

            if key in seen:
                continue

            existing.append(
                record
            )

            seen.add(
                key
            )

            added += 1

        existing.sort(
            key=lambda item:
                (
                    int(
                        item.get(
                            "timestamp_ns"
                        )
                        or 0
                    ),
                    str(
                        item.get(
                            "session_id"
                        )
                        or ""
                    ),
                )
        )

        data[
            "records"
        ] = existing

        data[
            "record_count"
        ] = len(
            existing
        )

        data[
            "session_ids"
        ] = sorted(
            {
                str(
                    item.get(
                        "session_id"
                    )
                )
                for item
                in existing
                if item.get(
                    "session_id"
                )
            }
        )

        data[
            "updated_at_ns"
        ] = time.time_ns()

        _write_atomic(
            data
        )

        return {
            "added":
                added,

            "total":
                len(
                    existing
                ),

            "session_count":
                len(
                    data[
                        "session_ids"
                    ]
                ),
        }
