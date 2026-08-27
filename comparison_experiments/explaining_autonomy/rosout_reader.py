#!/usr/bin/env python3
from pathlib import Path

def read_rosout_records(bag_dir):
    try:
        import rosbag2_py
        from rclpy.serialization import deserialize_message
        from rosidl_runtime_py.utilities import get_message
    except Exception as exc:
        raise RuntimeError(
            "ROS 2 Python rosbag packages are unavailable. "
            f"Original error: {exc}"
        )

    bag_dir = Path(bag_dir)

    reader = rosbag2_py.SequentialReader()
    reader.open(
        rosbag2_py.StorageOptions(uri=str(bag_dir), storage_id="sqlite3"),
        rosbag2_py.ConverterOptions(
            input_serialization_format="cdr",
            output_serialization_format="cdr",
        ),
    )

    topic_types = {
        item.name: item.type
        for item in reader.get_all_topics_and_types()
    }

    if "/rosout" not in topic_types:
        raise RuntimeError(
            "The rosbag does not contain /rosout. "
            "This baseline will not substitute raw sensor topics."
        )

    msg_type = get_message(topic_types["/rosout"])

    records = []
    previous_signature = None
    skipped = 0

    while reader.has_next():
        topic, raw_data, timestamp_ns = reader.read_next()
        if topic != "/rosout":
            continue

        message = deserialize_message(raw_data, msg_type)

        level = getattr(message, "level", None)
        name = getattr(message, "name", "")
        if name == "rosbag2_recorder":
            continue
        msg = getattr(message, "msg", "")
        file_name = getattr(message, "file", "")
        function_name = getattr(message, "function", "")
        line = getattr(message, "line", None)

        signature = (
            level,
            name,
            msg,
            file_name,
            function_name,
            line,
        )

        if signature == previous_signature:
            skipped += 1
            continue

        previous_signature = signature

        records.append({
            "timestamp_ns": int(timestamp_ns),
            "level": level,
            "name": name,
            "message": msg,
            "file": file_name,
            "function": function_name,
            "line": line,
            "text": f"[{level}] [{name}] {msg}",
        })

    return {
        "records": records,
        "record_count": len(records),
        "skipped_adjacent_duplicates": skipped,
    }
