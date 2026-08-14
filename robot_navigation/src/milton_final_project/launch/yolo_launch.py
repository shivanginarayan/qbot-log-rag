import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    realsense_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('realsense2_camera'),
                'launch',
                'rs_launch.py',
            )
        ),
        launch_arguments={
            'align_depth.enable': 'true',
        }.items(),
    )

    yolo_node = Node(
        package='milton_final_project',
        executable='yolo_node',
        name='yolo_node',
        output='screen',
        additional_env={
            'LD_PRELOAD': '/lib/aarch64-linux-gnu/libgomp.so.1',
        },
        parameters=[
            {'detection_model': 'yolov8n.pt'},
            {'image_topic': '/camera/color/image_raw'},
            {'depth_topic': '/camera/aligned_depth_to_color/image_raw'},
            {'confidence': 0.25},
        ],
    )

    web_stream = Node(
        package='milton_final_project',
        executable='yolo_web_stream',
        name='yolo_web_stream',
        output='screen',
        parameters=[
            {'image_topic': '/yolo/annotated_image'},
            {'host': '0.0.0.0'},
            {'port': 8080},
        ],
    )

    return LaunchDescription([
        realsense_launch,
        yolo_node,
        web_stream,
    ])
