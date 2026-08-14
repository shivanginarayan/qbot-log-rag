import math


def _safe_float(value):
    try:
        if value is None:
            return None

        value = float(value)

        if math.isnan(value):
            return None

        return value

    except Exception:
        return None


def _is_zero(value, threshold=0.01):
    value = _safe_float(value)

    return value is not None and abs(value) < threshold


def apply_rules(retrieved_logs, current_context=None, mode="follower", user_query=""):
    findings = []

    user_query = (user_query or "").lower()
    mode = (mode or "follower").lower()

    is_battery_question = (
        "battery" in user_query
        or "voltage" in user_query
        or "power" in user_query
        or "charge" in user_query
    )

    is_movement_question = (
        not is_battery_question
        and (
            "move" in user_query
            or "moving" in user_query
            or "not moving" in user_query
            or "stopped" in user_query
            or "stop" in user_query
            or "follow" in user_query
            or "follower" in user_query
            or "bot" in user_query
            or "robot" in user_query
            or "why" in user_query
        )
    )

    ctx = current_context or {}
    topics = ctx.get("topics", {})

    cmd = topics.get("/cmd_vel", {}).get("latest_value", {}) or {}
    scan = topics.get("/scan", {}).get("latest_value", {}) or {}
    speed = topics.get("/qbot_speed_feedback", {}).get("latest_value", {}) or {}
    battery = topics.get("/qbot_battery", {}).get("latest_value", {}) or {}

    cmd_linear = _safe_float(cmd.get("linear_x"))
    cmd_angular = _safe_float(cmd.get("angular_z"))

    speed_linear = _safe_float(speed.get("linear_x"))
    speed_angular = _safe_float(speed.get("angular_z"))

    min_range = _safe_float(scan.get("min_range"))
    min_angle_rad = _safe_float(scan.get("min_angle_rad"))
    min_angle_deg = _safe_float(scan.get("min_angle_deg"))

    voltage = _safe_float(battery.get("voltage"))

    if min_angle_rad is not None and min_angle_deg is not None:
        angle_text = (
            f" at angle {min_angle_rad:.2f} rad "
            f"({min_angle_deg:.1f} degrees)"
        )
    else:
        angle_text = ""

    has_cmd = cmd_linear is not None and cmd_angular is not None
    has_speed = speed_linear is not None and speed_angular is not None
    has_scan = min_range is not None

    cmd_zero = has_cmd and _is_zero(cmd_linear) and _is_zero(cmd_angular)
    speed_zero = has_speed and _is_zero(speed_linear) and _is_zero(speed_angular)

    cmd_nonzero = has_cmd and not cmd_zero
    speed_nonzero = has_speed and not speed_zero

    # =========================================================
    # Battery questions
    # =========================================================

    if is_battery_question:

        if voltage is not None:

            findings.append({
                "issue": "Battery voltage available",
                "cause": (
                    f"Battery percentage is unavailable, "
                    f"but voltage is about {voltage:.2f} V."
                ),
                "action": (
                    "Use voltage instead of percentage for this QBot."
                )
            })

            if voltage < 11.5:
                findings.append({
                    "issue": "Battery voltage may be low",
                    "cause": (
                        f"The battery voltage is about {voltage:.2f} V, "
                        f"which may be low for reliable operation."
                    ),
                    "action": (
                        "Charge the QBot or connect it "
                        "to a stable power source."
                    )
                })

            return findings

        findings.append({
            "issue": "Battery data unavailable",
            "cause": (
                "The system could not read battery voltage "
                "from /qbot_battery."
            ),
            "action": (
                "Check whether /qbot_battery is publishing using: "
                "ros2 topic echo /qbot_battery"
            )
        })

        return findings

    # =========================================================
    # Follower mode diagnosis
    # =========================================================

    if mode == "follower" and is_movement_question:

        if not has_scan:
            global_min_range = _safe_float(scan.get("global_min_range"))
            global_min_angle_rad = _safe_float(scan.get("global_min_angle_rad"))
            global_min_angle_deg = _safe_float(scan.get("global_min_angle_deg"))

            if global_min_range is not None:
                findings.append({
                    "issue": "No object detected in follower front sector",
                    "cause": (
                        f"The follower front sector did not detect a valid object, "
                        f"but LiDAR sees the closest object elsewhere at about "
                        f"{global_min_range:.2f} m, angle {global_min_angle_rad:.2f} rad "
                        f"({global_min_angle_deg:.1f} degrees)."
                    ),
                    "action": (
                        "Move the object/person into the robot's front LiDAR sector, "
                        "or widen/adjust the follower front-angle range."
                    )
                })
                return findings

            findings.append({
                "issue": "Follower cannot diagnose distance",
                "cause": "No valid LiDAR distance was found from /scan.",
                "action": "Check whether /scan is active using: ros2 topic echo /scan"
            })
            return findings

        # -----------------------------------------------------
        # Too close
        # -----------------------------------------------------

        if min_range < 1.0:

            findings.append({
                "issue": "Follower stopped because object is too close",
                "cause": (
                    f"The closest object is about "
                    f"{min_range:.2f} m away{angle_text}. "
                    f"Your follower stops when the object "
                    f"is closer than about 1.0 m."
                ),
                "action": (
                    "Move the object/person farther away "
                    "so it is between about 1.0 m and 2.0 m."
                )
            })

            return findings

        # -----------------------------------------------------
        # Too far
        # -----------------------------------------------------

        if min_range > 2.0:

            findings.append({
                "issue": "Follower has nothing in range to follow",
                "cause": (
                    f"The closest object is about "
                    f"{min_range:.2f} m away{angle_text}. "
                    f"Your follower only starts following "
                    f"when something is within about 2.0 m."
                ),
                "action": (
                    "Place an object/person within 2.0 m "
                    "in front of the robot."
                )
            })

            return findings

        # -----------------------------------------------------
        # Inside follower range
        # -----------------------------------------------------

        if 1.0 <= min_range <= 2.0:

            if cmd_zero and speed_zero:

                findings.append({
                    "issue": (
                        "Follower sees object but is not commanding movement"
                    ),
                    "cause": (
                        f"The closest object is about "
                        f"{min_range:.2f} m away{angle_text}, "
                        f"which is inside the follower range, "
                        f"but /cmd_vel is still zero."
                    ),
                    "action": (
                        "Check whether /follower is running "
                        "and check runtime_logs/follower.err."
                    )
                })

                return findings

            if cmd_nonzero and speed_zero:

                findings.append({
                    "issue": (
                        "Follower is commanding movement "
                        "but robot is not moving"
                    ),
                    "cause": (
                        f"The object is in follower range at "
                        f"about {min_range:.2f} m{angle_text} "
                        f"and /cmd_vel is non-zero, "
                        f"but /qbot_speed_feedback is still zero."
                    ),
                    "action": (
                        "Check QBot motor enable state, "
                        "driver status, and physical blockage."
                    )
                })

                return findings

            if cmd_nonzero and speed_nonzero:

                findings.append({
                    "issue": "Follower is working",
                    "cause": (
                        f"The object is in range at "
                        f"about {min_range:.2f} m{angle_text}, "
                        f"/cmd_vel is active, "
                        f"and speed feedback shows movement."
                    ),
                    "action": "No action needed."
                })

                return findings

            findings.append({
                "issue": "Follower object is in range",
                "cause": (
                    f"The closest object is about "
                    f"{min_range:.2f} m away{angle_text}, "
                    f"which is inside the expected follower range."
                ),
                "action": (
                    "If the robot is not moving, "
                    "check /cmd_vel and /qbot_speed_feedback."
                )
            })

            return findings

    # =========================================================
    # Joystick mode diagnosis
    # =========================================================

    if mode == "joystick" and is_movement_question:

        if cmd_zero and speed_zero:

            findings.append({
                "issue": "Joystick is not sending movement command",
                "cause": (
                    "/cmd_vel is zero and "
                    "/qbot_speed_feedback is zero."
                ),
                "action": (
                    "Move the joystick and "
                    "check whether /cmd_vel changes."
                )
            })

            return findings

        if cmd_nonzero and speed_zero:

            findings.append({
                "issue": (
                    "Joystick command sent but robot is not moving"
                ),
                "cause": (
                    "/cmd_vel is non-zero, "
                    "but /qbot_speed_feedback is still zero."
                ),
                "action": (
                    "Check QBot driver, motor enable state, "
                    "and physical blockage."
                )
            })

            return findings

        if cmd_nonzero and speed_nonzero:

            findings.append({
                "issue": "Joystick control is working",
                "cause": (
                    "/cmd_vel is non-zero and "
                    "/qbot_speed_feedback shows movement."
                ),
                "action": "No action needed."
            })

            return findings

    # =========================================================
    # Generic fallback
    # =========================================================

    if is_movement_question:

        if cmd_zero and speed_zero:

            findings.append({
                "issue": (
                    "Robot is not moving because "
                    "no movement command is being sent"
                ),
                "cause": (
                    "/cmd_vel is zero and "
                    "/qbot_speed_feedback is also zero."
                ),
                "action": (
                    "In follower mode, check object distance. "
                    "In joystick mode, move the joystick "
                    "and check /cmd_vel."
                )
            })

            return findings

        if cmd_nonzero and speed_zero:

            findings.append({
                "issue": "Command sent but robot is not moving",
                "cause": (
                    "/cmd_vel appears non-zero, "
                    "but /qbot_speed_feedback is zero."
                ),
                "action": (
                    "Check motor enable state, "
                    "QBot driver status, and physical blockage."
                )
            })

            return findings

    findings.append({
        "issue": "No specific issue detected",
        "cause": (
            "The current question did not match "
            "a movement or battery diagnostic rule."
        ),
        "action": (
            "Ask about movement, follower behavior, "
            "battery, voltage, LiDAR, or previous errors."
        )
    })

    return findings