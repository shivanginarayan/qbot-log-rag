import json
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
import rag_compat  # noqa: E402


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

    def test_uses_latest_task_event_map_when_session_map_is_blank(self):
        with tempfile.TemporaryDirectory() as directory:
            database = create_session_database(
                directory, "mapped_session", "running", 100
            )
            connection = sqlite3.connect(str(database))
            connection.execute("UPDATE sessions SET map_name = NULL")
            connection.execute(
                """
                CREATE TABLE task_events (
                    session_id TEXT NOT NULL,
                    event_time_ns INTEGER NOT NULL,
                    map_name TEXT
                )
                """
            )
            connection.executemany(
                "INSERT INTO task_events VALUES (?, ?, ?)",
                [
                    ("mapped_session", 200, "old_map"),
                    ("mapped_session", 300, "new_map"),
                ],
            )
            connection.commit()
            connection.close()

            located = server.SessionLocator(runtime_dir=directory).locate()

            self.assertEqual(located["map_name"], "new_map")


class MapStatusLocatorTest(unittest.TestCase):
    def test_prefers_active_navigation_map(self):
        locator = server.MapStatusLocator(maps_dir="/missing")
        locator._read_status = mock.Mock(
            side_effect=[{"active_map": "active_map.pgm"}, {}]
        )

        self.assertEqual(locator.locate({"map_name": "database_map"}), "active_map")

    def test_detects_map_created_during_session(self):
        with tempfile.TemporaryDirectory() as directory:
            maps_dir = Path(directory)
            yaml_path = maps_dir / "new_robot_map.yaml"
            pgm_path = maps_dir / "new_robot_map.pgm"
            yaml_path.touch()
            pgm_path.touch()
            modified_ns = yaml_path.stat().st_mtime_ns
            locator = server.MapStatusLocator(maps_dir=maps_dir)
            locator._read_status = mock.Mock(return_value={})

            found = locator.locate(
                {"started_at_ns": modified_ns - 1, "map_name": ""}
            )

            self.assertEqual(found, "new_robot_map")

    def test_marks_active_map_claimable_only_when_created_in_session(self):
        with tempfile.TemporaryDirectory() as directory:
            maps_dir = Path(directory)
            (maps_dir / "active.yaml").touch()
            (maps_dir / "active.pgm").touch()
            modified_ns = (maps_dir / "active.yaml").stat().st_mtime_ns
            locator = server.MapStatusLocator(maps_dir=maps_dir)
            locator._read_status = mock.Mock(
                return_value={"active_map": "active.pgm"}
            )

            current = locator.locate_details(
                {"started_at_ns": modified_ns - 1, "map_name": ""}
            )
            older = locator.locate_details(
                {"started_at_ns": modified_ns + 1, "map_name": ""}
            )

            self.assertTrue(current["claimable"])
            self.assertFalse(older["claimable"])


class DemographicQuestionTest(unittest.TestCase):
    def test_has_three_direct_questions_then_twenty_numeric_ratings(self):
        self.assertEqual(len(server.DEMOGRAPHIC_QUESTIONS), 23)
        self.assertEqual(
            [item["kind"] for item in server.DEMOGRAPHIC_QUESTIONS[:3]],
            ["birth_year", "text", "text"],
        )
        self.assertTrue(
            all(
                item["kind"] == "rating_1_5"
                for item in server.DEMOGRAPHIC_QUESTIONS[3:]
            )
        )

    def test_rating_questions_accept_only_numbers_one_through_five(self):
        for value in (1, 2, 3, 4, 5, "1", "5"):
            normalized = server.validate_demographic_answer(3, value)
            self.assertIn(normalized, {"1", "2", "3", "4", "5"})

        for value in (0, 6, "0", "6", "yes", "strongly agree", True, ""):
            with self.assertRaises(ValueError):
                server.validate_demographic_answer(3, value)

    def test_birth_year_requires_a_reasonable_four_digit_year(self):
        self.assertEqual(
            server.validate_demographic_answer(0, "1999"),
            "1999",
        )
        for value in ("99", "1899", "next year", ""):
            with self.assertRaises(ValueError):
                server.validate_demographic_answer(0, value)


