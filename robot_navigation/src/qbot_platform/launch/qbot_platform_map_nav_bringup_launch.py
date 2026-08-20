import os

from ament_index_python.packages import get_package_share_directory

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from nav2_common.launch import RewrittenYaml


def generate_launch_description():
    package_dir = get_package_share_directory("qbot_platform")
    nav2_dir = get_package_share_directory("nav2_bringup")

    navigation_root = os.path.abspath(
        os.path.join(package_dir, "..", "..", "..", "..")
    )
    labels_file = LaunchConfiguration("labels_file")
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
    configured_params = RewrittenYaml(
        source_file=params_file,
        param_rewrites={
            "amcl.ros__parameters.scan_topic": nav_scan_topic,
            "local_costmap.local_costmap.ros__parameters.voxel_layer.scan.topic": nav_scan_topic,
            "global_costmap.global_costmap.ros__parameters.obstacle_layer.scan.topic": nav_scan_topic,
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
        PythonLaunchDescriptionSource(os.path.join(package_dir, "launch", "qbot_platform_launch.py"))
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
        launch_arguments={
            "map": LaunchConfiguration("map"),
            "use_sim_time": "False",
            "params_file": configured_params,
            "autostart": "True",
            "use_composition": "False",
        }.items(),
    )

    navigation_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(nav2_dir, "launch", "navigation_launch.py")),
        launch_arguments={
            "use_sim_time": "False",
            "params_file": configured_params,
            "autostart": "True",
            "use_composition": "False",
        }.items(),
    )

    go_to_label_node = Node(
        package="qbot_platform",
        executable="go_to_label.py",
        name="go_to_label",
        output="screen",
        arguments=["--labels-file", labels_file],
    )

    breadcrumb_return_node = Node(
        condition=IfCondition(use_breadcrumb_return),
        package="qbot_platform",
        executable="breadcrumb_return.py",
        name="breadcrumb_return",
        output="screen",
    )

    return LaunchDescription(
        [
            map_arg,
            labels_file_arg,
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
            navigation_launch,
            go_to_label_node,
            breadcrumb_return_node,
        ]
    )
