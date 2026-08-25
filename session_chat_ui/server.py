#!/usr/bin/env python3

"""Standalone browser UI for the QBot session-aware RAG pipeline.

This module intentionally does not import the project's previous chat UI.
It calls the same ask_robot.py command used by run_full_log_experiment.sh and
stores each exchange in the experiment session's robot.db database.
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen


UI_DIR = Path(__file__).resolve().parent
REPO_DIR = UI_DIR.parent
STATIC_DIR = UI_DIR / "static"
RUNTIME_DIR = REPO_DIR / "runtime_logs"
ASK_ROBOT_SCRIPT = REPO_DIR / "src" / "reasoning" / "ask_robot.py"

NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"
ANSWER_MARKER = "ANSWER\n" + ("=" * 70) + "\n"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
PACKET_PATTERN = re.compile(r"SELECTED OCCURRENCES:\s*(\d+)")

MAX_REQUEST_BYTES = 32 * 1024
MAX_USER_ID_LENGTH = 128
MAX_QUESTION_LENGTH = 8000
MAX_ERROR_LENGTH = 4000


class RagFailure(RuntimeError):
    """A RAG failure with separate public and diagnostic messages."""

    def __init__(self, public_message, details=""):
        super().__init__(public_message)
        self.public_message = public_message
        self.details = (details or public_message)[-MAX_ERROR_LENGTH:]


def utc_now():
    """Return nanoseconds and an ISO-8601 UTC timestamp."""

    now_ns = time.time_ns()
    now_iso = (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    return now_ns, now_iso


def has_control_characters(value):
    return any(ord(character) < 32 for character in value)


class SessionLocator:
    """Find the latest usable database created by the full experiment."""

    def __init__(self, runtime_dir=RUNTIME_DIR, fixed_session_id=None):
        self.runtime_dir = Path(runtime_dir)
        self.fixed_session_id = fixed_session_id or None

        if self.fixed_session_id and not SESSION_ID_PATTERN.fullmatch(
            self.fixed_session_id
        ):
            raise ValueError("Invalid fixed session ID.")

    def _database_for(self, session_id):
        if not session_id or not SESSION_ID_PATTERN.fullmatch(session_id):
            return None

        database = (
            self.runtime_dir / ("session_" + session_id) / "robot.db"
        )
        return database if database.is_file() else None

    @staticmethod
    def _read_session(database):
        connection = None
        try:
            connection = sqlite3.connect(str(database), timeout=2)
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT session_id, status, started_at_ns, map_name
                FROM sessions
                ORDER BY started_at_ns DESC
                LIMIT 1
                """
            ).fetchone()
        except (OSError, sqlite3.Error):
            return None
        finally:
            if connection is not None:
                connection.close()

        if row is None:
            return None

        return {
            "session_id": str(row["session_id"]),
            "status": str(row["status"] or "unknown"),
            "started_at_ns": int(row["started_at_ns"] or 0),
            "map_name": row["map_name"] or "",
            "database": database,
        }

    def locate(self):
        requested_ids = []

        if self.fixed_session_id:
            requested_ids.append(self.fixed_session_id)
        else:
            environment_id = os.environ.get(
                "QBOT_EXPERIMENT_SESSION_ID", ""
            ).strip()
            if environment_id:
                requested_ids.append(environment_id)

        for session_id in requested_ids:
            database = self._database_for(session_id)
            if database:
                session = self._read_session(database)
                if session:
                    return session

        if self.fixed_session_id:
            return None

        candidates = []
        for database in self.runtime_dir.glob("session_*/robot.db"):
            session = self._read_session(database)
            if session:
                candidates.append(session)

        if not candidates:
            return None

        candidates.sort(
            key=lambda item: (
                item["started_at_ns"],
                item["status"].casefold() == "running",
            ),
            reverse=True,
        )
        return candidates[0]


