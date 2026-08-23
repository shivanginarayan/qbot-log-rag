#!/usr/bin/env python3

import argparse
import dbm
import json
import math
import os
import urllib.request
from pathlib import Path

import requests

from build_evidence_packet import (
    build_packet,
    build_live_packet,
)


MODEL_EMBED = "bge-m3"

NVIDIA_MODEL = (
    "nvidia/nemotron-3-super-120b-a12b"
)

NVIDIA_URL = (
    "https://integrate.api.nvidia.com/"
    "v1/chat/completions"
)

REPO_DIR = Path(__file__).resolve().parents[2]

RUNTIME_DIR = (
    REPO_DIR / "runtime_logs"
)

GLOBAL_EMBEDDINGS = (
    RUNTIME_DIR
    / "behavior_embeddings.json"
)

GLOBAL_INDEX = str(
    RUNTIME_DIR
    / "behavior_index"
)

INTENT_EMBEDDINGS = (
    RUNTIME_DIR
    / "task_intent_embeddings.json"
)

INTENT_INDEX = str(
    RUNTIME_DIR
    / "task_intent_index"
)

MAPS_DIR = (
    REPO_DIR
    / "robot_navigation"
    / "maps"
)

def search_intents(
    query_vector,
):
    if not INTENT_EMBEDDINGS.exists():
        return []

    data = json.loads(
        INTENT_EMBEDDINGS.read_text(
            encoding="utf-8"
        )
    )

    results = []

    for record in data.get(
        "records",
        [],
    ):
        score = cosine(
            query_vector,
            record["embedding"],
        )

        results.append(
            {
                "score": score,
                **record,
            }
        )

    results.sort(
        key=lambda item:
            item["score"],
        reverse=True,
    )

    return results

def load_intent_record(label_key,):
    with dbm.open(
        INTENT_INDEX,
        "r",
    ) as index:

        key = label_key.encode(
            "utf-8"
        )

        if key not in index:
            return None

        return json.loads(
            index[key].decode(
                "utf-8"
            )
        )

def asks_about_nonexecution(
    question,
):
    q = question.casefold()

    phrases = [
        "didn't",
        "did not",
        "didnt",
        "not go",
        "never went",
        "never started",
        "didn't start",
        "did not start",
        "why wasn't",
        "why was not",
        "failed to start",
    ]

    return any(
        phrase in q
        for phrase in phrases
    )

def collect_intent_occurrences(
    intent_hit,
    requested_map=None,
):
    if not intent_hit:
        return []

    record = load_intent_record(
        intent_hit[
            "label_key"
        ]
    )

    if not record:
        return []

    occurrences = []

    for occurrence in record.get(
        "occurrences",
        [],
    ):
        if (
            requested_map
            and occurrence.get("map")
            and occurrence.get("map")
            != requested_map
        ):
            continue

        item = dict(
            occurrence
        )

        item[
            "_retrieval_source"
        ] = "task_intent_memory"

        occurrences.append(
            item
        )

    occurrences.sort(
        key=lambda item:
            item.get(
                "command_time_ns",
                0,
            ),
        reverse=True,
    )

    return occurrences


def normalize(vector):
    norm = math.sqrt(
        sum(
            value * value
            for value in vector
        )
    )

    if norm == 0:
        return vector

    return [
        value / norm
        for value in vector
    ]


def embed(text):
    payload = json.dumps(
        {
            "model":
                MODEL_EMBED,

            "input":
                text,
        }
    ).encode("utf-8")

    request = urllib.request.Request(
        "http://localhost:11434/api/embed",
        data=payload,
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=120,
    ) as response:
        data = json.loads(
            response
            .read()
            .decode("utf-8")
        )

    return normalize(
        data["embeddings"][0]
    )


def cosine(a, b):
    return sum(
        x * y
        for x, y in zip(a, b)
    )


