from session_manager import SessionManager


manager = SessionManager(
    base_log_dir="runtime_logs",
    ROS_DOMAIN_ID=39,
    map_name="home_test_v1",
    map_yaml_path=(
        "robot_navigation/maps/"
        "home_test_v1/home_test_v1.yaml"
    ),
    notes="SessionManager test",
)

manager.start_session()

input("Press Enter to close the session...")

manager.close_session()
