DIAGNOSTIC_GRAPH = {
    "joystick": {
        "depends_on": [],
        "affects": ["teleop"],
        "description": "Joystick provides human input through /joy."
    },
    "teleop": {
        "depends_on": ["joystick"],
        "affects": ["/cmd_vel"],
        "description": "Teleop converts joystick input into velocity commands."
    },
    "/cmd_vel": {
        "depends_on": ["teleop"],
        "affects": ["qbot_driver"],
        "description": "/cmd_vel carries movement commands."
    },
    "qbot_driver": {
        "depends_on": ["/cmd_vel"],
        "affects": ["/qbot_speed_feedback"],
        "description": "QBot driver sends commands to robot hardware."
    },
    "/qbot_speed_feedback": {
        "depends_on": ["qbot_driver"],
        "affects": ["robot_movement"],
        "description": "Speed feedback confirms whether robot is actually moving."
    },
    "robot_movement": {
        "depends_on": ["/qbot_speed_feedback"],
        "affects": [],
        "description": "Final observable robot movement."
    },
    "lidar": {
        "depends_on": [],
        "affects": ["/scan"],
        "description": "LiDAR produces LaserScan data."
    },
    "/scan": {
        "depends_on": ["lidar"],
        "affects": ["obstacle_detection"],
        "description": "/scan provides obstacle distance readings."
    },
    "battery": {
        "depends_on": [],
        "affects": ["qbot_driver", "lidar"],
        "description": "Battery affects robot hardware and sensors."
    }
}


def explain_graph_path(issue_key):
    if issue_key == "robot_not_moving":
        return (
            "Graph reasoning path:\n"
            "joystick → teleop → /cmd_vel → qbot_driver → /qbot_speed_feedback → robot_movement\n"
            "This means a movement failure can come from joystick input, teleop publishing, command velocity, driver behavior, or motor feedback."
        )

    if issue_key == "lidar_issue":
        return (
            "Graph reasoning path:\n"
            "lidar → /scan → obstacle_detection\n"
            "This means a perception failure can come from the LiDAR node, sensor connection, or missing /scan messages."
        )

    if issue_key == "battery_issue":
        return (
            "Graph reasoning path:\n"
            "battery → qbot_driver / lidar\n"
            "This means low power can affect both movement and sensor reliability."
        )

    return "Graph reasoning path: No specific graph path found."