def search_global(
    query_vector,
):
    if not GLOBAL_EMBEDDINGS.exists():
        return []

    data = json.loads(
        GLOBAL_EMBEDDINGS.read_text(
            encoding="utf-8"
        )
    )

    results = []

    for record in data.get(
        "records",
        [],
    ):
        score = cosine(
            query_vector,
            record["embedding"],
        )

        results.append(
            {
                "score": score,
                **record,
            }
        )

    results.sort(
        key=lambda item:
            item["score"],
        reverse=True,
    )

    return results


def map_embedding_files(
    requested_map=None,
):
    root = (
        RUNTIME_DIR
        / "map_indexes"
    )

    if requested_map:
        path = (
            root
            / requested_map
            / "label_embeddings.json"
        )

        return (
            [path]
            if path.exists()
            else []
        )

    return list(
        root.glob(
            "*/label_embeddings.json"
        )
    )


def search_maps(
    query_vector,
    requested_map=None,
):
    results = []

    for path in map_embedding_files(
        requested_map
    ):
        try:
            data = json.loads(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except Exception:
            continue

        for record in data.get(
            "records",
            [],
        ):
            score = cosine(
                query_vector,
                record["embedding"],
            )

            results.append(
                {
                    "score":
                        score,

                    "map":
                        data.get("map"),

                    **record,
                }
            )

    results.sort(
        key=lambda item:
            item["score"],
        reverse=True,
    )

    return results


def load_map_record(
    map_name,
    label_key,
):
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

        key = label_key.encode(
            "utf-8"
        )

        if key not in index:
            return None

        return json.loads(
            index[key].decode(
                "utf-8"
            )
        )


def load_global_record(
    behavior_key,
):
    with dbm.open(
        GLOBAL_INDEX,
        "r",
    ) as index:

        key = behavior_key.encode(
            "utf-8"
        )

        if key not in index:
            return None

        return json.loads(
            index[key].decode(
                "utf-8"
            )
        )


def outcome_status(
    occurrence,
):
    outcome = occurrence.get(
        "outcome",
        {},
    )

    return (
        outcome.get("status")
        or outcome.get(
            "navigation_status"
        )
        or "unknown"
    )


def choose_occurrences(
    occurrences,
    question,
    limit=3,
):
    q = question.casefold()

    desired = None

    if any(
        word in q
        for word in [
            "failed",
            "fail",
            "failure",
        ]
    ):
        desired = "failed"

    elif any(
        word in q
        for word in [
            "succeeded",
            "success",
            "successful",
        ]
    ):
        desired = "succeeded"

    elif any(
        word in q
        for word in [
            "interrupted",
            "stopped",
            "unfinished",
        ]
    ):
        desired = "unknown_interrupted"

    selected = occurrences

    if desired:
        filtered = [
            occurrence
            for occurrence
            in occurrences
            if outcome_status(
                occurrence
            ) == desired
        ]

        if filtered:
            selected = filtered

    selected = sorted(
        selected,
        key=lambda occurrence:
            occurrence.get(
                "time_range",
                {},
            ).get(
                "start_ns",
                0,
            ),
        reverse=True,
    )

    return selected[:limit]


def collect_map_occurrences(
    map_hit,
    question,
):
    if not map_hit:
        return []

    record = load_map_record(
        map_hit["map"],
        map_hit["label_key"],
    )

    if not record:
        return []

    occurrences = []

    for task_name, task_data in (
        record.get(
            "tasks",
            {}
        ).items()
    ):
        for occurrence in (
            task_data.get(
                "occurrences",
                []
            )
        ):
            item = dict(
                occurrence
            )

            item[
                "_retrieval_source"
            ] = "map_memory"

            item[
                "_map"
            ] = map_hit["map"]

            item[
                "_label"
            ] = record.get(
                "label",
                {},
            ).get("name")

            occurrences.append(
                item
            )

    return choose_occurrences(
        occurrences,
        question,
    )


def collect_global_occurrences(
    global_hit,
    question,
):
    if not global_hit:
        return []

    record = load_global_record(
        global_hit[
            "behavior_key"
        ]
    )

    if not record:
        return []

    occurrences = []

    for occurrence in record.get(
        "occurrences",
        []
    ):
        item = dict(
            occurrence
        )

        item[
            "_retrieval_source"
        ] = "global_memory"

        occurrences.append(
            item
        )

    return choose_occurrences(
        occurrences,
        question,
    )


def deduplicate_occurrences(
    occurrences,
):
    result = []
    seen = set()

    for occurrence in occurrences:
        occurrence_id = (
            occurrence.get(
                "occurrence_id"
            )
        )

        if occurrence_id in seen:
            continue

        seen.add(
            occurrence_id
        )

        result.append(
            occurrence
        )

    return result


def occurrence_packet(
    occurrence,
):
    session_id = occurrence.get(
        "session_id"
    )

    time_range = occurrence.get(
        "time_range",
        {},
    )

    start_ns = time_range.get(
        "start_ns"
    )

    end_ns = time_range.get(
        "end_ns"
    )

    if (
        not session_id
        or start_ns is None
        or end_ns is None
    ):
        return None

    packet = build_packet(
        session_id,
        int(start_ns),
        int(end_ns),
    )

    packet[
        "retrieved_occurrence"
    ] = {
        "occurrence_id":
            occurrence.get(
                "occurrence_id"
            ),

        "retrieval_source":
            occurrence.get(
                "_retrieval_source"
            ),

        "task_context":
            occurrence.get(
                "task_context"
            )
            or occurrence.get(
                "task"
            ),

        "indexed_outcome":
            occurrence.get(
                "outcome"
            ),
    }

    return packet

def intent_occurrence_packet(
    occurrence,
):
    session_id = occurrence.get(
        "session_id"
    )

    time_range = occurrence.get(
        "evidence_time_range",
        {},
    )

    start_ns = time_range.get(
        "start_ns"
    )

    end_ns = time_range.get(
        "end_ns"
    )

    if (
        not session_id
        or start_ns is None
        or end_ns is None
    ):
        return None

    packet = build_packet(
        session_id,
        int(start_ns),
        int(end_ns),
    )

    packet[
        "retrieved_intent"
    ] = {
        "occurrence_id":
            occurrence.get(
                "occurrence_id"
            ),

        "label_name":
            occurrence.get(
                "label_name"
            ),

        "map":
            occurrence.get(
                "map"
            ),

        "command_time_ns":
            occurrence.get(
                "command_time_ns"
            ),

        "execution_start_ns":
            occurrence.get(
                "execution_start_ns"
            ),

        "finish_ns":
            occurrence.get(
                "finish_ns"
            ),

        "state":
            occurrence.get(
                "state"
            ),

        "outcome":
            occurrence.get(
                "outcome"
            ),
    }

    return packet


def build_llm_prompt(
    question,
    map_hits,
    global_hits,
    packets,
    audience,
    live_packet=None,
):
    retrieval_summary = {
        "map_matches": [
            {
                "map":
                    hit.get("map"),

                "label":
                    hit.get(
                        "label_name"
                    ),

                "score":
                    round(
                        hit["score"],
                        4,
                    ),
            }
            for hit in map_hits[:3]
        ],

        "global_behavior_matches": [
            {
                "behavior_key":
                    hit.get(
                        "behavior_key"
                    ),

                "score":
                    round(
                        hit["score"],
                        4,
                    ),

                "description":
                    hit.get(
                        "embedding_text"
                    ),
            }
            for hit in global_hits[:2]
        ],
    }
    if live_packet is not None:

        retrieval_summary[
            "current_session"
        ] = (
            live_packet.get(
                "live_session"
            )
        )

    if audience == "developer":
        audience_instructions = """
    AUDIENCE: DEVELOPER

    Write a technical diagnostic explanation.

    You may use internal terminology when it is useful,
    including:
    - NAVIGATION_COMMAND
    - NAVIGATION_STARTED
    - NAVIGATION_FINISHED
    - cmd_vel
    - wheel odometry
    - AMCL
    - LiDAR
    - Nav2 status values
    - event timing
    - session evidence

    Include useful numerical measurements.

    Explain which facts are directly recorded,
    which values are derived, and which explanations
    are hypotheses.

    When evidence is missing, identify what additional
    logging or subsystem evidence would be useful.

    Do not simplify away important technical details.
    """.strip()

    else:
        audience_instructions = """
    AUDIENCE: END USER

    Write for a person using the robot, not for
    a robotics developer.

    Use plain, natural language.

    Focus on:
    - what the robot was asked to do,
    - what actually happened,
    - what the robot could observe,
    - and what can or cannot be concluded.

    Do NOT expose internal implementation details
    unless they are necessary to understand the answer.

    Normally avoid terms such as:
    - NAVIGATION_COMMAND
    - NAVIGATION_STARTED
    - NAVIGATION_FINISHED
    - event_time_ns
    - cmd_vel
    - AMCL
    - ROS
    - SQLite
    - raw status codes
    - internal occurrence IDs
    - session IDs

    Translate technical evidence into user-facing
    language.

    For example:
    "no cmd_vel intervals were recorded"
    should normally become:
    "the robot did not receive movement commands."

    "No NAVIGATION_STARTED event was recorded"
    should normally become:
    "the navigation never began."

    "wheel odometry estimated 0.0008 m displacement"
    may become:
    "the robot remained essentially in place."

    Keep the answer concise.
    Do not overwhelm the user with raw numbers unless
    a number materially helps answer the question.
    """.strip()

    return f"""
You are explaining robot behavior using
recorded evidence.

{audience_instructions}

USER QUESTION:
{question}

RETRIEVAL RESULTS:
{json.dumps(retrieval_summary, indent=2)}

EVIDENCE PACKETS:
{json.dumps(packets, indent=2)}

GROUNDING RULES:

1. Use only the supplied evidence.

2. Clearly distinguish:
   - observed/recorded facts,
   - derived measurements,
   - hypotheses or possible explanations.

3. Wheel odometry is an estimate.
   Never describe odometry displacement as
   guaranteed physical chassis movement.

   Do not say the robot moved "toward the goal"
   unless the goal coordinates and observed pose
   support that conclusion.

   Do not infer that a destination was or was not
   physically reached solely from odometry distance.

4. A Nav2 success or failure status is the
   navigation system's decision. It is not
   independent proof of physical success
   or failure.

5. Do not infer causality merely because
   one event occurred before another.

6. If LiDAR suggests a nearby obstacle,
   you may say the evidence is consistent
   with obstruction. Do not claim an
   obstacle definitely caused a failure
   unless the evidence establishes that.

7. If the evidence is insufficient to
   answer "why", explicitly say what is
   known and what cannot be concluded.

8. Do not invent missing labels, map
   coordinates, sensor readings, status
   messages, or events.

9. Prefer concise explanations with the
   most relevant evidence and numerical
   values where useful.

10. A failed navigation status does not identify
    which Nav2 component caused the failure.
    Do not attribute failure specifically to the
    planner, controller, localization, obstacle
    avoidance, or hardware unless corresponding
    evidence is present.

11. Do not invent citation markers, reference
    numbers, source links, or bracketed citations.
    Refer to evidence naturally, for example:
    "The recorded task event shows..." or
    "LiDAR recorded..."

12. NAVIGATION_COMMAND represents a recorded
    request or intent. It does not prove that
    navigation execution began.

13. If there is a NAVIGATION_COMMAND but no
    matching NAVIGATION_STARTED, say:
    "No execution-start event was recorded."
    Do not claim that Nav2 definitely never
    received the goal unless the evidence proves it.

14. If no velocity command was recorded during
    the relevant interval, you may say that no
    cmd_vel motion command was recorded.

15. Passive odometry, LiDAR, TF, or localization
    data may continue even when a requested task
    is not executing. Do not treat passive sensor
    data as proof that navigation started.

16. If a request was recorded but the evidence
    does not identify why execution did not start,
    explicitly say that the cause is unknown from
    the available logs.

17. Change only the explanation level based on
    the audience. Do not change the underlying
    factual conclusion based on whether the reader
    is a user or developer.

18. A live session is not a completed historical occurrence.

19. If current_navigation.state is
    "navigation_requested_waiting_for_start",
    say that the request has been recorded but no
    execution-start event has been recorded yet.
    Do not call it a failure simply because STARTED
    has not arrived yet.

20. If current_navigation.state is
    "navigation_in_progress",
    the task is still executing.
    Do not describe it as failed, interrupted,
    unfinished, or successful unless a corresponding
    completion event exists.

21. Current-session SQLite evidence has priority for
    questions about what the robot is doing now,
    where it is now, why it is currently moving,
    or what just happened.

22. Historical memories may be used for comparison,
    such as "Has this happened before?" or
    "Why is this different from previous runs?"

23. Do not treat the absence of a FINISHED event in
    an active session as evidence that the task was
    interrupted. It may simply still be running.

24. For questions about the current map or the labels
    currently defined on that map, prefer
    current_map_metadata over historical map memory.

25. The historical map behavior index contains executed
    behavior occurrences and may not contain every label
    defined in the current map.

26. If current_map_metadata provides label_count or labels,
    use those values directly when answering questions such
    as "how many labels are there?" or "what labels are on
    this map?"

27. Do not infer the current map from the highest-scoring
    historical semantic match when live current-session map
    information is available.

Answer the user's question directly.
""".strip()


def call_nemotron(prompt):
    api_key = os.environ.get(
        "NVIDIA_API_KEY"
    )

    if not api_key:
        raise RuntimeError(
            "NVIDIA_API_KEY is not set."
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
                    "role": "user",
                    "content": prompt,
                }
            ],

            "temperature": 0.2,

            "max_tokens": 1600,
        },
        timeout=120,
    )

    response.raise_for_status()

    data = response.json()

    return data[
        "choices"
    ][0][
        "message"
    ][
        "content"
    ]

