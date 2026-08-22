#include "rclcpp/rclcpp.hpp"

#include <geometry_msgs/msg/twist.hpp>
#include <std_msgs/msg/empty.hpp>

#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>

#include "quanser/quanser_hid.h"
#include "quanser/quanser_messages.h"
#include "quanser/quanser_memory.h"

using namespace std::chrono_literals;


class CommandPublisher : public rclcpp::Node
{
public:
    CommandPublisher()
    : Node("joystick_publisher")
    {
        mapping_label_topic_ = this->declare_parameter<std::string>(
            "mapping_label_topic", "/mapping/drop_label");
        mapping_label_button_bit_ = this->declare_parameter<int>(
            "mapping_label_button_bit", 1);
        const int controller_number = this->declare_parameter<int>(
            "controller_number", 1);
        const int reconnect_interval_ms = this->declare_parameter<int>(
            "reconnect_interval_ms", 2000);
        this->declare_parameter<bool>("manual_drive_enabled", true);

        validate_button_bit("mapping_label_button_bit", mapping_label_button_bit_);
        if (mapping_label_topic_.empty())
        {
            throw std::invalid_argument("mapping_label_topic cannot be empty");
        }
        if (controller_number < 1 || controller_number > 16)
        {
            throw std::invalid_argument("controller_number must be between 1 and 16");
        }
        if (reconnect_interval_ms < 100)
        {
            throw std::invalid_argument(
                "reconnect_interval_ms must be at least 100");
        }
        controller_number_ = static_cast<t_uint8>(controller_number);
        reconnect_interval_ = std::chrono::milliseconds(reconnect_interval_ms);

        command_publisher_ = this->create_publisher<geometry_msgs::msg::Twist>(
            "cmd_vel", 10);
        mapping_label_publisher_ = this->create_publisher<std_msgs::msg::Empty>(
            mapping_label_topic_, 10);

        last_open_attempt_ =
            std::chrono::steady_clock::now() - reconnect_interval_;
        try_open_controller();
        timer_ = this->create_wall_timer(
            50ms, std::bind(&CommandPublisher::poll_controller, this));
        RCLCPP_INFO(
            this->get_logger(),
            "Gamepad ready: release LB and press B to drop a mapping label.");
    }

    ~CommandPublisher() override
    {
        close_controller();
    }

private:
    static void validate_button_bit(const char * name, int bit)
    {
        if (bit < 0 || bit > 31)
        {
            throw std::invalid_argument(
                std::string(name) + " must be between 0 and 31");
        }
    }

    static bool button_pressed(std::uint32_t buttons, int bit)
    {
        return (buttons & (std::uint32_t{1} << bit)) != 0;
    }

    void publish_stop()
    {
        geometry_msgs::msg::Twist stop;
        command_publisher_->publish(stop);
    }

    bool try_open_controller()
    {
        last_open_attempt_ = std::chrono::steady_clock::now();
        const t_uint16 buffer_size = 12;
        t_double deadzone[6] = {0.0};
        t_double saturation[6] = {0.0};
        const t_boolean auto_center = false;
        const t_uint16 max_force_feedback_effects = 0;
        const t_double force_feedback_gain = 0.0;
        result_ = game_controller_open(
            controller_number_,
            buffer_size,
            deadzone,
            saturation,
            auto_center,
            max_force_feedback_effects,
            force_feedback_gain,
            &gamepad_);
        if (result_ < 0)
        {
            RCLCPP_WARN_THROTTLE(
                this->get_logger(),
                *this->get_clock(),
                10000,
                "QBot game controller %u is unavailable (Quanser error %d); "
                "connect it and make sure no other command node owns it",
                static_cast<unsigned int>(controller_number_),
                static_cast<int>(result_));
            gamepad_open_ = false;
            return false;
        }

        gamepad_open_ = true;
        data_ = t_game_controller_states{};
        is_new_ = false;
        suppress_button_edges_once_ = true;
        RCLCPP_INFO(
            this->get_logger(),
            "Connected to QBot game controller %u.",
            static_cast<unsigned int>(controller_number_));
        return true;
    }

    void close_controller()
    {
        if (!gamepad_open_)
        {
            return;
        }
        game_controller_close(gamepad_);
        gamepad_open_ = false;
        gamepad_ = {};
    }

