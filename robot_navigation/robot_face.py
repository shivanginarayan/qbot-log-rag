from dataclasses import dataclass
from pathlib import Path
import sys

import pygame


@dataclass(frozen=True)
class AssetExpression:
    name: str
    label: str
    folder: str
    eye_height: int
    eye_gap: int
    baseline_offset: int


class RobotFace:
    def __init__(self, width=1024, height=600):
        pygame.init()
        pygame.display.set_caption("Kaia-Style Robot Face")
        self.width = width
        self.height = height
        self.screen = pygame.display.set_mode((width, height))
        self.clock = pygame.time.Clock()

        self.bg = (8, 10, 14)
        self.label = (225, 232, 244)
        self.help_color = (168, 178, 198)

        self.cx = width // 2
        self.cy = height // 2
        self.face_size = 440

        self.assets_dir = Path(__file__).resolve().parent / "assets" / "kaia_face"
        self.background = self.load_image("happy/background-min.png")

        self.expression_order = [
            "annoyed",
            "anxious",
            "apologetic",
            "awkward",
            "blinking",
            "bored",
            "happy",
            "confused",
            "ready_to_go",
            "so_excited",
            "thank_you",
        ]
        self.expressions = {
            "annoyed": AssetExpression("annoyed", "Annoyed", "annoyed", eye_height=150, eye_gap=108, baseline_offset=48),
            "anxious": AssetExpression("anxious", "Anxious", "anxious", eye_height=154, eye_gap=102, baseline_offset=54),
            "apologetic": AssetExpression("apologetic", "Apologetic", "apologetic", eye_height=170, eye_gap=106, baseline_offset=50),
            "awkward": AssetExpression("awkward", "Awkward", "awkward", eye_height=146, eye_gap=108, baseline_offset=54),
            "blinking": AssetExpression("blinking", "Blinking", "blinking", eye_height=14, eye_gap=76, baseline_offset=6),
            "bored": AssetExpression("bored", "Bored", "bored", eye_height=124, eye_gap=104, baseline_offset=48),
            "happy": AssetExpression("happy", "Happy", "happy", eye_height=58, eye_gap=108, baseline_offset=6),
            "confused": AssetExpression("confused", "Confused", "thinking", eye_height=118, eye_gap=118, baseline_offset=56),
            "ready_to_go": AssetExpression("ready_to_go", "Ready To Go", "determined", eye_height=134, eye_gap=110, baseline_offset=52),
            "so_excited": AssetExpression("so_excited", "So Excited", "excited", eye_height=140, eye_gap=110, baseline_offset=50),
            "thank_you": AssetExpression("thank_you", "Thank You", "giggle", eye_height=48, eye_gap=106, baseline_offset=8),
        }
        self.loaded_eyes = {
            name: {
                "left": self.load_image(f"{expr.folder}/left-eye.png"),
                "right": self.load_image(f"{expr.folder}/right-eye.png"),
            }
            for name, expr in self.expressions.items()
        }

        self.expression_index = 0
        self.show_help = True

        self.font = pygame.font.SysFont("arial", 28, bold=True)
        self.small_font = pygame.font.SysFont("arial", 18)
        self.help_lines = [
            "1 Annoyed   2 Anxious   3 Apologetic   4 Awkward   5 Blinking   6 Bored",
            "7 Happy   8 Confused   9 Ready To Go   0 So Excited   Q Thank You",
            "Left/Right: cycle expressions   H: help   Esc: quit",
        ]

    def load_image(self, relative_path: str) -> pygame.Surface:
        path = self.assets_dir / relative_path
        if not path.exists():
            raise FileNotFoundError(f"Missing asset: {path}")
        return pygame.image.load(path).convert_alpha()

    def set_expression(self, name: str):
        if name in self.expressions:
            self.expression_index = self.expression_order.index(name)

    def cycle_expression(self, direction: int):
        self.expression_index = (self.expression_index + direction) % len(self.expression_order)

    def current_expression(self) -> AssetExpression:
        return self.expressions[self.expression_order[self.expression_index]]

    def scaled_surface(self, surface: pygame.Surface, target_height: int) -> pygame.Surface:
        width, height = surface.get_size()
        scale = target_height / height
        target_width = max(1, int(width * scale))
        return pygame.transform.smoothscale(surface, (target_width, target_height))

    def draw_background(self):
        shadow = pygame.Surface((self.face_size + 44, self.face_size + 44), pygame.SRCALPHA)
        pygame.draw.ellipse(shadow, (0, 0, 0, 72), shadow.get_rect())
        shadow_rect = shadow.get_rect(center=(self.cx, self.cy + 12))
        self.screen.blit(shadow, shadow_rect)

        face = pygame.transform.smoothscale(self.background, (self.face_size, self.face_size))
        face_rect = face.get_rect(center=(self.cx, self.cy))
        self.screen.blit(face, face_rect)

    def draw_expression(self):
        expr = self.current_expression()
        eyes = self.loaded_eyes[expr.name]
        left_eye = self.scaled_surface(eyes["left"], expr.eye_height)
        right_eye = self.scaled_surface(eyes["right"], expr.eye_height)

        baseline = self.cy + expr.baseline_offset
        left_rect = left_eye.get_rect(midbottom=(self.cx - expr.eye_gap, baseline))
        right_rect = right_eye.get_rect(midbottom=(self.cx + expr.eye_gap, baseline))

        self.screen.blit(left_eye, left_rect)
        self.screen.blit(right_eye, right_rect)

    def draw_status(self):
        name = self.current_expression().label
        label = self.font.render(f"Expression: {name}", True, self.label)
        self.screen.blit(label, (26, 20))

        if self.show_help:
            y = self.height - 62
            for line in self.help_lines:
                text = self.small_font.render(line, True, self.help_color)
                self.screen.blit(text, (26, y))
                y += 22

    def draw(self):
        self.screen.fill(self.bg)
        self.draw_background()
        self.draw_expression()
        self.draw_status()
        pygame.display.flip()

    def handle_key(self, key):
        if key == pygame.K_1:
            self.set_expression("annoyed")
        elif key == pygame.K_2:
            self.set_expression("anxious")
        elif key == pygame.K_3:
            self.set_expression("apologetic")
        elif key == pygame.K_4:
            self.set_expression("awkward")
        elif key == pygame.K_5:
            self.set_expression("blinking")
        elif key == pygame.K_6:
            self.set_expression("bored")
        elif key == pygame.K_7:
            self.set_expression("happy")
        elif key == pygame.K_8:
            self.set_expression("confused")
        elif key == pygame.K_9:
            self.set_expression("ready_to_go")
        elif key == pygame.K_0:
            self.set_expression("so_excited")
        elif key == pygame.K_q:
            self.set_expression("thank_you")
        elif key == pygame.K_LEFT:
            self.cycle_expression(-1)
        elif key == pygame.K_RIGHT:
            self.cycle_expression(1)
        elif key == pygame.K_h:
            self.show_help = not self.show_help

    def run(self):
        while True:
            self.clock.tick(60)

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit(0)
                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_ESCAPE:
                        pygame.quit()
                        sys.exit(0)
                    self.handle_key(event.key)

            self.draw()


if __name__ == "__main__":
    RobotFace().run()
