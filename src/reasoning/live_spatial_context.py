#!/usr/bin/env python3
import json
import math
import urllib.request

POSE_URL = "http://localhost:8765/api/robot-pose"

def get_live_robot_pose(timeout_s=2.0):
    try:
        req = urllib.request.Request(POSE_URL, method="GET")
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except Exception as exc:
        return {
            "available": False,
            "source": "/api/robot-pose",
            "topic": "/amcl_pose",
            "error": str(exc),
        }

    if not isinstance(payload, dict):
        return {
            "available": False,
            "source": "/api/robot-pose",
            "topic": "/amcl_pose",
            "error": "Pose endpoint did not return a JSON object",
        }

    result = dict(payload)
    result["source"] = "/api/robot-pose"
    result.setdefault("topic", "/amcl_pose")
    return result

def build_live_spatial_context(current_map_metadata):
    pose = get_live_robot_pose()

    result = {
        "source_type": "live_spatial_context",
        "pose_source": "/api/robot-pose",
        "pose_topic": pose.get("topic") or "/amcl_pose",
        "current_pose": pose,
        "current_map": (
            current_map_metadata.get("map")
            if isinstance(current_map_metadata, dict)
            else None
        ),
        "nearest_label": None,
        "label_distances": [],
        "distance_definition": (
            "straight-line Euclidean distance in map/world coordinates; "
            "not Nav2 path distance"
        ),
    }

    if not pose.get("available"):
        return result

    world = pose.get("world")
    if not isinstance(world, dict):
        return result

    try:
        robot_x = float(world["x"])
        robot_y = float(world["y"])
    except (KeyError, TypeError, ValueError):
        return result

    labels = (
        current_map_metadata.get("labels", [])
        if isinstance(current_map_metadata, dict)
        else []
    )

    distances = []
    for label in labels:
        if not isinstance(label, dict):
            continue
        lw = label.get("world")
        if not isinstance(lw, dict):
            continue

        try:
            lx = float(lw["x"])
            ly = float(lw["y"])
        except (KeyError, TypeError, ValueError):
            continue

        dx = lx - robot_x
        dy = ly - robot_y

        distances.append({
            "id": label.get("id"),
            "name": label.get("name"),
            "kind": label.get("kind"),
            "detail": label.get("detail"),
            "world": {"x": lx, "y": ly},
            "yaw": label.get("yaw"),
            "distance_m": math.hypot(dx, dy),
            "delta_from_robot_m": {"x": dx, "y": dy},
        })

    distances.sort(key=lambda item: item["distance_m"])
    result["label_distances"] = distances
    if distances:
        result["nearest_label"] = distances[0]

    return result
