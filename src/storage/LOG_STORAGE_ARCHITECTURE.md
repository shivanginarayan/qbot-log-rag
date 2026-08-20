# QBot Log Storage Architecture — Current Version

This file documents the current QBot log-storage and evidence pipeline.

## 1. Goal

The system is being built to answer open-ended questions from robot evidence, including:
- Where are you now?
- Why did you stop?
- Did you reach the goal?
- Why did navigation report success?
- Was something blocking you?
- What did you see?
- Did localization fail?

The LLM is not the source of truth. It receives robot evidence and explains it.

## 2. Two evidence layers

### Raw evidence: rosbag2
Raw ROS messages are preserved in rosbag.

Current topics:
- `/scan`
- `/scan_filtered`
- `/odom`
- `/amcl_pose`
- `/cmd_vel`
- `/tf`
- `/tf_static`

A completed session example contained 67,797 messages over 451.976 seconds and used 89.5 MiB.

### Structured evidence: SQLite
SQLite stores compact, searchable robot evidence.

Current tables:
- `sessions`
- `pose_samples`
- `odom_samples`
- `cmd_vel_intervals`
- `lidar_summary_intervals`
- `navigation_goals`
- `navigation_feedback`
- `navigation_events`

## 3. Session layout

Example:

```text
runtime_logs/
└── session_20260819_194134_d305/
    ├── robot.db
    ├── rosbag/
    │   ├── metadata.yaml
    │   └── rosbag_0.db3
    └── process_logs/
```

The same `session_id` ties raw and structured evidence together.

## 4. ROS / navigation context

- ROS2 Humble
- `ROS_DOMAIN_ID=57`
- Map: `home_test_v1`
- Map YAML: `robot_navigation/maps/home_test_v1/home_test_v1.yaml`
- Nav2 consumes `/scan_filtered`
- Raw `/scan` is still kept for verification
- Navigation launcher: `./run_qbot_navigation.sh`

## 5. Timestamp policy

Time is the common index across evidence.

Machine-readable timestamps are stored as integer nanoseconds.

Examples:
- `started_at_ns`
- `ended_at_ns`
- `ros_time_ns`
- `received_at_ns`
- `requested_at_ns`
- `accepted_at_ns`
- `completed_at_ns`
- `event_time_ns`

For ROS messages with a header:

```python
ros_time_ns = sec * 1_000_000_000 + nanosec
```

Receive time uses:

```python
received_at_ns = time.time_ns()
```

Messages like `geometry_msgs/msg/Twist` have no header, so receive time is the primary timestamp.

The sessions table also stores timezone-aware ISO strings in `started_at_iso` and `ended_at_iso`.

## 6. `sessions`

Purpose: one row per experiment.

Columns:

```text
session_id TEXT PRIMARY KEY
started_at_ns INTEGER NOT NULL
started_at_iso TEXT NOT NULL
ended_at_ns INTEGER
ended_at_iso TEXT
robot_id TEXT NOT NULL
ros_domain_id INTEGER NOT NULL
map_name TEXT
map_yaml_path TEXT
git_commit TEXT
status TEXT NOT NULL
notes TEXT
```

Typical lifecycle:

```text
running → completed
```

The git commit is stored so a run can be tied to a code version.

## 7. `pose_samples`

Source:
- topic: `/amcl_pose`
- type: `geometry_msgs/msg/PoseWithCovarianceStamped`

Purpose: map-level localization belief.

Columns:

```text
pose_id INTEGER PRIMARY KEY AUTOINCREMENT
session_id TEXT NOT NULL
ros_time_ns INTEGER NOT NULL
received_at_ns INTEGER NOT NULL
is_stale INTEGER NOT NULL DEFAULT 0
frame_id TEXT
x REAL NOT NULL
y REAL NOT NULL
z REAL NOT NULL
qx REAL NOT NULL
qy REAL NOT NULL
qz REAL NOT NULL
qw REAL NOT NULL
yaw_rad REAL NOT NULL
x_variance REAL
y_variance REAL
yaw_variance REAL
```

Foreign key:
`session_id → sessions(session_id)`

Index:
`(session_id, ros_time_ns)`

AMCL QoS:
- RELIABLE
- TRANSIENT_LOCAL
- KEEP_LAST
- depth 10

Because AMCL is transient-local, a late subscriber may receive an old retained pose. A pose older than roughly one second at receipt is marked `is_stale=1`.

## 8. `odom_samples`

Source:
- topic: `/odom`
- type: `nav_msgs/msg/Odometry`

Purpose: local motion evidence.

Columns:

```text
odom_id INTEGER PRIMARY KEY AUTOINCREMENT
session_id TEXT NOT NULL
ros_time_ns INTEGER NOT NULL
received_at_ns INTEGER NOT NULL
frame_id TEXT
child_frame_id TEXT
x REAL NOT NULL
y REAL NOT NULL
z REAL NOT NULL
qx REAL NOT NULL
qy REAL NOT NULL
qz REAL NOT NULL
qw REAL NOT NULL
yaw_rad REAL NOT NULL
linear_x REAL
linear_y REAL
linear_z REAL
angular_x REAL
angular_y REAL
angular_z REAL
```

