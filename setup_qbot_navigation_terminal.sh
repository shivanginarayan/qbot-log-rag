#!/usr/bin/env bash

# Source this file, then launch navigation:
#   source ./setup_qbot_navigation_terminal.sh
#   ./run_qbot_navigation.sh --map robot_navigation/maps/MAP_NAME.yaml

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    echo "This script must be sourced, not executed:"
    echo "  source ./setup_qbot_navigation_terminal.sh"
    exit 2
fi

QBOT_NAV_SETUP_REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$QBOT_NAV_SETUP_REPO_DIR/setup_qbot_terminal.sh" || return 1

echo
echo "Navigation terminal ready. Start it with:"
echo "  ./run_qbot_navigation.sh --map robot_navigation/maps/MAP_NAME.yaml"

unset QBOT_NAV_SETUP_REPO_DIR
