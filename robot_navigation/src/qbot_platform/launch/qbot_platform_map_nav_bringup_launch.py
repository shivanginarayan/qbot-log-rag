import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, GroupAction, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node, SetRemap
from nav2_common.launch import RewrittenYaml


def generate_launch_description():
    package_dir = get_package_share_directory("qbot_platform")
    nav2_dir = get_package_share_directory("nav2_bringup")

    navigation_root = os.path.abspath(
        os.path.join(package_dir, "..", "..", "..", "..")
    )
    labels_file = LaunchConfiguration("labels_file")
    localizer = LaunchConfiguration("localizer")
    pbstream = LaunchConfiguration("pbstream")
    use_adaptive_goal_tolerance = LaunchConfiguration(
        "use_adaptive_goal_tolerance"
    )
    use_breadcrumb_return = LaunchConfiguration("use_breadcrumb_return")
    use_scan_filter = LaunchConfiguration("use_scan_filter")
    scan_filter_file = LaunchConfiguration("scan_filter_file")
    raw_scan_topic = LaunchConfiguration("raw_scan_topic")
    filtered_scan_topic = LaunchConfiguration("filtered_scan_topic")
    nav_scan_topic = PythonExpression([
        "'",
        use_scan_filter,
        "'.lower() in ['true', '1', 'yes'] and '",
        filtered_scan_topic,
        "' or '",
        raw_scan_topic,
        "'",
    ])
    params_file = os.path.join(package_dir, "config", "qbot_platform_slam_and_nav.yaml")
    navigate_to_pose_bt = os.path.join(
        package_dir,
        "behavior_trees",
        "qbot_navigate_to_pose_with_backup.xml",
    )
    amcl_condition = IfCondition(
        PythonExpression(["'", localizer, "'.lower() == 'amcl'"])
    )
    cartographer_condition = IfCondition(
        PythonExpression(["'", localizer, "'.lower() == 'cartographer'"])
    )
    configured_params = RewrittenYaml(
        source_file=params_file,
        param_rewrites={
            "amcl.ros__parameters.scan_topic": nav_scan_topic,
            "local_costmap.local_costmap.ros__parameters.voxel_layer.scan.topic": nav_scan_topic,
            (
                "global_costmap.global_costmap.ros__parameters."
                "obstacle_layer.scan.topic"
            ): nav_scan_topic,
            "bt_navigator.ros__parameters.default_nav_to_pose_bt_xml": navigate_to_pose_bt,
        },
        convert_types=True,
    )

    map_arg = DeclareLaunchArgument(
        "map",
        description="Required full path to the map YAML used by Nav2 localization.",
    )
    labels_file_arg = DeclareLaunchArgument(
        "labels_file",
        description="Required full path to the matching labels JSON.",
    )
    localizer_arg = DeclareLaunchArgument(
        "localizer",
        default_value="amcl",
        description="Localization backend: amcl or cartographer.",
    )
    pbstream_arg = DeclareLaunchArgument(
        "pbstream",
        default_value="",
        description="Required Cartographer state file in cartographer mode.",
    )
    use_adaptive_goal_tolerance_arg = DeclareLaunchArgument(
        "use_adaptive_goal_tolerance",
        default_value="true",
        description=(
            "Adjust Nav2 XY goal tolerance between 0.15 m and 0.20 m from "
            "AMCL covariance. Disable to retain the fixed YAML tolerance."
        ),
    )
    use_breadcrumb_return_arg = DeclareLaunchArgument(
        "use_breadcrumb_return",
        default_value="true",
        description="Record sparse outbound breadcrumbs and use them for return-home.",
    )
    use_scan_filter_arg = DeclareLaunchArgument(
        "use_scan_filter",
        default_value="true",
        description="Use /scan_filtered for AMCL and Nav2 costmaps.",
    )
    scan_filter_file_arg = DeclareLaunchArgument(
        "scan_filter_file",
        default_value=os.path.join(
            navigation_root,
            "filters",
            "scan_wedge_filter.json",
        ),
        description="JSON/YAML wedge filter file used by scan_wedge_filter.py.",
    )
    raw_scan_topic_arg = DeclareLaunchArgument(
        "raw_scan_topic",
        default_value="/scan",
        description="Raw LaserScan topic from the lidar driver.",
    )
    filtered_scan_topic_arg = DeclareLaunchArgument(
        "filtered_scan_topic",
        default_value="/scan_filtered",
        description="Filtered LaserScan topic consumed by navigation when enabled.",
    )

    base_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(package_dir, "launch", "qbot_platform_launch.py")
        )
    )

    lidar_tf_node = Node(
        package="qbot_platform",
        executable="fixed_lidar_frame",
        name="fixed_lidar_frame",
        output="screen",
    )

    wheel_odom_node = Node(
        package="qbot_platform",
        executable="wheel_odometry.py",
        name="wheel_odometry",
        output="screen",
        parameters=[
            {
                "imu_angular_velocity_scale": 0.970,
                "use_imu_yaw": False,
            }
        ],
    )

    scan_filter_node = Node(
        condition=IfCondition(use_scan_filter),
        package="qbot_platform",
        executable="scan_wedge_filter.py",
        name="scan_wedge_filter",
        output="screen",
        parameters=[
            {"input_topic": raw_scan_topic},
            {"output_topic": filtered_scan_topic},
            {"filter_file": scan_filter_file},
        ],
    )

    localization_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(nav2_dir, "launch", "localization_launch.py")),
        condition=amcl_condition,
        launch_arguments={
            "map": LaunchConfiguration("map"),
            "use_sim_time": "False",
            "params_file": configured_params,
            "autostart": "True",
            "use_composition": "False",
        }.items(),
    )

    cartographer_localizer = Node(
        condition=cartographer_condition,
        package="cartographer_ros",
        executable="cartographer_node",
        name="cartographer_node",
        output="screen",
        arguments=[
            "-configuration_directory",
            os.path.join(package_dir, "config"),
            "-configuration_basename",
            "qbot_platform_2d_localization.lua",
            "-load_state_filename",
            pbstream,
        ],
        remappings=[("scan", nav_scan_topic)],
    )
    cartographer_map_server = Node(
        condition=cartographer_condition,
        package="nav2_map_server",
        executable="map_server",
        name="map_server",
        output="screen",
        parameters=[configured_params, {"yaml_filename": LaunchConfiguration("map")}],
    )
    cartographer_map_lifecycle = Node(
        condition=cartographer_condition,
        package="nav2_lifecycle_manager",
        executable="lifecycle_manager",
        name="lifecycle_manager_localization",
        output="screen",
        parameters=[
            {"use_sim_time": False},
            {"autostart": True},
            {"node_names": ["map_server"]},
        ],
    )

    # Nav2 Humble otherwise leaves the velocity smoother and behavior server as
    # competing /cmd_vel publishers. Node-specific remaps give each path a
    # dedicated input to cmd_vel_arbiter while preserving Nav2's internal
    # controller -> /cmd_vel_nav -> velocity_smoother connection.
    navigation_launch = GroupAction(
        actions=[
            SetRemap(
                src="velocity_smoother:cmd_vel_smoothed",
                dst="/cmd_vel_auto",
            ),
            SetRemap(
                src="behavior_server:cmd_vel",
                dst="/cmd_vel_behavior",
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    os.path.join(nav2_dir, "launch", "navigation_launch.py")
                ),
                launch_arguments={
                    "use_sim_time": "False",
                    "params_file": configured_params,
                    "autostart": "True",
                    "use_composition": "False",
                }.items(),
            ),
        ]
    )

    cmd_vel_arbiter_node = Node(
        package="qbot_platform",
        executable="cmd_vel_arbiter.py",
        name="cmd_vel_arbiter",
        output="screen",
        parameters=[
            {"navigation_topic": "/cmd_vel_auto"},
            {"behavior_topic": "/cmd_vel_behavior"},
            {"output_topic": "/cmd_vel"},
            {"navigation_timeout": 0.5},
            {"behavior_timeout": 0.3},
            {"publish_frequency": 20.0},
        ],
    )

    go_to_label_node = Node(
        package="qbot_platform",
        executable="go_to_label.py",
        name="go_to_label",
        output="screen",
        arguments=[
            "--labels-file",
            labels_file,
            "--cmd-vel-topic",
            "/cmd_vel_nav",
            "--localizer",
            localizer,
            "--normal-bt",
            navigate_to_pose_bt,
        ],
    )

    adaptive_goal_tolerance_node = Node(
        condition=IfCondition(
            PythonExpression(
                [
                    "'",
                    use_adaptive_goal_tolerance,
                    "'.lower() in ['true', '1', 'yes'] and '",
                    localizer,
                    "'.lower() == 'amcl'",
                ]
            )
        ),
        package="qbot_platform",
        executable="adaptive_goal_tolerance.py",
        name="adaptive_goal_tolerance",
        output="screen",
        parameters=[configured_params],
    )

    breadcrumb_return_node = Node(
        condition=IfCondition(use_breadcrumb_return),
        package="qbot_platform",
        executable="breadcrumb_return.py",
        name="breadcrumb_return",
        output="screen",
    )

    navigation_joystick = Node(
        package="qbot_platform",
        executable="command",
        name="navigation_joystick",
        output="screen",
        parameters=[
            {"manual_drive_enabled": True},
            {"cmd_vel_topic": "/cmd_vel_teleop"},
            {"lb_state_topic": "/controller/lb_held"},
        ],
    )
    manual_assistance_node = Node(
        package="qbot_platform",
        executable="manual_assistance.py",
        name="manual_assistance",
        output="screen",
    )

    return LaunchDescription(
        [
            map_arg,
            labels_file_arg,
            localizer_arg,
            pbstream_arg,
            use_adaptive_goal_tolerance_arg,
            use_breadcrumb_return_arg,
            use_scan_filter_arg,
            scan_filter_file_arg,
            raw_scan_topic_arg,
            filtered_scan_topic_arg,
            base_launch,
            lidar_tf_node,
            wheel_odom_node,
            scan_filter_node,
            localization_launch,
            cartographer_localizer,
            cartographer_map_server,
            cartographer_map_lifecycle,
            navigation_launch,
            cmd_vel_arbiter_node,
            adaptive_goal_tolerance_node,
            go_to_label_node,
            breadcrumb_return_node,
            navigation_joystick,
            manual_assistance_node,
        ]
    )
