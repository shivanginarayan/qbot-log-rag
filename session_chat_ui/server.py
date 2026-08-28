#!/usr/bin/env python3

"""Standalone browser UI for the QBot session-aware RAG pipeline.

This module intentionally does not import the project's previous chat UI.
It calls the same ask_robot.py command used by run_full_log_experiment.sh and
stores each exchange in the experiment session's robot.db database.
"""

import argparse
import hashlib
import ipaddress
import json
import os
import random
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
RAG_COMPAT_SCRIPT = UI_DIR / "rag_compat.py"
MAPS_DIR = REPO_DIR / "robot_navigation" / "maps"
NAVIGATION_STATUS_URL = "http://127.0.0.1:8765/api/navigation/status"
MAPPING_STATUS_URL = "http://127.0.0.1:8765/api/mapping/status"

COMPARISON_DIR = REPO_DIR / "comparison_experiments"
COMPARISON_SCRIPT = COMPARISON_DIR / "run_comparison.sh"
ROSOUT_BAG_ROOT = COMPARISON_DIR / "runtime" / "rosout_bags"
ROSOUT_INDEX_ROOT = COMPARISON_DIR / "runtime" / "explaining_autonomy"

NVIDIA_MODEL = "nvidia/nemotron-3-super-120b-a12b"
ANSWER_MARKER = "ANSWER\n" + ("=" * 70) + "\n"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
PACKET_PATTERN = re.compile(r"SELECTED OCCURRENCES:\s*(\d+)")
RETRIEVED_PATTERN = re.compile(r"RETRIEVED:\s*(\d+)")
ROSOUT_TOTAL_PATTERN = re.compile(r"ROSOUT RECORDS:\s*(\d+)")
ROSOUT_PROGRESS_PATTERN = re.compile(r"Embedded\s+(\d+)\s*/\s*(\d+)")

MAX_REQUEST_BYTES = 32 * 1024
MAX_USER_ID_LENGTH = 128
MAX_QUESTION_LENGTH = 8000
MAX_ERROR_LENGTH = 4000
MAX_API_KEY_LENGTH = 1024
MAX_HISTORY_ITEMS = 100
MAX_DEMOGRAPHIC_RESPONSE_LENGTH = 2000

DEFAULT_SYSTEM = "proposed"

# The explanation systems the chat page can switch between.  The proposed
# QBot pipeline is the default; the other two are the unchanged comparison
# baselines reached through comparison_experiments/run_comparison.sh.
SYSTEMS = {
    "proposed": {
        "label": "QBot (proposed)",
        "description": (
            "Structured query, task lifecycle, and evidence packets built "
            "from the session database."
        ),
        "uses_audience": True,
        "evidence_pattern": PACKET_PATTERN,
    },
    "rosout": {
        # True identity, used only in logs and analysis. Participants see an
        # anonymous "System X"; this baseline is not implemented yet, so its
        # button stays greyed out as "coming soon".
        "label": "Explaining autonomy",
        "description": (
            "Explaining-Autonomy style: BGE-M3 semantic retrieval over this "
            "session's /rosout log messages. Ignores answer style."
        ),
        "uses_audience": False,
        "evidence_pattern": RETRIEVED_PATTERN,
    },
    "causal": {
        "label": "Causal / counterfactual",
        "description": (
            "Adapted baseline: a fixed causal log and local counterfactuals "
            "built from recorded task events."
        ),
        "uses_audience": True,
        "evidence_pattern": PACKET_PATTERN,
    },
}

MISSING_API_KEY_DETAIL = "Enter the NVIDIA API key to use this system."
EMBEDDING_OFFLINE_DETAIL = "The local embedding service is offline."

# The chat page shows the three systems as anonymous "System A/B/C" so a
# participant cannot recognise the pipeline behind an answer. Each participant
# gets a stable random letter->system permutation derived from their User ID.
SYSTEM_SLOT_SALT = "qbot-system-blinding-v1"
SYSTEM_SLOTS = ("A", "B", "C")
COMING_SOON_DETAIL = "Coming soon."
UNAVAILABLE_DETAIL = "Currently unavailable."

DEMOGRAPHIC_QUESTIONS = (
    {
        "text": "What year were you born?",
        "kind": "birth_year",
    },
    {
        "text": "What is your gender?",
        "kind": "text",
    },
    {
        "text": (
            "Do you have any engineering background, experience or knowledge?"
        ),
        "kind": "text",
    },
    {
        "text": (
            "I can trust persons and organizations related to development "
            "of robots"
        ),
        "kind": "rating_1_5",
    },
    {
        "text": (
            "Persons and organizations related to development of robots will "
            "consider the needs, thoughts and feelings of their users"
        ),
        "kind": "rating_1_5",
    },
    {"text": "I can trust a robot", "kind": "rating_1_5"},
    {
        "text": "I would feel relaxed talking with a robot",
        "kind": "rating_1_5",
    },
    {
        "text": (
            "If robots had emotions, I would be able to befriend them"
        ),
        "kind": "rating_1_5",
    },
    {
        "text": (
            "I would feel uneasy if I was given a job where I had to use robots"
        ),
        "kind": "rating_1_5",
    },
    {
        "text": "I fear that a robot would not understand my commands",
        "kind": "rating_1_5",
    },
    {"text": "Robots scare me", "kind": "rating_1_5"},
    {
        "text": "I would feel very nervous just being around a robot",
        "kind": "rating_1_5",
    },
    {
        "text": "I don't want a robot to touch me",
        "kind": "rating_1_5",
    },
    {
        "text": (
            "Robots are necessary because they can do jobs that are too hard "
            "or too dangerous for people"
        ),
        "kind": "rating_1_5",
    },
    {"text": "Robots can make life easier", "kind": "rating_1_5"},
    {
        "text": (
            "Assigning routine tasks to robots lets people do more meaningful "
            "tasks"
        ),
        "kind": "rating_1_5",
    },
    {
        "text": "Dangerous tasks should primarily be given to robots",
        "kind": "rating_1_5",
    },
    {
        "text": (
            "Robots are a good thing for society, because they help people"
        ),
        "kind": "rating_1_5",
    },
    {"text": "Robots may make us even lazier", "kind": "rating_1_5"},
    {
        "text": (
            "Widespread use of robots is going to take away jobs from people"
        ),
        "kind": "rating_1_5",
    },
    {
        "text": (
            "I am afraid that robots will encourage less interaction between "
            "humans"
        ),
        "kind": "rating_1_5",
    },
    {
        "text": (
            "Robotics is one of the areas of technology that needs to be "
            "closely monitored"
        ),
        "kind": "rating_1_5",
    },
    {
        "text": (
            "Unregulated use of robotics can lead to societal upheavals"
        ),
        "kind": "rating_1_5",
    },
)


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


