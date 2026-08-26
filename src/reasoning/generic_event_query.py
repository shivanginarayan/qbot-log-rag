#!/usr/bin/env python3

import json
import os
import sqlite3
from pathlib import Path

import requests
try:
    from .task_timeline import (
        build_task_lifecycles,
        compact_lifecycle,
    )

except ImportError:
    from task_timeline import (
        build_task_lifecycles,
        compact_lifecycle,
    )

REPO_DIR = Path(__file__).resolve().parents[2]

RUNTIME_DIR = (
    REPO_DIR
    / "runtime_logs"
)

NVIDIA_MODEL = (
    "nvidia/nemotron-3-super-120b-a12b"
)

NVIDIA_URL = (
    "https://integrate.api.nvidia.com/"
    "v1/chat/completions"
)


# ============================================================
# NORMALIZATION
# ============================================================

def normalize_map_name(
    value,
):
    if value is None:
        return None

    value = str(
        value
    ).strip()

    if not value:
        return None

    return Path(
        value
    ).stem.casefold()


def normalize_text(
    value,
):
    if value is None:
        return None

    value = str(
        value
    ).strip()

    if not value:
        return None

    return value.casefold()


# ============================================================
# LOAD ALL TASK EVENTS
# ============================================================

def session_databases():
    return sorted(
        RUNTIME_DIR.glob(
            "session_*/robot.db"
        )
    )


def safe_json(
    raw,
):
    if not raw:
        return {}

    try:
        value = json.loads(
            raw
        )

        if isinstance(
            value,
            dict,
        ):
            return value

    except Exception:
        pass

    return {}


