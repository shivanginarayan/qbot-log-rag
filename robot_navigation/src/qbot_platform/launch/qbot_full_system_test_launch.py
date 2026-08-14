import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.actions import IncludeLaunchDescription
from launch.actions import TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


WAITING_MESSAGE = (
    "Hi, I'm the navigation robot that helps you find a location or room."
)


def generate_launch_description():
    qbot_share = get_package_share_directory("qbot_platform")
    realsense_share = get_package_share_directory("realsense2_camera")

    maps_dir = "/home/nvidia/857_Final_Project_Code/maps"
    map_name = LaunchConfiguration("map_name")
    map_yaml = LaunchConfiguration("map")
    labels_file = LaunchConfiguration("labels_file")
    use_breadcrumb_return = LaunchConfiguration("use_breadcrumb_return")
    use_scan_filter = LaunchConfiguration("use_scan_filter")
    scan_filter_file = LaunchConfiguration("scan_filter_file")
    raw_scan_topic = LaunchConfiguration("raw_scan_topic")
    filtered_scan_topic = LaunchConfiguration("filtered_scan_topic")
    default_map = PythonExpression(["'", maps_dir, "/' + '", map_name, "' + '.yaml'"])
    default_labels_file = PythonExpression([
        "'", maps_dir, "/' + '", map_name, "' + '_labels.json'"
    ])
    milton_start_delay = LaunchConfiguration("milton_start_delay")
    fullscreen = LaunchConfiguration("fullscreen")
    show_preview = LaunchConfiguration("show_preview")
    use_camera = LaunchConfiguration("use_camera")
    use_yolo = LaunchConfiguration("use_yolo")
    use_web_stream = LaunchConfiguration("use_web_stream")
    use_face = LaunchConfiguration("use_face")
    use_speech = LaunchConfiguration("use_speech")
    use_lights = LaunchConfiguration("use_lights")
    use_greeter = LaunchConfiguration("use_greeter")
    use_main_controller = LaunchConfiguration("use_main_controller")
    return_label = LaunchConfiguration("return_label")
    use_return_spin = LaunchConfiguration("use_return_spin")
    use_return_staging = LaunchConfiguration("use_return_staging")
    detection_model = LaunchConfiguration("detection_model")
    image_topic = LaunchConfiguration("image_topic")
    depth_topic = LaunchConfiguration("depth_topic")
    confidence = LaunchConfiguration("confidence")
    web_stream_port = LaunchConfiguration("web_stream_port")
    idle_search_delay_sec = LaunchConfiguration("idle_search_delay_sec")

    map_name_arg = DeclareLaunchArgument(
        "map_name",
        default_value="lab_map_new",
        description="Base map name used to derive maps/<name>.yaml and maps/<name>_labels.json.",
    )
    map_arg = DeclareLaunchArgument(
        "map",
        default_value=default_map,
        description="Full path to the map yaml used by Nav2 localization.",
    )
    labels_file_arg = DeclareLaunchArgument(
        "labels_file",
        default_value=default_labels_file,
        description="Full path to the map labels JSON used by label navigation.",
    )
    use_breadcrumb_return_arg = DeclareLaunchArgument(
        "use_breadcrumb_return",
        default_value="true",
        description="Start the breadcrumb return node.",
    )
    use_scan_filter_arg = DeclareLaunchArgument(
        "use_scan_filter",
        default_value="true",
        description="Use /scan_filtered for AMCL and Nav2 costmaps.",
    )
    scan_filter_file_arg = DeclareLaunchArgument(
        "scan_filter_file",
        default_value="/home/nvidia/857_Final_Project_Code/filters/scan_wedge_filter.json",
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
    milton_start_delay_arg = DeclareLaunchArgument(
        "milton_start_delay",
        default_value="5.0",
        description="Seconds to wait before starting Milton interaction nodes.",
    )
    fullscreen_arg = DeclareLaunchArgument(
        "fullscreen",
        default_value="true",
        description="Start the face display in fullscreen mode.",
    )
    show_preview_arg = DeclareLaunchArgument(
        "show_preview",
        default_value="false",
        description="Show the YOLO camera preview on the face display.",
    )
    use_camera_arg = DeclareLaunchArgument(
        "use_camera",
        default_value="true",
        description="Start the RealSense camera driver.",
    )
    use_yolo_arg = DeclareLaunchArgument(
        "use_yolo",
        default_value="true",
        description="Start YOLO detection.",
    )
    use_web_stream_arg = DeclareLaunchArgument(
        "use_web_stream",
        default_value="true",
        description="Start the YOLO web stream.",
    )
    use_face_arg = DeclareLaunchArgument(
        "use_face",
        default_value="true",
        description="Start the face display UI.",
    )
    use_speech_arg = DeclareLaunchArgument(
        "use_speech",
        default_value="true",
        description="Start speech input.",
    )
    use_lights_arg = DeclareLaunchArgument(
        "use_lights",
        default_value="true",
        description="Start light controller.",
    )
    use_greeter_arg = DeclareLaunchArgument(
        "use_greeter",
        default_value="true",
        description="Start waiting-person greeter.",
    )
    use_main_controller_arg = DeclareLaunchArgument(
        "use_main_controller",
        default_value="true",
        description="Start the Milton controller that publishes /label.",
    )
    return_label_arg = DeclareLaunchArgument(
        "return_label",
        default_value="__return_breadcrumbs__",
        description="Label or internal command used when returning after arrival.",
    )
    use_return_spin_arg = DeclareLaunchArgument(
        "use_return_spin",
        default_value="false",
        description="Spin before return; disabled for breadcrumb return.",
    )
    use_return_staging_arg = DeclareLaunchArgument(
        "use_return_staging",
        default_value="false",
        description="Use lidar staging before return; disabled for breadcrumb return.",
    )
    detection_model_arg = DeclareLaunchArgument(
        "detection_model",
        default_value="yolov8n.pt",
        description="YOLO model file.",
    )
    image_topic_arg = DeclareLaunchArgument(
        "image_topic",
        default_value="/camera/color/image_raw",
        description="Input color image topic for YOLO and face preview.",
    )
    depth_topic_arg = DeclareLaunchArgument(
        "depth_topic",
        default_value="/camera/aligned_depth_to_color/image_raw",
        description="Input aligned depth topic for YOLO.",
    )
    confidence_arg = DeclareLaunchArgument(
        "confidence",
        default_value="0.25",
        description="YOLO confidence threshold.",
    )
    web_stream_port_arg = DeclareLaunchArgument(
        "web_stream_port",
        default_value="8080",
        description="YOLO web stream port.",
    )
    idle_search_delay_sec_arg = DeclareLaunchArgument(
        "idle_search_delay_sec",
        default_value="2.0",
        description="Idle seconds before the greeter reacts to a detected person.",
    )

    qbot_navigation = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                qbot_share,
                "launch",
                "qbot_platform_map_nav_bringup_launch.py",
            )
        ),
        launch_arguments={
            "map_name": map_name,
            "map": map_yaml,
            "labels_file": labels_file,
            "use_breadcrumb_return": use_breadcrumb_return,
            "use_scan_filter": use_scan_filter,
            "scan_filter_file": scan_filter_file,
            "raw_scan_topic": raw_scan_topic,
            "filtered_scan_topic": filtered_scan_topic,
        }.items(),
    )

    realsense_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(
                realsense_share,
                "launch",
                "rs_launch.py",
            )
        ),
        condition=IfCondition(use_camera),
        launch_arguments={"align_depth.enable": "true"}.items(),
    )

    yolo_node = Node(
        condition=IfCondition(use_yolo),
        package="milton_final_project",
        executable="yolo_node",
        name="yolo_node",
        output="screen",
        additional_env={
            "LD_PRELOAD": "/lib/aarch64-linux-gnu/libgomp.so.1",
        },
        parameters=[
            {"detection_model": detection_model},
            {"image_topic": image_topic},
            {"depth_topic": depth_topic},
            {"confidence": confidence},
        ],
    )

    yolo_web_stream = Node(
        condition=IfCondition(use_web_stream),
        package="milton_final_project",
        executable="yolo_web_stream",
        name="yolo_web_stream",
        output="screen",
        parameters=[
            {"image_topic": "/yolo/annotated_image"},
            {"host": "0.0.0.0"},
            {"port": web_stream_port},
        ],
    )

    face_display_node = Node(
        condition=IfCondition(use_face),
        package="milton_final_project",
        executable="face_display_node",
        name="face_display_node",
        output="screen",
        parameters=[
            {"width": 1024},
            {"height": 600},
            {"fullscreen": fullscreen},
            {"show_preview": show_preview},
            {"show_help": False},
            {"initial_expression": "neutral"},
            {"waiting_message": WAITING_MESSAGE},
            {"response_duration_sec": 10.0},
        ],
    )

    main_controller_node = Node(
        condition=IfCondition(use_main_controller),
        package="milton_final_project",
        executable="main_controller_node",
        name="main_controller_node",
        output="screen",
        parameters=[
            {"waiting_message": WAITING_MESSAGE},
            {"response_duration_sec": 10.0},
            {"return_label": return_label},
            {"use_return_spin": use_return_spin},
            {"use_return_staging": use_return_staging},
        ],
    )

    speech_node = Node(
        condition=IfCondition(use_speech),
        package="milton_final_project",
        executable="speech_node",
        name="speech_node",
        output="screen",
    )

    light_controller_node = Node(
        condition=IfCondition(use_lights),
        package="milton_final_project",
        executable="light_controller_node",
        name="light_controller_node",
        output="screen",
    )

    waiting_person_greeter_node = Node(
        condition=IfCondition(use_greeter),
        package="milton_final_project",
        executable="waiting_person_greeter_node",
        name="waiting_person_greeter_node",
        output="screen",
        parameters=[
            {"idle_search_delay_sec": idle_search_delay_sec},
            {"stable_detection_sec": 0.2},
            {"greeting_cooldown_sec": 12.0},
        ],
    )

    milton_nodes = TimerAction(
        period=milton_start_delay,
        actions=[
            speech_node,
            face_display_node,
            main_controller_node,
            waiting_person_greeter_node,
            light_controller_node,
            yolo_node,
            yolo_web_stream,
        ],
    )

    return LaunchDescription(
        [
            map_name_arg,
            map_arg,
            labels_file_arg,
            use_breadcrumb_return_arg,
            use_scan_filter_arg,
            scan_filter_file_arg,
            raw_scan_topic_arg,
            filtered_scan_topic_arg,
            milton_start_delay_arg,
            fullscreen_arg,
            show_preview_arg,
            use_camera_arg,
            use_yolo_arg,
            use_web_stream_arg,
            use_face_arg,
            use_speech_arg,
            use_lights_arg,
            use_greeter_arg,
            use_main_controller_arg,
            return_label_arg,
            use_return_spin_arg,
            use_return_staging_arg,
            detection_model_arg,
            image_topic_arg,
            depth_topic_arg,
            confidence_arg,
            web_stream_port_arg,
            idle_search_delay_sec_arg,
            qbot_navigation,
            realsense_launch,
            milton_nodes,
        ]
    )
