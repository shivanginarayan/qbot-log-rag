# QBot Navigation and Localization Setup

This document records the working navigation configuration used by the
QBot Log Analysis project.

## Environment

Robot:

- QBot Platform
- ROS2 Humble
- Differential-drive mobile robot

Working navigation workspace:

```text
~/ENGR857_Narayan_Shivangi/project/navigation

Log-analysis repository:

~/ENGR857_Narayan_Shivangi/project/qbot-log-rag

All navigation and localization testing uses:

export ROS_DOMAIN_ID=57

This prevents the navigation system from interacting with unrelated
QBot ROS2 nodes running on other domains.

Map

Current map:

maps/home_test_v1/home_test_v1.yaml

Associated files:

home_test_v1.pgm
home_test_v1.yaml
home_test_v1_labels.json

Map resolution:

0.05 m/cell

Home corresponds to the physical mapping start position:

x = 0.0
y = 0.0
yaw = 0.0
LiDAR

Raw /scan contains invalid zero-distance readings.

These readings caused Nav2 to incorrectly detect obstacles and abort
rotation behaviors.

Navigation therefore uses:

/scan_filtered

Launch with:

use_scan_filter:=true

Raw /scan should still be preserved later for log analysis.

AMCL

Initial configuration used:

min_particles: 500
max_particles: 2000

Global localization was unreliable in the mapped environment.

AMCL sometimes converged with low covariance to the wrong physical
location.

The working configuration is:

min_particles: 2000
max_particles: 10000

A successful global-localization sequence was:

global localization
       |
       v
360 degree spin
       |
       v
0.5 m forward movement
       |
       v
360 degree spin
       |
       v
validate pose consistency and covariance

The pose must not be accepted merely because covariance is low.

The estimate should also:

remain spatially consistent,
respond correctly to known robot movement, and
be physically plausible.

In the successful test:

after first spin:
x ~= 2.82
y ~= -0.16

after 0.5 m forward:
x ~= 3.35
y ~= -0.11

after second spin:
x ~= 3.36
y ~= -0.15

The estimated displacement matched the commanded movement.

Final covariance after localization was approximately:

x variance   ~= 0.021
y variance   ~= 0.020
yaw variance ~= 0.022
Go Home

Run:

ros2 run qbot_platform go_to_label.py gohome \
  --labels-file ~/ENGR857_Narayan_Shivangi/project/navigation/maps/home_test_v1/home_test_v1_labels.json

A successful test from approximately 3-4 m away returned the robot to
the physical starting area with the correct orientation.

Final AMCL pose:

x ~= 0.183
y ~= 0.113
yaw ~= -5.7 degrees

Navigation result:

status = 4
SUCCEEDED
Nav2 Goal Tolerance

The fixed source configuration remains:

xy_goal_tolerance: 0.25
yaw_goal_tolerance: 0.25

The separately launched adaptive_goal_tolerance node tightens only the XY
tolerance to 0.10 m after three AMCL position standard-deviation readings at
or below 0.08 m. It restores 0.25 m above 0.12 m uncertainty, or when the AMCL
pose is invalid, missing, or stale. This behavior is enabled by default.

Start the website with the fixed fallback behavior when diagnosing or rolling
back the feature:

./run_qbot_map_labeler.sh --fixed-goal-tolerance

Disable it during a running session with:

ros2 param set /adaptive_goal_tolerance enabled false

The direct controller fallback is:

ros2 param set /controller_server general_goal_checker.xy_goal_tolerance 0.25

Starting Navigation

From the project repository, start the browser controller:

./run_qbot_map_labeler.sh

Select the desired map in the website and press Start Navigation. The website
uses ROS_DOMAIN_ID=63, saves the matching labels JSON, builds if necessary,
starts the filtered-LiDAR Nav2 stack, and notifies the page when it is ready.
Use Stop Navigation before starting a different selected map. Build and launch
logs remain in the terminal that runs the website.

Web-Controlled Manual Mapping

The same website can create a new Cartographer map without opening additional
terminals. Stop Navigation, press New Map, and reserve a unique map name. The
website starts the QBot driver, filtered LiDAR, wheel odometry, Cartographer,
the occupancy-grid publisher, and the physical gamepad command node on
ROS_DOMAIN_ID=63.

Hold LB on the gamepad to enable motion and release LB to stop. A scaled live
/map preview updates in the browser about once per second. This preview is
downsampled only for display; Finish & Save writes the full 0.01 m/cell map.

Finish & Save stages and validates the PGM/YAML pair, creates the matching
labels JSON with the map-origin label, and only then exposes the map in the
selector. It never overwrites an existing map. If saving fails, mapping remains
active so the operator can retry. Cancel Mapping stops the stack and discards
the unsaved session.

Next Stage: Log Analysis

The next stage is to record generic robot evidence rather than
hard-code answers to particular questions.

Examples of questions the eventual system should support:

Where are you now?
Why did you stop?
Why did you not return to the starting position?
What did you see?
Where did you think you were?
Did localization fail?
Why did navigation report success?

The logger should preserve raw observations and derived events so that
answers can be reconstructed from evidence.

Candidate evidence includes:

/scan
/scan_filtered
/odom
/amcl_pose
/tf
/tf_static
/map
/cmd_vel
/robot/navigation_status
Nav2 action state
planner/controller state
localization confidence
goal coordinates
navigation result