class ChatStore:
    """Write chat exchanges into the selected experiment database."""

    SCHEMA = """
        CREATE TABLE IF NOT EXISTS ui_chat_interactions (
            request_id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            question TEXT NOT NULL,
            robot_response TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL,
            audience TEXT NOT NULL,
            model TEXT NOT NULL DEFAULT '',
            retrieval_packet_count INTEGER NOT NULL DEFAULT 0,
            used_llm INTEGER NOT NULL DEFAULT 0,
            response_time_ms INTEGER,
            asked_at_ns INTEGER NOT NULL,
            asked_at_iso TEXT NOT NULL,
            answered_at_ns INTEGER,
            answered_at_iso TEXT,
            error_message TEXT NOT NULL DEFAULT '',
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """

    INDEX = """
        CREATE INDEX IF NOT EXISTS idx_ui_chat_session_time
        ON ui_chat_interactions(session_id, asked_at_ns)
    """

    def __init__(self, attempts=5):
        self.attempts = attempts

    def _write(self, database, operation):
        last_error = None

        for attempt in range(self.attempts):
            connection = None
            try:
                connection = sqlite3.connect(str(database), timeout=5)
                connection.execute("PRAGMA busy_timeout = 5000")
                operation(connection)
                connection.commit()
                return
            except sqlite3.OperationalError as exc:
                last_error = exc
                if "locked" not in str(exc).casefold():
                    raise
                time.sleep(0.05 * (2 ** attempt))
            finally:
                if connection is not None:
                    connection.close()

        raise last_error or RuntimeError("Database write failed.")

    def begin(self, session, request_id, user_id, question, audience):
        asked_at_ns, asked_at_iso = utc_now()

        def operation(connection):
            connection.execute(self.SCHEMA)
            connection.execute(self.INDEX)
            connection.execute(
                """
                INSERT INTO ui_chat_interactions (
                    request_id,
                    session_id,
                    user_id,
                    question,
                    status,
                    audience,
                    asked_at_ns,
                    asked_at_iso
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    session["session_id"],
                    user_id,
                    question,
                    "processing",
                    audience,
                    asked_at_ns,
                    asked_at_iso,
                ),
            )

        self._write(session["database"], operation)

    def finish(
        self,
        session,
        request_id,
        robot_response,
        status,
        model,
        packet_count,
        used_llm,
        response_time_ms,
        error_message="",
    ):
        answered_at_ns, answered_at_iso = utc_now()

        def operation(connection):
            cursor = connection.execute(
                """
                UPDATE ui_chat_interactions
                SET robot_response = ?,
                    status = ?,
                    model = ?,
                    retrieval_packet_count = ?,
                    used_llm = ?,
                    response_time_ms = ?,
                    answered_at_ns = ?,
                    answered_at_iso = ?,
                    error_message = ?
                WHERE request_id = ?
                """,
                (
                    robot_response,
                    status,
                    model,
                    int(packet_count),
                    1 if used_llm else 0,
                    int(response_time_ms),
                    answered_at_ns,
                    answered_at_iso,
                    (error_message or "")[-MAX_ERROR_LENGTH:],
                    request_id,
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("Pending chat row was not found.")

        self._write(session["database"], operation)

    @staticmethod
    def count(session):
        connection = None
        try:
            connection = sqlite3.connect(
                str(session["database"]), timeout=2
            )
            row = connection.execute(
                """
                SELECT COUNT(*)
                FROM ui_chat_interactions
                WHERE session_id = ?
                """,
                (session["session_id"],),
            ).fetchone()
            return int(row[0]) if row else 0
        except sqlite3.Error:
            return 0
        finally:
            if connection is not None:
                connection.close()


class RagRunner:
    """Invoke the team's unchanged session-aware RAG command."""

    def __init__(self, script=ASK_ROBOT_SCRIPT, timeout=240):
        self.script = Path(script)
        self.timeout = timeout

    @staticmethod
    def _last_nonempty_line(output):
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def answer(self, question, session_id, audience):
        if not self.script.is_file():
            raise RagFailure(
                "The QBot RAG command is unavailable.",
                "Missing file: " + str(self.script),
            )

        command = [
            sys.executable,
            str(self.script),
            "--session-id",
            session_id,
            "--audience",
            audience,
            "--question",
            question,
        ]

        try:
            completed = subprocess.run(
                command,
                cwd=str(REPO_DIR),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RagFailure(
                "The QBot assistant took too long to answer. Please try again.",
                "ask_robot.py timed out after {} seconds".format(self.timeout),
            ) from exc
        except OSError as exc:
            raise RagFailure(
                "The QBot RAG process could not be started.", str(exc)
            ) from exc

        if completed.returncode != 0:
            details = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or "ask_robot.py exited with status {}".format(
                    completed.returncode
                )
            )
            raise RagFailure(
                "The QBot RAG pipeline could not answer this question.",
                details,
            )

        output = completed.stdout
        packet_match = PACKET_PATTERN.search(output)
        packet_count = int(packet_match.group(1)) if packet_match else 0
        used_llm = ANSWER_MARKER in output

        if used_llm:
            answer = output.rsplit(ANSWER_MARKER, 1)[1].strip()
        else:
            answer = self._last_nonempty_line(output)

        if not answer:
            raise RagFailure(
                "The QBot RAG pipeline returned an empty answer.",
                "ask_robot.py completed without answer text",
            )

        return {
            "answer": answer,
            "model": NVIDIA_MODEL,
            "packet_count": packet_count,
            "used_llm": used_llm,
        }


class ChatApplication:
    def __init__(self, locator, store, runner, max_parallel_requests=2):
        self.locator = locator
        self.store = store
        self.runner = runner
        self.request_slots = threading.BoundedSemaphore(max_parallel_requests)

    @staticmethod
    def embedding_ready():
        try:
            with urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as response:
                return 200 <= response.status < 300
        except (OSError, URLError, ValueError):
            return False

    def status(self):
        session = self.locator.locate()
        api_key_configured = bool(os.environ.get("NVIDIA_API_KEY", "").strip())
        embedding_ready = self.embedding_ready()
        rag_command_ready = ASK_ROBOT_SCRIPT.is_file()
        session_ready = session is not None

        return {
            "ready": all(
                [
                    api_key_configured,
                    embedding_ready,
                    rag_command_ready,
                    session_ready,
                ]
            ),
            "api_key_configured": api_key_configured,
            "embedding_ready": embedding_ready,
            "rag_command_ready": rag_command_ready,
            "session_ready": session_ready,
            "session_id": session["session_id"] if session else "",
            "session_status": session["status"] if session else "not found",
            "map_name": session["map_name"] if session else "",
            "stored_exchange_count": self.store.count(session) if session else 0,
            "model": NVIDIA_MODEL,
        }


class ChatRequestHandler(BaseHTTPRequestHandler):
    server_version = "QBotSessionChat/1.0"

    STATIC_FILES = {
        "/": ("index.html", "text/html; charset=utf-8"),
        "/index.html": ("index.html", "text/html; charset=utf-8"),
        "/styles.css": ("styles.css", "text/css; charset=utf-8"),
        "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    }

    def log_message(self, message_format, *args):
        sys.stdout.write(
            "{} - {}\n".format(self.log_date_time_string(), message_format % args)
        )
        sys.stdout.flush()

    def _common_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; style-src 'self'; script-src 'self'; "
            "connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'",
        )

    def _send_json(self, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._common_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _serve_static(self, path):
        item = self.STATIC_FILES.get(path)
        if item is None:
            self._send_json(404, {"error": "Not found."})
            return

        file_name, content_type = item
        try:
            body = (STATIC_DIR / file_name).read_bytes()
        except OSError:
            self._send_json(500, {"error": "UI asset unavailable."})
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self._common_headers()
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = urlsplit(self.path).path

        if path == "/api/status":
            self._send_json(200, self.server.application.status())
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self._common_headers()
            self.end_headers()
            return

        self._serve_static(path)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path != "/api/chat":
            self._send_json(404, {"error": "Not found."})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(400, {"error": "Request body is empty or too large."})
            return

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Request body must be valid JSON."})
            return

        if not isinstance(payload, dict):
            self._send_json(400, {"error": "JSON body must be an object."})
            return

        user_id = payload.get("user_id", "")
        question = payload.get("question", "")
        audience = payload.get("audience", "user")

        if not isinstance(user_id, str):
            user_id = ""
        if not isinstance(question, str):
            question = ""
        if not isinstance(audience, str):
            audience = ""

        user_id = user_id.strip()
        question = question.strip()
        audience = audience.strip().casefold()

        validation_error = ""
        if not user_id:
            validation_error = "User ID is required."
        elif len(user_id) > MAX_USER_ID_LENGTH:
            validation_error = "User ID is too long."
        elif has_control_characters(user_id):
            validation_error = "User ID contains invalid characters."
        elif not question:
            validation_error = "Question is required."
        elif len(question) > MAX_QUESTION_LENGTH:
            validation_error = "Question is too long."
        elif audience not in {"user", "developer"}:
            validation_error = "Answer style is invalid."

        if validation_error:
            self._send_json(400, {"error": validation_error})
            return

        session = self.server.application.locator.locate()
        if session is None:
            self._send_json(
                503,
                {
                    "error": (
                        "No QBot experiment database was found. Start "
                        "run_full_log_experiment.sh first."
                    )
                },
            )
            return

        if not self.server.application.request_slots.acquire(blocking=False):
            self._send_json(
                429,
                {"error": "The assistant is busy. Please try again shortly."},
            )
            return

        request_id = uuid.uuid4().hex
        started = time.monotonic()

        try:
            try:
                self.server.application.store.begin(
                    session, request_id, user_id, question, audience
                )
            except Exception as exc:
                self._send_json(
                    503,
                    {
                        "error": (
                            "The question could not be saved to robot.db, so it "
                            "was not sent to the LLM."
                        )
                    },
                )
                print("Chat storage begin failed for {}: {}".format(request_id, exc))
                return

            answer = ""
            model = NVIDIA_MODEL
            packet_count = 0
            used_llm = False
            record_status = "error"
            error_details = ""
            http_status = 200

            try:
                result = self.server.application.runner.answer(
                    question, session["session_id"], audience
                )
                answer = result["answer"]
                model = result["model"]
                packet_count = result["packet_count"]
                used_llm = result["used_llm"]
                record_status = "answered" if used_llm else "no_evidence"
            except RagFailure as exc:
                answer = exc.public_message
                error_details = exc.details
                http_status = 502
            except Exception as exc:
                answer = "The QBot assistant encountered an unexpected error."
                error_details = str(exc)[-MAX_ERROR_LENGTH:]
                http_status = 500

            elapsed_ms = round((time.monotonic() - started) * 1000)

            try:
                self.server.application.store.finish(
                    session=session,
                    request_id=request_id,
                    robot_response=answer,
                    status=record_status,
                    model=model,
                    packet_count=packet_count,
                    used_llm=used_llm,
                    response_time_ms=elapsed_ms,
                    error_message=error_details,
                )
            except Exception as exc:
                print("Chat storage finish failed for {}: {}".format(request_id, exc))
                self._send_json(
                    500,
                    {
                        "answer": answer,
                        "error": (
                            "An answer was produced, but its database row could "
                            "not be completed."
                        ),
                        "request_id": request_id,
                    },
                )
                return

            self._send_json(
                http_status,
                {
                    "answer": answer,
                    "status": record_status,
                    "session_id": session["session_id"],
                    "request_id": request_id,
                    "used_llm": used_llm,
                    "retrieval_packet_count": packet_count,
                    "response_time_ms": elapsed_ms,
                    "error": "" if http_status == 200 else answer,
                },
            )
        finally:
            self.server.application.request_slots.release()


def build_parser():
    parser = argparse.ArgumentParser(
        description="Serve the standalone QBot session chat UI."
    )
    parser.add_argument(
        "--host", default=os.environ.get("QBOT_SESSION_UI_HOST", "0.0.0.0")
    )
    parser.add_argument(
        "--port",
        default=int(os.environ.get("QBOT_SESSION_UI_PORT", "8766")),
        type=int,
    )
    parser.add_argument(
        "--session-id",
        default=os.environ.get("QBOT_SESSION_UI_SESSION_ID", "") or None,
        help="Use one specific experiment session instead of auto-detection.",
    )
    parser.add_argument(
        "--rag-timeout",
        default=240,
        type=int,
        help="Maximum seconds allowed for one RAG answer.",
    )
    return parser


def main():
    args = build_parser().parse_args()

    locator = SessionLocator(fixed_session_id=args.session_id)
    application = ChatApplication(
        locator=locator,
        store=ChatStore(),
        runner=RagRunner(timeout=args.rag_timeout),
    )

    server = ThreadingHTTPServer((args.host, args.port), ChatRequestHandler)
    server.daemon_threads = True
    server.application = application

    display_host = "ROBOT_IP" if args.host in {"0.0.0.0", "::"} else args.host
    print("QBot session chat UI is running.")
    print("Open: http://{}:{}".format(display_host, args.port))
    print("RAG command: {}".format(ASK_ROBOT_SCRIPT))
    print("Chat database: active session robot.db (auto-detected)")

    session = locator.locate()
    if session:
        print(
            "Detected session: {} ({})".format(
                session["session_id"], session["status"]
            )
        )
    else:
        print("Waiting for run_full_log_experiment.sh to create a session.")

    if not os.environ.get("NVIDIA_API_KEY", "").strip():
        print("WARNING: NVIDIA_API_KEY is not set for this UI process.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping QBot session chat UI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
