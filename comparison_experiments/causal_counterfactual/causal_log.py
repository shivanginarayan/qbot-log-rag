#!/usr/bin/env python3
import json
import sqlite3

COMMAND_TYPES = {
    "NAVIGATION_COMMAND",
    "LOCALIZE_COMMAND",
}
START_TYPE = "NAVIGATION_STARTED"
FINISH_TYPE = "NAVIGATION_FINISHED"

def _normalize(value):
    if value is None:
        return None
    return str(value).strip().casefold()

def _payload(row):
    raw = row.get("payload_json")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}

def load_task_events(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
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
    return [dict(row) for row in rows]

def same_task(command, event):
    if command.get("session_id") != event.get("session_id"):
        return False

    command_task = _normalize(command.get("task_type"))
    event_task = _normalize(event.get("task_type"))

    if command_task != event_task:
        return False

    if command_task == "navigate_to_location":
        c = _normalize(command.get("label_name"))
        e = _normalize(event.get("label_name"))
        if c and e and c != e:
            return False

    return True

def outcome_from_status(status):
    value = str(status)
    if value == "4":
        return "succeeded"
    if value == "5":
        return "canceled"
    if value == "6":
        return "failed"
    return "finished_unknown"

def build_occurrences(events):
    result = []

    for index, command in enumerate(events):
        if command.get("event_type") not in COMMAND_TYPES:
            continue

        started = None
        finished = None
        command_task = _normalize(command.get("task_type"))

        for later in events[index + 1:]:
            if later.get("session_id") != command.get("session_id"):
                break

            later_type = later.get("event_type")
            later_task = _normalize(later.get("task_type"))

            if later_type in COMMAND_TYPES and later_task == command_task:
                break

            if not same_task(command, later):
                continue

            if started is None and later_type == START_TYPE:
                started = later
                continue

            if later_type == FINISH_TYPE:
                finished = later
                break

        if finished is not None:
            outcome = outcome_from_status(finished.get("status"))
        elif started is not None:
            outcome = "started_no_completion_recorded"
        else:
            outcome = "no_execution_start_recorded"

        occurrence = {
            "command": command,
            "started": started,
            "finished": finished,
            "outcome": outcome,
        }

        occurrence["causal_log"] = build_causal_log(occurrence)
        occurrence["counterfactuals"] = build_counterfactuals(occurrence)

        result.append(occurrence)

    return result

def build_causal_log(occurrence):
    command = occurrence.get("command") or {}
    started = occurrence.get("started") or {}
    finished = occurrence.get("finished") or {}
    message = _payload(finished).get("message")

    entries = [{
        "cause": "user_or_system_request_recorded",
        "effect": "task_request_exists",
        "evidence": command.get("event_type"),
    }]

    if started:
        entries.append({
            "cause": "execution_start_recorded",
            "effect": "task_entered_execution",
            "evidence": START_TYPE,
        })

    if finished:
        entries.append({
            "cause": "completion_event_recorded",
            "effect": occurrence.get("outcome"),
            "evidence": {
                "event_type": FINISH_TYPE,
                "status": finished.get("status"),
                "message": message,
            },
        })

    if occurrence.get("outcome") == "failed" and message:
        entries.append({
            "cause": "recorded_failure_condition",
            "effect": "task_failed",
            "evidence": message,
            "note": (
                "This adapted baseline treats the explicit completion "
                "message as the causal-log failure condition."
            ),
        })

    return entries

def build_counterfactuals(occurrence):
    finished = occurrence.get("finished") or {}
    message = _payload(finished).get("message")
    outcome = occurrence.get("outcome")

    result = []

    if outcome == "no_execution_start_recorded":
        result.append({
            "change": "execution_start_recorded = true",
            "would_change": (
                "the explanation from request-only to task-entered-execution"
            ),
            "does_not_prove": "that the task would succeed",
        })

    if outcome == "failed" and message:
        result.append({
            "change": (
                "the recorded failure condition described by the "
                "completion message is absent"
            ),
            "would_change": (
                "this specific failure condition would no longer explain "
                "the observed failure"
            ),
            "does_not_prove": (
                "that the overall task would necessarily succeed"
            ),
            "observed_failure_condition": message,
        })

    return result

def compact_occurrence(occurrence):
    command = occurrence.get("command") or {}
    started = occurrence.get("started") or {}
    finished = occurrence.get("finished") or {}

    return {
        "task_event_id": command.get("task_event_id"),
        "task_type": command.get("task_type"),
        "label": command.get("label_name"),
        "map": (
            command.get("map_name")
            or started.get("map_name")
            or finished.get("map_name")
        ),
        "command_time_ns": command.get("event_time_ns"),
        "execution_start_ns": started.get("event_time_ns"),
        "finish_ns": finished.get("event_time_ns"),
        "outcome": occurrence.get("outcome"),
        "causal_log": occurrence.get("causal_log"),
        "counterfactuals": occurrence.get("counterfactuals"),
    }
