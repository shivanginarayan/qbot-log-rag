#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
MODE="${1:-ask}"
case "$MODE" in
  ask) shift || true; exec python "$HERE/ask_causal.py" "$@" ;;
  logger|live) shift || true; exec python "$HERE/live_causal_logger.py" "$@" ;;
  *) echo "Use: ask or logger"; exit 2 ;;
esac
