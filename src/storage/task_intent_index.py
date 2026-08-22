#!/usr/bin/env python3

import argparse
import dbm
import json
import sqlite3
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_DIR / "runtime_logs"

INDEX_PATH = str(
    RUNTIME_DIR / "task_intent_index"
)


def normalize(value):
    return str(
        value or ""
    ).strip().casefold()


def get_session_end(
    conn,
    session_id,
):
    row = conn.execute(
        """
        SELECT ended_at_ns
        FROM sessions
        WHERE session_id = ?
        """,
        (session_id,),
    ).fetchone()

    if not row:
        return None

    return row[0]


def find_navigation_commands(
    conn,
    session_id,
    supplied_map=None,
):
    rows = conn.execute(
        """
        SELECT
            task_event_id,
            event_time_ns,
            event_type,
            map_name,
            label_id,
            label_name,
            task_type,
            status,
            payload_json
        FROM task_events
        ORDER BY event_time_ns
        """
    ).fetchall()

    session_end = get_session_end(
        conn,
        session_id,
    )

    results = []

    for i, row in enumerate(rows):
        (
            event_id,
            command_time,
            event_type,
            map_name,
            label_id,
            label_name,
            task_type,
            status,
            payload_json,
        ) = row

        if event_type != "NAVIGATION_COMMAND":
            continue

        if task_type != "navigate_to_location":
            continue

        label_key = normalize(
            label_name
        )

        execution_start_ns = None
        finish_ns = None

        start_event_id = None
        finish_event_id = None

        final_status = None

        # Default state:
        # command exists, but no recorded
        # execution start yet.
        state = (
            "no_execution_start_recorded"
        )

        outcome = (
            "no_execution_start_recorded"
        )

        # Search until the next navigation command.
        for later in rows[i + 1:]:
            (
                later_id,
                later_time,
                later_type,
                later_map,
                later_label_id,
                later_label,
                later_task,
                later_status,
                later_payload,
            ) = later

            if (
                later_type
                == "NAVIGATION_COMMAND"
                and later_task
                == "navigate_to_location"
            ):
                break

            later_label_key = normalize(
                later_label
            )

            if (
                later_type
                == "NAVIGATION_STARTED"
                and later_task
                == "navigate_to_location"
                and later_label_key
                == label_key
            ):
                execution_start_ns = (
                    later_time
                )

                start_event_id = (
                    later_id
                )

                state = (
                    "execution_started"
                )

                outcome = (
                    "execution_started_no_finish_recorded"
                )

            if (
                execution_start_ns
                is not None
                and later_type
                == "NAVIGATION_FINISHED"
                and later_task
                == "navigate_to_location"
                and later_label_key
                == label_key
            ):
                finish_ns = later_time
                finish_event_id = later_id
                final_status = later_status

                state = "finished"

                if str(
                    later_status
                ) == "4":
                    outcome = "succeeded"

                elif str(
                    later_status
                ) == "5":
                    outcome = "canceled"

                elif str(
                    later_status
                ) == "6":
                    outcome = "failed"

                else:
                    outcome = (
                        "finished_unknown"
                    )

                break

        if finish_ns is not None:
            evidence_end_ns = (
                finish_ns
            )

        elif execution_start_ns is not None:
            evidence_end_ns = (
                session_end
                or execution_start_ns
            )

        else:
            evidence_end_ns = (
                session_end
                or command_time
            )

        results.append(
            {
                "command_event_id":
                    event_id,

                "session_id":
                    session_id,

                "label_name":
                    label_name,

                "label_id":
                    label_id,

                "map_name":
                    map_name
                    or supplied_map,

                "task_type":
                    task_type,

                "command_time_ns":
                    command_time,

                "execution_start_ns":
                    execution_start_ns,

                "finish_ns":
                    finish_ns,

                "evidence_end_ns":
                    evidence_end_ns,

                "start_event_id":
                    start_event_id,

                "finish_event_id":
                    finish_event_id,

                "state":
                    state,

                "outcome":
                    outcome,

                "final_status":
                    final_status,
            }
        )

    return results


def store_intent(
    item,
):
    label_key = normalize(
        item["label_name"]
    )

    if not label_key:
        return False

    with dbm.open(
        INDEX_PATH,
        "c",
    ) as index:

        key = label_key.encode(
            "utf-8"
        )

        if key in index:
            record = json.loads(
                index[key].decode(
                    "utf-8"
                )
            )
        else:
            record = {
                "label_key":
                    label_key,

                "label_name":
                    item[
                        "label_name"
                    ],

                "task_type":
                    "navigate_to_location",

                "occurrences":
                    [],
            }

        occurrence_id = (
            f"{item['session_id']}:"
            f"task_command:"
            f"{item['command_event_id']}"
        )

        occurrence = {
            "occurrence_id":
                occurrence_id,

            "session_id":
                item["session_id"],

            "map":
                item["map_name"],

            "label_id":
                item["label_id"],

            "label_name":
                item["label_name"],

            "task_type":
                item["task_type"],

            "command_time_ns":
                item[
                    "command_time_ns"
                ],

            "execution_start_ns":
                item[
                    "execution_start_ns"
                ],

            "finish_ns":
                item["finish_ns"],

            "evidence_time_range": {
                "start_ns":
                    item[
                        "command_time_ns"
                    ],

                "end_ns":
                    item[
                        "evidence_end_ns"
                    ],
            },

            "state":
                item["state"],

            "outcome":
                item["outcome"],

            "final_status":
                item[
                    "final_status"
                ],
        }

        exists = any(
            old.get(
                "occurrence_id"
            ) == occurrence_id
            for old
            in record[
                "occurrences"
            ]
        )

        if not exists:
            record[
                "occurrences"
            ].append(
                occurrence
            )

        index[key] = json.dumps(
            record,
            indent=2,
        ).encode("utf-8")

    return not exists


def index_session(
    session_id,
    supplied_map=None,
):
    db_path = (
        RUNTIME_DIR
        / f"session_{session_id}"
        / "robot.db"
    )

    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found: "
            f"{db_path}"
        )

    conn = sqlite3.connect(
        db_path
    )

    commands = (
        find_navigation_commands(
            conn,
            session_id,
            supplied_map,
        )
    )

    if not commands:
        print(
            "No navigation commands "
            "found."
        )

        conn.close()
        return

    for item in commands:
        added = store_intent(
            item
        )

        print()
        print(
            "Label:",
            item[
                "label_name"
            ],
        )

        print(
            "State:",
            item[
                "state"
            ],
        )

        print(
            "Outcome:",
            item[
                "outcome"
            ],
        )

        print(
            "Command event:",
            item[
                "command_event_id"
            ],
        )

        if added:
            print(
                "Added to task-intent "
                "index."
            )
        else:
            print(
                "Already indexed."
            )

    conn.close()


def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--session-id",
        required=True,
    )

    parser.add_argument(
        "--map",
        default=None,
    )

    args = parser.parse_args()

    index_session(
        args.session_id,
        args.map,
    )


if __name__ == "__main__":
    main()
