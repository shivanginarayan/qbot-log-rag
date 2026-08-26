include "qbot_platform_2d.lua"

-- Match live scans against a frozen mapping state. wheel_odometry remains the
-- only odom -> base_link authority; Cartographer publishes map -> odom.
TRAJECTORY_BUILDER.pure_localization_trimmer = {
  max_submaps_to_keep = 3,
}
POSE_GRAPH.optimize_every_n_nodes = 20

return options