Index:
`(session_id, ros_time_ns)`

Measured raw publication rate was about 59.9 Hz. Structured SQLite storage is reduced to about 10 Hz. Full-rate odometry remains in rosbag.

## 9. `cmd_vel_intervals`

Source:
- topic: `/cmd_vel`
- type: `geometry_msgs/msg/Twist`

Purpose: commanded motion.

Columns:

```text
cmd_vel_id INTEGER PRIMARY KEY AUTOINCREMENT
session_id TEXT NOT NULL
started_at_ns INTEGER NOT NULL
ended_at_ns INTEGER
linear_x REAL NOT NULL
linear_y REAL NOT NULL
linear_z REAL NOT NULL
angular_x REAL NOT NULL
angular_y REAL NOT NULL
angular_z REAL NOT NULL
sample_count INTEGER NOT NULL DEFAULT 1
```

Index:
`(session_id, started_at_ns)`

Repeated commands are compressed into intervals. Example:

```text
17 repeated messages at linear_x=0.15
→ one row
started_at_ns=...
ended_at_ns=...
linear_x=0.15
sample_count=17
```

A small float tolerance avoids splitting an interval on insignificant numerical noise.

## 10. `lidar_summary_intervals`

Primary structured source:
- topic: `/scan_filtered`
- type: `sensor_msgs/msg/LaserScan`

Raw `/scan` and `/scan_filtered` are both kept in rosbag.

Columns:

```text
lidar_id INTEGER PRIMARY KEY AUTOINCREMENT
session_id TEXT NOT NULL
started_at_ns INTEGER NOT NULL
ended_at_ns INTEGER
source_topic TEXT NOT NULL
closest_distance REAL
closest_angle REAL
front_min REAL
left_min REAL
right_min REAL
rear_min REAL
distance_band TEXT NOT NULL
front_band TEXT
left_band TEXT
right_band TEXT
rear_band TEXT
closest_bin INTEGER
front_bin INTEGER
left_bin INTEGER
right_bin INTEGER
rear_bin INTEGER
zero_count INTEGER NOT NULL DEFAULT 0
inf_count INTEGER NOT NULL DEFAULT 0
valid_count INTEGER NOT NULL DEFAULT 0
sample_count INTEGER NOT NULL DEFAULT 1
previous_interval_id INTEGER
```

Foreign keys:
- `session_id → sessions(session_id)`
- `previous_interval_id → lidar_summary_intervals(lidar_id)`

Indexes:
- `(session_id, started_at_ns)`
- `(session_id, distance_band)`

### LiDAR sectors

Approximate angular sectors:
- front: -45° to +45°
- left: +45° to +135°
- right: -135° to -45°
- rear: remaining angles

For each sector, the logger records the minimum valid range.

It also records:
- closest range over the whole scan
- angle of closest range
- zero count
- infinity count
- valid reading count

### Distance bands

Current provisional labels:

```text
critical < 0.35 m
near     < 0.75 m
caution  < 1.50 m
clear    >= 1.50 m
```

These are heuristics and can later be tuned to the QBot footprint and Nav2 settings.

### Distance bins

Current structured logger uses 10 cm bins, plus hysteresis to reduce boundary oscillation.

Examples:

```text
0.064 m → bin 0
0.487 m → bin 4
0.742 m → bin 7
1.356 m → bin 13
```

The raw LaserScan is still fully preserved in rosbag.

## 11. Exact-change principle

Going forward, the evidence architecture follows this rule:

```text
Raw rosbag:
    keep every ROS message.

Structured evidence:
    keep useful extracted state.

Timeline / LLM evidence:
    if two consecutive semantic records are exactly identical,
    represent them as one interval:
        start_time_ns
        end_time_ns

    if any compared evidence field changes,
    preserve the new state.
```

The LLM should decide whether a change matters to the question. The storage layer should avoid prematurely deciding causality.

## 12. `navigation_goals`

Source:
- action: `/navigate_to_pose`
- type: `nav2_msgs/action/NavigateToPose`

Columns:

```text
navigation_goal_id INTEGER PRIMARY KEY AUTOINCREMENT
session_id TEXT NOT NULL
client_goal_id TEXT NOT NULL
action_goal_uuid TEXT
action_name TEXT NOT NULL
requested_at_ns INTEGER NOT NULL
accepted_at_ns INTEGER
completed_at_ns INTEGER
frame_id TEXT NOT NULL
target_x REAL NOT NULL
target_y REAL NOT NULL
target_z REAL NOT NULL
target_qx REAL NOT NULL
target_qy REAL NOT NULL
target_qz REAL NOT NULL
target_qw REAL NOT NULL
target_yaw_rad REAL NOT NULL
status_code INTEGER
status_text TEXT NOT NULL
result_error_code INTEGER
result_error_message TEXT
```

