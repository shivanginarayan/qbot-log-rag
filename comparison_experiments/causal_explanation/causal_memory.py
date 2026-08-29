#!/usr/bin/env python3
import json, threading, time
from pathlib import Path

HERE = Path(__file__).resolve()
COMPARISON_ROOT = HERE.parents[1]
_LOCK = threading.Lock()

def causal_log_path():
    root = COMPARISON_ROOT / "runtime" / "causal_explanation"
    root.mkdir(parents=True, exist_ok=True)
    return root / "causal_log.json"

def load_causal_log():
    p = causal_log_path()
    if not p.exists():
        return {"system":"adapted_personalized_causal_explanation","occurrences":[]}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        data = {"system":"adapted_personalized_causal_explanation","occurrences":[]}
    if not isinstance(data.get("occurrences"), list):
        data["occurrences"] = []
    return data

def append_occurrence(occurrence):
    with _LOCK:
        data = load_causal_log()
        occs = data["occurrences"]
        item = dict(occurrence)
        item.setdefault("causal_occurrence_id", f"cause_{len(occs)+1}_{int(item.get('timestamp_ns') or time.time_ns())}")
        occs.append(item)
        data["updated_at_ns"] = time.time_ns()
        tmp = causal_log_path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(causal_log_path())
        return item
