# 857_Final_Project_Code

This repository contains a ROS 2 wayfinding and object-detection project plus a
standalone `pygame` robot face demo.

## Main Features

- A standalone animated robot face in `robot_face.py`
- A ROS 2 face display node with a lighter UI, purple face glow, camera preview, and a border that turns green when a tracked person is currently seen
- A terminal-based wayfinding input node plus a history logger for destination requests
- A light controller node that maps robot states to LED colors
- A SEIC directory lookup workflow backed by `data/seic_public_directory.xlsx` plus custom person entries and alias matching
- A YOLO object-detection node using `yolov8n.pt` and aligned depth for distance estimates
- State-aware YOLO and lidar tracking that automatically pauses while the robot is not in the `waiting` state
- A waiting greeter node that turns toward nearby people and stops once they are within `6 in`
- A simple web stream for the annotated YOLO output

## Run The Standalone Face Demo

```bash
cd /home/nvidia/857_Final_Project_Code
python robot_face.py
```

## Install Python Requirements

```bash
cd /home/nvidia/857_Final_Project_Code
python3 -m pip install -r requirements.txt
```

## Run The ROS 2 Face And YOLO System

```bash
cd /home/nvidia/857_Final_Project_Code
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash
ros2 launch milton_final_project face_yolo_launch.py
```

This launch file starts the face display, YOLO pipeline, face display web GUI,
and light controller.
The face UI now subscribes to `/yolo/person_target` and draws a blue border while idle, then a green border when a person is actively detected.

Open the face display web GUI at:

```text
http://localhost:8080
```

When viewing from another machine, replace `localhost` with the robot's IP
address or forward the port with SSH.
The browser page streams the same `face_display_node` screen shown on the robot
and includes controls for entering destinations and sending yes/no replies.

## Waiting Greeter Behavior

The waiting greeter node listens for YOLO person detections, rotates the robot
toward the detected person, and now stops moving once that person is within
`6 in` of the robot.

The stop threshold is controlled by the `stop_distance_ft` ROS parameter in
`waiting_person_greeter_node.py`, and its default value is `0.5`.
The detection stability window was also reduced to `0.2 s` so the robot responds more quickly when a person enters view.

When the robot leaves the `waiting` state, the greeter now clears stale motion and person targets and immediately publishes a zero-velocity command.

## Run The Terminal Wayfinding Input Node

```bash
cd /home/nvidia/857_Final_Project_Code
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash
ros2 run milton_final_project wayfinding_input_node
```

## Run The Input History Logger Node

This companion node records each typed destination and confirmation response to
`/home/nvidia/857_Final_Project_Code/runtime_logs/wayfinding_input_history.csv`.

```bash
cd /home/nvidia/857_Final_Project_Code
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash
ros2 run milton_final_project wayfinding_history_node
```

## Run The LED Light Controller Node

This node listens for robot state updates such as `waiting`, `confirmation`,
and `navigation`, then publishes matching LED colors.

```bash
cd /home/nvidia/857_Final_Project_Code
source /opt/ros/humble/setup.bash
colcon build
source install/setup.bash
ros2 run milton_final_project light_controller_node
```

## Run Controller QBot Mapping

This launch file starts the QBot platform driver, QBot lidar, QBot lidar TF,
Cartographer mapping, and QBot's built-in controller command node. Use the QBot
controller to drive while Cartographer builds the map.

Saved maps are written to `/home/nvidia/857_Final_Project_Code/maps` as paired
`.yaml` and image files with names like `mapped_area_20260505_153000.yaml`.

```bash
cd /home/nvidia/857_Final_Project_Code
source /opt/ros/humble/setup.bash
source /home/nvidia/ros2/install/setup.bash
colcon build
source install/setup.bash
ros2 launch milton_final_project slam_keyboard_mapping_launch.py
```

When you are ready to save the map, keep the mapping launch running and use a
second terminal:

```bash
cd /home/nvidia/857_Final_Project_Code
source /opt/ros/humble/setup.bash
source /home/nvidia/ros2/install/setup.bash
source install/setup.bash
ros2 run milton_final_project save_latest_map
```

Saved maps are cleaned by default: tiny occupied speckles are removed and very
small wall gaps are closed in the generated `.pgm`. To save the unfiltered map
instead, run:

```bash
ros2 run milton_final_project save_latest_map -- --raw
```

If you saved with `nav2_map_server map_saver_cli`, clean that saved map after
saving:

```bash
ROS_DOMAIN_ID=57 ros2 run milton_final_project filter_saved_map -- \
  --map /home/nvidia/857_Final_Project_Code/maps/slam_toolbox_map.yaml \
  --overwrite
```

This keeps `.raw` backups beside the original files and removes small occupied
speckles, small wall gaps, and thin free-space ray spikes.

After it prints `Map save complete`, you can stop the mapping launch with
`Ctrl+C`.

To save the robot's current pose as the starting location for the map, run this
after saving the map:

```bash
ROS_DOMAIN_ID=57 ros2 run milton_final_project save_robot_start_pose \
  --map-dir /home/nvidia/857_Final_Project_Code/maps \
  --map slam_toolbox_map.yaml
```

This resets the map's labels by default and writes `robot_start`, `start`,
`home`, and `original` to the same pose. Add `--keep-existing-labels` if you are
updating the start pose on a map whose other labels you want to keep.

## View A Saved Map In 3D Over SSH

This starts a small web server on the QBot and streams a browser-based 3D map
viewer. It automatically opens the newest map in
`/home/nvidia/857_Final_Project_Code/maps`.

