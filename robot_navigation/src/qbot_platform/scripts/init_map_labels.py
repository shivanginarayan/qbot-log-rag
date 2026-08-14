#!/usr/bin/env python3
"""Initialize a map label file with a saved home/start pose."""

import argparse
import json
from pathlib import Path


DEFAULT_LABELS = (
    ("home", "Mapping start/home position"),
    ("robot_start", "Robot start pose"),
    ("start", "Start pose"),
    ("original", "Original pose"),
    ("origin", "Map origin"),
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Create or update a <map>_labels.json file with home/start labels. "
            "By default this records the mapping start pose as x=0, y=0, yaw=0."
        )
    )
    parser.add_argument(
        "--map-yaml",
        required=True,
        help="Path to the saved map yaml file.",
    )
    parser.add_argument(
        "--x",
        type=float,
        default=0.0,
        help="Home pose x in map frame. Default: 0.0",
    )
    parser.add_argument(
        "--y",
        type=float,
        default=0.0,
        help="Home pose y in map frame. Default: 0.0",
    )
    parser.add_argument(
        "--yaw",
        type=float,
        default=0.0,
        help="Home pose yaw in radians. Default: 0.0",
    )
    parser.add_argument(
        "--keep-existing-labels",
        action="store_true",
        help="Preserve non-home labels that already exist in the file.",
    )
    return parser.parse_args()


def build_label(name, detail, x, y, yaw):
    return {
        "id": name,
        "name": name,
        "kind": "navigation",
        "detail": detail,
        "source": "init_map_labels.py",
        "world": {
            "x": float(x),
            "y": float(y),
        },
        "yaw": float(yaw),
    }


def labels_path_for_map(map_yaml: Path) -> Path:
    return map_yaml.with_name(f"{map_yaml.stem}_labels.json")


def load_existing_labels(labels_path: Path):
    if not labels_path.exists():
        return []
    try:
        data = json.loads(labels_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    labels = data.get("labels", [])
    return labels if isinstance(labels, list) else []


def main():
    args = parse_args()
    map_yaml = Path(args.map_yaml).expanduser().resolve()
    if not map_yaml.exists():
        raise SystemExit(f"Map yaml not found: {map_yaml}")

    labels_path = labels_path_for_map(map_yaml)
    existing_labels = load_existing_labels(labels_path) if args.keep_existing_labels else []
    reserved_names = {name for name, _ in DEFAULT_LABELS}

    kept_labels = []
    for label in existing_labels:
        if not isinstance(label, dict):
            continue
        if str(label.get("name", "")).strip().lower() in reserved_names:
            continue
        kept_labels.append(label)

    new_labels = [
        build_label(name, detail, args.x, args.y, args.yaw)
        for name, detail in DEFAULT_LABELS
    ]

    output = {
        "map": map_yaml.with_suffix(".pgm").name,
        "yaml": map_yaml.name,
        "labels": new_labels + kept_labels,
    }

    labels_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote labels to {labels_path}")
    print(
        "Saved mapping start/home pose at "
        f"x={args.x:.3f}, y={args.y:.3f}, yaw={args.yaw:.3f}"
    )


if __name__ == "__main__":
    main()
