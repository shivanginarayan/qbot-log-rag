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
# ============================================================
# TASK INTENT MEMORY
# ============================================================

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


def load_intent_record(
    label_key,
):
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


# ============================================================
# EMBEDDINGS
# ============================================================

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


# ============================================================
# GLOBAL MEMORY
# ============================================================

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


# ============================================================
# MAP MEMORY
# ============================================================

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


# ============================================================
# OCCURRENCE SELECTION
# ============================================================

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
        [],
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


# ============================================================
# EVIDENCE PACKETS
# ============================================================

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


# ============================================================
# CURRENT MAP METADATA
# ============================================================

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

def load_saved_maps_metadata():
    """
    Inspect the actual robot_navigation/maps directory.

    A saved map may contain both:
        <name>.pgm
        <name>.yaml

    Count each map name only once.
    """

    result = {
        "maps_directory":
            str(MAPS_DIR),

        "directory_exists":
            MAPS_DIR.exists(),

        "map_count":
            0,

        "maps":
            [],
    }

    if not MAPS_DIR.exists():
        return result

    discovered = {}

    # --------------------------------------------------------
    # Discover standard ROS occupancy-grid map files.
    #
    # Use both YAML and PGM so we do not accidentally miss
    # a partially saved map, but deduplicate by map stem.
    # --------------------------------------------------------

    for path in MAPS_DIR.iterdir():

        if not path.is_file():
            continue

        suffix = path.suffix.casefold()

        if suffix not in {
            ".pgm",
            ".yaml",
        }:
            continue

        map_name = path.stem

        if not map_name:
            continue

        if map_name not in discovered:

            discovered[
                map_name
            ] = {
                "name":
                    map_name,

                "pgm":
                    None,

                "yaml":
                    None,

                "labels":
                    None,
            }

        if suffix == ".pgm":

            discovered[
                map_name
            ][
                "pgm"
            ] = str(path)

        elif suffix == ".yaml":

            discovered[
                map_name
            ][
                "yaml"
            ] = str(path)

    # --------------------------------------------------------
    # Attach label file if one exists.
    # --------------------------------------------------------

    for map_name, item in discovered.items():

        labels_path = (
            MAPS_DIR
            / f"{map_name}_labels.json"
        )

        if labels_path.exists():

            item[
                "labels"
            ] = str(
                labels_path
            )

    maps = sorted(
        discovered.values(),
        key=lambda item:
            item["name"].casefold(),
    )

    result[
        "maps"
    ] = maps

    result[
        "map_count"
    ] = len(
        maps
    )

    return result

# ============================================================
# QUESTION ROUTING
# ============================================================

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
        "active map",
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


def asks_for_history(
    question,
):
    q = question.casefold()

    phrases = [
        "before",
        "previous",
        "previously",
        "earlier",
        "last time",
        "used to",
        "usually",
        "historically",
        "has this happened",
        "ever happened",
        "have you done",
        "has the robot done",
        "compared to",
        "different from",
    ]

    return any(
        phrase in q
        for phrase in phrases
    )


def asks_about_live_state(
    question,
):
    q = question.casefold()

    phrases = [
        "now",
        "current",
        "currently",
        "active",
        "what map",
        "which map",
        "localized",
        "localised",
        "localization",
        "localisation",
        "amcl",
        "where are you",
        "what are you doing",
        "why is it not",
        "why isn't it",
        "why is the robot not",
        "why isn't the robot",
        "is it moving",
        "are you moving",
        "what do you see",
        "why did localization fail",
        "why did localisation fail",
        "planner",
        "controller",
        "bt navigator",
        "map server",
        "nav2",
        "ros node",
        "ros topic",
        "ros service",
    ]

    return any(
        phrase in q
        for phrase in phrases
    )

def asks_about_saved_maps(
    question,
):
    q = question.casefold()

    phrases = [
        "saved maps",
        "maps saved",
        "how many maps",
        "how many maps are saved",
        "what maps are saved",
        "which maps are saved",
        "list maps",
        "list the maps",
        "available maps",
        "maps available",
        "what maps exist",
        "which maps exist",
    ]

    return any(
        phrase in q
        for phrase in phrases
    )

