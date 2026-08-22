#include "rclcpp/rclcpp.hpp"

#include <geometry_msgs/msg/twist.hpp>
#include <std_msgs/msg/empty.hpp>

#include <chrono>
#include <cstdint>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>


#include "quanser/quanser_extern.h"
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
        const int poll_failure_grace_ms = this->declare_parameter<int>(
            "poll_failure_grace_ms", 1000);
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
        if (poll_failure_grace_ms < 0)
        {
            throw std::invalid_argument(
                "poll_failure_grace_ms cannot be negative");
        }
        controller_number_ = static_cast<t_uint8>(controller_number);
        reconnect_interval_ = std::chrono::milliseconds(reconnect_interval_ms);
        poll_failure_grace_ = std::chrono::milliseconds(poll_failure_grace_ms);

        command_publisher_ = this->create_publisher<geometry_msgs::msg::Twist>(
            "cmd_vel", 10);
        mapping_label_publisher_ = this->create_publisher<std_msgs::msg::Empty>(
            mapping_label_topic_, 10);

        last_open_attempt_ =
            std::chrono::steady_clock::now() - reconnect_interval_;
        const bool connected = try_open_controller();
        // The stock driver polled the gamepad continuously. 20 ms keeps the
        // state fresh and the device buffer drained without burning a core.
        timer_ = this->create_wall_timer(
            20ms, std::bind(&CommandPublisher::poll_controller, this));
        if (connected)
        {
            RCLCPP_INFO(
                this->get_logger(),
                "Gamepad ready: release LB and press B to drop a mapping label.");
        }
        else
        {
            RCLCPP_WARN(
                this->get_logger(),
                "Gamepad is not connected yet; retrying every %.1f seconds.",
                std::chrono::duration<double>(reconnect_interval_).count());
        }
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
        poll_failing_ = false;
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

    // The gamepad only produces a report when something actually moves, and the
    // handle is non-blocking, so an idle controller answers nearly every poll
    // with -QERR_WOULD_BLOCK. That means "nothing newer queued", not a fault:
    // data_ still holds the live stick and button state and must keep driving.
    // Drain whatever is queued, then fall back on the last known state.
    bool read_latest_state()
    {
        constexpr int max_reads = 32;
        for (int read = 0; read < max_reads; ++read)
        {
            t_boolean is_new = false;
            t_game_controller_states latest = data_;
            result_ = game_controller_poll(gamepad_, &latest, &is_new);
            if (result_ == -QERR_WOULD_BLOCK || result_ == -QERR_INTERRUPTED)
            {
                break;
            }
            if (result_ < 0)
            {
                note_poll_failure();
                return false;
            }
            data_ = latest;
            if (!is_new)
            {
                break;
            }
        }

        poll_failing_ = false;
        return true;
    }

    // Only genuine device errors reach here. Give up on the controller once one
    // has persisted for the whole grace window, so the gamepad is not taken down
    // for reconnect_interval_ by a single transient Quanser error.
    void note_poll_failure()
    {
        const auto now = std::chrono::steady_clock::now();
        if (!poll_failing_)
        {
            poll_failing_ = true;
            poll_failure_started_ = now;
        }

        if (now - poll_failure_started_ < poll_failure_grace_)
        {
            RCLCPP_WARN_THROTTLE(
                this->get_logger(),
                *this->get_clock(),
                5000,
                "QBot game controller %u poll failed (Quanser error %d); "
                "keeping it open because it has not failed for %.1f seconds yet",
                static_cast<unsigned int>(controller_number_),
                static_cast<int>(result_),
                std::chrono::duration<double>(poll_failure_grace_).count());
            // Stop publishing while the state is unknown. The driver's own
            // body_speed_duration timeout stops the robot if this persists.
            return;
        }

        RCLCPP_ERROR(
            this->get_logger(),
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
        poll_failing_ = false;
        // Reopen on the next tick; try_open_controller() backs off from there.
        last_open_attempt_ = now - reconnect_interval_;
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

        if (!read_latest_state())
        {
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
    std::chrono::milliseconds poll_failure_grace_{1000};
    std::chrono::steady_clock::time_point last_open_attempt_{};
    std::chrono::steady_clock::time_point poll_failure_started_{};
    bool poll_failing_ = false;
    bool previous_label_button_pressed_ = false;
    bool suppress_button_edges_once_ = true;
    bool was_manual_drive_enabled_ = false;
    bool gamepad_open_ = false;
    t_game_controller gamepad_{};
    t_game_controller_states data_{};
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