def normalize_map_name(
    map_name,
):
    if not map_name:
        return None

    name = Path(
        str(map_name)
    ).stem

    if name.endswith(
        "_labels"
    ):
        name = name[
            :-len("_labels")
        ]

    return name


def load_current_map_metadata(
    map_name,
):
    map_name = normalize_map_name(
        map_name
    )

    if not map_name:
        return None

    labels_path = (
        MAPS_DIR
        / f"{map_name}_labels.json"
    )

    result = {
        "map":
            map_name,

        "labels_file":
            str(labels_path),

        "labels_file_exists":
            labels_path.exists(),

        "label_count":
            None,

        "labels":
            [],
    }

    if not labels_path.exists():
        return result

    try:

        data = json.loads(
            labels_path.read_text(
                encoding="utf-8"
            )
        )

    except Exception as exc:

        result[
            "read_error"
        ] = str(exc)

        return result

    labels = data.get(
        "labels",
        [],
    )

    if not isinstance(
        labels,
        list,
    ):
        labels = []

    clean_labels = []

    for label in labels:

        if not isinstance(
            label,
            dict,
        ):
            continue

        clean_labels.append(
            {
                "id":
                    label.get("id"),

                "name":
                    label.get("name"),

                "kind":
                    label.get("kind"),

                "detail":
                    label.get("detail"),

                "world":
                    label.get("world"),

                "yaw":
                    label.get("yaw"),
            }
        )

    result[
        "labels"
    ] = clean_labels

    result[
        "label_count"
    ] = len(
        clean_labels
    )

    return result


