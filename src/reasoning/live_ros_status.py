#!/usr/bin/env python3

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parents[2]
if str(REPO_DIR) not in sys.path:
    sys.path.insert(0, str(REPO_DIR))

from ros_domain_config import get_ros_domain_id


ROS_DOMAIN_ID = str(get_ros_domain_id())


def run_ros2(
    command,
    timeout=4,
):
    """
    Run a ROS 2 CLI command in the correct ROS environment.
    Returns stdout, stderr and return code.
    """

    shell_command = f"""
source /opt/ros/humble/setup.bash

if [ -f "$HOME/ros2/install/setup.bash" ]; then
    source "$HOME/ros2/install/setup.bash"
fi

export ROS_DOMAIN_ID={ROS_DOMAIN_ID}

{command}
"""

    try:

        result = subprocess.run(
            [
                "bash",
                "-lc",
                shell_command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )

        return {
            "ok":
                result.returncode == 0,

            "returncode":
                result.returncode,

            "stdout":
                result.stdout.strip(),

            "stderr":
                result.stderr.strip(),
        }

    except subprocess.TimeoutExpired:

        return {
            "ok":
                False,

            "returncode":
                None,

            "stdout":
                "",

            "stderr":
                "timeout",
        }

    except Exception as exc:

        return {
            "ok":
                False,

            "returncode":
                None,

            "stdout":
                "",

            "stderr":
                str(exc),
        }


def split_lines(
    result,
):
    text = result.get(
        "stdout",
        "",
    )

    return [
        line.strip()
        for line in text.splitlines()
        if line.strip()
    ]


def get_lifecycle_state(
    node_name,
):
    result = run_ros2(
        f"ros2 lifecycle get {node_name}",
        timeout=4,
    )

    if not result["ok"]:
        return {
            "available":
                False,

            "state":
                None,

            "message":
                result.get("stderr")
                or result.get("stdout"),
        }

    text = result[
        "stdout"
    ]

    state = None

    if "[" in text and "]" in text:
        state = (
            text.split(
                "[",
                1,
            )[1]
            .split(
                "]",
                1,
            )[0]
            .strip()
        )

    return {
        "available":
            True,

        "state":
            state,

        "raw":
            text,
    }


def collect_ros_runtime():
    """
    Collect direct live ROS graph evidence.
    """

    node_result = run_ros2(
        "ros2 node list"
    )

    topic_result = run_ros2(
        "ros2 topic list"
    )

    service_result = run_ros2(
        "ros2 service list"
    )


    nodes = split_lines(
        node_result
    )

    topics = split_lines(
        topic_result
    )

    services = split_lines(
        service_result
    )


    important_nodes = [
        "/amcl",
        "/map_server",
        "/controller_server",
        "/planner_server",
        "/bt_navigator",
        "/behavior_server",
        "/waypoint_follower",
        "/velocity_smoother",
    ]


    node_presence = {
        node:
            node in nodes
        for node in important_nodes
    }


    important_topics = [
        "/amcl_pose",
        "/scan",
        "/scan_filtered",
        "/odom",
        "/cmd_vel",
        "/map",
        "/tf",
    ]


    topic_presence = {
        topic:
            topic in topics
        for topic in important_topics
    }


    important_services = [
        "/reinitialize_global_localization",
    ]


    service_presence = {
        service:
            service in services
        for service in important_services
    }


    lifecycle = {}

    for node in [
        "/amcl",
        "/map_server",
        "/controller_server",
        "/planner_server",
        "/bt_navigator",
    ]:

        if node_presence.get(
            node
        ):

            lifecycle[node] = (
                get_lifecycle_state(
                    node
                )
            )

        else:

            lifecycle[node] = {
                "available":
                    False,

                "state":
                    None,

                "message":
                    "node_not_present",
            }


    return {
        "ros_domain_id":
            ROS_DOMAIN_ID,

        "node_list_available":
            node_result["ok"],

        "topic_list_available":
            topic_result["ok"],

        "service_list_available":
            service_result["ok"],

        "nodes":
            nodes,

        "topics":
            topics,

        "services":
            services,

        "important_node_presence":
            node_presence,

        "important_topic_presence":
            topic_presence,

        "important_service_presence":
            service_presence,

        "lifecycle":
            lifecycle,
    }


def main():
    print(
        json.dumps(
            collect_ros_runtime(),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
