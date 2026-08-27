#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
COMPARISON_ROOT = HERE.parents[1]
if str(COMPARISON_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPARISON_ROOT))

from common.nvidia_client import call_nemotron
from common.session_utils import robot_db_path
from causal_counterfactual.causal_log import (
    load_task_events, build_occurrences, compact_occurrence
)

def occ_task_type(occ):
    for key in ("command","started","finished"):
        e = occ.get(key) or {}
        if e.get("task_type"):
            return str(e.get("task_type")).casefold()
    return ""

def select_occurrences(question, occurrences, limit=8):
    q = question.casefold()
    selected = list(occurrences)

    if "localiz" in q:
        f = [x for x in selected if occ_task_type(x) == "localization"]
        if f: selected = f
    elif "navigat" in q or "go to" in q:
        f = [x for x in selected if occ_task_type(x) == "navigate_to_location"]
        if f: selected = f

    if "fail" in q:
        f = [x for x in selected if x.get("outcome") == "failed"]
        if f: selected = f
    elif "success" in q or "succeed" in q:
        f = [x for x in selected if x.get("outcome") == "succeeded"]
        if f: selected = f

    def when(x):
        for key in ("command","started","finished"):
            e = x.get(key) or {}
            if e.get("event_time_ns") is not None:
                return e.get("event_time_ns")
        return 0

    selected.sort(key=when, reverse=True)
    return selected[:limit]

def role_instructions(role):
    if role == "engineer":
        return (
            "ROLE: ENGINEER\nUse technical terminology when useful. "
            "Preserve recorded messages and distinguish model assumptions from evidence."
        )
    return (
        "ROLE: END USER\nUse plain language. Focus on what happened and why "
        "according to the fixed causal log."
    )

def build_prompt(question, session_id, role, selected):
    evidence = [compact_occurrence(x) for x in selected]
    return f"""
You are generating an explanation from an adapted fixed causal-log
and temporal-counterfactual robot-navigation model.

{role_instructions(role)}

Use only the supplied causal log and counterfactual statements.

Important:
- do not invent causes;
- temporal order alone is not proof of causation;
- a missing request event means the request stage is unavailable in this evidence,
  not that no request physically occurred;
- a recorded failure message is treated as the explicit failure condition;
- removing one failure condition does not prove the whole task succeeds;
- if the model lacks enough causal information, say so.

SESSION:
{session_id}

QUESTION:
{question}

CAUSAL / COUNTERFACTUAL MODEL:
{json.dumps(evidence, indent=2)}

Answer directly.
""".strip()

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--session-id", default="latest")
    p.add_argument("--question", required=True)
    p.add_argument("--role", choices=["user","engineer"], default="user")
    p.add_argument("--show-model", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    args = p.parse_args()

    session_id, db_path = robot_db_path(args.session_id)
    events = load_task_events(db_path)
    occurrences = build_occurrences(events)
    selected = select_occurrences(args.question, occurrences)

    print()
    print("SYSTEM: adapted_causal_counterfactual")
    print("SESSION:", session_id)
    print("ROLE:", args.role)
    print("TASK EVENTS:", len(events))
    print("TASK OCCURRENCES:", len(occurrences))
    print("SELECTED OCCURRENCES:", len(selected))

    if args.show_model:
        print()
        print("MODEL EVIDENCE")
        print("=" * 70)
        print(json.dumps([compact_occurrence(x) for x in selected], indent=2))

    if args.no_llm:
        return

    if not selected:
        print()
        print("No matching task occurrence was available.")
        return

    answer = call_nemotron(build_prompt(
        args.question, session_id, args.role, selected
    ))

    print()
    print("ANSWER")
    print("=" * 70)
    print(answer)

if __name__ == "__main__":
    main()