def system_label(system):
    entry = SYSTEMS.get(system)
    return entry["label"] if entry else str(system)


def assign_slots(user_id):
    """Map anonymous slots A/B/C to real system ids for one participant.

    The permutation is derived from the User ID, so it is identical across
    reloads, logins, sessions and server restarts, needs no stored randomness,
    and is still evenly distributed across users. An empty User ID (only seen
    before login, when the toggle is not shown) falls back to registry order.
    """

    system_ids = list(SYSTEMS)
    clean_user_id = (user_id or "").strip()

    if clean_user_id:
        digest = hashlib.sha256(
            (SYSTEM_SLOT_SALT + clean_user_id).encode("utf-8")
        ).digest()
        seed = int.from_bytes(digest[:8], "big")
        ordered = random.Random(seed).sample(system_ids, k=len(system_ids))
    else:
        ordered = system_ids

    return list(zip(SYSTEM_SLOTS, ordered))


def rosout_index_path(session_id):
    """Where build_rosout_index.py stores one session's /rosout index."""

    return ROSOUT_INDEX_ROOT / "{}_rosout_embeddings.json".format(session_id)


def rosout_bag_dir(session_id):
    """Where the comparison /rosout recording for one session must live."""

    return ROSOUT_BAG_ROOT / "session_{}".format(session_id) / "rosout"


def demographic_question_payload(question_index):
    if not 0 <= question_index < len(DEMOGRAPHIC_QUESTIONS):
        return None

    question = DEMOGRAPHIC_QUESTIONS[question_index]
    return {
        "index": question_index,
        "number": question_index + 1,
        "total": len(DEMOGRAPHIC_QUESTIONS),
        "text": question["text"],
        "kind": question["kind"],
    }


