#!/usr/bin/env python3
import argparse, json
from datetime import datetime
from pathlib import Path
import sys

HERE = Path(__file__).resolve()
COMPARISON_ROOT = HERE.parents[1]
if str(COMPARISON_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPARISON_ROOT))

from causal_explanation.causal_events import get_event_definition
from causal_explanation.causal_memory import append_occurrence, causal_log_path

def safe_json(raw):
    try:
        x = json.loads(raw)
        return x if isinstance(x, dict) else {}
    except Exception:
        return {}

def classify_status(payload):
    event = str(payload.get("event") or "").casefold()
    name = str(payload.get("name") or "").casefold()
    label = str(payload.get("label") or "").casefold()
    status = str(payload.get("status") or "")
    message = str(payload.get("message") or "").casefold()
    is_loc = name == "localize" or "localiz" in label
    if event == "started":
        return "localization_started" if is_loc else "navigation_started"
    if event != "finished":
        return None
    if status == "4":
        return "localization_succeeded" if is_loc else "navigation_succeeded"
    if status == "5":
        return "navigation_canceled"
    if status == "6":
        return "localization_failed" if is_loc else "navigation_failed"
    return None

def classify_rosout(name, message):
    lower = str(message or "").casefold()
    if "transform from base_link to map" in lower and ("timed out" in lower or "does not exist" in lower or "unavailable" in lower):
        return "map_transform_unavailable"
    return None

def occurrence(event_name, t, run_id, source, payload):
    d = get_event_definition(event_name)
    cause = payload.get("message") or d.get("default_cause")
    return {
        "run_id": run_id,
        "timestamp_ns": int(t),
        "event_name": event_name,
        "event_label": d.get("event_label"),
        "cause": cause,
        "effect": d.get("effect"),
        "source": source,
        "map": payload.get("map"),
        "label": payload.get("label"),
        "status": payload.get("status"),
        "raw_message": payload.get("message"),
        "evidence_payload": payload,
    }

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-id")
    args = p.parse_args()
    run_id = args.run_id or datetime.now().strftime("causal_%Y%m%d_%H%M%S")

    import rclpy
    from std_msgs.msg import String
    from rcl_interfaces.msg import Log
    try:
        from rclpy.qos import qos_profile_rosout_default
        rosout_qos = qos_profile_rosout_default
    except Exception:
        from rclpy.qos import QoSProfile
        rosout_qos = QoSProfile(depth=1000)

    rclpy.init()
    node = rclpy.create_node("adapted_causal_explanation_logger")
    last = {}

    def save(item):
        if not item:
            return
        sig = (item["event_name"], item.get("raw_message"), item.get("map"), item.get("label"))
        t = item["timestamp_ns"]
        if sig in last and t - last[sig] < 30_000_000_000:
            return
        last[sig] = t
        saved = append_occurrence(item)
        print("CAUSAL EVENT:", saved["event_name"], "| cause=", saved["cause"], "| effect=", saved["effect"])

    def status_cb(msg):
        payload = safe_json(msg.data)
        event_name = classify_status(payload)
        if event_name:
            save(occurrence(event_name, node.get_clock().now().nanoseconds, run_id, "/robot/navigation_status", payload))

    def rosout_cb(msg):
        event_name = classify_rosout(getattr(msg, "name", ""), getattr(msg, "msg", ""))
        if not event_name:
            return
        stamp = getattr(msg, "stamp", None)
        t = int(stamp.sec)*1_000_000_000 + int(stamp.nanosec) if stamp is not None else node.get_clock().now().nanoseconds
        payload = {"message": getattr(msg, "msg", ""), "node": getattr(msg, "name", "")}
        save(occurrence(event_name, t, run_id, "/rosout", payload))

    node.create_subscription(String, "/robot/navigation_status", status_cb, 100)
    node.create_subscription(Log, "/rosout", rosout_cb, rosout_qos)

    print("Adapted causal logger running")
    print("RUN ID:", run_id)
    print("CAUSAL LOG:", causal_log_path())
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