On the QBot:

```bash
cd /home/nvidia/857_Final_Project_Code
source /opt/ros/humble/setup.bash
source /home/nvidia/ros2/install/setup.bash
source install/setup.bash
ros2 run milton_final_project map_3d_viewer
```

From your laptop, open an SSH tunnel:

```bash
ssh -L 8092:localhost:8092 nvidia@<qbot-ip>
```

Then open this in your laptop browser:

```text
http://localhost:8092
```

Labels are saved per map. For a map named
`mapped_area_20260505_153000.yaml`, labels are saved beside it as
`mapped_area_20260505_153000.labels.yaml`.

## Navigate To A Saved Map Label

First start the QBot driver, localization, map server, and Nav2 navigation
stack. By default, this launch uses the newest saved map in
`/home/nvidia/857_Final_Project_Code/maps`.

```bash
cd /home/nvidia/857_Final_Project_Code
source /opt/ros/humble/setup.bash
source /home/nvidia/ros2/install/setup.bash
colcon build --packages-select milton_final_project
source install/setup.bash
ros2 launch milton_final_project qbot_navigation_launch.py
```

In a second terminal, send the robot to a label from the newest map's matching
`.labels.yaml` file:

```bash
cd /home/nvidia/857_Final_Project_Code
source /opt/ros/humble/setup.bash
source /home/nvidia/ros2/install/setup.bash
source install/setup.bash
ros2 run milton_final_project navigate_to_label overthere
```

Use the 3D map viewer to add more labels, then replace `overthere` with the
label name.

To return to the saved starting pose:

```bash
ROS_DOMAIN_ID=57 ros2 run milton_final_project return_to_start
```

The same behavior is also available through:

```bash
ROS_DOMAIN_ID=57 ros2 run milton_final_project navigate_to_label -- --start
```

Default web ports are kept separate: live SLAM map `8090`, mapping LiDAR/filter
viewer `8091`, saved 3D map label viewer `8092`, navigation map viewer `8093`,
optional navigation LiDAR/filter viewer `8094`, and mapping camera stream `8095`.

During mapping, the live SLAM map page on port `8090` also has buttons for
`Save Map`, `Filter Map`, and `Save Start`. Use them in that order while the
mapping launch is still running.

## Python Requirements

The pip-based Python dependencies are listed in `requirements.txt`.
Install them with `python3 -m pip install -r requirements.txt`.

ROS-specific packages such as `rclpy`, `cv_bridge`, `sensor_msgs`, `std_msgs`,
`geometry_msgs`, `launch`, and `launch_ros` are normally installed through ROS 2
rather than through `pip`.

## Folder Organization

### Repository Root

- `README.md`: project overview, run commands, and folder guide
- `requirements.txt`: pip-installable Python dependencies used by the project
- `robot_face.py`: standalone non-ROS `pygame` face demo
- `yolov8n.pt`: YOLO model weights used by the detection node

### Assets And Data

- `assets/`: image assets used by the robot face
- `assets/kaia_face/`: grouped facial-expression graphics
- `data/`: project data files
- `data/seic_public_directory.xlsx`: SEIC public directory spreadsheet used for room and person lookup

### ROS 2 Source Package

- `src/milton_final_project/`: ROS 2 Python package root
- `src/milton_final_project/package.xml`: ROS 2 package manifest and runtime dependencies
- `src/milton_final_project/setup.py`: Python packaging and install configuration
- `src/milton_final_project/setup.cfg`: setuptools configuration
- `src/milton_final_project/resource/`: ROS package resource markers
- `src/milton_final_project/launch/`: ROS 2 launch files
- `src/milton_final_project/test/`: package test files

### Main Python Modules

- `src/milton_final_project/milton_final_project/__init__.py`: package initializer
- `src/milton_final_project/milton_final_project/face_display_node.py`: ROS 2 node that renders the robot face, expressions, and text messages on screen
- `src/milton_final_project/milton_final_project/wayfinding_input_node.py`: ROS 2 node that reads terminal input, publishes face updates, and emits user input events
- `src/milton_final_project/milton_final_project/wayfinding_history_node.py`: ROS 2 node that records destination and confirmation input history to a CSV log
- `src/milton_final_project/milton_final_project/light_controller_node.py`: ROS 2 node that converts robot state messages into LED color output
- `src/milton_final_project/milton_final_project/seic_directory.py`: loads the SEIC spreadsheet and finds the best room or person match
- `src/milton_final_project/milton_final_project/robot_interpreter.py`: extracts a destination target from free-form user input
- `src/milton_final_project/milton_final_project/robot_assistant.py`: helper for short robot-style responses using an Ollama model when available
- `src/milton_final_project/milton_final_project/yolo_node.py`: ROS 2 node that runs YOLO on camera images and publishes annotated detections
- `src/milton_final_project/milton_final_project/yolo_web_stream.py`: ROS 2 node that serves the annotated YOLO camera stream over HTTP

### Launch Files

- `src/milton_final_project/launch/yolo_launch.py`: launches the YOLO pipeline
- `src/milton_final_project/launch/face_yolo_launch.py`: launches the face display, light controller, YOLO pipeline, and face display web GUI together

### Generated Build Output

- `build/`: colcon build artifacts generated during compilation
- `install/`: installed ROS 2 package output created by `colcon build`
- `log/`: colcon build logs and run logs

These generated folders are useful for running the project locally after a build,
but they are not the primary source files you edit during development.
They are intentionally ignored by Git so the repository stays focused on source,
assets, data, documentation, and the model file.