def validate_demographic_answer(question_index, answer):
    """Return a normalized stored answer or raise ValueError."""

    if not isinstance(question_index, int) or isinstance(question_index, bool):
        raise ValueError("The demographic question number is invalid.")
    if not 0 <= question_index < len(DEMOGRAPHIC_QUESTIONS):
        raise ValueError("The demographic question number is invalid.")

    kind = DEMOGRAPHIC_QUESTIONS[question_index]["kind"]

    if kind == "rating_1_5":
        if isinstance(answer, bool):
            raise ValueError("Select a number from 1 to 5.")
        value = str(answer).strip()
        if value not in {"1", "2", "3", "4", "5"}:
            raise ValueError("Select a number from 1 to 5.")
        return value

    if not isinstance(answer, str):
        answer = ""
    value = answer.strip()
    if not value:
        raise ValueError("Enter a response before continuing.")
    if len(value) > MAX_DEMOGRAPHIC_RESPONSE_LENGTH:
        raise ValueError("The demographic response is too long.")

    if kind == "birth_year":
        current_year = datetime.now(timezone.utc).year
        if not re.fullmatch(r"\d{4}", value):
            raise ValueError("Enter a four-digit birth year.")
        if not 1900 <= int(value) <= current_year:
            raise ValueError(
                "Enter a birth year between 1900 and {}.".format(current_year)
            )

    return value


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

            event_map_name = ""
            if row is not None and not (row["map_name"] or "").strip():
                try:
                    event_row = connection.execute(
                        """
                        SELECT map_name
                        FROM task_events
                        WHERE session_id = ?
                          AND map_name IS NOT NULL
                          AND TRIM(map_name) != ''
                        ORDER BY event_time_ns DESC
                        LIMIT 1
                        """,
                        (str(row["session_id"]),),
                    ).fetchone()
                    if event_row is not None:
                        event_map_name = str(event_row["map_name"] or "")
                except sqlite3.Error:
                    pass
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
            "map_name": row["map_name"] or event_map_name,
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

        candidates = self.list_sessions()

        return candidates[0] if candidates else None

    def list_sessions(self):
        """Return every readable experiment session, newest first."""

        candidates = []
        for database in self.runtime_dir.glob("session_*/robot.db"):
            session = self._read_session(database)
            if session:
                candidates.append(session)

        if not candidates:
            return []

        candidates.sort(
            key=lambda item: (
                item["started_at_ns"],
                item["status"].casefold() == "running",
            ),
            reverse=True,
        )
        return candidates


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
            system TEXT NOT NULL DEFAULT 'proposed',
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

    USER_MAP_SCHEMA = """
        CREATE TABLE IF NOT EXISTS ui_user_maps (
            session_id TEXT NOT NULL,
            map_name TEXT NOT NULL,
            user_id TEXT NOT NULL,
            claimed_at_ns INTEGER NOT NULL,
            claimed_at_iso TEXT NOT NULL,
            PRIMARY KEY (session_id, map_name),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """

    USER_MAP_INDEX = """
        CREATE INDEX IF NOT EXISTS idx_ui_user_maps_user_time
        ON ui_user_maps(user_id, claimed_at_ns)
    """

    PARTICIPANT_SCHEMA = """
        CREATE TABLE IF NOT EXISTS ui_participants (
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            logged_in_at_ns INTEGER NOT NULL,
            logged_in_at_iso TEXT NOT NULL,
            demographics_completed_at_ns INTEGER,
            demographics_completed_at_iso TEXT,
            PRIMARY KEY (session_id, user_id),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """

    DEMOGRAPHIC_SCHEMA = """
        CREATE TABLE IF NOT EXISTS ui_demographic_responses (
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            question_index INTEGER NOT NULL,
            question_text TEXT NOT NULL,
            response_value TEXT NOT NULL,
            response_kind TEXT NOT NULL,
            answered_at_ns INTEGER NOT NULL,
            answered_at_iso TEXT NOT NULL,
            PRIMARY KEY (session_id, user_id, question_index),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """

    SYSTEM_ASSIGNMENT_SCHEMA = """
        CREATE TABLE IF NOT EXISTS ui_system_assignments (
            session_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            slot TEXT NOT NULL,
            system TEXT NOT NULL,
            assigned_at_ns INTEGER NOT NULL,
            assigned_at_iso TEXT NOT NULL,
            PRIMARY KEY (session_id, user_id, slot),
            FOREIGN KEY (session_id) REFERENCES sessions(session_id)
        )
    """

    DEMOGRAPHIC_INDEX = """
        CREATE INDEX IF NOT EXISTS idx_ui_demographics_user_time
        ON ui_demographic_responses(user_id, answered_at_ns)
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

    @staticmethod
    def _has_system_column(connection):
        try:
            rows = connection.execute(
                "PRAGMA table_info(ui_chat_interactions)"
            ).fetchall()
        except sqlite3.Error:
            return False
        return any(str(row[1]) == "system" for row in rows)

    @staticmethod
    def _ensure_system_column(connection):
        """Add the additive system column to a table created before it."""

        if ChatStore._has_system_column(connection):
            return
        connection.execute(
            "ALTER TABLE ui_chat_interactions "
            "ADD COLUMN system TEXT NOT NULL DEFAULT '{}'".format(DEFAULT_SYSTEM)
        )

    def begin(
        self,
        session,
        request_id,
        user_id,
        question,
        audience,
        system=DEFAULT_SYSTEM,
    ):
        asked_at_ns, asked_at_iso = utc_now()

        def operation(connection):
            connection.execute(self.SCHEMA)
            connection.execute(self.INDEX)
            self._ensure_system_column(connection)
            connection.execute(
                """
                INSERT INTO ui_chat_interactions (
                    request_id,
                    session_id,
                    user_id,
                    question,
                    status,
                    audience,
                    system,
                    asked_at_ns,
                    asked_at_iso
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    request_id,
                    session["session_id"],
                    user_id,
                    question,
                    "processing",
                    audience,
                    system,
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

    @staticmethod
    def history(sessions, user_id, system=None, limit=MAX_HISTORY_ITEMS):
        """Read one user's completed UI chats across experiment sessions.

        Databases written before the system column existed hold only proposed
        system answers, so they report their rows as such.
        """

        interactions = []
        wanted_system = (system or "").strip()

        for session in sessions:
            connection = None
            rows = []
            try:
                database_uri = "file:{}?mode=ro".format(session["database"])
                connection = sqlite3.connect(
                    database_uri, timeout=2, uri=True
                )
                connection.row_factory = sqlite3.Row

                has_system = ChatStore._has_system_column(connection)
                if (
                    wanted_system
                    and not has_system
                    and wanted_system != DEFAULT_SYSTEM
                ):
                    continue

                parameters = [user_id]
                if wanted_system and has_system:
                    system_filter = "AND system = ?"
                    parameters.append(wanted_system)
                else:
                    system_filter = ""
                parameters.append(int(limit))

                rows = connection.execute(
                    """
                    SELECT request_id, session_id, question, robot_response,
                           status, audience, asked_at_ns, asked_at_iso,
                           answered_at_iso, response_time_ms, {}
                    FROM ui_chat_interactions
                    WHERE user_id = ?
                      AND robot_response != ''
                      {}
                    ORDER BY asked_at_ns DESC
                    LIMIT ?
                    """.format(
                        "system"
                        if has_system
                        else "'{}' AS system".format(DEFAULT_SYSTEM),
                        system_filter,
                    ),
                    parameters,
                ).fetchall()
            except (OSError, sqlite3.Error):
                continue
            finally:
                if connection is not None:
                    connection.close()

            for row in rows:
                interactions.append(
                    {
                        "request_id": str(row["request_id"]),
                        "session_id": str(row["session_id"]),
                        "question": str(row["question"]),
                        "robot_response": str(row["robot_response"]),
                        "status": str(row["status"]),
                        "audience": str(row["audience"]),
                        "system": str(row["system"] or DEFAULT_SYSTEM),
                        "asked_at_ns": int(row["asked_at_ns"] or 0),
                        "asked_at_iso": str(row["asked_at_iso"] or ""),
                        "answered_at_iso": str(row["answered_at_iso"] or ""),
                        "response_time_ms": int(row["response_time_ms"] or 0),
                    }
                )

        interactions.sort(key=lambda item: item["asked_at_ns"], reverse=True)
        interactions = interactions[: int(limit)]
        interactions.reverse()
        return interactions

    def register_participant(self, session, user_id):
        logged_in_at_ns, logged_in_at_iso = utc_now()

        def operation(connection):
            connection.execute(self.PARTICIPANT_SCHEMA)
            connection.execute(self.DEMOGRAPHIC_SCHEMA)
            connection.execute(self.DEMOGRAPHIC_INDEX)
            connection.execute(
                """
                INSERT OR IGNORE INTO ui_participants (
                    session_id,
                    user_id,
                    logged_in_at_ns,
                    logged_in_at_iso
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    session["session_id"],
                    user_id,
                    logged_in_at_ns,
                    logged_in_at_iso,
                ),
            )

        self._write(session["database"], operation)

    def record_system_assignment(self, session, user_id):
        """Persist this participant's slot->system map for later de-anonymizing.

        Idempotent: the deterministic assignment is written once per user with
        INSERT OR IGNORE, so repeated logins do not duplicate or change it.
        """

        assigned_at_ns, assigned_at_iso = utc_now()
        assignment = assign_slots(user_id)

        def operation(connection):
            connection.execute(self.SYSTEM_ASSIGNMENT_SCHEMA)
            for slot, system in assignment:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO ui_system_assignments (
                        session_id,
                        user_id,
                        slot,
                        system,
                        assigned_at_ns,
                        assigned_at_iso
                    )
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session["session_id"],
                        user_id,
                        slot,
                        system,
                        assigned_at_ns,
                        assigned_at_iso,
                    ),
                )

        self._write(session["database"], operation)

    @staticmethod
    def demographic_progress(session, user_id):
        connection = None
        answered_indexes = set()
        try:
            database_uri = "file:{}?mode=ro".format(session["database"])
            connection = sqlite3.connect(database_uri, timeout=2, uri=True)
            rows = connection.execute(
                """
                SELECT question_index
                FROM ui_demographic_responses
                WHERE session_id = ? AND user_id = ?
                """,
                (session["session_id"], user_id),
            ).fetchall()
            answered_indexes = {int(row[0]) for row in rows}
        except (OSError, sqlite3.Error):
            answered_indexes = set()
        finally:
            if connection is not None:
                connection.close()

        next_index = next(
            (
                index
                for index in range(len(DEMOGRAPHIC_QUESTIONS))
                if index not in answered_indexes
            ),
            None,
        )
        return {
            "answered_count": len(answered_indexes),
            "completed": next_index is None,
            "next_question_index": next_index,
        }

    def save_demographic_answer(
        self,
        session,
        user_id,
        question_index,
        response_value,
    ):
        answered_at_ns, answered_at_iso = utc_now()
        question = DEMOGRAPHIC_QUESTIONS[question_index]
        completed = question_index == len(DEMOGRAPHIC_QUESTIONS) - 1

        def operation(connection):
            connection.execute(self.PARTICIPANT_SCHEMA)
            connection.execute(self.DEMOGRAPHIC_SCHEMA)
            connection.execute(self.DEMOGRAPHIC_INDEX)
            connection.execute(
                """
                INSERT OR REPLACE INTO ui_demographic_responses (
                    session_id,
                    user_id,
                    question_index,
                    question_text,
                    response_value,
                    response_kind,
                    answered_at_ns,
                    answered_at_iso
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session["session_id"],
                    user_id,
                    question_index,
                    question["text"],
                    response_value,
                    question["kind"],
                    answered_at_ns,
                    answered_at_iso,
                ),
            )
            if completed:
                connection.execute(
                    """
                    UPDATE ui_participants
                    SET demographics_completed_at_ns = ?,
                        demographics_completed_at_iso = ?
                    WHERE session_id = ? AND user_id = ?
                    """,
                    (
                        answered_at_ns,
                        answered_at_iso,
                        session["session_id"],
                        user_id,
                    ),
                )

        self._write(session["database"], operation)

    def claim_map(self, session, user_id, map_name):
        """Assign a newly detected map once; never transfer its ownership."""

        claimed_at_ns, claimed_at_iso = utc_now()
        inserted = [False]

        def operation(connection):
            connection.execute(self.USER_MAP_SCHEMA)
            connection.execute(self.USER_MAP_INDEX)
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO ui_user_maps (
                    session_id,
                    map_name,
                    user_id,
                    claimed_at_ns,
                    claimed_at_iso
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    session["session_id"],
                    map_name,
                    user_id,
                    claimed_at_ns,
                    claimed_at_iso,
                ),
            )
            inserted[0] = cursor.rowcount == 1

        self._write(session["database"], operation)
        return inserted[0]

    @staticmethod
    def user_maps(sessions, user_id):
        """Return maps owned by one user across readable experiment databases."""

        maps = []
        for session in sessions:
            connection = None
            try:
                database_uri = "file:{}?mode=ro".format(session["database"])
                connection = sqlite3.connect(database_uri, timeout=2, uri=True)
                rows = connection.execute(
                    """
                    SELECT session_id, map_name, claimed_at_ns, claimed_at_iso
                    FROM ui_user_maps
                    WHERE user_id = ?
                    ORDER BY claimed_at_ns DESC
                    """,
                    (user_id,),
                ).fetchall()
            except (OSError, sqlite3.Error):
                continue
            finally:
                if connection is not None:
                    connection.close()

            for row in rows:
                maps.append(
                    {
                        "session_id": str(row[0]),
                        "map_name": str(row[1]),
                        "claimed_at_ns": int(row[2] or 0),
                        "claimed_at_iso": str(row[3] or ""),
                    }
                )

        maps.sort(key=lambda item: item["claimed_at_ns"], reverse=True)
        return maps

    @staticmethod
    def map_owner(sessions, map_name):
        earliest_owner = None
        earliest_time = None

        for session in sessions:
            connection = None
            try:
                database_uri = "file:{}?mode=ro".format(session["database"])
                connection = sqlite3.connect(database_uri, timeout=2, uri=True)
                row = connection.execute(
                    """
                    SELECT user_id, claimed_at_ns
                    FROM ui_user_maps
                    WHERE map_name = ?
                    ORDER BY claimed_at_ns ASC
                    LIMIT 1
                    """,
                    (map_name,),
                ).fetchone()
            except (OSError, sqlite3.Error):
                continue
            finally:
                if connection is not None:
                    connection.close()

            if row is not None:
                claimed_at_ns = int(row[1] or 0)
                if earliest_time is None or claimed_at_ns < earliest_time:
                    earliest_owner = str(row[0])
                    earliest_time = claimed_at_ns

        return earliest_owner

    @classmethod
    def latest_map_for_user(cls, sessions, user_id, preferred_map=""):
        maps = cls.user_maps(sessions, user_id)
        if preferred_map and any(
            item["map_name"] == preferred_map for item in maps
        ):
            return preferred_map
        return maps[0]["map_name"] if maps else ""


