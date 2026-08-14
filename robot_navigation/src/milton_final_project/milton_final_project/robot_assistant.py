from dataclasses import dataclass
import re
import shutil
import subprocess
from typing import Optional


DEFAULT_WAITING_MESSAGE = "Hi, I'm the navigation robot that helps you find a location or room."


@dataclass(frozen=True)
class RobotReply:
    message: str
    expression: str


class FriendlyRobotAssistant:
    def __init__(
        self,
        model: str = 'llama3.2:latest',
        timeout_sec: float = 12.0,
        waiting_message: str = DEFAULT_WAITING_MESSAGE,
    ):
        self.model = model
        self.timeout_sec = timeout_sec
        self.waiting_message = waiting_message
        self.ollama_path: Optional[str] = shutil.which('ollama')

    def available(self) -> bool:
        return bool(self.ollama_path)

    def reply(self, user_text: str) -> RobotReply:
        cleaned = ' '.join(user_text.strip().split())
        if not cleaned:
            return RobotReply(self.waiting_message, 'confused')

        llm_reply = self._run_model(cleaned)
        if llm_reply:
            return RobotReply(llm_reply, self._infer_expression(cleaned, llm_reply))

        return self._fallback_reply(cleaned)

    def _run_model(self, user_text: str) -> Optional[str]:
        if not self.ollama_path:
            return None

        prompt = (
            'You are a friendly indoor navigation robot. '
            'The user already gave you a destination or room name. '
            'Reply with one short friendly acknowledgment sentence only. '
            'Do not ask follow-up questions. Do not give directions. '
            'Do not mention maps, phones, apps, or uncertainty. '
            'No markdown, no lists, max 18 words.\n'
            f'Destination: {user_text}\n'
            'Robot reply:'
        )

        try:
            result = subprocess.run(
                [self.ollama_path, 'run', self.model, prompt],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired):
            return None

        if result.returncode != 0:
            return None

        output = self._clean_output(result.stdout)
        if not output:
            return None

        return self._shorten(output, max_chars=150)

    def _clean_output(self, text: str) -> str:
        ansi_escape = re.compile(r'\x1b\[[0-?]*[ -/]*[@-~]')
        text = ansi_escape.sub('', text)
        text = text.replace('\r', ' ')
        text = ' '.join(text.split())

        if 'Robot reply:' in text:
            text = text.split('Robot reply:', 1)[-1].strip()

        return text.strip(' "')

    def _fallback_reply(self, user_text: str) -> RobotReply:
        lowered = user_text.lower()

        if any(token in lowered for token in ('thank', 'thanks')):
            return RobotReply("You're welcome. I'm happy to help.", 'thank_you')

        if any(token in lowered for token in ('hi', 'hello', 'hey')):
            return RobotReply('Hi there. Tell me where you want to go.', 'happy')

        if any(token in lowered for token in ('bye', 'goodbye', 'see you')):
            return RobotReply('Goodbye. I hope you have a great day.', 'happy')

        if any(token in lowered for token in ('where', 'find', 'room', 'lab', 'office')):
            return RobotReply(
                f"Absolutely. I'll help you find {user_text}.",
                'ready_to_go',
            )

        return RobotReply(
            f"Thanks. I'll help you find {user_text}.",
            'happy',
        )

    def _infer_expression(self, user_text: str, reply_text: str) -> str:
        lowered_input = user_text.lower()

        if any(token in lowered_input for token in ('thank', 'thanks')):
            return 'thank_you'
        if any(token in lowered_input for token in ('hi', 'hello', 'hey')):
            return 'happy'
        if any(token in lowered_input for token in ('sorry', 'apologize')):
            return 'apologetic'
        if any(token in lowered_input for token in ('where', 'find', 'take me', 'direction')):
            return 'ready_to_go'
        return 'happy'

    def _shorten(self, text: str, max_chars: int) -> str:
        if len(text) <= max_chars:
            return text

        shortened = text[: max_chars - 3].rstrip()
        last_break = max(shortened.rfind('.'), shortened.rfind('!'), shortened.rfind('?'))
        if last_break >= 48:
            shortened = shortened[: last_break + 1]
        return shortened.rstrip() + ('...' if not shortened.endswith(('.', '!', '?')) else '')
