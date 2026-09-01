# QBot Navigation Cheat Sheet

Commands below assume the repository is located at `~/qbot-log-rag` and ROS
uses domain ID `63`.

## Start the Website and Navigation

The normal operator workflow needs one terminal command:

```bash
./run_qbot_map_labeler.sh
```

Adaptive goal tolerance is enabled by default. To start the same website with
the original fixed `0.25 m` Nav2 tolerance instead:

```bash
./run_qbot_map_labeler.sh --fixed-goal-tolerance
```

Open `http://ROBOT_IP:8765`, choose a map, and press **Start Navigation**. The
website saves the selected map's labels and starts Nav2 with its matching YAML
and JSON. Build and ROS launch output stays in this terminal; the page shows a
ready notification when AMCL and Nav2 are active.

When the ready notification appears, press **Localize** and keep the robot's
surroundings clear for the full spin. The website keeps every **Go** button
locked until the spin succeeds and a fresh `/amcl_pose` arrives. Stopping or
failing localization requires pressing **Localize** again.

Use **Stop Navigation** before starting a different map. Merely changing the
displayed map does not reload Nav2; while the maps differ, the page disables
Go, Localize, and the live pose marker and shows both map names.

Use **Rebuild** after changing package source, configuration, or launch files.
All website-managed commands use `ROS_DOMAIN_ID=39`.

The Nav2 costmaps retain the QBot's `0.35 m` physical collision radius. Their
soft inflation radii are `0.50 m` locally and `0.65 m` globally, allowing more
usable clearance near walls without shrinking the collision footprint.

If Nav2 sees less than `0.15 m` of movement over 10 seconds while following a
path, it clears the local costmap and tries a slow, collision-checked `0.20 m`
backup before retrying. A blocked rear path causes that action to fail safely
and lets the general clear/spin/wait/replan sequence run. This detects lack of
progress; it is not a bumper sensor.

## Map a New Area from the Website

Stop Navigation first, then press **New Map**. Enter a unique filename using
letters, numbers, underscores, or hyphens. The website builds when necessary
and starts the physical driver, filtered LiDAR, wheel odometry, Cartographer,
and the QBot gamepad node.

The map canvas switches to a downsampled live `/map` preview. The preview is
limited to 1200 pixels on its longest edge and updates about once per second;
the saved map still uses the full `0.01 m/pixel` occupancy grid.

Drive with the physical controller:

```text
Hold LB       enable motion
RT            forward
Left stick    turn
A + RT        reverse
Release LB    stop motion
B (LB released) drop label1, label2, ... at the QBot pose
```

If the terminal reports that the QBot controller is unavailable or was lost,
reconnect/power-cycle it and ensure no separately launched `command` or
`joystickCommands` process is running. The mapping controller node closes a
failed handle and retries controller 1 automatically every two seconds.

The live map shows Cartographer's `/tracked_pose` as an orange QBot arrow.
Each B press is edge-triggered, so holding B cannot create duplicates. Dropped
labels are shown immediately and are written into the new map's labels JSON;
rename or delete them normally after **Finish & Save**.

When the area is complete, release LB and press **Finish & Save**. The website
saves and validates `<name>.pgm` and `<name>.yaml`, creates
`<name>_labels.json`, stops mapping, refreshes the selector, and opens the new
map for labels. Existing map files are never overwritten.

To remove an old map, stop Navigation and Mapping, select the map, and press
**Delete Map**. After exact-name confirmation, its PGM, YAML, and labels JSON
move to `robot_navigation/maps/.trash/` rather than being permanently erased.

Press **Cancel Mapping** to stop Cartographer without saving. The red **Stop
robot** button is navigation-only during manual mapping; release the gamepad's
LB deadman to stop manual motion.

For terminal troubleshooting, the equivalent managed mapping entrypoint is:

```bash
./run_qbot_mapping.sh \
  --scan-filter-file robot_navigation/filters/scan_wedge_filter.json \
  --resolution 0.01 \
  --publish-period 1.0
```

## 1. Build After Changing Source, Launch, or Configuration Files

```bash
cd ~/qbot-log-rag/robot_navigation
source /opt/ros/humble/setup.bash
source "$HOME/ros2/install/setup.bash"
colcon build --packages-select qbot_platform
source install/setup.bash
```

This is the terminal equivalent of the website's **Rebuild** button. Rebuild
after changing anything under `robot_navigation/src/qbot_platform`, including
`qbot_platform_slam_and_nav.yaml`.

## 2. Select the Map and Labels

Choose the PGM in the website map selector. **Start Navigation** automatically
passes its matching YAML and `<map_stem>_labels.json` to Nav2; there is no
hardcoded map in `run_qbot_navigation.sh`.

## 3. Localize AMCL Before Navigation

Edit:

```text
robot_navigation/src/qbot_platform/config/qbot_platform_slam_and_nav.yaml
```

The robot is configured not to assume one hard-coded startup pose:

```yaml
amcl:
  ros__parameters:
    set_initial_pose: false
    always_reset_initial_pose: false
    recovery_alpha_fast: 0.1
    recovery_alpha_slow: 0.001
```

After navigation starts, open the browser labeler and press **Localize**. Confirm
that the robot has clear space. The routine resets AMCL's particles across the
map and slowly rotates the robot once to collect lidar matches. Press **Stop
robot** at any time to interrupt it.

On a large or repetitive map, one rotation may not uniquely identify the
location. If the AMCL particle cloud remains spread out, move the robot to a
distinctive nearby area and run **Localize** again. Alternatively, provide a
rough pose through RViz's **2D Pose Estimate**.

Common yaw values when using a manual pose estimate:

```text
 0.0000 = map +X
 1.5708 = map +Y
 3.1416 = map -X
-1.5708 = map -Y
```

Rebuild after changing these parameters.

## 4. Start Autonomous Navigation

```bash
cd ~/qbot-log-rag
./run_qbot_map_labeler.sh
```

Select the desired map and press **Start Navigation**. Do not simultaneously
run `start_qbot.sh joystick`, the follower, or `ros2 run qbot_platform command`;
those can start duplicate drivers or compete with Nav2 on `/cmd_vel`.

Use **Stop Navigation** to stop the whole stack. Closing the website process
with Ctrl+C also stops the navigation stack that website launched.

For manual troubleshooting only, the shell entrypoint now requires a map:

```bash
./run_qbot_navigation.sh \
  --map robot_navigation/maps/MAP_NAME.yaml
```

## 5. Prepare Every Additional Terminal

```bash
cd ~/qbot-log-rag
export ROS_DOMAIN_ID=39
source /opt/ros/humble/setup.bash
source "$HOME/ros2/install/setup.bash"
source "$PWD/robot_navigation/install/setup.bash"
```

All terminals must use the same `ROS_DOMAIN_ID`.

## 6. Check AMCL

Confirm the lifecycle state:

```bash
ros2 lifecycle get /amcl
```

Expected result:

```text
active [3]
```

Check the current estimated pose:

```bash
ros2 topic echo /amcl_pose --once
```

Check that automatic startup-pose injection is disabled:

```bash
ros2 param get /amcl set_initial_pose
ros2 param get /amcl always_reset_initial_pose
```

Check sensor and transform inputs:

```bash
ros2 topic hz /scan_filtered
ros2 topic hz /odom
ros2 run tf2_ros tf2_echo odom base_link
ros2 run tf2_ros tf2_echo map base_link
```

AMCL is probably localized when its pose is physically plausible and stable,
and the laser scan aligns with the map. A published pose alone does not prove
that it is correct.

## 7. Reset Localization Only When Needed

If the approximate robot position is known, use RViz's **2D Pose Estimate**. For
a large map, this is preferable to searching the entire map.

Use global localization only when the robot's location is completely unknown:

```bash
ros2 service call /reinitialize_global_localization std_srvs/srv/Empty "{}"
```

After calling it, slowly rotate and move the robot in a safe, distinctive area.
Do not send a navigation goal until AMCL has converged.

The browser's **Localize** button performs the global-localization reset and a
slow 360-degree rotation without blind translational movement. Its spin command
is sent to `/cmd_vel_nav`, allowing Nav2's velocity smoother to forward it to
the QBot driver on `/cmd_vel` without competing publishers.

## 8. Open the Browser Map Labeler

On the robot:

```bash
cd ~/qbot-log-rag
./run_qbot_map_labeler.sh
```

Find the robot's IP if needed:

```bash
hostname -I
```

On a laptop connected to the same network, open:

```text
http://ROBOT_IP:8765
```

Select a map, click a known white/free location, enter its name, and press
**Save Labels**. Press **Start Navigation** and wait for the ready notification.
The **Go** button saves pending changes, asks for confirmation, and publishes
the selected name on `/label`.

While a goal is active, its sidebar row displays a pulsing **Navigating** badge
and all Go buttons are locked. The page shows a notification when the goal
succeeds, is canceled, is rejected, or aborts. These results come from
`/robot/navigation_status`.

When `/amcl_pose` is available, an orange **QBot** arrow shows AMCL's live
position and heading on the selected map. The dashed circle represents the
largest reported X/Y standard deviation; a large circle means the pose is
uncertain. Make sure the browser is displaying the same map Nav2 loaded.

Press **Save init_pose** to snapshot the current live pose into the selected
map's labels JSON. `init_pose` then appears in the sidebar and behaves like any
other saved navigation label, including its **Go** button. This is a return
destination only—it does not set AMCL's startup pose. The snapshot is rejected
if `/amcl_pose` is stale, outside the selected map, or not on free map space.

