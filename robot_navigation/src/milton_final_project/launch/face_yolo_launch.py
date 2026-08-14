import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.actions import Node


def generate_launch_description():
    qbot_platform_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                get_package_share_directory('qbot_platform'),
                'launch',
                'qbot_platform_launch.py',
            )
        )
    )

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

    face_display_node = Node(
        package='milton_final_project',
        executable='face_display_node',
        name='face_display_node',
        output='screen',
        parameters=[
            {'width': 1024},
            {'height': 600},
            {'fullscreen': True},
            {'show_help': False},
            {'initial_expression': 'neutral'},
            {
                'waiting_message':
                "Hi, I'm the navigation robot that helps you find a location or room."
            },
            {'response_duration_sec': 10.0},
        ],
    )

    main_controller_node = Node(
        package='milton_final_project',
        executable='main_controller_node',
        name='main_controller_node',
        output='screen',
        parameters=[
            {
                'waiting_message':
                "Hi, I'm the navigation robot that helps you find a location or room."
            },
            {'response_duration_sec': 10.0},
        ],
    )

    speech_node = Node(
        package='milton_final_project',
        executable='speech_node',
        name='speech_node',
        output='screen',
    )

    light_controller_node = Node(
        package='milton_final_project',
        executable='light_controller_node',
        name='light_controller_node',
        output='screen',
    )

    waiting_person_greeter_node = Node(
        package='milton_final_project',
        executable='waiting_person_greeter_node',
        name='waiting_person_greeter_node',
        output='screen',
    )

    return LaunchDescription([
        qbot_platform_launch,
        realsense_launch,
        yolo_node,
        waiting_person_greeter_node,
        face_display_node,
        main_controller_node,
        speech_node,
        light_controller_node,
    ])
