#!/usr/bin/env python3

"""Additive adapter around the project's unchanged ask_robot.py command."""

import re
import subprocess
import sys
from pathlib import Path


REPO_DIR = Path(__file__).resolve().parents[1]
ASK_ROBOT_SCRIPT = (
    REPO_DIR
    / "src"
    / "reasoning"
    / "ask_robot.py"
)

NVIDIA_MODEL = (
    "nvidia/nemotron-3-super-120b-a12b"
)

RUNTIME_DIR = REPO_DIR / "runtime_logs"
GLOBAL_EMBEDDINGS = (
    RUNTIME_DIR
    / "behavior_embeddings.json"
)
INTENT_EMBEDDINGS = (
    RUNTIME_DIR
    / "task_intent_embeddings.json"
)

ANSWER_MARKER = (
    "ANSWER\n"
    + "=" * 70
    + "\n"
)


def map_embedding_files():
    return list(
        (
            RUNTIME_DIR
            / "map_indexes"
        ).glob(
            "*/label_embeddings.json"
        )
    )


def _last_output_line(output):
    lines = [
        line.strip()
        for line in output.splitlines()
        if line.strip()
    ]

    if not lines:
        return (
            "The RAG command returned no answer."
        )

    return lines[-1]


def answer_question(
    question,
    requested_map=None,
    audience="user",
    timeout=180,
):
    """Run ask_robot.py unchanged and return its answer as structured data."""
    question = str(question or "").strip()

    if not question:
        raise ValueError(
            "Question cannot be empty."
        )

    if audience not in {
        "user",
        "developer",
    }:
        raise ValueError(
            "Audience must be 'user' or 'developer'."
        )

    command = [
        sys.executable,
        str(ASK_ROBOT_SCRIPT),
        "--question",
        question,
        "--audience",
        audience,
    ]

    if requested_map:
        command.extend([
            "--map",
            str(requested_map),
        ])

    try:
        result = subprocess.run(
            command,
            cwd=str(REPO_DIR),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            "The RAG request timed out."
        ) from exc

    if result.returncode != 0:
        details = (
            result.stderr.strip()
            or result.stdout.strip()
            or (
                "ask_robot.py exited with status "
                + str(result.returncode)
            )
        )
        raise RuntimeError(
            details[-3000:]
        )

    output = result.stdout
    occurrence_match = re.search(
        r"SELECTED OCCURRENCES:\s*(\d+)",
        output,
    )
    packet_count = (
        int(occurrence_match.group(1))
        if occurrence_match
        else 0
    )

    if ANSWER_MARKER in output:
        answer = output.rsplit(
            ANSWER_MARKER,
            1,
        )[1].strip()
        used_llm = True
    else:
        answer = _last_output_line(
            output
        )
        used_llm = False

    return {
        "answer": answer,
        "model": NVIDIA_MODEL,
        "packet_count": packet_count,
        "used_llm": used_llm,
    }