Press **Stop robot** at any time to cancel the active Nav2 goal and publish zero
velocity commands. It also handles a stop pressed while Nav2 is still accepting
the goal. The terminal equivalent is:

```bash
ros2 topic pub --once /label std_msgs/msg/String \
  "{data: '__stop_navigation__'}"
```

The website requires its navigation status to be ready on the displayed map
before **Go** works. The label listener reloads the JSON for every request, so
newly saved labels do not require a Nav2 restart.

## 9. Convert a PGM Pixel to Map Coordinates

Pixel coordinates are measured from the image's top-left corner:

```bash
cd ~/qbot-log-rag
python3 robot_navigation/tools/pixel_to_coordinates.py \
  robot_navigation/maps/lab_map_new.yaml \
  PIXEL_X PIXEL_Y
```

Example:

```bash
python3 robot_navigation/tools/pixel_to_coordinates.py \
  robot_navigation/maps/lab_map_new.yaml \
  5210.4 930.4
```

Do not use a gray/unknown or black/occupied pixel as a navigation goal. Choose
white free space with enough clearance for the robot and inflated costmap.

## 10. Validate and List Saved Labels

Validate the JSON:

```bash
python3 -m json.tool \
  robot_navigation/maps/lab_map_new_labels.json >/dev/null
```

No output means the JSON is valid.

List labels and their world coordinates:

```bash
ros2 run qbot_platform go_to_label.py --list \
  --labels-file "$PWD/robot_navigation/maps/lab_map_new_labels.json"
```

## 11. Navigate to a Label

The navigation bringup starts a label listener on `/label`:

```bash
ros2 topic pub --once /label std_msgs/msg/String "{data: 'test_pose'}"
```

Replace `test_pose` with the exact saved label name. Watch the main navigation
terminal for messages similar to:

```text
Received 'test_pose'; going to test_pose.
Goal accepted.
```

To return to the saved `home` label:

```bash
ros2 topic pub --once /label std_msgs/msg/String "{data: 'home'}"
```

To observe the next reported navigation result, start this before sending the
goal:

```bash
ros2 topic echo /robot/navigation_status --once
```

Common action status values:

```text
4 = succeeded
5 = canceled
6 = aborted
```

## 12. Goal Accuracy

The YAML keeps Nav2's original fixed fallback:

```yaml
general_goal_checker:
  plugin: "nav2_controller::SimpleGoalChecker"
  stateful: false
  xy_goal_tolerance: 0.25
  yaw_goal_tolerance: 0.25
```

By default, `adaptive_goal_tolerance.py` watches `/amcl_pose` covariance. Three
consecutive position standard-deviation readings at or below `0.08 m` tighten
the XY tolerance to `0.10 m`. It returns to `0.25 m` above `0.12 m`, or when
the AMCL pose is missing, invalid, or stale for more than two seconds. The yaw
tolerance stays fixed at `0.25 rad`.

Check the live controller value:

```bash
ros2 param get /controller_server general_goal_checker.xy_goal_tolerance
```

Disable adaptation while navigation is running and restore `0.25 m`:

```bash
ros2 param set /adaptive_goal_tolerance enabled false
```

If the adaptive node is unavailable, restore the controller directly:

```bash
ros2 param set /controller_server general_goal_checker.xy_goal_tolerance 0.25
```

Re-enable adaptation with `enabled true`; it will require three new
high-confidence readings before selecting `0.10 m`. Low covariance does not
prove that AMCL chose the correct physical location, so still verify that the
live pose and lidar alignment match the map.

## 13. RViz

RViz requires a graphical display. On a graphical ROS machine:

```bash
export ROS_DOMAIN_ID=39
rviz2
```

Use fixed frame `map`, then add `/map`, `/scan_filtered`, and `TF`.

An ordinary headless SSH terminal produces `could not connect to display`.
Use the browser labeler, SSH X forwarding, VNC, or RViz on another ROS machine.

## 14. Quick Troubleshooting

Show relevant nodes:

```bash
ros2 node list | grep -E 'amcl|map_server|planner|controller|go_to_label'
```

Show relevant topics:

```bash
ros2 topic list | grep -E 'amcl|map|scan|odom|label|navigation_status'
```

If a label publication succeeds but the robot does not move, check the main
launch terminal for one of these conditions:

```text
No saved label matches ...   -> wrong labels file, unsaved label, or no restart
Goal rejected                -> Nav2 is not ready or cannot accept the goal
Goal aborted                 -> planning, localization, progress, or costmap issue
```

Also verify that:

- The website's active Nav2 map matches the displayed map.
- AMCL is active and localized on that map.
- The label lies in known free space, not unknown or occupied space.
- The joystick and follower are stopped.
- Configuration changes were rebuilt and the launch was restarted.