def asks_about_current_map(
    question,
):
    q = question.casefold()

    phrases = [
        "current map",
        "this map",
        "map are you using",
        "which map",
        "what map",
    ]

    return any(
        phrase in q
        for phrase in phrases
    )


def asks_about_labels(
    question,
):
    q = question.casefold()

    return (
        "label" in q
        or "labels" in q
    )


def asks_about_current_pose(
    question,
):
    q = question.casefold()

    phrases = [
        "where are you",
        "where is the robot",
        "current position",
        "current pose",
        "where are you now",
    ]

    return any(
        phrase in q
        for phrase in phrases
    )

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--audience",
        choices=[
            "user",
            "developer",
        ],
        default="user",
        help=(
            "Answer style: simple user-facing "
            "or technical developer-facing."
        ),
    )

    parser.add_argument(
        "--question",
        required=True,
    )

    parser.add_argument(
        "--map",
        default=None,
    )

    parser.add_argument(
        "--session-id",
        default=None,
        help=(
            "Optional current session ID. "
            "When supplied, live SQLite evidence "
            "is included in the answer."
        ),
    )

    parser.add_argument(
        "--show-evidence",
        action="store_true",
    )

    parser.add_argument(
        "--no-llm",
        action="store_true",
    )

    args = parser.parse_args()

    question = args.question

    live_packet = None

    if args.session_id:

        try:

            live_packet = (
                build_live_packet(
                    args.session_id
                )
            )

        except Exception as exc:

            print(
                "WARNING: Could not read "
                "live session evidence:"
            )

            print(
                f"  {exc}"
            )

    current_map_metadata = None

    if live_packet is not None:

        live_info = (
            live_packet.get(
                "live_session"
            )
            or {}
        )

        current_map_name = (
            live_info.get(
                "map"
            )
        )

        if current_map_name:

            current_map_metadata = (
                load_current_map_metadata(
                    current_map_name
                )
            )

    query_vector = embed(
        question
    )

    map_hits = search_maps(
        query_vector,
        args.map,
    )

    global_hits = search_global(
        query_vector
    )

    intent_hits = search_intents(
        query_vector
    )

    nonexecution_question = (
        asks_about_nonexecution(
            question
        )
    )

    top_map = (
        map_hits[0]
        if map_hits
        else None
    )

    top_global = (
        global_hits[0]
        if global_hits
        else None
    )

    top_intent = (
        intent_hits[0]
        if intent_hits
        else None
    )

    packets = []
    if current_map_metadata is not None:

        if (
            asks_about_current_map(
                question
            )
            or asks_about_labels(
                question
            )
        ):

            packets.append(
                {
                    "current_map_metadata":
                        current_map_metadata,

                    "source_type":
                        "current_map_file",
                }
            )

     # Live/current SQLite evidence is independent
    # from historical semantic memory.
    #
    # It is always available when --session-id
    # identifies an active experiment.
    if live_packet is not None:
        packets.append(
            live_packet
        )

    # --------------------------------------------------
    # ROUTE 1:
    # Question is about something that was requested
    # but may never have started.
    # Example:
    # "Why didn't the robot go to test_point?"
    # --------------------------------------------------

    if nonexecution_question:

        intent_occurrences = (
            collect_intent_occurrences(
                top_intent,
                args.map,
            )
        )

        # Prefer requests where no execution-start
        # event was recorded.
        no_start_occurrences = [
            occurrence
            for occurrence
            in intent_occurrences
            if occurrence.get("outcome")
            == "no_execution_start_recorded"
        ]

        if no_start_occurrences:
            intent_occurrences = (
                no_start_occurrences
            )

        # Use the most recent relevant request.
        intent_occurrences = (
            intent_occurrences[:1]
        )

        for occurrence in intent_occurrences:

            packet = (
                intent_occurrence_packet(
                    occurrence
                )
            )

            if packet:
                packets.append(
                    packet
                )

    # --------------------------------------------------
    # ROUTE 2:
    # Normal executed-behavior question.
    # Example:
    # "Why did navigation under the table fail?"
    # --------------------------------------------------

    else:

        occurrences = []

        occurrences.extend(
            collect_map_occurrences(
                top_map,
                question,
            )
        )

        occurrences.extend(
            collect_global_occurrences(
                top_global,
                question,
            )
        )

        occurrences = (
            deduplicate_occurrences(
                occurrences
            )
        )

        for occurrence in occurrences:

            packet = occurrence_packet(
                occurrence
            )

            if packet:
                packets.append(
                    packet
                )

    print()
    print("MAP MATCHES")
    print("=" * 70)

    for hit in map_hits[:3]:
        print(
            f"{hit.get('map')} / "
            f"{hit.get('label_name')} "
            f"score={hit['score']:.4f}"
        )

    print()
    print("GLOBAL MATCHES")
    print()
    print("TASK INTENT MATCHES")
    print("=" * 70)

    for hit in intent_hits[:3]:
        print(
            f"{hit.get('label_name')} "
            f"score={hit['score']:.4f}"
        )
    print("=" * 70)

    for hit in global_hits[:3]:
        print(
            f"{hit.get('behavior_key')} "
            f"score={hit['score']:.4f}"
        )

    print()
    print()
    print(
        "SELECTED OCCURRENCES:",
        len(packets),
    )

    for packet in packets:

        if "live_session" in packet:

            live = packet[
                "live_session"
            ]

            current_navigation = (
                live.get(
                    "current_navigation"
                )
                or {}
            )

            print(
                "- LIVE SESSION",
                {
                    "map":
                        live.get("map"),

                    "state":
                        current_navigation.get(
                            "state"
                        ),

                    "label":
                        current_navigation.get(
                            "label_name"
                        ),
                },
            )
        elif "current_map_metadata" in packet:

            metadata = packet[
                "current_map_metadata"
            ]

            print(
                "- CURRENT MAP",
                {
                    "map":
                        metadata.get(
                            "map"
                        ),

                    "label_count":
                        metadata.get(
                            "label_count"
                        ),

                    "labels":
                        [
                            item.get(
                                "name"
                            )
                            for item in metadata.get(
                                "labels",
                                []
                            )
                        ],
                },
            )

        elif "retrieved_intent" in packet:

            occurrence = packet[
                "retrieved_intent"
            ]

            print(
                "-",
                occurrence.get(
                    "occurrence_id"
                ),
                {
                    "state":
                        occurrence.get(
                            "state"
                        ),

                    "outcome":
                        occurrence.get(
                            "outcome"
                        ),
                },
            )

        elif "retrieved_occurrence" in packet:

            occurrence = packet[
                "retrieved_occurrence"
            ]

            print(
                "-",
                occurrence.get(
                    "occurrence_id"
                ),
                occurrence.get(
                    "indexed_outcome"
                ),
            )

        else:

            print(
                "- UNKNOWN PACKET TYPE"
            )

    if args.show_evidence:
        print()
        print("EVIDENCE")
        print("=" * 70)

        print(
            json.dumps(
                packets,
                indent=2,
            )
        )

    if args.no_llm:
        return

    if not packets:
        print()
        if nonexecution_question:
            print(
                "No matching requested-task "
                "occurrence could be retrieved."
            )
        else:
            print(
                "No executed occurrence "
                "could be retrieved."
            )
        return

    prompt = build_llm_prompt(
        question,
        map_hits,
        global_hits,
        packets,
        args.audience,
        live_packet,
    )

    answer = call_nemotron(
        prompt
    )

    print()
    print(
        f"AUDIENCE: {args.audience}"
    )
    print("ANSWER")
    print("=" * 70)
    print(answer)


if __name__ == "__main__":
    main()
