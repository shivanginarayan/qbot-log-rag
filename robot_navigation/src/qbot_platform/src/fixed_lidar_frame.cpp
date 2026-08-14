#include <chrono>
#include <cmath>
#include <functional>
#include <memory>
#include <string>

#include "geometry_msgs/msg/transform_stamped.hpp"
#include "rclcpp/rclcpp.hpp"
#include "tf2/LinearMath/Quaternion.h"
#include "tf2_ros/static_transform_broadcaster.h"

class FixedFrameBroadcaster : public rclcpp::Node
{
public:
  FixedFrameBroadcaster()
  : Node("fixed_lidar_frame")
  {
    this->declare_parameter("parent_frame_id", "base_link");
    this->declare_parameter("child_frame_id", "base_scan");
    this->declare_parameter("translation_x", 0.15);
    this->declare_parameter("translation_y", 0.0);
    this->declare_parameter("translation_z", 0.2);
    this->declare_parameter("roll_deg", 0.0);
    this->declare_parameter("pitch_deg", 0.0);
    this->declare_parameter("yaw_deg", 90.0);

    tf_broadcaster_ = std::make_shared<tf2_ros::StaticTransformBroadcaster>(this);
    publish_transform();
  }

private:
  static double deg_to_rad(double degrees)
  {
    return degrees * M_PI / 180.0;
  }

  void publish_transform()
  {
    geometry_msgs::msg::TransformStamped t;
    t.header.stamp = this->get_clock()->now();
    t.header.frame_id = this->get_parameter("parent_frame_id").as_string();
    t.child_frame_id = this->get_parameter("child_frame_id").as_string();
    t.transform.translation.x = this->get_parameter("translation_x").as_double();
    t.transform.translation.y = this->get_parameter("translation_y").as_double();
    t.transform.translation.z = this->get_parameter("translation_z").as_double();

    tf2::Quaternion q;
    q.setRPY(
      deg_to_rad(this->get_parameter("roll_deg").as_double()),
      deg_to_rad(this->get_parameter("pitch_deg").as_double()),
      deg_to_rad(this->get_parameter("yaw_deg").as_double()));

    t.transform.rotation.x = q.x();
    t.transform.rotation.y = q.y();
    t.transform.rotation.z = q.z();
    t.transform.rotation.w = q.w();

    tf_broadcaster_->sendTransform(t);
    RCLCPP_INFO(
      this->get_logger(),
      "Published static lidar TF %s -> %s: xyz=(%.3f, %.3f, %.3f), rpy_deg=(%.1f, %.1f, %.1f)",
      t.header.frame_id.c_str(),
      t.child_frame_id.c_str(),
      t.transform.translation.x,
      t.transform.translation.y,
      t.transform.translation.z,
      this->get_parameter("roll_deg").as_double(),
      this->get_parameter("pitch_deg").as_double(),
      this->get_parameter("yaw_deg").as_double());
  }

  std::shared_ptr<tf2_ros::StaticTransformBroadcaster> tf_broadcaster_;
};

int main(int argc, char * argv[])
{
  rclcpp::init(argc, argv);
  rclcpp::spin(std::make_shared<FixedFrameBroadcaster>());
  rclcpp::shutdown();
  return 0;
}
