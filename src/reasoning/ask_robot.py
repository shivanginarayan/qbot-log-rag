#!/usr/bin/env python3

import argparse
import dbm
import json
import math
import os
import urllib.request
from pathlib import Path

import requests

from build_evidence_packet import build_packet


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
        "--show-evidence",
        action="store_true",
    )

    parser.add_argument(
        "--no-llm",
        action="store_true",
    )

    args = parser.parse_args()

    question = args.question

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

        if "retrieved_intent" in packet:

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

        else:

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
