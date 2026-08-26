#!/usr/bin/env python3

"""Run the team RAG command with narrowly scoped compatibility helpers.

The current team ``ask_robot.py`` references map metadata helpers that may be
absent after a merge.  Import the command unchanged and provide only helpers
that it does not already define.  This keeps the compatibility code inside the
standalone UI and automatically gets out of the way when the team script is
fixed upstream.
"""

import argparse
import importlib.util
import json
import sys
from pathlib import Path


def normalize_map_name(map_name):
    if not map_name:
        return None

    name = Path(str(map_name)).stem
    if name.endswith("_labels"):
        name = name[: -len("_labels")]
    return name or None


def load_current_map_metadata(maps_dir, map_name):
    map_name = normalize_map_name(map_name)
    if not map_name:
        return None

    labels_path = Path(maps_dir) / (map_name + "_labels.json")
    result = {
        "map": map_name,
        "labels_file": str(labels_path),
        "labels_file_exists": labels_path.exists(),
        "label_count": None,
        "labels": [],
    }

    if not labels_path.exists():
        return result

    try:
        data = json.loads(labels_path.read_text(encoding="utf-8"))
    except Exception as exc:
        result["read_error"] = str(exc)
        return result

    labels = data.get("labels", [])
    if not isinstance(labels, list):
        labels = []

    for label in labels:
        if not isinstance(label, dict):
            continue
        result["labels"].append(
            {
                "id": label.get("id"),
                "name": label.get("name"),
                "kind": label.get("kind"),
                "detail": label.get("detail"),
                "world": label.get("world"),
                "yaw": label.get("yaw"),
            }
        )

    result["label_count"] = len(result["labels"])
    return result


def load_saved_maps_metadata(maps_dir):
    maps_dir = Path(maps_dir)
    result = {
        "maps_directory": str(maps_dir),
        "directory_exists": maps_dir.exists(),
        "map_count": 0,
        "maps": [],
    }
    if not maps_dir.exists():
        return result

    discovered = {}
    for path in maps_dir.iterdir():
        if not path.is_file() or path.suffix.casefold() not in {".pgm", ".yaml"}:
            continue

        map_name = path.stem
        item = discovered.setdefault(
            map_name,
            {"name": map_name, "pgm": None, "yaml": None, "labels": None},
        )
        item[path.suffix.casefold()[1:]] = str(path)

    for map_name, item in discovered.items():
        labels_path = maps_dir / (map_name + "_labels.json")
        if labels_path.exists():
            item["labels"] = str(labels_path)

    result["maps"] = sorted(
        discovered.values(), key=lambda item: item["name"].casefold()
    )
    result["map_count"] = len(result["maps"])
    return result


def install_missing_helpers(core_module):
    """Add map helpers only when the imported team module lacks them."""

    maps_dir = Path(core_module.MAPS_DIR)

    if not hasattr(core_module, "normalize_map_name"):
        core_module.normalize_map_name = normalize_map_name
    if not hasattr(core_module, "load_current_map_metadata"):
        core_module.load_current_map_metadata = (
            lambda map_name: load_current_map_metadata(maps_dir, map_name)
        )
    if not hasattr(core_module, "load_saved_maps_metadata"):
        core_module.load_saved_maps_metadata = (
            lambda: load_saved_maps_metadata(maps_dir)
        )


def load_core(core_script):
    core_script = Path(core_script).resolve()
    if not core_script.is_file():
        raise RuntimeError("Core QBot RAG script was not found: " + str(core_script))

    core_directory = str(core_script.parent)
    if core_directory not in sys.path:
        sys.path.insert(0, core_directory)

    specification = importlib.util.spec_from_file_location(
        "qbot_session_ui_core_rag", str(core_script)
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("Core QBot RAG script could not be loaded.")

    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    install_missing_helpers(module)
    return module


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--core-script", required=True)
    args, core_args = parser.parse_known_args()

    if core_args and core_args[0] == "--":
        core_args = core_args[1:]

    core = load_core(args.core_script)
    sys.argv = [str(Path(args.core_script).resolve())] + core_args
    core.main()


if __name__ == "__main__":
    main()
