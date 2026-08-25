cmake_minimum_required(VERSION 3.8)
project(qbot_platform)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(action_msgs REQUIRED)
find_package(behaviortree_cpp_v3 REQUIRED)
find_package(control_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(nav2_behavior_tree REQUIRED)
find_package(nav2_msgs REQUIRED)
find_package(rclcpp REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(std_msgs REQUIRED)
find_package(tf2 REQUIRED)
find_package(tf2_ros REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "action/ManualAssistance.action"
  DEPENDENCIES action_msgs
)

add_compile_definitions(_NVIDIA)

add_executable(qbot_platform_driver_interface src/qbot_platform_driver_interface.cpp)
target_link_libraries(qbot_platform_driver_interface -lquanser_communications)
ament_target_dependencies(
  qbot_platform_driver_interface
  control_msgs
  geometry_msgs
  rclcpp
  sensor_msgs
  std_msgs
)

add_executable(lidar src/lidar.cpp)
target_link_libraries(lidar -lquanser_devices -lquanser_communications -lquanser_runtime -lquanser_common)
ament_target_dependencies(lidar rclcpp sensor_msgs)

add_executable(fixed_lidar_frame src/fixed_lidar_frame.cpp)
ament_target_dependencies(fixed_lidar_frame geometry_msgs rclcpp tf2 tf2_ros)

add_executable(command src/command.cpp)
target_link_libraries(command -lquanser_devices -lquanser_communications -lquanser_runtime -lquanser_common)
ament_target_dependencies(command geometry_msgs rclcpp std_msgs)

add_library(qbot_manual_assistance_action_bt_node SHARED
  src/manual_assistance_action.cpp
)
ament_target_dependencies(
  qbot_manual_assistance_action_bt_node
  behaviortree_cpp_v3
  nav2_behavior_tree
  rclcpp
)
rosidl_target_interfaces(
  qbot_manual_assistance_action_bt_node
  ${PROJECT_NAME} "rosidl_typesupport_cpp"
)
target_compile_definitions(qbot_manual_assistance_action_bt_node PRIVATE BT_PLUGIN_EXPORT)

install(
  TARGETS
    command
    fixed_lidar_frame
    lidar
    qbot_platform_driver_interface
    qbot_manual_assistance_action_bt_node
  ARCHIVE DESTINATION lib
  LIBRARY DESTINATION lib
  RUNTIME DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY launch
  DESTINATION share/${PROJECT_NAME}/
)

install(PROGRAMS
  scripts/adaptive_goal_tolerance.py
  scripts/breadcrumb_return.py
  scripts/cmd_vel_arbiter.py
  scripts/init_map_labels.py
  scripts/go_to_label.py
  scripts/led_controller.py
  scripts/manual_assistance.py
  scripts/scan_wedge_filter.py
  scripts/wheel_odometry.py
  DESTINATION lib/${PROJECT_NAME}
)

install(DIRECTORY rt_models
  DESTINATION share/${PROJECT_NAME}/
)

install(DIRECTORY config
  DESTINATION share/${PROJECT_NAME}/
)

install(DIRECTORY behavior_trees
  DESTINATION share/${PROJECT_NAME}/
)

if(BUILD_TESTING)
  find_package(ament_lint_auto REQUIRED)
  set(ament_cmake_copyright_FOUND TRUE)
  set(ament_cmake_cpplint_FOUND TRUE)
  ament_lint_auto_find_test_dependencies()
endif()

ament_export_dependencies(rosidl_default_runtime)

ament_package()