class RagRunner:
    """Invoke the team's unchanged RAG command or a comparison baseline."""

    def __init__(self, script=ASK_ROBOT_SCRIPT, timeout=240):
        self.script = Path(script)
        self.timeout = timeout

    @staticmethod
    def _last_nonempty_line(output):
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        return lines[-1] if lines else ""

    def _command(self, system, question, session_id, audience):
        """Build the argv for one explanation system.

        The comparison baselines are reached through the unchanged
        run_comparison.sh dispatcher so this UI never becomes a second
        definition of how they are launched.
        """

        if system == "rosout":
            return [
                "bash",
                str(COMPARISON_SCRIPT),
                "rosout",
                "--session-id",
                session_id,
                "--question",
                question,
            ]

        if system == "causal":
            return [
                "bash",
                str(COMPARISON_SCRIPT),
                "causal",
                "--session-id",
                session_id,
                "--role",
                "engineer" if audience == "developer" else "user",
                "--question",
                question,
            ]

        return [
            sys.executable,
            str(RAG_COMPAT_SCRIPT),
            "--core-script",
            str(self.script),
            "--",
            "--session-id",
            session_id,
            "--audience",
            audience,
            "--question",
            question,
        ]

    def answer(
        self,
        question,
        session_id,
        audience,
        api_key,
        system=DEFAULT_SYSTEM,
    ):
        if system not in SYSTEMS:
            raise RagFailure(
                "That explanation system is not available.",
                "Unknown explanation system: " + str(system),
            )

        required_script = (
            self.script if system == DEFAULT_SYSTEM else COMPARISON_SCRIPT
        )
        if not Path(required_script).is_file():
            raise RagFailure(
                "This explanation system is unavailable.",
                "{} command missing: {}".format(
                    system_label(system), required_script
                ),
            )

        if not api_key:
            raise RagFailure(
                "Enter the NVIDIA API key in the QBot UI before asking a "
                "question.",
                "NVIDIA API key is not configured in the UI server memory.",
            )

        command = self._command(system, question, session_id, audience)

        child_environment = os.environ.copy()
        child_environment["NVIDIA_API_KEY"] = api_key

        try:
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
                    env=child_environment,
                    stdin=subprocess.DEVNULL,
                )
            finally:
                child_environment.pop("NVIDIA_API_KEY", None)
        except subprocess.TimeoutExpired as exc:
            raise RagFailure(
                "The QBot assistant took too long to answer. Please try again.",
                "{} timed out after {} seconds".format(
                    system_label(system), self.timeout
                ),
            ) from exc
        except OSError as exc:
            raise RagFailure(
                "This explanation system could not be started.",
                "{} process error: {}".format(system_label(system), exc),
            ) from exc

        if completed.returncode != 0:
            details = (
                completed.stderr.strip()
                or completed.stdout.strip()
                or "{} exited with status {}".format(
                    system_label(system), completed.returncode
                )
            )
            details = details.replace(api_key, "[REDACTED]")
            raise RagFailure(
                "This explanation system could not answer this question.",
                details,
            )

        output = completed.stdout
        packet_match = SYSTEMS[system]["evidence_pattern"].search(output)
        packet_count = int(packet_match.group(1)) if packet_match else 0
        used_llm = ANSWER_MARKER in output

        if used_llm:
            answer = output.rsplit(ANSWER_MARKER, 1)[1].strip()
        else:
            answer = self._last_nonempty_line(output)

        if not answer:
            raise RagFailure(
                "This explanation system returned an empty answer.",
                "{} completed without answer text".format(system_label(system)),
            )

        return {
            "answer": answer,
            "model": NVIDIA_MODEL,
            "packet_count": packet_count,
            "used_llm": used_llm,
            "system": system,
        }


