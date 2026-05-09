def make_simple_explanation(current_snapshot, error_history):
    lines = []

    lines.append("Simple explanation:")

    topics = current_snapshot.get("topics", {}) if current_snapshot else {}

    cmd = topics.get("/cmd_vel", {}).get("latest_value", {})
    speed = topics.get("/qbot_speed_feedback", {}).get("latest_value", {})
    scan = topics.get("/scan", {}).get("latest_value", {})

    cmd_zero = cmd.get("linear_x") == 0.0 and cmd.get("angular_z") == 0.0
    speed_zero = speed.get("linear_x") == 0.0 and speed.get("angular_z") == 0.0
    obstacle_close = scan.get("obstacle_close") is True

    if cmd_zero and speed_zero:
        lines.append("The robot is not moving because no movement command is currently being sent.")
        lines.append("The joystick or teleop node may be idle, disabled, or not publishing non-zero /cmd_vel commands.")

    elif not cmd_zero and speed_zero and obstacle_close:
        lines.append("The robot is being told to move, but it is not moving.")
        lines.append("LiDAR also sees something close, so the robot may be blocked by an obstacle.")

    elif not cmd_zero and speed_zero:
        lines.append("The robot is receiving movement commands, but the speed feedback is still zero.")
        lines.append("This suggests the issue may be in the QBot driver, motor enable state, or hardware response.")

    elif obstacle_close:
        lines.append("LiDAR is detecting a close object.")
        lines.append("The robot may need a clearer path before moving safely.")

    else:
        lines.append("The current topic state does not show a clear failure pattern.")
        lines.append("Check /cmd_vel, /qbot_speed_feedback, and /scan together.")

    if error_history:
        latest = error_history[0]
        count = latest.get("count", 0)

        if count > 1:
            lines.append(
                f"This stored error has happened before. It has been seen {count} times."
            )
        else:
            lines.append("This stored error appears to be new or has only been seen once.")

        lines.append(
            f"Latest stored error: [{latest.get('severity')}] {latest.get('node')}: {latest.get('message')}"
        )

    else:
        lines.append("No previous error history is stored yet.")

    return "\n".join(lines)
