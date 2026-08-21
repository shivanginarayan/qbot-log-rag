"""Physical QBot manual mapping with Cartographer and the gamepad controller."""

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def generate_launch_description():
    package_dir = get_package_share_directory("qbot_platform")
    navigation_root = os.path.abspath(
        os.path.join(package_dir, "..", "..", "..", "..")
    )

    configuration_basename = LaunchConfiguration("configuration_basename")
    resolution = LaunchConfiguration("resolution")
    publish_period_sec = LaunchConfiguration("publish_period_sec")
    use_scan_filter = LaunchConfiguration("use_scan_filter")
    scan_filter_file = LaunchConfiguration("scan_filter_file")
    raw_scan_topic = LaunchConfiguration("raw_scan_topic")
    filtered_scan_topic = LaunchConfiguration("filtered_scan_topic")
    mapping_scan_topic = PythonExpression(
        [
            "'",
            use_scan_filter,
            "'.lower() in ['true', '1', 'yes'] and '",
            filtered_scan_topic,
            "' or '",
            raw_scan_topic,
            "'",
        ]
    )

    arguments = [
        DeclareLaunchArgument(
            "configuration_basename",
            default_value="qbot_platform_2d.lua",
            description="Cartographer Lua configuration filename",
        ),
        DeclareLaunchArgument(
            "resolution",
            default_value="0.01",
            description="Occupancy grid resolution in meters per pixel",
        ),
        DeclareLaunchArgument(
            "publish_period_sec",
            default_value="1.0",
            description="Seconds between live occupancy-grid publications",
        ),
        DeclareLaunchArgument(
            "use_scan_filter",
            default_value="true",
            description="Filter fixed QBot LaserScan wedges before mapping",
        ),
        DeclareLaunchArgument(
            "scan_filter_file",
            default_value=os.path.join(
                navigation_root, "filters", "scan_wedge_filter.json"
            ),
            description="JSON/YAML wedge filter used while mapping",
        ),
        DeclareLaunchArgument(
            "raw_scan_topic",
            default_value="/scan",
            description="Raw QBot LaserScan topic",
        ),
        DeclareLaunchArgument(
            "filtered_scan_topic",
            default_value="/scan_filtered",
            description="Filtered LaserScan topic consumed by Cartographer",
        ),
    ]

    base_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(package_dir, "launch", "qbot_platform_launch.py")
        )
    )
    lidar_transform = Node(
        package="qbot_platform",
        executable="fixed_lidar_frame",
        name="fixed_lidar_frame",
        output="screen",
    )
    wheel_odometry = Node(
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
    joystick = Node(
        package="qbot_platform",
        executable="command",
        name="joystickCommands",
        output="screen",
    )
    scan_filter = Node(
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
    cartographer = Node(
        package="cartographer_ros",
        executable="cartographer_node",
        name="cartographer_node",
        output="screen",
        arguments=[
            "-configuration_directory",
            os.path.join(package_dir, "config"),
            "-configuration_basename",
            configuration_basename,
        ],
        remappings=[("scan", mapping_scan_topic)],
    )
    occupancy_grid = Node(
        package="cartographer_ros",
        executable="cartographer_occupancy_grid_node",
        name="cartographer_occupancy_grid_node",
        output="screen",
        arguments=[
            "-resolution",
            resolution,
            "-publish_period_sec",
            publish_period_sec,
        ],
    )

    return LaunchDescription(
        [
            *arguments,
            base_launch,
            lidar_transform,
            wheel_odometry,
            joystick,
            scan_filter,
            cartographer,
            occupancy_grid,
        ]
    )
