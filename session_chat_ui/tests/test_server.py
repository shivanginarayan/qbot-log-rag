import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


UI_DIR = Path(__file__).resolve().parents[1]
if str(UI_DIR) not in sys.path:
    sys.path.insert(0, str(UI_DIR))

import server  # noqa: E402


def create_session_database(runtime_dir, session_id, status, started_at_ns):
    session_dir = Path(runtime_dir) / ("session_" + session_id)
    session_dir.mkdir(parents=True)
    database = session_dir / "robot.db"
    connection = sqlite3.connect(str(database))
    connection.execute(
        """
        CREATE TABLE sessions (
            session_id TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            started_at_ns INTEGER NOT NULL,
            map_name TEXT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO sessions (session_id, status, started_at_ns, map_name)
        VALUES (?, ?, ?, ?)
        """,
        (session_id, status, started_at_ns, "test_map"),
    )
    connection.commit()
    connection.close()
    return database


class SessionLocatorTest(unittest.TestCase):
    def test_prefers_newest_session(self):
        with tempfile.TemporaryDirectory() as directory:
            create_session_database(directory, "old_running", "running", 100)
            create_session_database(directory, "new_completed", "completed", 300)
            create_session_database(directory, "new_running", "running", 200)

            located = server.SessionLocator(runtime_dir=directory).locate()

            self.assertIsNotNone(located)
            self.assertEqual(located["session_id"], "new_completed")
            self.assertEqual(located["map_name"], "test_map")

    def test_fixed_session_is_respected(self):
        with tempfile.TemporaryDirectory() as directory:
            create_session_database(directory, "first", "running", 100)
            create_session_database(directory, "second", "running", 200)

            located = server.SessionLocator(
                runtime_dir=directory, fixed_session_id="first"
            ).locate()

            self.assertEqual(located["session_id"], "first")


class ChatStoreTest(unittest.TestCase):
    def test_stores_user_question_and_robot_response_in_robot_db(self):
        with tempfile.TemporaryDirectory() as directory:
            database = create_session_database(
                directory, "session_a", "running", 100
            )
            session = {
                "session_id": "session_a",
                "database": database,
            }
            store = server.ChatStore()

            store.begin(
                session=session,
                request_id="request-1",
                user_id="student-17",
                question="Why did navigation stop?",
                audience="user",
            )
            store.finish(
                session=session,
                request_id="request-1",
                robot_response="The obstacle evidence caused the stop.",
                status="answered",
                model="test-model",
                packet_count=2,
                used_llm=True,
                response_time_ms=1250,
            )

            connection = sqlite3.connect(str(database))
            row = connection.execute(
                """
                SELECT user_id, question, robot_response, status,
                       retrieval_packet_count, used_llm
                FROM ui_chat_interactions
                WHERE request_id = ?
                """,
                ("request-1",),
            ).fetchone()
            connection.close()

            self.assertEqual(row[0], "student-17")
            self.assertEqual(row[1], "Why did navigation stop?")
            self.assertEqual(row[2], "The obstacle evidence caused the stop.")
            self.assertEqual(row[3], "answered")
            self.assertEqual(row[4], 2)
            self.assertEqual(row[5], 1)

    def test_failed_answer_is_also_completed_in_database(self):
        with tempfile.TemporaryDirectory() as directory:
            database = create_session_database(
                directory, "session_b", "running", 100
            )
            session = {"session_id": "session_b", "database": database}
            store = server.ChatStore()

            store.begin(session, "request-2", "user-b", "What happened?", "user")
            store.finish(
                session,
                "request-2",
                "The pipeline could not answer.",
                "error",
                server.NVIDIA_MODEL,
                0,
                False,
                25,
                "test failure",
            )

            connection = sqlite3.connect(str(database))
            row = connection.execute(
                """
                SELECT robot_response, status, error_message
                FROM ui_chat_interactions
                WHERE request_id = 'request-2'
                """
            ).fetchone()
            connection.close()

            self.assertEqual(row[0], "The pipeline could not answer.")
            self.assertEqual(row[1], "error")
            self.assertEqual(row[2], "test failure")


class RagRunnerTest(unittest.TestCase):
    def test_calls_core_rag_with_session_and_extracts_answer(self):
        output = (
            "SELECTED OCCURRENCES: 3\n"
            "AUDIENCE: user\n"
            + server.ANSWER_MARKER
            + "Grounded robot answer\n"
        )
        completed = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=output, stderr=""
        )

        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "ask_robot.py"
            script.touch()
            runner = server.RagRunner(script=script)

            with mock.patch.object(
                server.subprocess, "run", return_value=completed
            ) as run_command:
                result = runner.answer(
                    "What happened?", "20260824_abc1", "developer"
                )

        command = run_command.call_args.args[0]
        self.assertIn("--session-id", command)
        self.assertIn("20260824_abc1", command)
        self.assertIn("--question", command)
        self.assertIn("What happened?", command)
        self.assertEqual(result["answer"], "Grounded robot answer")
        self.assertEqual(result["packet_count"], 3)
        self.assertTrue(result["used_llm"])

    def test_preserves_no_evidence_response(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                "SELECTED OCCURRENCES: 0\n"
                "No executed occurrence could be retrieved.\n"
            ),
            stderr="",
        )

        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "ask_robot.py"
            script.touch()
            runner = server.RagRunner(script=script)

            with mock.patch.object(server.subprocess, "run", return_value=completed):
                result = runner.answer("What happened?", "session-x", "user")

        self.assertEqual(
            result["answer"], "No executed occurrence could be retrieved."
        )
        self.assertFalse(result["used_llm"])


if __name__ == "__main__":
    unittest.main()
