#!/usr/bin/env python3
from pathlib import Path

def repo_root():
    return Path(__file__).resolve().parents[2]

def runtime_root():
    return repo_root() / "runtime_logs"

def list_session_ids():
    root = runtime_root()
    if not root.exists():
        return []
    result = []
    for path in root.glob("session_*"):
        if path.is_dir():
            sid = path.name[len("session_"):]
            if sid:
                result.append(sid)
    return sorted(result)

def resolve_session_id(session_id):
    if session_id and session_id != "latest":
        return session_id
    sessions = list_session_ids()
    if not sessions:
        raise RuntimeError("No runtime_logs/session_* directories were found.")
    return sessions[-1]

def session_dir(session_id):
    sid = resolve_session_id(session_id)
    path = runtime_root() / f"session_{sid}"
    if not path.exists():
        raise RuntimeError(f"Session directory does not exist: {path}")
    return sid, path

def robot_db_path(session_id):
    sid, path = session_dir(session_id)
    db_path = path / "robot.db"
    if not db_path.exists():
        raise RuntimeError(f"robot.db does not exist for session {sid}")
    return sid, db_path

def rosbag_dir(session_id):
    sid, path = session_dir(session_id)
    bag_dir = path / "rosbag"
    if not bag_dir.exists():
        raise RuntimeError(f"rosbag directory does not exist for session {sid}")
    return sid, bag_dir
