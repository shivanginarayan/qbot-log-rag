#include <memory>
#include <string>

#include "behaviortree_cpp_v3/bt_factory.h"
#include "nav2_behavior_tree/bt_action_node.hpp"
#include "qbot_platform/action/manual_assistance.hpp"

namespace qbot_platform
{

class ManualAssistanceAction
  : public nav2_behavior_tree::BtActionNode<qbot_platform::action::ManualAssistance>
{
public:
  ManualAssistanceAction(
    const std::string & xml_tag_name,
    const std::string & action_name,
    const BT::NodeConfiguration & configuration)
  : nav2_behavior_tree::BtActionNode<qbot_platform::action::ManualAssistance>(
      xml_tag_name, action_name, configuration)
  {
  }

  void on_tick() override
  {
    goal_.reason = "Navigation recovery needs collision-checked controller help";
    getInput("reason", goal_.reason);
  }

  BT::NodeStatus on_success() override
  {
    if (!result_.result || !result_.result->completed) {
      RCLCPP_ERROR(
        node_->get_logger(),
        "Manual assistance returned success without completing operator recovery");
      return BT::NodeStatus::FAILURE;
    }
    RCLCPP_INFO(node_->get_logger(), "Manual assistance completed; retrying the saved goal");
    return BT::NodeStatus::SUCCESS;
  }

  static BT::PortsList providedPorts()
  {
    return providedBasicPorts(
      {BT::InputPort<std::string>(
          "reason",
          std::string("Navigation recovery needs collision-checked controller help"),
          "Reason shown to the operator while navigation is paused")});
  }
};

}  // namespace qbot_platform

BT_REGISTER_NODES(factory)
{
  BT::NodeBuilder builder =
    [](const std::string & name, const BT::NodeConfiguration & config) {
      return std::make_unique<qbot_platform::ManualAssistanceAction>(
        name, "manual_assistance", config);
    };
  factory.registerBuilder<qbot_platform::ManualAssistanceAction>(
    "ManualAssistance", builder);
}
