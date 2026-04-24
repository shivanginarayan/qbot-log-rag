def apply_rules(retrieved_logs):
    logs_text = "\n".join(retrieved_logs).lower()

    findings = []

    if "/joy" in logs_text and "/cmd_vel" in logs_text and "no velocity command" in logs_text:
        findings.append({
            "issue": "Teleoperation issue",
            "cause": "Joystick input is present, but the teleop node is not publishing velocity commands to /cmd_vel.",
            "action": "Check if the teleop node is running and verify /cmd_vel using: ros2 topic echo /cmd_vel"
        })

    if "/qbot_speed_feedback" in logs_text and "speed feedback remains zero" in logs_text:
        findings.append({
            "issue": "Robot motion issue",
            "cause": "The robot is not reporting movement even though motion-related logs are present.",
            "action": "Check QBot driver status, motor enable state, and whether /cmd_vel is reaching the driver."
        })

    if "/scan" in logs_text and ("not being received" in logs_text or "no laserscan" in logs_text):
        findings.append({
            "issue": "LiDAR issue",
            "cause": "LaserScan data is missing, so the robot may not perceive obstacles correctly.",
            "action": "Check the LiDAR node, cable/power, and run: ros2 topic echo /scan"
        })

    if "/qbot_battery" in logs_text and ("battery level is low" in logs_text or "low at" in logs_text):
        findings.append({
            "issue": "Battery issue",
            "cause": "Battery level is low and may affect robot movement or sensor reliability.",
            "action": "Charge the QBot or connect it to a stable power source."
        })

    if not findings:
        findings.append({
            "issue": "Unknown issue",
            "cause": "The retrieved logs do not match the current diagnostic rules.",
            "action": "Check active ROS 2 nodes and topics using: ros2 node list and ros2 topic list"
        })

    return findings