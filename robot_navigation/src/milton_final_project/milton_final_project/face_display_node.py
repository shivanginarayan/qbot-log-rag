from dataclasses import dataclass
import json
import math
from pathlib import Path
import textwrap

from ament_index_python.packages import get_package_share_directory
from cv_bridge import CvBridge
import numpy as np
import pygame
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from std_msgs.msg import String

from .status_qos import status_qos


@dataclass(frozen=True)
class AssetExpression:
    name: str
    label: str
    folder: str
    eye_height: int
    eye_gap: int
    baseline_offset: int


class FaceDisplayNode(Node):
    def __init__(self):
        super().__init__('face_display_node')

        self.declare_parameter('width', 1024)
        self.declare_parameter('height', 600)
        self.declare_parameter('fullscreen', True)
        self.declare_parameter('show_help', False)
        self.declare_parameter('show_preview', False)
        self.declare_parameter('message_topic', '/robot/message')
        self.declare_parameter('display_status_topic', '/face/status_message')
        self.declare_parameter('preview_topic', '/yolo/annotated_image')
        self.declare_parameter('person_target_topic', '/yolo/person_target')
        self.declare_parameter('stage_topic', '/robot/stage')
        self.declare_parameter('initial_expression', 'neutral')
        self.declare_parameter(
            'waiting_message',
            "Hi, I'm the navigation robot that helps you find a location or room.",
        )
        self.declare_parameter('response_duration_sec', 10.0)
        self.declare_parameter('confirmation_timeout_sec', 15.0)
        self.declare_parameter('navigation_timeout_sec', 20.0)
        requested_width = int(self.get_parameter('width').value)
        requested_height = int(self.get_parameter('height').value)
        self.fullscreen = bool(self.get_parameter('fullscreen').value)
        self.show_help = bool(self.get_parameter('show_help').value)
        self.show_preview = bool(self.get_parameter('show_preview').value)
        self.response_duration_sec = float(
            self.get_parameter('response_duration_sec').value
        )
        self.confirmation_timeout_sec = float(
            self.get_parameter('confirmation_timeout_sec').value
        )
        self.navigation_timeout_sec = float(
            self.get_parameter('navigation_timeout_sec').value
        )
        self.preview_topic = self.get_parameter('preview_topic').value
        self.message_topic = self.get_parameter('message_topic').value
        self.display_status_topic = self.get_parameter('display_status_topic').value
        self.person_target_topic = self.get_parameter('person_target_topic').value
        self.stage_topic = self.get_parameter('stage_topic').value
        self.expression_index = 0

        pygame.init()
        pygame.font.init()

        display_info = pygame.display.Info()
        if self.fullscreen:
            self.width = display_info.current_w
            self.height = display_info.current_h
        else:
            self.width = requested_width
            self.height = requested_height

        display_flags = pygame.FULLSCREEN if self.fullscreen else 0
        self.screen = pygame.display.set_mode((self.width, self.height), display_flags)
        self.clock = pygame.time.Clock()

        self.bg = (236, 244, 248)
        self.label = (79, 105, 120)
        self.help_color = (106, 130, 144)
        self.message_bg = (250, 253, 255, 238)
        self.message_outline = (132, 198, 214)
        self.message_text = (48, 68, 82)
        self.navigation_bg = (104, 193, 143)
        self.navigation_bg_dark = (66, 144, 104)
        self.navigation_text = (244, 255, 247)
        self.detected_border_color = (52, 199, 89)
        self.idle_border_color = (44, 132, 255)
        self.ui_scale = min(self.width / 1024.0, self.height / 600.0)
        self.border_thickness = max(14, int(22 * self.ui_scale))

        self.cx = self.width // 2
        self.bottom_panel_height = min(210, max(130, int(self.height * 0.30)))
        self.cy = max(0, (self.height - self.bottom_panel_height) // 2)
        self.face_size = min(
            int(self.width * 0.70),
            int((self.height - self.bottom_panel_height) * 0.85),
        )

        share_dir = Path(get_package_share_directory('milton_final_project'))
        self.assets_dir = share_dir / 'assets' / 'kaia_face'
        self.background = self.load_image('happy/background-min.png')

        self.expression_order = [
            'neutral',
            'happy',
            'confused',
        ]
        self.expressions = {
            'neutral': AssetExpression('neutral', 'Neutral', 'happy', 58, 108, 6),
            'happy': AssetExpression('happy', 'Happy', 'happy', 58, 108, 6),
            'confused': AssetExpression('confused', 'Confused', 'happy', 58, 108, 6),
        }
        self.loaded_eyes = {
            name: {
                'left': self.load_image(f'{expr.folder}/left-eye.png'),
                'right': self.load_image(f'{expr.folder}/right-eye.png'),
            }
            for name, expr in self.expressions.items()
        }

        self.waiting_message = self.get_parameter('waiting_message').value
        self.current_message = self.waiting_message
        self.idle_expression = self.normalize_expression(
            self.get_parameter('initial_expression').value
        )
        self.active_expression = self.idle_expression
        self.override_expression = None
        self.override_message = None
        self.override_until = None
        self.input_buffer = ''
        self.stage = 'waiting'
        self.bridge = CvBridge()
        self.preview_surface = None
        self.preview_size = (
            max(220, int(320 * self.ui_scale)),
            max(124, int(180 * self.ui_scale)),
        )
        self.person_detected = False
        self.face_glow_color = (196, 168, 255, 92)
        self.face_halo_color = (156, 126, 235, 78)

        self.set_expression(self.active_expression)

        self.font = pygame.font.SysFont('arial', max(18, int(28 * self.ui_scale)), bold=True)
        self.small_font = pygame.font.SysFont('arial', max(12, int(18 * self.ui_scale)))
        self.message_font = pygame.font.SysFont('arial', max(18, int(30 * self.ui_scale)), bold=True)
        self.navigation_font = pygame.font.SysFont('arial', max(30, int(58 * self.ui_scale)), bold=True)
        self.input_font = pygame.font.SysFont('arial', max(16, int(26 * self.ui_scale)))
        self.help_lines = []

        self.expression_sub = self.create_subscription(
            String,
            '/face/expression',
            self.expression_callback,
            10,
        )
        self.message_sub = self.create_subscription(
            String,
            self.message_topic,
            self.message_callback,
            10,
        )
        self.display_status_sub = self.create_subscription(
            String,
            self.display_status_topic,
            self.message_callback,
            10,
        )
        self.preview_sub = self.create_subscription(
            Image,
            self.preview_topic,
            self.preview_callback,
            10,
        )
        self.person_target_sub = self.create_subscription(
            String,
            self.person_target_topic,
            self.person_target_callback,
            10,
        )
        self.stage_sub = self.create_subscription(
            String,
            self.stage_topic,
            self.stage_callback,
            status_qos(),
        )
        self.user_input_pub = self.create_publisher(String, '/wayfinding/user_input', 10)

        self.timer = self.create_timer(1.0 / 30.0, self.update_frame)
        self.get_logger().info(f'Face monitor ready with assets from: {self.assets_dir}')
        self.get_logger().info(f'Face preview subscribed to: {self.preview_topic}')
        self.get_logger().info(
            f'Face border subscribed to person target topic: {self.person_target_topic}'
        )
        self.get_logger().info(f'Face stage subscribed to: {self.stage_topic}')

    def load_image(self, relative_path: str) -> pygame.Surface:
        path = self.assets_dir / relative_path
        if not path.exists():
            raise FileNotFoundError(f'Missing asset: {path}')
        return pygame.image.load(path).convert_alpha()

    def set_expression(self, name: str):
        normalized = self.normalize_expression(name)
        if normalized in self.expressions:
            self.expression_index = self.expression_order.index(normalized)

    def cycle_expression(self, direction: int):
        self.expression_index = (self.expression_index + direction) % len(self.expression_order)
        self.idle_expression = self.expression_order[self.expression_index]
        self.active_expression = self.idle_expression

    def normalize_expression(self, name: str) -> str:
        if name == 'happy':
            return 'happy'
        if name == 'confused':
            return 'confused'
        return 'neutral'

    def current_expression(self) -> AssetExpression:
        return self.expressions[self.expression_order[self.expression_index]]

    def scaled_surface(self, surface: pygame.Surface, target_height: int) -> pygame.Surface:
        width, height = surface.get_size()
        scale = target_height / height
        target_width = max(1, int(width * scale))
        return pygame.transform.smoothscale(surface, (target_width, target_height))

    def wrap_message(self, message: str):
        max_chars = max(18, min(42, int((self.width - 220) / 18)))
        return textwrap.wrap(message, width=max_chars) or ['']

    def fit_input_text(self, message: str, max_width: int) -> str:
        if self.input_font.size(message)[0] <= max_width:
            return message

        shortened = message
        while shortened and self.input_font.size('...' + shortened)[0] > max_width:
            shortened = shortened[1:]
        return '...' + shortened if shortened else ''

    def set_override(self, expression=None, message=None):
        if expression is not None:
            normalized_expression = self.normalize_expression(expression)
            self.override_expression = normalized_expression
            self.active_expression = normalized_expression
            self.set_expression(normalized_expression)

        if message is not None:
            self.override_message = message
            self.current_message = message

        self.override_until = (
            self.get_clock().now().nanoseconds / 1e9 + self.response_duration_sec
        )

    def clear_override(self):
        self.override_expression = None
        self.override_message = None
        self.override_until = None
        self.active_expression = self.idle_expression
        self.current_message = self.waiting_message
        self.set_expression(self.idle_expression)

    def publish_user_input(self, prompt_type: str, text: str):
        msg = String()
        msg.data = f'{prompt_type}|{text}'
        self.user_input_pub.publish(msg)

    def expression_callback(self, msg: String):
        expression = msg.data.strip()
        if expression:
            self.set_override(expression=expression)

    def message_callback(self, msg: String):
        message = msg.data.strip()
        if message:
            self.set_override(message=message)

    def preview_callback(self, msg: Image):
        try:
            frame = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            rgb_frame = frame[:, :, ::-1]
            rgb_frame = np.ascontiguousarray(rgb_frame)
            self.preview_surface = pygame.image.fromstring(
                rgb_frame.tobytes(),
                (rgb_frame.shape[1], rgb_frame.shape[0]),
                'RGB',
            )
        except Exception as exc:
            self.get_logger().warning(
                f'Preview frame conversion failed: {exc!r}',
                throttle_duration_sec=2.0,
            )

    def person_target_callback(self, msg: String):
        try:
            payload = json.loads(msg.data)
        except json.JSONDecodeError as exc:
            self.get_logger().warning(
                f'Person target decode failed: {exc!r}',
                throttle_duration_sec=2.0,
            )
            self.person_detected = False
            return

        self.person_detected = bool(payload.get('seen', False))

    def stage_callback(self, msg: String):
        stage = msg.data.strip().lower()
        if not stage:
            return

        self.stage = stage

    def current_gaze_offset(self):
        if self.override_expression == 'happy':
            elapsed = self.get_clock().now().nanoseconds / 1e9
            return int(math.sin(elapsed * 3.2) * 8)

        if self.override_until is not None:
            return 0

        elapsed = self.get_clock().now().nanoseconds / 1e9
        return int(math.sin(elapsed * 0.9) * 18)

    def is_blinking(self):
        return False

    def current_face_offset_y(self):
        if self.override_expression == 'happy':
            elapsed = self.get_clock().now().nanoseconds / 1e9
            return int(math.sin(elapsed * 4.0) * 6)
        return 0

    def draw_background(self):
        face_offset_y = self.current_face_offset_y()
        halo = pygame.Surface((self.face_size + 160, self.face_size + 160), pygame.SRCALPHA)
        pygame.draw.ellipse(halo, self.face_halo_color, halo.get_rect())
        halo_rect = halo.get_rect(center=(self.cx, self.cy - 10 + face_offset_y))
        self.screen.blit(halo, halo_rect)

        glow = pygame.Surface((self.face_size + 70, self.face_size + 70), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, self.face_glow_color, glow.get_rect())
        glow_rect = glow.get_rect(center=(self.cx, self.cy - 6 + face_offset_y))
        self.screen.blit(glow, glow_rect)

        shadow = pygame.Surface((self.face_size + 44, self.face_size + 44), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (56, 91, 104, 42), shadow.get_rect())
        shadow_rect = shadow.get_rect(center=(self.cx, self.cy + 12 + face_offset_y))
        self.screen.blit(shadow, shadow_rect)

        face = pygame.transform.smoothscale(self.background, (self.face_size, self.face_size))
        face_rect = face.get_rect(center=(self.cx, self.cy + face_offset_y))
        self.screen.blit(face, face_rect)

    def draw_bottom_panel(self):
        panel_surface = pygame.Surface((self.width, self.bottom_panel_height), pygame.SRCALPHA)
        pygame.draw.rect(
            panel_surface,
            (222, 238, 244, 228),
            panel_surface.get_rect(),
            border_radius=28,
        )
        pygame.draw.line(
            panel_surface,
            (159, 207, 217, 255),
            (42, 0),
            (self.width - 42, 0),
            2,
        )
        panel_rect = panel_surface.get_rect(midbottom=(self.cx, self.height))
        self.screen.blit(panel_surface, panel_rect)

    def draw_expression(self):
        expr = self.current_expression()
        eyes = self.loaded_eyes[expr.name]
        left_eye = self.scaled_surface(eyes['left'], expr.eye_height)
        right_eye = self.scaled_surface(eyes['right'], expr.eye_height)

        baseline = self.cy + expr.baseline_offset + self.current_face_offset_y()
        gaze_offset = self.current_gaze_offset()
        left_rect = left_eye.get_rect(
            midbottom=(self.cx - expr.eye_gap + gaze_offset, baseline)
        )
        right_rect = right_eye.get_rect(
            midbottom=(self.cx + expr.eye_gap + gaze_offset, baseline)
        )

        self.screen.blit(left_eye, left_rect)
        self.screen.blit(right_eye, right_rect)

    def draw_message(self):
        lines = self.wrap_message(self.current_message)
        text_surfaces = [
            self.message_font.render(line, True, self.message_text) for line in lines
        ]
        max_width = max(surface.get_width() for surface in text_surfaces)
        line_gap = 8
        total_height = sum(surface.get_height() for surface in text_surfaces)
        total_height += line_gap * max(0, len(text_surfaces) - 1)

        box_width = max_width + 48
        box_height = total_height + 36
        box_surface = pygame.Surface((box_width, box_height), pygame.SRCALPHA)
        pygame.draw.rect(
            box_surface,
            self.message_bg,
            box_surface.get_rect(),
            border_radius=24,
        )
        pygame.draw.rect(
            box_surface,
            self.message_outline,
            box_surface.get_rect(),
            width=2,
            border_radius=24,
        )

        input_box_top = self.height - 64
        message_bottom = input_box_top - 20
        box_rect = box_surface.get_rect(midbottom=(self.cx, message_bottom))
        self.screen.blit(box_surface, box_rect)

        y = box_rect.top + 18
        for surface in text_surfaces:
            text_rect = surface.get_rect(centerx=self.cx, y=y)
            self.screen.blit(surface, text_rect)
            y += surface.get_height() + line_gap

    def draw_input_box(self):
        box_width = min(self.width - 120, 760)
        box_height = 58
        box_surface = pygame.Surface((box_width, box_height), pygame.SRCALPHA)
        pygame.draw.rect(
            box_surface,
            (248, 251, 253, 240),
            box_surface.get_rect(),
            border_radius=18,
        )
        pygame.draw.rect(
            box_surface,
            (132, 198, 214),
            box_surface.get_rect(),
            width=2,
            border_radius=18,
        )

        box_rect = box_surface.get_rect(midbottom=(self.cx, self.height - 8))
        self.screen.blit(box_surface, box_rect)

        if self.stage == 'confirmation':
            placeholder = 'Type yes or no...'
        elif self.stage == 'navigation':
            placeholder = 'Press Enter to start over...'
        else:
            placeholder = 'Room or location...'

        display_text = self.input_buffer if self.input_buffer else placeholder
        text_color = self.message_text if self.input_buffer else (136, 154, 165)
        max_text_width = box_width - 36
        display_text = self.fit_input_text(display_text, max_text_width)
        text_surface = self.input_font.render(display_text, True, text_color)
        text_rect = text_surface.get_rect(midleft=(box_rect.left + 18, box_rect.centery))
        self.screen.blit(text_surface, text_rect)

    def draw_status(self):
        if self.show_help and self.help_lines:
            y = self.height - 62
            for line in self.help_lines:
                text = self.small_font.render(line, True, self.help_color)
                self.screen.blit(text, (26, y))
                y += 22

    def draw_preview(self):
        if self.preview_surface is None:
            return

        preview_width, preview_height = self.preview_size
        frame_surface = pygame.Surface((preview_width + 16, preview_height + 16), pygame.SRCALPHA)
        pygame.draw.rect(
            frame_surface,
            (246, 250, 252, 228),
            frame_surface.get_rect(),
            border_radius=18,
        )
        pygame.draw.rect(
            frame_surface,
            (132, 198, 214, 255),
            frame_surface.get_rect(),
            width=2,
            border_radius=18,
        )

        frame_rect = frame_surface.get_rect(topright=(self.width - 22, 22))
        self.screen.blit(frame_surface, frame_rect)

        scaled_preview = pygame.transform.smoothscale(
            self.preview_surface,
            (preview_width, preview_height),
        )
        preview_rect = scaled_preview.get_rect(center=frame_rect.center)
        self.screen.blit(scaled_preview, preview_rect)

        label_surface = self.small_font.render('Camera Preview', True, self.label)
        label_rect = label_surface.get_rect(topright=(frame_rect.right - 10, frame_rect.bottom + 6))
        self.screen.blit(label_surface, label_rect)

    def draw_detection_border(self):
        border_color = (
            self.detected_border_color if self.person_detected else self.idle_border_color
        )
        pygame.draw.rect(
            self.screen,
            border_color,
            self.screen.get_rect(),
            width=self.border_thickness,
            border_radius=18,
        )

    def draw(self):
        if self.stage in {'navigation', 'returning'}:
            self.draw_navigation_mode()
            self.draw_detection_border()
            pygame.display.flip()
            return

        self.screen.fill(self.bg)
        self.draw_background()
        self.draw_expression()
        if self.show_preview:
            self.draw_preview()
        self.draw_bottom_panel()
        self.draw_message()
        self.draw_input_box()
        self.draw_status()
        self.draw_detection_border()
        pygame.display.flip()

    def draw_navigation_mode(self):
        self.screen.fill(self.navigation_bg)
        banner = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
        pygame.draw.rect(
            banner,
            (*self.navigation_bg_dark, 160),
            pygame.Rect(50, 50, self.width - 100, self.height - 100),
            border_radius=36,
        )
        self.screen.blit(banner, (0, 0))

        headline = self.navigation_font.render("Let's go", True, self.navigation_text)
        subline = self.message_font.render(
            self.current_message,
            True,
            self.navigation_text,
        )

        self.screen.blit(
            headline,
            headline.get_rect(center=(self.cx, self.height // 2 - 70)),
        )
        self.screen.blit(
            subline,
            subline.get_rect(center=(self.cx, self.height // 2 + 10)),
        )

    def process_destination(self):
        user_text = self.input_buffer.strip()
        self.input_buffer = ''

        if user_text.lower() == 'q':
            rclpy.shutdown()
            return

        prompt_type = 'confirmation' if self.stage == 'confirmation' else 'destination'
        self.publish_user_input(prompt_type, user_text)

    def now_seconds(self) -> float:
        return self.get_clock().now().nanoseconds / 1e9

    def handle_key(self, key):
        if key == pygame.K_RETURN:
            self.process_destination()
        elif key == pygame.K_BACKSPACE:
            self.input_buffer = self.input_buffer[:-1]
        elif key == pygame.K_h:
            self.show_help = not self.show_help

    def update_frame(self):
        self.clock.tick(30)

        if (
            self.override_until is not None
            and self.now_seconds() >= self.override_until
        ):
            if self.stage == 'waiting':
                self.clear_override()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                rclpy.shutdown()
                return
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    rclpy.shutdown()
                    return
                if event.unicode and event.unicode.isprintable() and event.key not in (
                    pygame.K_RETURN,
                    pygame.K_BACKSPACE,
                ):
                    if len(self.input_buffer) < 40:
                        self.input_buffer += event.unicode
                self.handle_key(event.key)

        self.draw()

    def destroy_node(self):
        pygame.quit()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FaceDisplayNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if rclpy.ok():
            node.destroy_node()
            rclpy.shutdown()
        else:
            node.destroy_node()


if __name__ == '__main__':
    main()