# ============================================================
# LLM PROMPT
# ============================================================

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

You may use internal terminology when useful, including:
- NAVIGATION_COMMAND
- NAVIGATION_STARTED
- NAVIGATION_FINISHED
- cmd_vel
- wheel odometry
- AMCL
- LiDAR
- Nav2
- ROS nodes/topics/services
- lifecycle state
- status values
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
- what the robot can currently observe or report,
- and what can or cannot be concluded.

Do NOT expose internal implementation details unless
they are necessary to understand the answer.

Normally avoid terms such as:
- NAVIGATION_COMMAND
- NAVIGATION_STARTED
- NAVIGATION_FINISHED
- event_time_ns
- cmd_vel
- ROS
- SQLite
- raw status codes
- internal occurrence IDs
- session IDs

Technical terms such as AMCL or Nav2 may be used when
the user explicitly asks about them.

Translate technical evidence into user-facing language.

For example:
"no cmd_vel intervals were recorded"
should normally become:
"the robot did not receive movement commands."

"No NAVIGATION_STARTED event was recorded"
should normally become:
"there is no recorded evidence that navigation began."

Keep the answer concise.
Do not overwhelm the user with raw numbers unless
a number materially helps answer the question.
""".strip()

    return f"""
You are explaining robot behavior using supplied evidence.

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
   Never describe odometry displacement as guaranteed
   physical chassis movement.

   Do not say the robot moved "toward the goal"
   unless goal coordinates and observed pose support it.

4. A Nav2 success or failure status is the navigation
   system's decision. It is not independent proof of
   physical success or failure.

5. Do not infer causality merely because one event
   occurred before another.

6. If LiDAR suggests a nearby obstacle, you may say
   the evidence is consistent with an obstacle being
   nearby. Do not say that obstacle caused a failure
   unless evidence establishes that.

7. If evidence is insufficient to answer "why",
   explicitly say what is known and what cannot
   be concluded.

8. Do not invent missing labels, map coordinates,
   sensor readings, status messages, events, nodes,
   topics, services, or causes.

9. Prefer concise explanations using the most
   relevant evidence.

10. A failed navigation status does not identify
    which Nav2 component caused the failure.

11. Do not invent citation markers, reference numbers,
    source links, or bracketed citations.

12. NAVIGATION_COMMAND represents a recorded request.
    It does not prove navigation execution began.

13. If there is a NAVIGATION_COMMAND but no matching
    NAVIGATION_STARTED, say:
    "No execution-start event was recorded."

    Do not claim that Nav2 definitely never received
    the goal unless evidence proves it.

14. If no velocity command was recorded during the
    relevant interval, you may say no motion command
    was recorded.

15. Passive odometry, LiDAR, TF, or localization data
    may continue even when a requested task is not
    executing.

16. If a request was recorded but evidence does not
    identify why execution did not start, say the cause
    is unknown from the available evidence.

17. Audience changes explanation style only.
    It must not change the factual conclusion.

18. A live session is not a completed historical
    occurrence.

19. If current_navigation.state is
    "navigation_requested_waiting_for_start",
    the request exists but no execution-start event
    has yet been recorded.

    Do not call this a failure simply because STARTED
    has not arrived.

20. If current_navigation.state is
    "navigation_in_progress", the task is still
    executing.

    Do not describe it as failed, interrupted or
    successful unless a completion event exists.

21. Current-session evidence has priority for questions
    about what the robot is doing now, where it is now,
    why it is currently moving, or what just happened.

22. Historical memories are primarily for questions
    about previous behavior, repetition, comparison,
    patterns, or past occurrences.

23. Do not treat absence of a FINISHED event in an
    active session as evidence that the task was
    interrupted.

24. For questions about the current map or labels,
    prefer current_map_metadata and live runtime
    information over historical map memory.

25. The historical map behavior index contains executed
    behavior occurrences and may not contain every
    defined label.

26. If current_map_metadata provides label_count or
    labels, use those values directly.