class SystemPreparer:
    """Build the comparison /rosout index in the background, one at a time.

    Whether a session is prepared is decided by the index file on disk, so a
    restarted UI server always reports the truth.  The in-memory state only
    tracks a build that is running now and the reason the last one failed.
    """

    def __init__(self, script=COMPARISON_SCRIPT, timeout=3600):
        self.script = Path(script)
        self.timeout = timeout
        self._lock = threading.Lock()
        self._running_session = ""
        self._progress = None
        self._failures = {}

    @staticmethod
    def _idle_state():
        return {"state": "idle", "detail": "", "progress": None}

    def state(self, session_id):
        session_id = session_id or ""

        if session_id and rosout_index_path(session_id).is_file():
            return {"state": "ready", "detail": "", "progress": None}

        with self._lock:
            running_session = self._running_session
            progress = dict(self._progress) if self._progress else None
            failure = self._failures.get(session_id, "")

        if running_session and running_session == session_id:
            return {
                "state": "preparing",
                "detail": "Building the /rosout index for this session.",
                "progress": progress,
            }
        if running_session:
            return {
                "state": "busy",
                "detail": "Another /rosout index is being built right now.",
                "progress": None,
            }
        if failure:
            return {"state": "failed", "detail": failure, "progress": None}
        return self._idle_state()

    def start(self, session_id):
        """Begin a build if one is needed and none is already running."""

        session_id = session_id or ""
        if not session_id:
            return {
                "state": "failed",
                "detail": "No QBot experiment session was found.",
                "progress": None,
            }
        if rosout_index_path(session_id).is_file():
            return self.state(session_id)

        with self._lock:
            if self._running_session:
                should_start = False
            else:
                should_start = True
                self._running_session = session_id
                self._progress = None
                self._failures.pop(session_id, None)

        if should_start:
            worker = threading.Thread(
                target=self._build,
                args=(session_id,),
                name="rosout-index-build",
                daemon=True,
            )
            worker.start()

        return self.state(session_id)

    def _record_progress(self, line):
        total_match = ROSOUT_TOTAL_PATTERN.search(line)
        if total_match:
            with self._lock:
                self._progress = {"done": 0, "total": int(total_match.group(1))}
            return

        progress_match = ROSOUT_PROGRESS_PATTERN.search(line)
        if progress_match:
            with self._lock:
                self._progress = {
                    "done": int(progress_match.group(1)),
                    "total": int(progress_match.group(2)),
                }

    def _build(self, session_id):
        command = [
            "bash",
            str(self.script),
            "rosout-build",
            "--session-id",
            session_id,
        ]

        # The index build only needs the local embedding service.  Never hand
        # the NVIDIA API key to it.
        child_environment = os.environ.copy()
        child_environment.pop("NVIDIA_API_KEY", None)

        detail = ""
        recent_output = []
        process = None
        timed_out = []
        watchdog = None

        try:
            process = subprocess.Popen(
                command,
                cwd=str(REPO_DIR),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=child_environment,
            )

            def stop_after_timeout():
                timed_out.append(True)
                try:
                    process.kill()
                except OSError:
                    pass

            watchdog = threading.Timer(self.timeout, stop_after_timeout)
            watchdog.daemon = True
            watchdog.start()

            for line in process.stdout:
                line = line.strip()
                if not line:
                    continue
                recent_output.append(line)
                del recent_output[:-20]
                self._record_progress(line)

            process.stdout.close()
            returncode = process.wait()

            if timed_out:
                detail = "The /rosout index build timed out after {} seconds.".format(
                    self.timeout
                )
            elif returncode != 0:
                detail = "\n".join(recent_output) or (
                    "rosout-build exited with status {}".format(returncode)
                )
        except OSError as exc:
            detail = str(exc)
        finally:
            if watchdog is not None:
                watchdog.cancel()
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                    process.wait()
                except OSError:
                    pass

        if not detail and not rosout_index_path(session_id).is_file():
            detail = "\n".join(recent_output) or (
                "The /rosout index file was not created."
            )

        with self._lock:
            self._running_session = ""
            self._progress = None
            if detail:
                self._failures[session_id] = detail[-MAX_ERROR_LENGTH:]
            else:
                self._failures.pop(session_id, None)


class MapStatusLocator:
    """Resolve the current/newest experiment map without changing team data."""

    def __init__(
        self,
        maps_dir=MAPS_DIR,
        navigation_status_url=NAVIGATION_STATUS_URL,
        mapping_status_url=MAPPING_STATUS_URL,
        request_timeout=0.75,
    ):
        self.maps_dir = Path(maps_dir)
        self.navigation_status_url = navigation_status_url
        self.mapping_status_url = mapping_status_url
        self.request_timeout = request_timeout

    @staticmethod
    def _clean_name(value):
        if not isinstance(value, str) or not value.strip():
            return ""
        return Path(value.strip()).stem

    def _read_status(self, url):
        try:
            with urlopen(url, timeout=self.request_timeout) as response:
                if not 200 <= response.status < 300:
                    return {}
                payload = json.loads(response.read().decode("utf-8"))
                return payload if isinstance(payload, dict) else {}
        except (OSError, URLError, ValueError, json.JSONDecodeError):
            return {}

    def _newest_session_map(self, session):
        if not self.maps_dir.is_dir() or session is None:
            return ""

        started_at_ns = int(session.get("started_at_ns") or 0)
        candidates = []
        try:
            for yaml_path in self.maps_dir.glob("*.yaml"):
                pgm_path = yaml_path.with_suffix(".pgm")
                if not pgm_path.is_file():
                    continue
                modified_ns = max(
                    yaml_path.stat().st_mtime_ns,
                    pgm_path.stat().st_mtime_ns,
                )
                if modified_ns >= started_at_ns:
                    candidates.append((modified_ns, yaml_path.stem))
        except OSError:
            return ""

        return max(candidates)[1] if candidates else ""

    def _created_during_session(self, map_name, session):
        if not map_name or session is None:
            return False

        started_at_ns = int(session.get("started_at_ns") or 0)
        paths = [
            self.maps_dir / (map_name + ".yaml"),
            self.maps_dir / (map_name + ".pgm"),
        ]
        try:
            modified_times = [
                path.stat().st_mtime_ns for path in paths if path.is_file()
            ]
        except OSError:
            return False
        return bool(modified_times and max(modified_times) >= started_at_ns)

    def locate_details(self, session):
        """Return a map name and whether this session created that map."""

        navigation = self._read_status(self.navigation_status_url)
        active_map = self._clean_name(navigation.get("active_map"))
        if active_map:
            return {
                "name": active_map,
                "claimable": self._created_during_session(active_map, session),
            }

        mapping = self._read_status(self.mapping_status_url)
        for key in ("reserved_map", "saved_map"):
            mapping_name = self._clean_name(mapping.get(key))
            if mapping_name:
                return {"name": mapping_name, "claimable": True}

        newest_map = self._newest_session_map(session)
        if newest_map:
            return {"name": newest_map, "claimable": True}

        recorded_map = self._clean_name((session or {}).get("map_name"))
        return {
            "name": recorded_map,
            "claimable": self._created_during_session(recorded_map, session),
        }

    def locate(self, session):
        return self.locate_details(session)["name"]


