import os
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

    def test_lists_no_sessions_as_an_empty_list(self):
        with tempfile.TemporaryDirectory() as directory:
            sessions = server.SessionLocator(runtime_dir=directory).list_sessions()

            self.assertEqual(sessions, [])


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

            connection = sqlite3.connect(str(database))
            columns = {
                item[1]
                for item in connection.execute(
                    "PRAGMA table_info(ui_chat_interactions)"
                ).fetchall()
            }
            connection.close()
            self.assertNotIn("api_key", columns)
            self.assertNotIn("nvidia_api_key", columns)

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

    def test_loads_returning_user_history_across_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            old_database = create_session_database(
                directory, "old_session", "completed", 100
            )
            new_database = create_session_database(
                directory, "new_session", "running", 200
            )
            store = server.ChatStore()

            old_session = {
                "session_id": "old_session",
                "database": old_database,
            }
            new_session = {
                "session_id": "new_session",
                "database": new_database,
            }

            store.begin(
                old_session,
                "history-1",
                "returning-user",
                "What happened yesterday?",
                "user",
            )
            store.finish(
                old_session,
                "history-1",
                "The earlier run completed.",
                "answered",
                "test-model",
                1,
                True,
                100,
            )
            store.begin(
                new_session,
                "history-2",
                "returning-user",
                "What is happening now?",
                "developer",
            )
            store.finish(
                new_session,
                "history-2",
                "The current run is active.",
                "answered",
                "test-model",
                2,
                True,
                200,
            )
            store.begin(
                new_session,
                "different-user",
                "someone-else",
                "Do not return this question.",
                "user",
            )
            store.finish(
                new_session,
                "different-user",
                "Do not return this answer.",
                "answered",
                "test-model",
                0,
                True,
                50,
            )

            sessions = server.SessionLocator(runtime_dir=directory).list_sessions()
            history = store.history(sessions, "returning-user")

            self.assertEqual(len(history), 2)
            self.assertEqual(history[0]["session_id"], "old_session")
            self.assertEqual(history[0]["question"], "What happened yesterday?")
            self.assertEqual(history[1]["session_id"], "new_session")
            self.assertEqual(
                history[1]["robot_response"], "The current run is active."
            )


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
        observed_environment = {}

        def complete_command(*_args, **kwargs):
            observed_environment.update(kwargs["env"])
            return completed

        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "ask_robot.py"
            script.touch()
            runner = server.RagRunner(script=script)

            with mock.patch.object(
                server.subprocess, "run", side_effect=complete_command
            ) as run_command:
                result = runner.answer(
                    "What happened?",
                    "20260824_abc1",
                    "developer",
                    "nvapi-test-only-secret",
                )

        command = run_command.call_args.args[0]
        self.assertIn("--session-id", command)
        self.assertIn("20260824_abc1", command)
        self.assertIn("--question", command)
        self.assertIn("What happened?", command)
        self.assertNotIn("nvapi-test-only-secret", command)
        self.assertEqual(
            observed_environment["NVIDIA_API_KEY"], "nvapi-test-only-secret"
        )
        self.assertNotIn("NVIDIA_API_KEY", run_command.call_args.kwargs["env"])
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
                result = runner.answer(
                    "What happened?", "session-x", "user", "nvapi-test-key"
                )

        self.assertEqual(
            result["answer"], "No executed occurrence could be retrieved."
        )
        self.assertFalse(result["used_llm"])

    def test_redacts_key_from_rag_error_details(self):
        fake_key = "nvapi-redaction-test"
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="request failed for " + fake_key,
        )

        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / "ask_robot.py"
            script.touch()
            runner = server.RagRunner(script=script)

            with mock.patch.object(server.subprocess, "run", return_value=completed):
                with self.assertRaises(server.RagFailure) as raised:
                    runner.answer(
                        "What happened?", "session-x", "user", fake_key
                    )

        self.assertNotIn(fake_key, raised.exception.details)
        self.assertIn("[REDACTED]", raised.exception.details)


class ApiKeyMemoryTest(unittest.TestCase):
    class Locator:
        @staticmethod
        def locate():
            return None

    class Store:
        @staticmethod
        def count(_session):
            return 0

    def test_key_can_be_set_and_cleared_only_in_application_memory(self):
        application = server.ChatApplication(
            locator=self.Locator(),
            store=self.Store(),
            runner=object(),
        )
        fake_key = "nvapi-memory-only-test"

        application.set_api_key(fake_key)

        self.assertTrue(application.has_api_key())
        self.assertEqual(application.get_api_key(), fake_key)
        self.assertNotEqual(os.environ.get("NVIDIA_API_KEY"), fake_key)

        application.clear_api_key()

        self.assertFalse(application.has_api_key())

    def test_loopback_detection_rejects_network_addresses(self):
        handler = object.__new__(server.ChatRequestHandler)

        handler.client_address = ("127.0.0.1", 10000)
        self.assertTrue(handler._is_loopback_client())

        handler.client_address = ("192.168.1.50", 10000)
        self.assertFalse(handler._is_loopback_client())


if __name__ == "__main__":
    unittest.main()
