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
    load_task_events,
    build_occurrences,
    compact_occurrence,
)

def select_occurrences(question, occurrences, limit=8):
    q = question.casefold()
    selected = list(occurrences)

    if "localiz" in q:
        filtered = [
            x for x in selected
            if str((x.get("command") or {}).get("task_type")).casefold()
            == "localization"
        ]
        if filtered:
            selected = filtered

    elif "navigat" in q or "go to" in q:
        filtered = [
            x for x in selected
            if str((x.get("command") or {}).get("task_type")).casefold()
            == "navigate_to_location"
        ]
        if filtered:
            selected = filtered

    if "fail" in q:
        filtered = [x for x in selected if x.get("outcome") == "failed"]
        if filtered:
            selected = filtered
    elif "success" in q or "succeed" in q:
        filtered = [x for x in selected if x.get("outcome") == "succeeded"]
        if filtered:
            selected = filtered

    selected.sort(
        key=lambda x: (x.get("command") or {}).get("event_time_ns", 0),
        reverse=True,
    )
    return selected[:limit]

def role_instructions(role):
    if role == "engineer":
        return (
            "ROLE: ENGINEER\n"
            "Use technical terminology when useful. Preserve recorded "
            "messages and distinguish fixed-model assumptions from evidence."
        )
    return (
        "ROLE: END USER\n"
        "Use plain language. Focus on what happened and why according "
        "to the fixed causal log."
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
- a recorded failure message is treated as the explicit failure
  condition for this adapted baseline;
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
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default="latest")
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--role",
        choices=["user", "engineer"],
        default="user",
    )
    parser.add_argument("--show-model", action="store_true")
    parser.add_argument("--no-llm", action="store_true")
    args = parser.parse_args()

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
        print(json.dumps(
            [compact_occurrence(x) for x in selected],
            indent=2,
        ))

    if args.no_llm:
        return

    if not selected:
        print()
        print("No matching task occurrence was available.")
        return

    answer = call_nemotron(
        build_prompt(
            args.question,
            session_id,
            args.role,
            selected,
        )
    )

    print()
    print("ANSWER")
    print("=" * 70)
    print(answer)

if __name__ == "__main__":
    main()