class ChatApplication:
    def __init__(
        self,
        locator,
        store,
        runner,
        max_parallel_requests=2,
        initial_api_key="",
        map_locator=None,
        preparer=None,
    ):
        self.locator = locator
        self.store = store
        self.runner = runner
        self.map_locator = map_locator or MapStatusLocator()
        self.preparer = preparer or SystemPreparer()
        self.request_slots = threading.BoundedSemaphore(max_parallel_requests)
        self._api_key_lock = threading.Lock()
        self._api_key = initial_api_key.strip()

    def set_api_key(self, api_key):
        with self._api_key_lock:
            self._api_key = api_key

    def clear_api_key(self):
        with self._api_key_lock:
            self._api_key = ""

    def get_api_key(self):
        with self._api_key_lock:
            return self._api_key

    def has_api_key(self):
        with self._api_key_lock:
            return bool(self._api_key)

    @staticmethod
    def embedding_ready():
        try:
            with urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as response:
                return 200 <= response.status < 300
        except (OSError, URLError, ValueError):
            return False

    @staticmethod
    def _table_exists(database, table):
        connection = None
        try:
            connection = sqlite3.connect(
                "file:{}?mode=ro".format(database), timeout=2, uri=True
            )
            row = connection.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            return row is not None
        except (OSError, sqlite3.Error):
            return False
        finally:
            if connection is not None:
                connection.close()

    def _system_state(
        self, system, session, api_key_configured, embedding_ready
    ):
        """Return (state, detail, progress) for one explanation system."""

        if session is None:
            return "unavailable", "No QBot experiment session was found.", None

        session_id = session["session_id"]

        if system == DEFAULT_SYSTEM:
            if not ASK_ROBOT_SCRIPT.is_file():
                return (
                    "unavailable",
                    "ask_robot.py is missing from this checkout.",
                    None,
                )
            if not embedding_ready:
                return "unavailable", EMBEDDING_OFFLINE_DETAIL, None
            if not api_key_configured:
                return "blocked", MISSING_API_KEY_DETAIL, None
            return "ready", "", None

        if not COMPARISON_SCRIPT.is_file():
            return (
                "unavailable",
                "comparison_experiments/run_comparison.sh is missing.",
                None,
            )

        if system == "causal":
            if not self._table_exists(session["database"], "task_events"):
                return (
                    "unavailable",
                    "This session's robot.db has no task_events table.",
                    None,
                )
            if not api_key_configured:
                return "blocked", MISSING_API_KEY_DETAIL, None
            return "ready", "", None

        build = self.preparer.state(session_id)

        if build["state"] == "preparing":
            return "preparing", build["detail"], build["progress"]

        if rosout_index_path(session_id).is_file():
            if not embedding_ready:
                return "unavailable", EMBEDDING_OFFLINE_DETAIL, None
            if not api_key_configured:
                return "blocked", MISSING_API_KEY_DETAIL, None
            return "ready", "", None

        if not rosout_bag_dir(session_id).is_dir():
            return (
                "unavailable",
                "No /rosout recording was made for this session.",
                None,
            )
        if not embedding_ready:
            return "unavailable", EMBEDDING_OFFLINE_DETAIL, None
        if build["state"] == "failed":
            return "failed", build["detail"], None
        if build["state"] == "busy":
            return "needs_preparation", build["detail"], None

        return (
            "needs_preparation",
            "Select this system to build its /rosout index.",
            None,
        )

    @staticmethod
    def _participant_detail(system, state, detail):
        """Anonymized status text for the blind chat page.

        The real reasons (missing /rosout bag, no task_events table) would
        reveal which pipeline a slot is, so participants see generic text.
        """

        if state == "ready":
            return ""
        if state == "blocked":
            return MISSING_API_KEY_DETAIL
        if state == "preparing":
            return "Preparing…"
        if system == "rosout":
            return COMING_SOON_DETAIL
        return UNAVAILABLE_DETAIL

    def system_states(
        self, session, api_key_configured, embedding_ready, user_id=""
    ):
        """Per-participant, anonymized readiness for the three systems.

        Entries are returned in fixed slot order (A, B, C); the real system
        behind each slot is this participant's stable permutation. The real
        ``id`` is kept for the client to send back, but the participant-facing
        ``label`` and ``detail`` never name the pipeline.
        """

        states = []
        for slot, system in assign_slots(user_id):
            entry = SYSTEMS[system]
            state, _reason, progress = self._system_state(
                system, session, api_key_configured, embedding_ready
            )
            states.append(
                {
                    "id": system,
                    "slot": slot,
                    "label": "System {}".format(slot),
                    "description": "",
                    "uses_audience": entry["uses_audience"],
                    "state": state,
                    "ready": state == "ready",
                    "actionable": state == "ready",
                    "detail": self._participant_detail(system, state, _reason),
                    "progress": progress,
                }
            )
        return states

    def system_state(self, system, session):
        """Readiness for one system, resolved on demand (keyed by real id).

        Used by the chat readiness check, which knows the real id. Readiness is
        order-independent, so the anonymized slot fields are irrelevant here.
        """

        for state in self.system_states(
            session, self.has_api_key(), self.embedding_ready()
        ):
            if state["id"] == system:
                return state
        return None

    def status(self, user_id=""):
        session = self.locator.locate()
        api_key_configured = self.has_api_key()
        embedding_ready = self.embedding_ready()
        rag_command_ready = ASK_ROBOT_SCRIPT.is_file()
        session_ready = session is not None
        map_name = ""

        if session and user_id:
            sessions = self.locator.list_sessions()
            detected_map = self.map_locator.locate_details(session)
            detected_name = detected_map["name"]

            if detected_name and detected_map["claimable"]:
                owner = self.store.map_owner(sessions, detected_name)
                if owner is None:
                    try:
                        self.store.claim_map(session, user_id, detected_name)
                    except Exception as exc:
                        print(
                            "Map ownership storage failed for {}: {}".format(
                                detected_name, exc
                            )
                        )

            map_name = self.store.latest_map_for_user(
                sessions,
                user_id,
                preferred_map=detected_name,
            )

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
            "map_name": map_name,
            "stored_exchange_count": self.store.count(session) if session else 0,
            "model": NVIDIA_MODEL,
            "systems": self.system_states(
                session, api_key_configured, embedding_ready, user_id=user_id
            ),
            "default_system": DEFAULT_SYSTEM,
        }

    def history(self, user_id, system=None):
        return self.store.history(
            self.locator.list_sessions(), user_id, system=system
        )


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

    def _is_loopback_client(self):
        try:
            address = ipaddress.ip_address(self.client_address[0])
            if address.is_loopback:
                return True
            return bool(
                getattr(address, "ipv4_mapped", None)
                and address.ipv4_mapped.is_loopback
            )
        except (ValueError, IndexError):
            return False

    def _read_json_payload(self):
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        if content_length <= 0 or content_length > MAX_REQUEST_BYTES:
            self._send_json(400, {"error": "Request body is empty or too large."})
            return None

        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"error": "Request body must be valid JSON."})
            return None

        if not isinstance(payload, dict):
            self._send_json(400, {"error": "JSON body must be an object."})
            return None

        return payload

    def do_GET(self):
        path = urlsplit(self.path).path

        if path == "/api/status":
            status = self.server.application.status()
            status["api_key_entry_allowed"] = self._is_loopback_client()
            self._send_json(200, status)
            return

        if path == "/favicon.ico":
            self.send_response(204)
            self._common_headers()
            self.end_headers()
            return

        self._serve_static(path)

    def do_POST(self):
        path = urlsplit(self.path).path
        if path == "/api/login":
            self._handle_login()
            return

        if path == "/api/demographics":
            self._handle_demographics()
            return

        if path == "/api/status":
            self._handle_status()
            return

        if path == "/api/api-key":
            self._handle_api_key()
            return

        if path == "/api/history":
            self._handle_history()
            return

        if path == "/api/system/prepare":
            self._handle_system_prepare()
            return

        if path != "/api/chat":
            self._send_json(404, {"error": "Not found."})
            return

        payload = self._read_json_payload()
        if payload is None:
            return

        user_id = payload.get("user_id", "")
        question = payload.get("question", "")
        audience = payload.get("audience", "user")
        system = payload.get("system", DEFAULT_SYSTEM)

        if not isinstance(user_id, str):
            user_id = ""
        if not isinstance(question, str):
            question = ""
        if not isinstance(audience, str):
            audience = ""
        if not isinstance(system, str):
            system = ""

        user_id = user_id.strip()
        question = question.strip()
        audience = audience.strip().casefold()
        system = system.strip().casefold() or DEFAULT_SYSTEM

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
        elif system not in SYSTEMS:
            validation_error = "That explanation system does not exist."

        if validation_error:
            self._send_json(400, {"error": validation_error})
            return

        api_key = self.server.application.get_api_key()
        if not api_key:
            self._send_json(
                428,
                {
                    "error": (
                        "Enter the NVIDIA API key in the QBot UI before "
                        "asking a question."
                    )
                },
            )
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

        demographic_progress = (
            self.server.application.store.demographic_progress(session, user_id)
        )
        if not demographic_progress["completed"]:
            self._send_json(
                403,
                {
                    "error": (
                        "Complete the demographic questionnaire before "
                        "using the QBot assistant."
                    )
                },
            )
            return

        system_state = self.server.application.system_state(system, session)
        if system_state is None or not system_state["ready"]:
            detail = (system_state or {}).get("detail", "")
            slot = dict(
                (real, slot_letter)
                for slot_letter, real in assign_slots(user_id)
            ).get(system, "?")
            self._send_json(
                409,
                {
                    "error": (
                        "System {} is not ready to answer questions. {}".format(
                            slot, detail
                        ).strip()
                    ),
                    "system": system_state,
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
                    session, request_id, user_id, question, audience, system
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
                    question,
                    session["session_id"],
                    audience,
                    api_key,
                    system=system,
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
                    "system": system,
                    "request_id": request_id,
                    "used_llm": used_llm,
                    "retrieval_packet_count": packet_count,
                    "response_time_ms": elapsed_ms,
                    "error": "" if http_status == 200 else answer,
                },
            )
        finally:
            api_key = None
            self.server.application.request_slots.release()

    def _handle_api_key(self):
        if not self._is_loopback_client():
            self._send_json(
                403,
                {
                    "error": (
                        "For security, enter the API key from a browser opened "
                        "at http://localhost on the QBot itself."
                    )
                },
            )
            return

        payload = self._read_json_payload()
        if payload is None:
            return

        api_key = payload.get("api_key", "")
        if not isinstance(api_key, str):
            api_key = ""
        api_key = api_key.strip()

        if not api_key:
            self._send_json(400, {"error": "NVIDIA API key is required."})
            return
        if len(api_key) > MAX_API_KEY_LENGTH:
            self._send_json(400, {"error": "NVIDIA API key is too long."})
            return
        if any(character.isspace() for character in api_key):
            self._send_json(
                400, {"error": "NVIDIA API key cannot contain spaces."}
            )
            return

        self.server.application.set_api_key(api_key)
        payload.clear()
        api_key = None
        self._send_json(
            200,
            {
                "configured": True,
                "message": "API key is ready in memory for this UI session.",
            },
        )

    def _handle_status(self):
        payload = self._read_json_payload()
        if payload is None:
            return

        user_id = payload.get("user_id", "")
        if not isinstance(user_id, str):
            user_id = ""
        user_id = user_id.strip()

        if len(user_id) > MAX_USER_ID_LENGTH:
            self._send_json(400, {"error": "User ID is too long."})
            return
        if user_id and has_control_characters(user_id):
            self._send_json(
                400, {"error": "User ID contains invalid characters."}
            )
            return

        status = self.server.application.status(user_id=user_id)
        status["api_key_entry_allowed"] = self._is_loopback_client()
        self._send_json(200, status)

    def _handle_login(self):
        payload = self._read_json_payload()
        if payload is None:
            return

        user_id = payload.get("user_id", "")
        if not isinstance(user_id, str):
            user_id = ""
        user_id = user_id.strip()

        if not user_id:
            self._send_json(400, {"error": "User ID is required."})
            return
        if len(user_id) > MAX_USER_ID_LENGTH:
            self._send_json(400, {"error": "User ID is too long."})
            return
        if has_control_characters(user_id):
            self._send_json(
                400, {"error": "User ID contains invalid characters."}
            )
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

        try:
            self.server.application.store.register_participant(session, user_id)
            progress = self.server.application.store.demographic_progress(
                session, user_id
            )
        except Exception as exc:
            print("Participant login storage failed: {}".format(exc))
            self._send_json(
                503,
                {"error": "The participant login could not be saved."},
            )
            return

        # Best-effort: the slot->system map is deterministic and recomputable,
        # so a storage hiccup here must not block the participant from logging in.
        try:
            self.server.application.store.record_system_assignment(
                session, user_id
            )
        except Exception as exc:
            print("System assignment storage failed: {}".format(exc))

        next_index = progress["next_question_index"]
        self._send_json(
            200,
            {
                "user_id": user_id,
                "session_id": session["session_id"],
                "completed": progress["completed"],
                "answered_count": progress["answered_count"],
                "question": (
                    demographic_question_payload(next_index)
                    if next_index is not None
                    else None
                ),
            },
        )

    def _handle_demographics(self):
        payload = self._read_json_payload()
        if payload is None:
            return

        user_id = payload.get("user_id", "")
        question_index = payload.get("question_index")
        answer = payload.get("answer")

        if not isinstance(user_id, str):
            user_id = ""
        user_id = user_id.strip()

        if not user_id or len(user_id) > MAX_USER_ID_LENGTH:
            self._send_json(400, {"error": "A valid User ID is required."})
            return
        if has_control_characters(user_id):
            self._send_json(
                400, {"error": "User ID contains invalid characters."}
            )
            return

        try:
            normalized_answer = validate_demographic_answer(
                question_index, answer
            )
        except ValueError as exc:
            self._send_json(400, {"error": str(exc)})
            return

        session = self.server.application.locator.locate()
        if session is None:
            self._send_json(
                503,
                {"error": "No active QBot experiment database was found."},
            )
            return

        try:
            self.server.application.store.register_participant(session, user_id)
            progress = self.server.application.store.demographic_progress(
                session, user_id
            )
            expected_index = progress["next_question_index"]
            if progress["completed"]:
                self._send_json(
                    200,
                    {
                        "user_id": user_id,
                        "completed": True,
                        "answered_count": len(DEMOGRAPHIC_QUESTIONS),
                        "question": None,
                    },
                )
                return
            if question_index != expected_index:
                self._send_json(
                    409,
                    {
                        "error": "Submit the currently displayed question first.",
                        "question": demographic_question_payload(expected_index),
                    },
                )
                return

            self.server.application.store.save_demographic_answer(
                session,
                user_id,
                question_index,
                normalized_answer,
            )
            progress = self.server.application.store.demographic_progress(
                session, user_id
            )
        except Exception as exc:
            print("Demographic response storage failed: {}".format(exc))
            self._send_json(
                503,
                {"error": "The demographic response could not be saved."},
            )
            return

        next_index = progress["next_question_index"]
        self._send_json(
            200,
            {
                "user_id": user_id,
                "completed": progress["completed"],
                "answered_count": progress["answered_count"],
                "question": (
                    demographic_question_payload(next_index)
                    if next_index is not None
                    else None
                ),
            },
        )

    def _handle_system_prepare(self):
        payload = self._read_json_payload()
        if payload is None:
            return

        system = payload.get("system", "")
        if not isinstance(system, str):
            system = ""
        system = system.strip().casefold()

        if system not in SYSTEMS:
            self._send_json(
                400, {"error": "That explanation system does not exist."}
            )
            return

        if system != "rosout":
            self._send_json(
                400,
                {"error": "This explanation system does not need preparation."},
            )
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

        session_id = session["session_id"]
        if not rosout_bag_dir(session_id).is_dir():
            self._send_json(
                409,
                {
                    "error": (
                        "No /rosout recording was made for this session, so "
                        "this baseline cannot be prepared."
                    )
                },
            )
            return

        self.server.application.preparer.start(session_id)
        self._send_json(
            200,
            {"system": self.server.application.system_state(system, session)},
        )

    def _handle_history(self):
        payload = self._read_json_payload()
        if payload is None:
            return

        user_id = payload.get("user_id", "")
        if not isinstance(user_id, str):
            user_id = ""
        user_id = user_id.strip()

        system = payload.get("system", "")
        if not isinstance(system, str):
            system = ""
        system = system.strip().casefold()

        if not user_id:
            self._send_json(400, {"error": "User ID is required."})
            return
        if len(user_id) > MAX_USER_ID_LENGTH:
            self._send_json(400, {"error": "User ID is too long."})
            return
        if has_control_characters(user_id):
            self._send_json(
                400, {"error": "User ID contains invalid characters."}
            )
            return
        if system and system not in SYSTEMS:
            self._send_json(
                400, {"error": "That explanation system does not exist."}
            )
            return

        interactions = self.server.application.history(
            user_id, system=system or None
        )
        self._send_json(
            200,
            {
                "user_id": user_id,
                "system": system,
                "count": len(interactions),
                "interactions": interactions,
            },
        )

    def do_DELETE(self):
        path = urlsplit(self.path).path
        if path != "/api/api-key":
            self._send_json(404, {"error": "Not found."})
            return

        if not self._is_loopback_client():
            self._send_json(
                403,
                {
                    "error": (
                        "For security, remove the API key from a browser opened "
                        "at http://localhost on the QBot itself."
                    )
                },
            )
            return

        self.server.application.clear_api_key()
        self._send_json(
            200,
            {"configured": False, "message": "API key removed from memory."},
        )


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
    parser.add_argument(
        "--prepare-timeout",
        default=3600,
        type=int,
        help="Maximum seconds allowed for one /rosout index build.",
    )
    return parser


