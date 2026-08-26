#!/usr/bin/env bash

set -e


# ============================================================
# QBot Log-RAG environment setup
#
# Run once after cloning:
#
#   ./setup_env.sh
#
# Requires:
#   - Ubuntu with ROS 2 Humble installed
#   - /opt/ros/humble/setup.bash
#   - Python 3
# ============================================================


REPO_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")"
    pwd
)"


cd "$REPO_DIR"


echo
echo "============================================================"
echo "QBOT LOG-RAG ENVIRONMENT SETUP"
echo "============================================================"
echo


# ============================================================
# CHECK ROS 2 HUMBLE
# ============================================================

if [ ! -f /opt/ros/humble/setup.bash ]; then

    echo "ERROR:"
    echo "ROS 2 Humble was not found at:"
    echo
    echo "  /opt/ros/humble/setup.bash"
    echo
    echo "Install ROS 2 Humble before running this setup."
    exit 1

fi


source /opt/ros/humble/setup.bash


echo "ROS 2 Humble found."


# ============================================================
# OPTIONAL USER ROS WORKSPACE
# ============================================================

if [ -f "$HOME/ros2/install/setup.bash" ]; then

    source "$HOME/ros2/install/setup.bash"

    echo "Loaded:"
    echo "  $HOME/ros2/install/setup.bash"

fi


# ============================================================
# CREATE VIRTUAL ENVIRONMENT
#
# IMPORTANT:
# --system-site-packages lets Python see ROS packages
# such as rclpy installed by ROS/apt.
# ============================================================

if [ ! -d ".venv" ]; then

    echo
    echo "Creating .venv..."

    python3 -m venv \
        --system-site-packages \
        .venv

else

    echo
    echo ".venv already exists."

fi


source .venv/bin/activate


# ============================================================
# PYTHON PACKAGES
# ============================================================

echo
echo "Installing Python requirements..."


python -m pip install \
    --upgrade pip


python -m pip install \
    -r requirements.txt


# ============================================================
# VERIFY IMPORTANT IMPORTS
# ============================================================

echo
echo "Checking Python environment..."


python - <<'PY'
import sys
import sqlite3
import requests

print("Python:", sys.version.split()[0])
print("sqlite3: OK")
print("requests: OK")

try:
    import rclpy
    print("rclpy: OK")

except Exception as exc:
    print()
    print("ERROR: rclpy could not be imported.")
    print(exc)
    raise SystemExit(1)
PY


# ============================================================
# OLLAMA CHECK
# ============================================================

echo
echo "Checking Ollama..."


if command -v ollama >/dev/null 2>&1; then

    echo "Ollama: installed"

    if ollama list \
        2>/dev/null \
        | grep -qi 'bge-m3'
    then

        echo "BGE-M3: installed"

    else

        echo
        echo "BGE-M3 is not installed."
        echo "Installing BGE-M3..."

        ollama pull bge-m3

    fi

else

    echo
    echo "WARNING:"
    echo "Ollama is not installed."
    echo
    echo "Semantic retrieval requires Ollama + bge-m3."
    echo "Install Ollama, then run:"
    echo
    echo "  ollama pull bge-m3"

fi


# ============================================================
# MAKE PROJECT SCRIPTS EXECUTABLE
# ============================================================

chmod +x \
    run_full_log_experiment.sh \
    2>/dev/null || true


chmod +x \
    run_qbot_map_labeler.sh \
    2>/dev/null || true


chmod +x \
    src/storage/start_evidence_logging.sh \
    2>/dev/null || true


# ============================================================
# DONE
# ============================================================

echo
echo "============================================================"
echo "SETUP COMPLETE"
echo "============================================================"
echo
echo "Environment:"
echo "  $REPO_DIR/.venv"
echo
echo "Next:"
echo
echo "  ./run_full_log_experiment.sh"
echo
