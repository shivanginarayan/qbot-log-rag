#!/usr/bin/env python3
import argparse, json, sys
from pathlib import Path

HERE = Path(__file__).resolve()
COMPARISON_ROOT = HERE.parents[1]
if str(COMPARISON_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPARISON_ROOT))

from common.nvidia_client import call_nemotron
from causal_explanation.causal_memory import load_causal_log
from causal_explanation.event_matcher import match_question

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--question", required=True)
    p.add_argument("--role", choices=["user","engineer"], default="user")
    p.add_argument("--show-model", action="store_true")
    p.add_argument("--no-llm", action="store_true")
    args = p.parse_args()

    matches = match_question(args.question, top_k=3)
    best = matches[0] if matches else None
    log = load_causal_log()
    occs = log.get("occurrences", [])
    selected = []
    if best:
        selected = [x for x in occs if x.get("event_name") == best["event_name"]]
        selected.sort(key=lambda x: int(x.get("timestamp_ns") or 0), reverse=True)
        selected = selected[:8]

    print()
    print("SYSTEM: adapted_personalized_causal_explanation")
    print("ROLE:", args.role)
    print("CAUSAL LOG OCCURRENCES:", len(occs))
    print("RECOGNIZED EVENT:", best["event_name"] if best else None)
    print("EVENT MATCH SCORE:", round(best["score"],4) if best else None)
    print("MATCHING OCCURRENCES:", len(selected))

    if args.show_model:
        print("\nEVENT MATCH CANDIDATES\n" + "="*70)
        print(json.dumps([{"event_name":x["event_name"],"score":round(x["score"],4)} for x in matches], indent=2))
        print("\nCAUSAL EVIDENCE\n" + "="*70)
        print(json.dumps(selected, indent=2))

    if args.no_llm:
        return

    role_text = (
        "Use technical terminology and preserve source/status/raw messages."
        if args.role == "engineer"
        else "Use plain language for a nontechnical robot user."
    )

    prompt = f"""
You are verbalizing an adapted personalized causal-explanation baseline.

{role_text}

The user's natural-language question has been mapped to one predefined
robot causal event. Use only the matching stored cause -> effect pairs.

Do not invent new causes.
If no matching occurrence exists, say the causal log has no recorded
occurrence of that recognized event.
Do not claim an event never physically happened outside this causal log.

QUESTION:
{args.question}

RECOGNIZED EVENT:
{json.dumps(best, indent=2) if best else "null"}

MATCHING CAUSAL OCCURRENCES:
{json.dumps(selected, indent=2)}

Answer directly.
""".strip()

    if not best:
        print("\nNo causal event could be recognized.")
        return

    answer = call_nemotron(prompt)
    print("\nANSWER\n" + "="*70)
    print(answer)

if __name__ == "__main__":
    main()