27. Never infer the current map from historical semantic
    similarity when live current-map information exists.

28. A null map value in SQLite does not mean no map is
    loaded. It only means SQLite has not identified it.

29. If navigation_runtime provides active_map, treat
    that as the current map reported by the runtime.

30. Clearly distinguish current runtime status from
    historical recorded evidence.

31. A localization_state such as "in_progress" means
    localization is currently underway.

    Do not say the robot is localized unless the
    localized field is true.

32. Direct live ROS graph evidence has priority for
    questions about whether ROS nodes, topics, services,
    or lifecycle components currently exist.

33. If important_node_presence["/amcl"] is false,
    you may state that /amcl is not present in the
    current ROS graph.

34. If /amcl is absent and /amcl_pose is absent,
    you may state that AMCL is not currently producing
    pose output.

35. A missing ROS node does NOT establish why the node
    failed to launch, exited, crashed, or was omitted.

    Do not state the underlying reason unless launch,
    process, lifecycle, or explicit runtime evidence
    identifies it.

36. Zero localization samples do not prove why
    localization failed. They only show no localization
    samples were recorded in the relevant interval.

37. Lack of robot motion does not prove localization
    failed because the robot did not move.

38. Nearby LiDAR obstacles do not prove they prevented
    localization or navigation.

39. A message such as "verify AMCL is active" is a
    diagnostic hint, not proof of the root cause.

40. For current-state questions, historical semantic
    similarity scores are not evidence about the
    robot's present state.

41. If current_navigation.state is
    "no_navigation_request_recorded", say only that
    no navigation request is recorded in the current
    session evidence.

    Do not turn that into:
    "the robot definitely never received a request"
    unless direct evidence proves that.

42. When answering "why", distinguish a symptom from
    a root cause.

    For example:
    "/amcl is absent"
    is an observed runtime condition.

    "AMCL crashed because of configuration"
    is a causal explanation and must not be stated
    without corresponding evidence.

    43. Distinguish an active map from saved maps.

    navigation_runtime.active_map identifies the map
    currently being used by navigation.

    It does not describe how many maps are saved.

44. For questions such as "how many maps are saved?",
    "what maps are available?", or "list the saved maps",
    use saved_maps_metadata.

45. saved_maps_metadata is derived from the current
    robot_navigation/maps directory.

    map_count is the number of unique map names found
    from .pgm or .yaml map files, deduplicated by name.

46. Do not infer the number of saved maps from the
    currently active map.

    One active map does not mean only one map is saved.

47. If saved_maps_metadata contains a map_count and map
    list, use those values directly rather than historical
    semantic memory.

