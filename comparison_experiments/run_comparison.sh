#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
if [ "$#" -lt 1 ]; then
  echo "Use: rosout-build, rosout, or causal"
  exit 1
fi
SYSTEM_NAME="$1"; shift
case "$SYSTEM_NAME" in
  rosout-build|explaining-autonomy-build)
    exec "$HERE/explaining_autonomy/run.sh" build "$@" ;;
  rosout|explaining-autonomy)
    exec "$HERE/explaining_autonomy/run.sh" ask "$@" ;;
  causal|causal-explanation|personalized-causal)
    exec "$HERE/causal_explanation/run.sh" ask "$@" ;;
  *)
    echo "Unknown comparison system: $SYSTEM_NAME"
    exit 2 ;;
esac