def main():
    args = build_parser().parse_args()

    initial_api_key = os.environ.pop("NVIDIA_API_KEY", "").strip()
    initial_api_key_loaded = bool(initial_api_key)

    locator = SessionLocator(fixed_session_id=args.session_id)
    application = ChatApplication(
        locator=locator,
        store=ChatStore(),
        runner=RagRunner(timeout=args.rag_timeout),
        initial_api_key=initial_api_key,
        preparer=SystemPreparer(timeout=args.prepare_timeout),
    )
    initial_api_key = None

    server = ThreadingHTTPServer((args.host, args.port), ChatRequestHandler)
    server.daemon_threads = True
    server.application = application

    display_host = "ROBOT_IP" if args.host in {"0.0.0.0", "::"} else args.host
    print("QBot session chat UI is running.")
    print("Open: http://{}:{}".format(display_host, args.port))
    print("RAG command: {}".format(ASK_ROBOT_SCRIPT))
    print("Comparison systems: {}".format(COMPARISON_SCRIPT))
    print(
        "Explanation systems: {} (default: {})".format(
            ", ".join(SYSTEMS), DEFAULT_SYSTEM
        )
    )
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

    if initial_api_key_loaded:
        print("NVIDIA API key loaded into UI memory from the current environment.")
    else:
        print(
            "Enter the NVIDIA API key from http://localhost:{} on the QBot; "
            "it will remain only in UI server memory.".format(args.port)
        )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping QBot session chat UI.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