def load_session_events(
    db_path,
    current_session_id=None,
    current_map=None,
):
    conn = sqlite3.connect(
        db_path,
        timeout=5.0,
    )

    conn.row_factory = (
        sqlite3.Row
    )

    session_row = conn.execute(
        """
        SELECT
            session_id,
            started_at_ns,
            ended_at_ns,
            status,
            map_name
        FROM sessions
        LIMIT 1
        """
    ).fetchone()

    if session_row is None:

        conn.close()

        return []

    session_id = (
        session_row[
            "session_id"
        ]
    )

    session_map = (
        session_row[
            "map_name"
        ]
    )

    rows = conn.execute(
        """
        SELECT
            task_event_id,
            session_id,
            event_time_ns,
            source_topic,
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

    conn.close()

    # --------------------------------------------------------
    # Find explicit map evidence anywhere in this session.
    # --------------------------------------------------------

    explicit_maps = []

    parsed_rows = []

    for row in rows:

        payload = safe_json(
            row[
                "payload_json"
            ]
        )

        explicit_map = (
            row[
                "map_name"
            ]
            or payload.get(
                "map"
            )
        )

        if explicit_map:

            explicit_maps.append(
                (
                    int(
                        row[
                            "event_time_ns"
                        ]
                    ),
                    explicit_map,
                )
            )

        parsed_rows.append(
            (
                row,
                payload,
            )
        )

    # --------------------------------------------------------
    # Determine map context for every event.
    #
    # Priority:
    #
    # 1. map directly stored on event
    # 2. payload map
    # 3. active runtime map for current session
    # 4. session.map_name
    # 5. nearest explicit map event in same session
    #
    # We preserve map_source so inference remains visible.
    # --------------------------------------------------------

    events = []

    for row, payload in parsed_rows:

        event_time_ns = int(
            row[
                "event_time_ns"
            ]
        )

        resolved_map = None
        map_source = None

        if row[
            "map_name"
        ]:

            resolved_map = (
                row[
                    "map_name"
                ]
            )

            map_source = (
                "task_event.map_name"
            )

        elif payload.get(
            "map"
        ):

            resolved_map = (
                payload.get(
                    "map"
                )
            )

            map_source = (
                "task_event.payload.map"
            )

        elif (
            current_session_id
            and session_id
            == current_session_id
            and current_map
        ):

            resolved_map = (
                current_map
            )

            map_source = (
                "current_runtime_map"
            )

        elif session_map:

            resolved_map = (
                session_map
            )

            map_source = (
                "session.map_name"
            )

        elif explicit_maps:

            nearest = min(
                explicit_maps,
                key=lambda item:
                    abs(
                        item[0]
                        - event_time_ns
                    ),
            )

            resolved_map = (
                nearest[1]
            )

            map_source = (
                "nearest_map_event"
            )

        events.append(
            {
                "task_event_id":
                    row[
                        "task_event_id"
                    ],

                "session_id":
                    session_id,

                "session_status":
                    session_row[
                        "status"
                    ],

                "session_started_at_ns":
                    session_row[
                        "started_at_ns"
                    ],

                "session_ended_at_ns":
                    session_row[
                        "ended_at_ns"
                    ],

                "event_time_ns":
                    event_time_ns,

                "source_topic":
                    row[
                        "source_topic"
                    ],

                "event_type":
                    row[
                        "event_type"
                    ],

                "task_type":
                    row[
                        "task_type"
                    ],

                "map":
                    resolved_map,

                "map_normalized":
                    normalize_map_name(
                        resolved_map
                    ),

                "map_source":
                    map_source,

                "label_id":
                    row[
                        "label_id"
                    ],

                "label_name":
                    row[
                        "label_name"
                    ],

                "status":
                    row[
                        "status"
                    ],

                "payload":
                    payload,
            }
        )

    return events


def load_all_events(
    current_session_id=None,
    current_map=None,
):
    events = []

    for db_path in session_databases():

        try:

            events.extend(
                load_session_events(
                    db_path,
                    current_session_id=(
                        current_session_id
                    ),
                    current_map=(
                        current_map
                    ),
                )
            )

        except Exception:
            continue

    events.sort(
        key=lambda event:
            event.get(
                "event_time_ns",
                0,
            )
    )

    return events


# ============================================================
# QUERY PLANNER
# ============================================================

QUERY_PLANNER_PROMPT = """
You convert a natural-language robot-log question into a
structured query over recorded task events.

Return JSON ONLY.

Available event fields:

- event_type
- task_type
- map
- label_name
- status
- session_id
- event_time_ns

Important recorded event types include:

LOCALIZE_COMMAND
STOP_COMMAND
NAVIGATION_COMMAND
NAVIGATION_STARTED
NAVIGATION_FINISHED
NAVIGATION_STATUS
NAVIGATION_STATUS_RAW

Important task types include:

localization
navigate_to_location
stop_navigation

Navigation result status values may include:

4 = succeeded
5 = canceled
6 = failed

The distinction between command and result is important.

Examples of meaning:

"How many times was localization run?"
means count localization REQUESTS/ATTEMPTS.
Use:
event_type = LOCALIZE_COMMAND
task_type = localization

"How many localization attempts failed?"
means count finished localization events whose status is failed.
Use:
event_type = NAVIGATION_FINISHED
task_type = localization
status = 6

"How many times was the robot told to go to label3?"
means:
event_type = NAVIGATION_COMMAND
task_type = navigate_to_location
label_name = label3

"How many navigation attempts started?"
means:
event_type = NAVIGATION_STARTED
task_type = navigate_to_location

"How many navigation attempts succeeded?"
means:
event_type = NAVIGATION_FINISHED
task_type = navigate_to_location
status = 4

"What commands were given?"
means command event types, not STARTED/FINISHED events.

Operations:

count
list
latest
group_count

Scope:

all_sessions
current_session

group_by may be one of:

event_type
task_type
map
label_name
status
session_id

Do not invent map, label, task, status, or session constraints
that the user did not request.

A word such as "now", "current", or "this session" can justify
current_session.

A question such as "how many times", "ever", "previously",
"on map X", or "history" normally requires all_sessions unless
the user explicitly says this/current session.

For questions that are NOT primarily structured event questions,
set use_structured_events=false.

Examples that are NOT primarily structured event queries:

"Why did the robot stop?"
"Is AMCL active right now?"
"What obstacle is in front of it?"
"Where is the robot now?"
"What maps are saved on disk?"

Those may require detailed sensor/runtime/filesystem evidence instead.

Return exactly:

{
  "use_structured_events": true or false,
  "reason": "short explanation",
  "operation": "count|list|latest|group_count",
  "scope": "all_sessions|current_session",
  "filters": {
    "event_types": [],
    "task_types": [],
    "maps": [],
    "labels": [],
    "statuses": []
  },
  "group_by": null,
  "limit": 20
}
""".strip()


def call_planner(
    question,
):
    api_key = os.environ.get(
        "NVIDIA_API_KEY"
    )

    if not api_key:

        raise RuntimeError(
            "NVIDIA_API_KEY is not set."
        )

    prompt = (
        QUERY_PLANNER_PROMPT
        + "\n\nUSER QUESTION:\n"
        + question
    )

    response = requests.post(
        NVIDIA_URL,
        headers={
            "Authorization":
                f"Bearer {api_key}",

            "Content-Type":
                "application/json",
        },
        json={
            "model":
                NVIDIA_MODEL,

            "messages": [
                {
                    "role":
                        "user",

                    "content":
                        prompt,
                }
            ],

            "temperature":
                0.0,

            "max_tokens":
                700,
        },
        timeout=120,
    )

    response.raise_for_status()

    text = (
        response.json()[
            "choices"
        ][0][
            "message"
        ][
            "content"
        ]
        .strip()
    )

    # --------------------------------------------------------
    # Tolerate accidental fenced JSON.
    # --------------------------------------------------------

    if text.startswith(
        "```"
    ):

        lines = (
            text.splitlines()
        )

        if lines:
            lines = lines[1:]

        if (
            lines
            and lines[-1]
            .strip()
            .startswith(
                "```"
            )
        ):
            lines = lines[:-1]

        text = "\n".join(
            lines
        ).strip()

    start = text.find(
        "{"
    )

    end = text.rfind(
        "}"
    )

    if (
        start < 0
        or end < start
    ):

        raise ValueError(
            "Planner did not return JSON."
        )

    plan = json.loads(
        text[
            start:
            end + 1
        ]
    )

    return sanitize_plan(
        plan
    )


def sanitize_plan(
    plan,
):
    allowed_operations = {
        "count",
        "list",
        "latest",
        "group_count",
    }

    allowed_scope = {
        "all_sessions",
        "current_session",
    }

    allowed_group_by = {
        None,
        "event_type",
        "task_type",
        "map",
        "label_name",
        "status",
        "session_id",
    }

    operation = plan.get(
        "operation"
    )

    if operation not in allowed_operations:

        operation = "list"

    scope = plan.get(
        "scope"
    )

    if scope not in allowed_scope:

        scope = "all_sessions"

    group_by = plan.get(
        "group_by"
    )

    if group_by not in allowed_group_by:

        group_by = None

    raw_filters = (
        plan.get(
            "filters"
        )
        or {}
    )

    def string_list(
        name,
    ):
        value = raw_filters.get(
            name,
            []
        )

        if not isinstance(
            value,
            list,
        ):
            return []

        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    try:

        limit = int(
            plan.get(
                "limit",
                20,
            )
        )

    except Exception:

        limit = 20

    limit = max(
        1,
        min(
            limit,
            100,
        ),
    )

    return {
        "use_structured_events":
            bool(
                plan.get(
                    "use_structured_events",
                    False,
                )
            ),

        "reason":
            str(
                plan.get(
                    "reason",
                    "",
                )
            ),

        "operation":
            operation,

        "scope":
            scope,

        "filters": {
            "event_types":
                string_list(
                    "event_types"
                ),

            "task_types":
                string_list(
                    "task_types"
                ),

            "maps":
                string_list(
                    "maps"
                ),

            "labels":
                string_list(
                    "labels"
                ),

            "statuses":
                string_list(
                    "statuses"
                ),
        },

        "group_by":
            group_by,

        "limit":
            limit,
    }


# ============================================================
# FILTERING
# ============================================================

def matches_any_exact(
    value,
    requested,
):
    if not requested:
        return True

    normalized_value = (
        normalize_text(
            value
        )
    )

    normalized_requested = {
        normalize_text(
            item
        )
        for item in requested
    }

    return (
        normalized_value
        in normalized_requested
    )


def matches_map(
    value,
    requested,
):
    if not requested:
        return True

    normalized_value = (
        normalize_map_name(
            value
        )
    )

    normalized_requested = {
        normalize_map_name(
            item
        )
        for item in requested
    }

    return (
        normalized_value
        in normalized_requested
    )


def filter_events(
    events,
    plan,
    current_session_id=None,
):
    filters = (
        plan.get(
            "filters",
            {}
        )
    )

    result = []

    for event in events:

        if (
            plan.get(
                "scope"
            )
            == "current_session"
        ):

            if not current_session_id:
                continue

            if (
                event.get(
                    "session_id"
                )
                != current_session_id
            ):
                continue

        if not matches_any_exact(
            event.get(
                "event_type"
            ),
            filters.get(
                "event_types",
                [],
            ),
        ):
            continue

        if not matches_any_exact(
            event.get(
                "task_type"
            ),
            filters.get(
                "task_types",
                [],
            ),
        ):
            continue

        if not matches_map(
            event.get(
                "map"
            ),
            filters.get(
                "maps",
                [],
            ),
        ):
            continue

        if not matches_any_exact(
            event.get(
                "label_name"
            ),
            filters.get(
                "labels",
                [],
            ),
        ):
            continue

        if not matches_any_exact(
            event.get(
                "status"
            ),
            filters.get(
                "statuses",
                [],
            ),
        ):
            continue

        result.append(
            event
        )

    return result


# ============================================================
# EXECUTE OPERATION
# ============================================================

def compact_event(
    event,
):
    return {
        "task_event_id":
            event.get(
                "task_event_id"
            ),

        "session_id":
            event.get(
                "session_id"
            ),

        "event_time_ns":
            event.get(
                "event_time_ns"
            ),

        "event_type":
            event.get(
                "event_type"
            ),

        "task_type":
            event.get(
                "task_type"
            ),

        "map":
            event.get(
                "map"
            ),

        "map_source":
            event.get(
                "map_source"
            ),

        "label_name":
            event.get(
                "label_name"
            ),

        "status":
            event.get(
                "status"
            ),
    }

# ============================================================
# TASK LIFECYCLE HELPERS
# ============================================================

def build_lifecycles_by_session(
    events,
):
    """
    Build task lifecycles separately inside each session.

    This prevents a command from one experiment from being
    accidentally paired with STARTED/FINISHED events from
    another experiment.
    """

    events_by_session = {}

    for event in events:

        session_id = event.get(
            "session_id"
        )

        if not session_id:
            continue

        events_by_session.setdefault(
            session_id,
            []
        ).append(
            event
        )

    lifecycles = []

    for session_id, session_events in (
        events_by_session.items()
    ):

        session_events.sort(
            key=lambda event:
                event.get(
                    "event_time_ns",
                    0,
                )
        )

        try:

            lifecycles.extend(
                build_task_lifecycles(
                    session_events
                )
            )

        except Exception as exc:

            print(
                "WARNING: Could not build "
                f"task lifecycle for session "
                f"{session_id}: {exc}"
            )

    return lifecycles


def lifecycle_contains_event(
    lifecycle,
    event,
):
    """
    Return True if an event belongs to this lifecycle.

    Checks:
        command
        execution_started
        completion
        status_events
    """

    event_session = event.get(
        "session_id"
    )

    event_id = event.get(
        "task_event_id"
    )

    if event_id is None:
        return False

    command = (
        lifecycle.get(
            "command"
        )
        or {}
    )

    # Never connect events across sessions.
    if (
        command.get(
            "session_id"
        )
        != event_session
    ):
        return False

    candidates = []

    candidates.append(
        command
    )

    started = lifecycle.get(
        "execution_started"
    )

    if started:
        candidates.append(
            started
        )

    completion = lifecycle.get(
        "completion"
    )

    if completion:
        candidates.append(
            completion
        )

    candidates.extend(
        lifecycle.get(
            "status_events",
            []
        )
        or []
    )

    for candidate in candidates:

        if (
            candidate.get(
                "task_event_id"
            )
            == event_id
        ):
            return True

    return False


def find_lifecycle_for_event(
    lifecycles,
    event,
):
    """
    Find the request → start → finish lifecycle
    containing a particular event.
    """

    for lifecycle in lifecycles:

        if lifecycle_contains_event(
            lifecycle,
            event,
        ):
            return lifecycle

    return None

def execute_plan(
    events,
    plan,
    current_session_id=None,
):
    matched = filter_events(
        events,
        plan,
        current_session_id=(
            current_session_id
        ),
    )

    operation = plan.get(
        "operation"
    )

    result = {
        "operation":
            operation,

        "scope":
            plan.get(
                "scope"
            ),

        "filters":
            plan.get(
                "filters"
            ),

        "matched_count":
            len(
                matched
            ),
    }

    # ========================================================
    # COUNT
    #
    # Exact structured event count.
    #
    # Do NOT replace this with lifecycle counting.
    # Example:
    #
    # COUNT LOCALIZE_COMMAND
    # = number of recorded localization requests.
    # ========================================================

    if operation == "count":

        result[
            "count"
        ] = len(
            matched
        )

        result[
            "matching_events"
        ] = [
            compact_event(
                event
            )
            for event
            in matched[-20:]
        ]

        return result


    # ========================================================
    # GROUP COUNT
    #
    # Also remains exact structured-event aggregation.
    # ========================================================

    if operation == "group_count":

        group_by = plan.get(
            "group_by"
        )

        groups = {}

        if group_by:

            for event in matched:

                value = event.get(
                    group_by
                )

                key = (
                    str(value)
                    if value is not None
                    else "null"
                )

                groups[
                    key
                ] = (
                    groups.get(
                        key,
                        0,
                    )
                    + 1
                )

        result[
            "group_by"
        ] = group_by

        result[
            "groups"
        ] = dict(
            sorted(
                groups.items(),
                key=lambda item:
                    (
                        -item[1],
                        item[0],
                    ),
            )
        )

        return result


    # ========================================================
    # Build task lifecycles only when an operation needs
    # relationship/context.
    #
    # This keeps COUNT/GROUP_COUNT simple and exact.
    # ========================================================

    lifecycles = (
        build_lifecycles_by_session(
            events
        )
    )


    # ========================================================
    # LATEST
    #
    # Return the latest matching event PLUS its complete
    # command → start → finish lifecycle when available.
    # ========================================================

    if operation == "latest":

        latest = (
            matched[-1]
            if matched
            else None
        )

        result[
            "latest_event"
        ] = (
            compact_event(
                latest
            )
            if latest
            else None
        )

        if latest:

            lifecycle = (
                find_lifecycle_for_event(
                    lifecycles,
                    latest,
                )
            )

            if lifecycle:

                result[
                    "task_lifecycle"
                ] = (
                    compact_lifecycle(
                        lifecycle
                    )
                )

        return result


    # ========================================================
    # LIST
    #
    # Return matching events.
    #
    # If any matching event belongs to a task lifecycle,
    # attach that lifecycle as additional context.
    # ========================================================

    limit = int(
        plan.get(
            "limit",
            20,
        )
    )

    selected_events = (
        matched[-limit:]
    )

    result[
        "events"
    ] = [
        compact_event(
            event
        )
        for event
        in selected_events
    ]


    related_lifecycles = []

    seen_lifecycles = set()


    for event in selected_events:

        lifecycle = (
            find_lifecycle_for_event(
                lifecycles,
                event,
            )
        )

        if not lifecycle:
            continue

        command = (
            lifecycle.get(
                "command"
            )
            or {}
        )

        lifecycle_key = (
            command.get(
                "session_id"
            ),
            command.get(
                "task_event_id"
            ),
        )

        if lifecycle_key in seen_lifecycles:
            continue

        seen_lifecycles.add(
            lifecycle_key
        )

        related_lifecycles.append(
            compact_lifecycle(
                lifecycle
            )
        )


    if related_lifecycles:

        result[
            "task_lifecycles"
        ] = (
            related_lifecycles
        )


    return result


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def plan_and_query_events(
    question,
    current_session_id=None,
    current_map=None,
):
    plan = call_planner(
        question
    )

    if not plan.get(
        "use_structured_events"
    ):

        return {
            "used":
                False,

            "plan":
                plan,
        }

    events = load_all_events(
        current_session_id=(
            current_session_id
        ),
        current_map=(
            current_map
        ),
    )

    result = execute_plan(
        events,
        plan,
        current_session_id=(
            current_session_id
        ),
    )

    return {
        "used":
            True,

        "plan":
            plan,

        "result":
            result,

        "event_store": {
            "database_count":
                len(
                    session_databases()
                ),

            "total_task_events":
                len(
                    events
                ),
        },
    }


# ============================================================
# CLI TEST
# ============================================================

def main():
    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--question",
        required=True,
    )

    parser.add_argument(
        "--session-id",
    )

    parser.add_argument(
        "--current-map",
    )

    args = parser.parse_args()

    result = plan_and_query_events(
        args.question,
        current_session_id=(
            args.session_id
        ),
        current_map=(
            args.current_map
        ),
    )

    print(
        json.dumps(
            result,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