class ChatStoreTest(unittest.TestCase):
    def test_stores_and_resumes_demographics_for_each_user(self):
        with tempfile.TemporaryDirectory() as directory:
            database = create_session_database(
                directory, "demographic_session", "running", 100
            )
            session = {
                "session_id": "demographic_session",
                "database": database,
            }
            store = server.ChatStore()

            store.register_participant(session, "student-22")
            self.assertEqual(
                store.demographic_progress(session, "student-22"),
                {
                    "answered_count": 0,
                    "completed": False,
                    "next_question_index": 0,
                },
            )

            answers = ["1998", "Non-binary", "Yes"] + ["3"] * 20
            for question_index, answer in enumerate(answers):
                store.save_demographic_answer(
                    session,
                    "student-22",
                    question_index,
                    answer,
                )

            progress = store.demographic_progress(session, "student-22")
            self.assertTrue(progress["completed"])
            self.assertEqual(progress["answered_count"], 23)
            self.assertIsNone(progress["next_question_index"])

            connection = sqlite3.connect(str(database))
            stored = connection.execute(
                """
                SELECT question_text, response_value, response_kind
                FROM ui_demographic_responses
                WHERE session_id = ? AND user_id = ?
                ORDER BY question_index
                """,
                ("demographic_session", "student-22"),
            ).fetchall()
            completed_at = connection.execute(
                """
                SELECT demographics_completed_at_iso
                FROM ui_participants
                WHERE session_id = ? AND user_id = ?
                """,
                ("demographic_session", "student-22"),
            ).fetchone()
            connection.close()

            self.assertEqual(len(stored), 23)
            self.assertEqual(stored[0][0], "What year were you born?")
            self.assertEqual(stored[0][1], "1998")
            self.assertEqual(stored[3][1:], ("3", "rating_1_5"))
            self.assertTrue(completed_at[0])
            self.assertEqual(
                store.demographic_progress(session, "different-user")[
                    "answered_count"
                ],
                0,
            )

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

    def test_map_ownership_is_persistent_and_cannot_be_transferred(self):
        with tempfile.TemporaryDirectory() as directory:
            database = create_session_database(
                directory, "map_session", "running", 100
            )
            session = {
                "session_id": "map_session",
                "database": database,
            }
            sessions = [session]
            store = server.ChatStore()

            self.assertTrue(store.claim_map(session, "user-a", "map-a"))
            self.assertFalse(store.claim_map(session, "user-b", "map-a"))
            self.assertTrue(store.claim_map(session, "user-b", "map-b"))

            self.assertEqual(store.map_owner(sessions, "map-a"), "user-a")
            self.assertEqual(
                store.latest_map_for_user(sessions, "user-a", "map-a"),
                "map-a",
            )
            self.assertEqual(
                store.latest_map_for_user(sessions, "user-b", "map-b"),
                "map-b",
            )