Purpose: navigation intent and final Nav2 outcome.

## 13. `navigation_feedback`

Columns:

```text
feedback_id INTEGER PRIMARY KEY AUTOINCREMENT
navigation_goal_id INTEGER NOT NULL
session_id TEXT NOT NULL
received_at_ns INTEGER NOT NULL
current_x REAL
current_y REAL
current_yaw_rad REAL
navigation_time_sec REAL
estimated_time_remaining_sec REAL
distance_remaining REAL
number_of_recoveries INTEGER
```

Structured feedback is sampled around 2 Hz.

Individual feedback values can be transient. A real run produced an early `distance_remaining=0.0` followed by `0.141 m`, so one feedback row should not be treated as absolute truth.

## 14. `navigation_events`

Columns:

```text
navigation_event_id INTEGER PRIMARY KEY AUTOINCREMENT
navigation_goal_id INTEGER NOT NULL
session_id TEXT NOT NULL
event_time_ns INTEGER NOT NULL
event_type TEXT NOT NULL
status_code INTEGER
status_text TEXT
```

Typical event types:
- `GOAL_REQUESTED`
- `GOAL_ACCEPTED`
- `GOAL_COMPLETED`
- `GOAL_REJECTED`
- `ACTION_SERVER_UNAVAILABLE`

## 15. Navigation action logger

`navigate_to_pose_logger.py` both sends the goal and records it.

Example:

```bash
python src/storage/navigate_to_pose_logger.py   --db runtime_logs/session_<SESSION_ID>/robot.db   --session-id <SESSION_ID>   --x 0.5 --y 0.0 --yaw 0.0
```

This records:
- requested target
- action UUID
- acceptance
- feedback
- final status

## 16. Session timeline

`session_timeline.py` combines multiple evidence sources chronologically.

Categories include:
- SESSION
- NAV
- NAV_FEEDBACK
- CMD_VEL
- ODOM
- AMCL
- LIDAR

The timeline is a human/reasoning view. It does not replace the database.

Important rule:

```text
A happened before B
```

does not automatically mean:

```text
A caused B
```

## 17. rosbag recorder

`record_rosbag.sh` records:

```text
/scan
/scan_filtered
/odom
/amcl_pose
/cmd_vel
/tf
/tf_static
```

Stop with `Ctrl+C` so rosbag can finalize metadata.

Inspect with:

```bash
ros2 bag info runtime_logs/session_<SESSION_ID>/rosbag
```

## 18. Evidence categories

Perception:
- raw/filtered LiDAR
- LiDAR summaries

Belief:
- AMCL
- odometry
- TF

Intent:
- navigation goal

Action:
- cmd_vel

Outcome:
- navigation result
- navigation feedback
- observed motion

Keeping these separate helps avoid confusing requested behavior with estimated state or physical motion.

## 19. First LLM architecture test

Because the number of structured logs is still small, Version 1 does not need embeddings.

Initial flow:

```text
question
→ load all structured SQLite evidence for one session
→ serialize as JSON
→ send question + evidence to LLM
→ receive grounded explanation
```

The raw rosbag contents are NOT sent to the LLM. Only rosbag metadata/topic counts are included.

If structured evidence is insufficient, a future version can inspect a narrow rosbag time window and extract exact messages.

## 20. LLM grounding rules

The explainer should:
- use only supplied robot evidence
- not invent events or causes
- distinguish observation from inference
- state disagreement between evidence sources
- not equate Nav2 `SUCCEEDED` with exact mathematical arrival
- not claim an obstacle caused a stop merely because one was nearby
- say when evidence is insufficient

## 21. Future retrieval

When sessions become large:

```text
question
→ LLM planner / semantic router
→ SQL time-window retrieval
+ optional embeddings
→ compact evidence packet
→ LLM explanation
```

Embeddings are a later retrieval optimization, not required for the current architecture test.

## 22. One-command logging supervisor

A new `run_logging_stack.py` can replace the many manual terminals.

It starts:
- navigation
- rosbag
- odom logger
- AMCL logger
- cmd_vel logger
- LiDAR logger

All child console outputs are written to:

```text
runtime_logs/session_<SESSION_ID>/process_logs/
```

Only one extra terminal is needed when you want to issue a navigation goal.

## 23. Current architecture

```text
                         QBot / ROS2
                              │
                ┌─────────────┴─────────────┐
                │                           │
             rosbag2                     loggers
                │                           │
          raw evidence                    SQLite
                │                           │
 /scan /scan_filtered /tf ...        structured evidence
                │                           │
                │                     timeline / JSON
                │                           │
                └──────── fallback ─────────┤
                                            │
                                            ▼
                                           LLM
                                            │
                                            ▼
                               grounded explanation
```