Answer the user's question directly.
""".strip()


# ============================================================
# NEMOTRON
# ============================================================

def call_nemotron(
    prompt,
):
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
                    "role":
                        "user",

                    "content":
                        prompt,
                }
            ],

            "temperature":
                0.2,

            "max_tokens":
                1600,
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


# ============================================================
# MAIN
# ============================================================

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
            "When supplied, live SQLite/runtime evidence "
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
    # ========================================================
    # LIVE EVIDENCE
    # ========================================================
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


    # ========================================================
    # CURRENT MAP METADATA
    # ========================================================

    current_map_metadata = None
    saved_maps_metadata = None

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

        if asks_about_saved_maps(
            question
        ):

            saved_maps_metadata = (
                load_saved_maps_metadata()
            )


    # ========================================================
    # QUESTION ROUTING
    #
    # Important:
    #
    # Purely live/current questions do NOT search old
    # semantic memories.
    #
    # Historical retrieval is still enabled when the
    # question asks about the past/comparison/history.
    # ========================================================

    historical_question = (
        asks_for_history(
            question
        )
    )

    live_question = (
        args.session_id is not None
        and (
            asks_about_live_state(
                question
            )
            or asks_about_current_map(
                question
            )
            or asks_about_saved_maps(
                question
            )
            or asks_about_labels(
                question
            )
            or asks_about_current_pose(
                question
            )
        )
    )

    use_historical_memory = (
        not live_question
        or historical_question
    )


    map_hits = []
    global_hits = []
    intent_hits = []


    if use_historical_memory:

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


    # ========================================================
    # BUILD EVIDENCE PACKETS
    # ========================================================

    packets = []

    # --------------------------------------------------------
    # Saved map inventory
    # --------------------------------------------------------

    if saved_maps_metadata is not None:

        packets.append(
            {
                "saved_maps_metadata":
                    saved_maps_metadata,

                "source_type":
                    "maps_directory",
            }
        )

    # --------------------------------------------------------
    # Current map metadata
    # --------------------------------------------------------

    if current_map_metadata is not None:

        if (
            (
                asks_about_current_map(
                    question
                )
                or asks_about_labels(
                    question
                )
            )
            and not asks_about_saved_maps(
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


    # --------------------------------------------------------
    # Current live evidence
    # --------------------------------------------------------

    if live_packet is not None:
        packets.append(
            live_packet
        )


    # --------------------------------------------------------
    # Historical retrieval
    #
    # Only run this branch if routing decided history
    # is actually relevant.
    # --------------------------------------------------------

    if use_historical_memory:

        # ----------------------------------------------------
        # Historical non-execution question
        # ----------------------------------------------------

        if nonexecution_question:

            intent_occurrences = (
                collect_intent_occurrences(
                    top_intent,
                    args.map,
                )
            )

            no_start_occurrences = [
                occurrence
                for occurrence
                in intent_occurrences
                if occurrence.get(
                    "outcome"
                )
                == "no_execution_start_recorded"
            ]

            if no_start_occurrences:

                intent_occurrences = (
                    no_start_occurrences
                )

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

        # ----------------------------------------------------
        # Historical executed behavior
        # ----------------------------------------------------

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


    # ========================================================
    # DEBUG / RETRIEVAL DISPLAY
    # ========================================================

    print()
    print("MAP MATCHES")
    print("=" * 70)

    if not use_historical_memory:

        print(
            "(historical retrieval skipped "
            "for live/current question)"
        )

    else:

        for hit in map_hits[:3]:

            print(
                f"{hit.get('map')} / "
                f"{hit.get('label_name')} "
                f"score={hit['score']:.4f}"
            )
    print()
    print("GLOBAL MATCHES")
    print("=" * 70)

    if use_historical_memory:

        for hit in global_hits[:3]:

            print(
                f"{hit.get('behavior_key')} "
                f"score={hit['score']:.4f}"
            )

    else:

        print(
            "(historical retrieval skipped)"
        )


    print()
    print("TASK INTENT MATCHES")
    print("=" * 70)

    if use_historical_memory:

        for hit in intent_hits[:3]:

            print(
                f"{hit.get('label_name')} "
                f"score={hit['score']:.4f}"
            )

    else:

        print("(historical retrieval skipped)")


    print()
    print(
        "SELECTED EVIDENCE PACKETS:",
        len(packets),
    )

    for packet in packets:

        if "saved_maps_metadata" in packet:

            metadata = packet[
                "saved_maps_metadata"
            ]

            print(
                "- SAVED MAPS",
                {
                    "map_count":
                        metadata.get(
                            "map_count"
                        ),

                    "maps":
                        [
                            item.get(
                                "name"
                            )
                            for item
                            in metadata.get(
                                "maps",
                                []
                            )
                        ],
                },
            )

        elif "live_session" in packet:

            live = packet[
                "live_session"
            ]

            current_navigation = (
                live.get(
                    "current_navigation"
                )
                or {}
            )

            ros_runtime = (
                live.get(
                    "ros_runtime"
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

                    "amcl_present":
                        (
                            ros_runtime.get(
                                "important_node_presence",
                                {},
                            )
                            .get(
                                "/amcl"
                            )
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

    # ========================================================
    # OPTIONAL EVIDENCE DISPLAY
    # ========================================================
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


    # ========================================================
    # NO EVIDENCE
    # ========================================================

    if not packets:
        print()
        print(
            "No relevant evidence could be retrieved."
        )

        return


    # ========================================================
    # LLM
    # ========================================================

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
