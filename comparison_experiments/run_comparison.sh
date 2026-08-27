#!/usr/bin/env bash
set -e

HERE="$(
    cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1
    pwd
)"

if [ "$#" -lt 1 ]; then
    echo "Use: rosout-build, rosout, or causal"
    exit 1
fi

SYSTEM_NAME="$1"
shift

case "$SYSTEM_NAME" in
    rosout-build|explaining-autonomy-build)
        exec "$HERE/explaining_autonomy/run.sh" build "$@"
        ;;
    rosout|explaining-autonomy)
        exec "$HERE/explaining_autonomy/run.sh" ask "$@"
        ;;
    causal|counterfactual|causal-counterfactual)
        exec "$HERE/causal_counterfactual/run.sh" "$@"
        ;;
    *)
        echo "Unknown comparison system: $SYSTEM_NAME"
        echo "Use: rosout-build, rosout, or causal"
        exit 2
        ;;
esac
