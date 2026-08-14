from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    fullscreen = LaunchConfiguration('fullscreen')
    show_preview = LaunchConfiguration('show_preview')
    use_camera = LaunchConfiguration('use_camera')
    use_yolo = LaunchConfiguration('use_yolo')
    detection_model = LaunchConfiguration('detection_model')
    image_topic = LaunchConfiguration('image_topic')
    depth_topic = LaunchConfiguration('depth_topic')
    confidence = LaunchConfiguration('confidence')
    idle_search_delay_sec = LaunchConfiguration('idle_search_delay_sec')

    qbot_platform_driver_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('qbot_platform'),
                'launch',
                'qbot_platform_launch.py',
            ])
        )
    )

    realsense_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('realsense2_camera'),
                'launch',
                'rs_launch.py',
            ])
        ),
        condition=IfCondition(use_camera),
        launch_arguments={
            'align_depth.enable': 'true',
        }.items(),
    )

    face_display_node = Node(
        package='milton_final_project',
        executable='face_display_node',
        name='face_display_node',
        output='screen',
        parameters=[
            {'width': 1024},
            {'height': 600},
            {'fullscreen': fullscreen},
            {'show_help': False},
            {'show_preview': show_preview},
            {'initial_expression': 'neutral'},
            {
                'waiting_message': (
                    'I am the SEIC navigation robot. Please enter the person '
                    'or room you are trying to find.'
                ),
            },
            {'response_duration_sec': 10.0},
            {'confirmation_timeout_sec': 60.0},
            {'navigation_timeout_sec': 20.0},
        ],
    )

    main_controller_node = Node(
        package='milton_final_project',
        executable='main_controller_node',
        name='main_controller_node',
        output='screen',
        parameters=[
            {
                'waiting_message': (
                    'I am the SEIC navigation robot. Please enter the person '
                    'or room you are trying to find.'
                ),
            },
            {'response_duration_sec': 10.0},
            {'confirmation_timeout_sec': 60.0},
            {'navigation_timeout_sec': 20.0},
        ],
    )

    speech_node = Node(
        package='milton_final_project',
        executable='speech_node',
        name='speech_node',
        output='screen',
    )

    waiting_person_greeter_node = Node(
        package='milton_final_project',
        executable='waiting_person_greeter_node',
        name='waiting_person_greeter_node',
        output='screen',
        parameters=[
            {'idle_search_delay_sec': idle_search_delay_sec},
            {'stable_detection_sec': 0.2},
            {'greeting_cooldown_sec': 12.0},
            {
                'greeting_message': (
                    'Hello there. I can help you find a room or person.'
                ),
            },
            {'greeting_expression': 'happy'},
        ],
    )

    light_controller_node = Node(
        package='milton_final_project',
        executable='light_controller_node',
        name='light_controller_node',
        output='screen',
    )

    yolo_node = Node(
        condition=IfCondition(use_yolo),
        package='milton_final_project',
        executable='yolo_node',
        name='yolo_node',
        output='screen',
        additional_env={
            'LD_PRELOAD': '/lib/aarch64-linux-gnu/libgomp.so.1',
        },
        parameters=[
            {'detection_model': detection_model},
            {'image_topic': image_topic},
            {'depth_topic': depth_topic},
            {'confidence': confidence},
        ],
    )

    return LaunchDescription([
        DeclareLaunchArgument('fullscreen', default_value='true'),
        DeclareLaunchArgument('show_preview', default_value='false'),
        DeclareLaunchArgument('use_camera', default_value='true'),
        DeclareLaunchArgument('use_yolo', default_value='true'),
        DeclareLaunchArgument('detection_model', default_value='yolov8n.pt'),
        DeclareLaunchArgument('image_topic', default_value='/camera/color/image_raw'),
        DeclareLaunchArgument(
            'depth_topic',
            default_value='/camera/aligned_depth_to_color/image_raw',
        ),
        DeclareLaunchArgument('confidence', default_value='0.25'),
        DeclareLaunchArgument('idle_search_delay_sec', default_value='2.0'),
        qbot_platform_driver_launch,
        realsense_launch,
        face_display_node,
        main_controller_node,
        speech_node,
        waiting_person_greeter_node,
        light_controller_node,
        yolo_node,
    ])