class DemographicRequestFlowTest(unittest.TestCase):
    @staticmethod
    def call_handler(application, method_name, payload, path=None):
        handler = object.__new__(server.ChatRequestHandler)
        request_server = type("RequestServer", (), {})()
        request_server.application = application
        handler.server = request_server
        handler._read_json_payload = mock.Mock(return_value=payload)
        handler._send_json = mock.Mock()
        if path is not None:
            handler.path = path
        getattr(handler, method_name)()
        return handler._send_json.call_args.args

    def test_login_resume_numeric_validation_and_chat_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            create_session_database(
                directory, "web_session", "running", 100
            )
            application = server.ChatApplication(
                locator=server.SessionLocator(runtime_dir=directory),
                store=server.ChatStore(),
                runner=object(),
                initial_api_key="nvapi-test-only",
            )

            status, login = self.call_handler(
                application,
                "_handle_login",
                {"user_id": "web-user"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(login["question"]["index"], 0)

            for index, answer in enumerate(("1997", "Woman", "Yes")):
                status, result = self.call_handler(
                    application,
                    "_handle_demographics",
                    {
                        "user_id": "web-user",
                        "question_index": index,
                        "answer": answer,
                    },
                )
                self.assertEqual(status, 200)

            status, rejected = self.call_handler(
                application,
                "_handle_demographics",
                {
                    "user_id": "web-user",
                    "question_index": 3,
                    "answer": "strongly agree",
                },
            )
            self.assertEqual(status, 400)
            self.assertIn("1 to 5", rejected["error"])

            status, blocked_chat = self.call_handler(
                application,
                "do_POST",
                {
                    "user_id": "web-user",
                    "question": "What happened?",
                    "audience": "user",
                },
                path="/api/chat",
            )
            self.assertEqual(status, 403)
            self.assertIn("demographic", blocked_chat["error"])

            status, resumed = self.call_handler(
                application,
                "_handle_login",
                {"user_id": "web-user"},
            )
            self.assertEqual(status, 200)
            self.assertEqual(resumed["answered_count"], 3)
            self.assertEqual(resumed["question"]["index"], 3)


class UserFilteredStatusTest(unittest.TestCase):
    class Locator:
        def __init__(self, session):
            self.session = session

        def locate(self):
            return self.session

        def list_sessions(self):
            return [self.session]

    class MapLocator:
        def __init__(self, name):
            self.name = name

        def locate_details(self, _session):
            return {"name": self.name, "claimable": True}

    def test_switching_user_ids_filters_maps_and_new_map_goes_to_active_user(self):
        with tempfile.TemporaryDirectory() as directory:
            database = create_session_database(
                directory, "map_session", "running", 100
            )
            session = {
                "session_id": "map_session",
                "status": "running",
                "started_at_ns": 100,
                "map_name": "",
                "database": database,
            }
            map_locator = self.MapLocator("map-a")
            application = server.ChatApplication(
                locator=self.Locator(session),
                store=server.ChatStore(),
                runner=object(),
                map_locator=map_locator,
            )

            with mock.patch.object(application, "embedding_ready", return_value=True):
                first_user = application.status(user_id="user-a")
                second_user_before_mapping = application.status(user_id="user-b")
                map_locator.name = "map-b"
                second_user_after_mapping = application.status(user_id="user-b")
                first_user_again = application.status(user_id="user-a")

            self.assertEqual(first_user["map_name"], "map-a")
            self.assertEqual(second_user_before_mapping["map_name"], "")
            self.assertEqual(second_user_after_mapping["map_name"], "map-b")
            self.assertEqual(first_user_again["map_name"], "map-a")


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

    def test_rosout_baseline_does_not_receive_session_id(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=(
                server.ANSWER_MARKER
                + "Explaining autonomy answer\n"
            ),
            stderr="",
        )

        runner = server.RagRunner()

        with mock.patch.object(
            server.subprocess,
            "run",
            return_value=completed,
        ) as run_command:
            runner.answer(
                "What is happening?",
                "20260824_abc1",
                "user",
                "nvapi-test-key",
                system="rosout",
            )

        command = run_command.call_args.args[0]

        self.assertIn("rosout", command)
        self.assertIn("--question", command)
        self.assertIn("What is happening?", command)

        self.assertNotIn("--session-id", command)
        self.assertNotIn("20260824_abc1", command)


def test_causal_baseline_does_not_receive_session_id(self):
    completed = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=(
            server.ANSWER_MARKER
            + "Causal explanation answer\n"
        ),
        stderr="",
    )

    runner = server.RagRunner()

    with mock.patch.object(
        server.subprocess,
        "run",
        return_value=completed,
    ) as run_command:
        runner.answer(
            "Why did localization succeed?",
            "20260824_abc1",
            "developer",
            "nvapi-test-key",
            system="causal",
        )

    command = run_command.call_args.args[0]

    self.assertIn("causal", command)
    self.assertIn("--question", command)
    self.assertIn(
        "Why did localization succeed?",
        command,
    )

    self.assertIn("--role", command)
    self.assertIn("engineer", command)

    self.assertNotIn("--session-id", command)
    self.assertNotIn("20260824_abc1", command)


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
        self.assertEqual(Path(command[1]), server.RAG_COMPAT_SCRIPT)
        self.assertIn("--core-script", command)
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


class RagCompatibilityTest(unittest.TestCase):
    def test_installs_missing_map_helpers_without_overwriting_existing_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            maps_dir = Path(directory)
            (maps_dir / "lab.pgm").touch()
            (maps_dir / "lab.yaml").touch()
            (maps_dir / "lab_labels.json").write_text(
                json.dumps(
                    {
                        "labels": [
                            {
                                "id": "one",
                                "name": "station",
                                "world": {"x": 1.0, "y": 2.0},
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            class CoreModule:
                MAPS_DIR = maps_dir

                @staticmethod
                def normalize_map_name(_value):
                    return "team-version"

            original = CoreModule.normalize_map_name
            rag_compat.install_missing_helpers(CoreModule)

            current = CoreModule.load_current_map_metadata("lab.pgm")
            saved = CoreModule.load_saved_maps_metadata()

            self.assertIs(CoreModule.normalize_map_name, original)
            self.assertEqual(current["map"], "lab")
            self.assertEqual(current["label_count"], 1)
            self.assertEqual(saved["map_count"], 1)

    def test_wrapper_runs_a_core_main_that_references_missing_helpers(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary_dir = Path(directory)
            maps_dir = temporary_dir / "maps"
            maps_dir.mkdir()
            (maps_dir / "active.pgm").touch()
            (maps_dir / "active.yaml").touch()
            (maps_dir / "active_labels.json").write_text(
                json.dumps({"labels": [{"id": "one", "name": "desk"}]}),
                encoding="utf-8",
            )
            core_script = temporary_dir / "core.py"
            core_script.write_text(
                "from pathlib import Path\n"
                "MAPS_DIR = Path({!r})\n"
                "def main():\n"
                "    current = load_current_map_metadata('active.pgm')\n"
                "    saved = load_saved_maps_metadata()\n"
                "    print(current['map'], current['label_count'], saved['map_count'])\n".format(
                    str(maps_dir)
                ),
                encoding="utf-8",
            )

            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(rag_compat.__file__)),
                    "--core-script",
                    str(core_script),
                    "--",
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(completed.stdout.strip(), "active 1 1")


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
