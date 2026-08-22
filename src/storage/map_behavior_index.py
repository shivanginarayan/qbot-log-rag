#!/usr/bin/env python3

import argparse
import dbm
import json
import sqlite3
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[2]
RUNTIME_DIR = REPO_DIR / "runtime_logs"
MAPS_DIR = REPO_DIR / "robot_navigation" / "maps"


def normalize_map_name(name):
    name = Path(name).stem
    return name


def load_labels(map_name):
    map_name = normalize_map_name(map_name)

    path = MAPS_DIR / f"{map_name}_labels.json"

    if not path.exists():
        raise FileNotFoundError(
            f"Label file not found: {path}"
        )

    data = json.loads(
        path.read_text(encoding="utf-8")
    )

    labels = data.get("labels", [])

    return {
        str(label.get("name", "")).strip().casefold(): label
        for label in labels
    }


def get_session_end(conn, session_id):
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


def get_row_range(
    conn,
    table,
    id_column,
    time_column,
    start_ns,
    end_ns,
):
    row = conn.execute(
        f"""
        SELECT
            MIN({id_column}),
            MAX({id_column}),
            COUNT(*)
        FROM {table}
        WHERE {time_column} >= ?
          AND {time_column} <= ?
        """,
        (start_ns, end_ns),
    ).fetchone()

    if not row or row[2] == 0:
        return None

    return {
        "first_id": row[0],
        "last_id": row[1],
        "count": row[2],
    }

def find_navigation_occurrences(conn, session_id):
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

    session_end_ns = get_session_end(conn, session_id)
    occurrences = []

    for i, row in enumerate(rows):
        (
            event_id,
            event_time_ns,
            event_type,
            map_name,
            label_id,
            label_name,
            task_type,
            status,
            payload_json,
        ) = row

        # A command is only intent.
        # An executed occurrence begins only when navigation actually starts.
        if event_type != "NAVIGATION_STARTED":
            continue

        if task_type != "navigate_to_location":
            continue

        start_ns = event_time_ns
        end_ns = None
        outcome = "unknown_interrupted"
        final_status = None
        final_payload = None

        label_key = str(label_name or "").strip().casefold()

        try:
            started_payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            started_payload = {}

        # Look for the matching completion event.
        for later in rows[i + 1:]:
            (
                later_event_id,
                later_time_ns,
                later_event_type,
                later_map_name,
                later_label_id,
                later_label_name,
                later_task_type,
                later_status,
                later_payload_json,
            ) = later

            later_label_key = (
                str(later_label_name or "")
                .strip()
                .casefold()
            )

            if (
                later_event_type == "NAVIGATION_FINISHED"
                and later_task_type == "navigate_to_location"
                and later_label_key == label_key
            ):
                end_ns = later_time_ns
                final_status = later_status
                final_payload = later_payload_json

                if str(later_status) == "4":
                    outcome = "succeeded"
                elif str(later_status) == "5":
                    outcome = "canceled"
                elif str(later_status) == "6":
                    outcome = "failed"
                else:
                    outcome = "finished_unknown"

                break

            # A new executed navigation started before this one finished.
            if (
                later_event_type == "NAVIGATION_STARTED"
                and later_task_type == "navigate_to_location"
            ):
                end_ns = later_time_ns
                break

        if end_ns is None:
            end_ns = session_end_ns or start_ns

        occurrences.append(
            {
                "command_event_id": event_id,
                "start_ns": start_ns,
                "end_ns": end_ns,

                # Prefer historical payload metadata when available.
                "map_name": (
                    started_payload.get("map")
                    or map_name
                ),

                "label_id": (
                    started_payload.get("label_id")
                    or label_id
                ),

                "label_name": (
                    started_payload.get("name")
                    or label_name
                ),

                "label_kind": started_payload.get("kind"),
                "label_detail": started_payload.get("detail"),
                "world": started_payload.get("world"),
                "yaw": started_payload.get("yaw"),

                "task_type": task_type,
                "outcome": outcome,
                "final_status": final_status,
                "final_payload": final_payload,
            }
        )

    return occurrences


def resolve_label(
    labels,
    occurrence,
):
    label_name = occurrence["label_name"]

    key = (
        str(label_name or "")
        .strip()
        .casefold()
    )

    label = labels.get(key)

    if label is None:
        return {
            "id": occurrence.get("label_id"),
            "name": label_name,
            "kind": None,
            "detail": None,
            "world": None,
            "yaw": None,
        }

    return {
        "id": label.get("id"),
        "name": label.get("name"),
        "kind": label.get("kind"),
        "detail": label.get("detail"),
        "world": label.get("world"),
        "yaw": label.get("yaw"),
    }


