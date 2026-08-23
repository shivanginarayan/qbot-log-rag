import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_DIR / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import rag_chat_adapter  # noqa: E402


class RagChatAdapterTest(unittest.TestCase):
    def test_runs_existing_command_and_extracts_llm_answer(self):
        output = (
            "SELECTED OCCURRENCES: 2\n\n"
            "AUDIENCE: USER\n"
            "ANSWER\n"
            + "=" * 70
            + "\nGrounded response\n"
        )

        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=output,
            stderr="",
        )

        with mock.patch.object(
            rag_chat_adapter.subprocess,
            "run",
            return_value=completed,
        ) as runner:
            result = (
                rag_chat_adapter
                .answer_question(
                    "What happened?",
                    requested_map="lab_map",
                    audience="developer",
                )
            )

        self.assertEqual(
            result["answer"],
            "Grounded response",
        )
        self.assertTrue(result["used_llm"])
        self.assertEqual(
            result["packet_count"],
            2,
        )

        command = runner.call_args.args[0]
        self.assertEqual(
            command[1],
            str(
                rag_chat_adapter
                .ASK_ROBOT_SCRIPT
            ),
        )
        self.assertIn("--map", command)
        self.assertIn("lab_map", command)

    def test_returns_existing_no_evidence_message(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "SELECTED OCCURRENCES: 0\n\n"
                "No executed occurrence could be retrieved.\n"
            ),
            stderr="",
        )

        with mock.patch.object(
            rag_chat_adapter.subprocess,
            "run",
            return_value=completed,
        ):
            result = (
                rag_chat_adapter
                .answer_question(
                    "What happened?"
                )
            )

        self.assertFalse(result["used_llm"])
        self.assertEqual(
            result["packet_count"],
            0,
        )
        self.assertEqual(
            result["answer"],
            (
                "No executed occurrence "
                "could be retrieved."
            ),
        )


if __name__ == "__main__":
    unittest.main()