    void poll_controller()
    {
        if (!gamepad_open_)
        {
            const auto now = std::chrono::steady_clock::now();
            if (now - last_open_attempt_ >= reconnect_interval_)
            {
                try_open_controller();
            }
            return;
        }

        result_ = game_controller_poll(gamepad_, &data_, &is_new_);
        if (result_ < 0)
        {
            RCLCPP_ERROR_THROTTLE(
                this->get_logger(),
                *this->get_clock(),
                10000,
                "Lost QBot game controller %u while polling (Quanser error %d); "
                "closing it and retrying every %.1f seconds",
                static_cast<unsigned int>(controller_number_),
                static_cast<int>(result_),
                std::chrono::duration<double>(reconnect_interval_).count());
            if (was_manual_drive_enabled_)
            {
                publish_stop();
                was_manual_drive_enabled_ = false;
            }
            close_controller();
            last_open_attempt_ = std::chrono::steady_clock::now();
            return;
        }

        const std::uint32_t buttons =
            static_cast<std::uint32_t>(data_.buttons);
        const bool lb_pressed = button_pressed(buttons, 4);
        const bool label_pressed =
            button_pressed(buttons, mapping_label_button_bit_);

        if (suppress_button_edges_once_)
        {
            // Establish the current button state after opening/reconnecting.
            // A button held during reconnection must not create an event.
            previous_label_button_pressed_ = label_pressed;
            suppress_button_edges_once_ = false;
        }
        else if (label_pressed && !previous_label_button_pressed_)
        {
            if (!lb_pressed)
            {
                mapping_label_publisher_->publish(std_msgs::msg::Empty());
                RCLCPP_INFO(this->get_logger(), "Mapping label button pressed.");
            }
            else
            {
                RCLCPP_WARN(
                    this->get_logger(),
                    "Release LB before pressing the mapping label button.");
            }
        }
        previous_label_button_pressed_ = label_pressed;

        const bool manual_drive_enabled =
            this->get_parameter("manual_drive_enabled").as_bool();
        if (!manual_drive_enabled)
        {
            if (was_manual_drive_enabled_)
            {
                publish_stop();
            }
            was_manual_drive_enabled_ = false;
            return;
        }

        was_manual_drive_enabled_ = true;
        const bool reverse = button_pressed(buttons, 0);
        const t_double steering_axis = -data_.x;
        const t_double right_trigger = data_.rz;
        t_double throttle = 0.0;
        t_double steering = 0.0;
        if (lb_pressed)
        {
            if (right_trigger != 0.0)
            {
                throttle = 0.3 * (0.5 + 0.5 * right_trigger);
            }
            steering = 0.5 * steering_axis;
            if (reverse)
            {
                throttle = -throttle;
            }
        }

        geometry_msgs::msg::Twist twist;
        twist.linear.x = throttle;
        twist.angular.z = steering;
        command_publisher_->publish(twist);
    }

    rclcpp::TimerBase::SharedPtr timer_;
    rclcpp::Publisher<geometry_msgs::msg::Twist>::SharedPtr command_publisher_;
    rclcpp::Publisher<std_msgs::msg::Empty>::SharedPtr mapping_label_publisher_;
    std::string mapping_label_topic_;
    int mapping_label_button_bit_ = 1;
    t_uint8 controller_number_ = 1;
    std::chrono::milliseconds reconnect_interval_{2000};
    std::chrono::steady_clock::time_point last_open_attempt_{};
    bool previous_label_button_pressed_ = false;
    bool suppress_button_edges_once_ = true;
    bool was_manual_drive_enabled_ = false;
    bool gamepad_open_ = false;
    t_game_controller gamepad_{};
    t_game_controller_states data_{};
    t_boolean is_new_ = false;
    t_error result_ = 0;
};


int main(int argc, char ** argv)
{
    rclcpp::init(argc, argv);
    try
    {
        rclcpp::spin(std::make_shared<CommandPublisher>());
    }
    catch (const std::exception & exception)
    {
        RCLCPP_FATAL(
            rclcpp::get_logger("joystick_publisher"), "%s", exception.what());
        rclcpp::shutdown();
        return 1;
    }
    rclcpp::shutdown();
    return 0;
}