def store_map_occurrence(
    map_name,
    label,
    occurrence,
):
    map_name = normalize_map_name(map_name)

    map_dir = (
        RUNTIME_DIR
        / "map_indexes"
        / map_name
    )

    map_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    index_path = str(
        map_dir / "label_index"
    )

    label_key = (
        str(label["name"])
        .strip()
        .casefold()
    )

    with dbm.open(index_path, "c") as index:
        key = label_key.encode("utf-8")

        if key in index:
            record = json.loads(
                index[key].decode("utf-8")
            )
        else:
            record = {
                "map": map_name,
                "label": label,
                "tasks": {},
            }

        task_type = occurrence["task"]["type"]

        if task_type not in record["tasks"]:
            record["tasks"][task_type] = {
                "occurrences": []
            }

        occurrences = record["tasks"][
            task_type
        ]["occurrences"]

        occurrence_id = occurrence[
            "occurrence_id"
        ]

        exists = any(
            item["occurrence_id"]
            == occurrence_id
            for item in occurrences
        )

        if not exists:
            occurrences.append(
                occurrence
            )

        index[key] = json.dumps(
            record,
            indent=2,
        ).encode("utf-8")

    return not exists


def index_session(
    session_id,
    map_name,
):
    map_name = normalize_map_name(
        map_name
    )

    db_path = (
        RUNTIME_DIR
        / f"session_{session_id}"
        / "robot.db"
    )

    if not db_path.exists():
        raise FileNotFoundError(
            f"Database not found: {db_path}"
        )

    labels = load_labels(
        map_name
    )

    conn = sqlite3.connect(
        db_path
    )

    occurrences = (
        find_navigation_occurrences(
            conn,
            session_id,
        )
    )

    if not occurrences:
        print(
            "No navigate_to_location "
            "occurrences found."
        )
        conn.close()
        return

    for occurrence in occurrences:
        label = resolve_label(
            labels,
            occurrence,
        )

        start_ns = occurrence[
            "start_ns"
        ]

        end_ns = occurrence[
            "end_ns"
        ]

        occurrence_record = {
            "occurrence_id":
                f"{session_id}:task_event:"
                f"{occurrence['command_event_id']}",

            "session_id":
                session_id,

            "time_range": {
                "start_ns":
                    start_ns,
                "end_ns":
                    end_ns,
            },

            "task": {
                "type":
                    occurrence["task_type"],
                "label_id":
                    label.get("id"),
                "label_name":
                    label.get("name"),
            },

            "outcome": {
                "status":
                    occurrence["outcome"],
                "raw_status":
                    occurrence["final_status"],
            },

            "sqlite_refs": {
                "task_events":
                    get_row_range(
                        conn,
                        "task_events",
                        "task_event_id",
                        "event_time_ns",
                        start_ns,
                        end_ns,
                    ),

                "odom_samples":
                    get_row_range(
                        conn,
                        "odom_samples",
                        "odom_id",
                        "received_at_ns",
                        start_ns,
                        end_ns,
                    ),

                "cmd_vel_intervals":
                    get_row_range(
                        conn,
                        "cmd_vel_intervals",
                        "cmd_vel_id",
                        "started_at_ns",
                        start_ns,
                        end_ns,
                    ),

                "lidar_summary_intervals":
                    get_row_range(
                        conn,
                        "lidar_summary_intervals",
                        "lidar_id",
                        "started_at_ns",
                        start_ns,
                        end_ns,
                    ),

                "pose_samples":
                    get_row_range(
                        conn,
                        "pose_samples",
                        "pose_id",
                        "received_at_ns",
                        start_ns,
                        end_ns,
                    ),
            },

            "source": {
                "sqlite_db":
                    str(db_path),

                "rosbag":
                    str(
                        RUNTIME_DIR
                        / f"session_{session_id}"
                        / "rosbag"
                    ),
            },
        }

        added = store_map_occurrence(
            map_name,
            label,
            occurrence_record,
        )

        print()
        print(
            f"Map: {map_name}"
        )
        print(
            f"Label: {label.get('name')}"
        )
        print(
            f"Task: {occurrence['task_type']}"
        )
        print(
            f"Outcome: {occurrence['outcome']}"
        )
        print(
            f"Occurrence: "
            f"{occurrence_record['occurrence_id']}"
        )

        if added:
            print(
                "Added to map-specific index."
            )
        else:
            print(
                "Occurrence already indexed."
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
        required=True,
    )

    args = parser.parse_args()

    index_session(
        args.session_id,
        args.map,
    )


if __name__ == "__main__":
    main()
