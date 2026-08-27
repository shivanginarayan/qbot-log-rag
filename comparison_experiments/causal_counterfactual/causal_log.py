#!/usr/bin/env python3
import json
import sqlite3

COMMAND_TYPES = {"NAVIGATION_COMMAND", "LOCALIZE_COMMAND"}
START_TYPE = "NAVIGATION_STARTED"
FINISH_TYPE = "NAVIGATION_FINISHED"

def _norm(v):
    return None if v is None else str(v).strip().casefold()

def _payload(row):
    raw = (row or {}).get("payload_json")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except Exception:
        return {}

def load_task_events(db_path):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT task_event_id, session_id, event_time_ns, source_topic,
               event_type, map_name, label_id, label_name, task_type,
               status, payload_json
        FROM task_events
        ORDER BY event_time_ns
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def same_task(a, b):
    if not a or not b:
        return False
    if a.get("session_id") != b.get("session_id"):
        return False
    ta, tb = _norm(a.get("task_type")), _norm(b.get("task_type"))
    if ta != tb:
        return False
    if ta == "navigate_to_location":
        la, lb = _norm(a.get("label_name")), _norm(b.get("label_name"))
        if la and lb and la != lb:
            return False
    return True

def _outcome(status):
    return {"4":"succeeded","5":"canceled","6":"failed"}.get(
        str(status), "finished_unknown"
    )

def _make_occurrence(command=None, started=None, finished=None):
    if finished:
        outcome = _outcome(finished.get("status"))
    elif started:
        outcome = "started_no_completion_recorded"
    elif command:
        outcome = "no_execution_start_recorded"
    else:
        outcome = "unknown"

    occ = {
        "command": command,
        "started": started,
        "finished": finished,
        "outcome": outcome,
        "request_recorded": command is not None,
        "execution_start_recorded": started is not None,
        "completion_recorded": finished is not None,
    }
    occ["causal_log"] = build_causal_log(occ)
    occ["counterfactuals"] = build_counterfactuals(occ)
    return occ

def build_occurrences(events):
    occurrences = []
    used = set()

    # Command-led occurrences.
    for i, command in enumerate(events):
        if command.get("event_type") not in COMMAND_TYPES:
            continue
        started = None
        finished = None
        task = _norm(command.get("task_type"))
        for later in events[i+1:]:
            if later.get("session_id") != command.get("session_id"):
                break
            if later.get("event_type") in COMMAND_TYPES and _norm(later.get("task_type")) == task:
                break
            if not same_task(command, later):
                continue
            if started is None and later.get("event_type") == START_TYPE:
                started = later
                continue
            if later.get("event_type") == FINISH_TYPE:
                finished = later
                break
        occ = _make_occurrence(command, started, finished)
        occurrences.append(occ)
        for e in (command, started, finished):
            if e:
                used.add(e.get("task_event_id"))

    # Orphan STARTED -> FINISHED.
    for i, started in enumerate(events):
        if started.get("event_type") != START_TYPE:
            continue
        if started.get("task_event_id") in used:
            continue
        finished = None
        for later in events[i+1:]:
            if later.get("session_id") != started.get("session_id"):
                break
            if later.get("event_type") == START_TYPE and _norm(later.get("task_type")) == _norm(started.get("task_type")):
                break
            if same_task(started, later) and later.get("event_type") == FINISH_TYPE:
                finished = later
                break
        occ = _make_occurrence(None, started, finished)
        occurrences.append(occ)
        used.add(started.get("task_event_id"))
        if finished:
            used.add(finished.get("task_event_id"))

    # Orphan FINISHED.
    for finished in events:
        if finished.get("event_type") != FINISH_TYPE:
            continue
        if finished.get("task_event_id") in used:
            continue
        occurrences.append(_make_occurrence(None, None, finished))
        used.add(finished.get("task_event_id"))

    def t(occ):
        for key in ("command","started","finished"):
            e = occ.get(key)
            if e:
                return e.get("event_time_ns", 0)
        return 0

    occurrences.sort(key=t)
    return occurrences

def build_causal_log(occ):
    command = occ.get("command") or {}
    started = occ.get("started") or {}
    finished = occ.get("finished") or {}
    message = _payload(finished).get("message")
    entries = []

    if command:
        entries.append({
            "cause": "user_or_system_request_recorded",
            "effect": "task_request_exists",
            "evidence": command.get("event_type"),
        })
    else:
        entries.append({
            "observation": "request_event_not_recorded",
            "meaning": "The request stage is unavailable in task_events for this occurrence.",
            "warning": "Do not infer that no request occurred.",
        })

    if started:
        entries.append({
            "cause": "execution_start_recorded",
            "effect": "task_entered_execution",
            "evidence": START_TYPE,
        })

    if finished:
        entries.append({
            "cause": "completion_event_recorded",
            "effect": occ.get("outcome"),
            "evidence": {
                "event_type": FINISH_TYPE,
                "status": finished.get("status"),
                "message": message,
            },
        })

    if occ.get("outcome") == "failed" and message:
        entries.append({
            "cause": "recorded_failure_condition",
            "effect": "task_failed",
            "evidence": message,
            "note": "Adapted baseline treats the explicit completion message as its causal-log failure condition.",
        })

    return entries

def build_counterfactuals(occ):
    finished = occ.get("finished") or {}
    message = _payload(finished).get("message")
    out = []
    if occ.get("outcome") == "failed" and message:
        out.append({
            "change": "the recorded failure condition is absent",
            "would_change": "this specific failure condition would no longer explain the observed failure",
            "does_not_prove": "that the overall task would necessarily succeed",
            "observed_failure_condition": message,
        })
    return out

def compact_occurrence(occ):
    command = occ.get("command") or {}
    started = occ.get("started") or {}
    finished = occ.get("finished") or {}
    return {
        "task_event_id": command.get("task_event_id") or started.get("task_event_id") or finished.get("task_event_id"),
        "task_type": command.get("task_type") or started.get("task_type") or finished.get("task_type"),
        "label": command.get("label_name") or started.get("label_name") or finished.get("label_name"),
        "map": command.get("map_name") or started.get("map_name") or finished.get("map_name"),
        "request_recorded": occ.get("request_recorded"),
        "execution_start_recorded": occ.get("execution_start_recorded"),
        "completion_recorded": occ.get("completion_recorded"),
        "command_time_ns": command.get("event_time_ns"),
        "execution_start_ns": started.get("event_time_ns"),
        "finish_ns": finished.get("event_time_ns"),
        "outcome": occ.get("outcome"),
        "causal_log": occ.get("causal_log"),
        "counterfactuals": occ.get("counterfactuals"),
    }
