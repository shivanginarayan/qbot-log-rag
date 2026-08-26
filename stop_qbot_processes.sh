#!/usr/bin/env bash
#
# stop_qbot_processes.sh - safely stop QBot processes that block a clean restart.
#
# The map labeler spawns run_qbot_navigation.sh / run_qbot_mapping.sh with
# start_new_session=True, so those trees survive if the labeler is killed hard.
# They keep holding port 8765 and the ROS domain, which makes the next start fail
# with "Address already in use" or a half-live navigation stack.
#
# Safety rules this script follows:
#   * only touches processes owned by the current user
#   * only matches a fixed allowlist of QBot command patterns
#   * never kills itself, its terminal, or any of its own ancestors
#   * ignores shell -c wrappers, greps and editors that merely mention a pattern
#   * SIGTERM first (so the run_qbot_*.sh traps shut ROS down cleanly),
#     SIGKILL only for whatever is still alive after the grace period
#
# Usage:
#   ./stop_qbot_processes.sh              # confirm, then stop labeler + nav/mapping
#   ./stop_qbot_processes.sh -n           # dry run, show what would be stopped
#   ./stop_qbot_processes.sh -y           # no prompt (for use inside other scripts)
#   ./stop_qbot_processes.sh --all        # also stop diagnostics/teleop collectors
#   ./stop_qbot_processes.sh --port 8765  # port to free (default $QBOT_LABELER_PORT or 8765)

set -uo pipefail

PORT="${QBOT_LABELER_PORT:-8765}"
GRACE=8
DRY_RUN=0
ASSUME_YES=0
INCLUDE_ALL=0
SELF_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

usage() { sed -n '2,26p' "$SELF_PATH" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
    case "$1" in
        -n|--dry-run) DRY_RUN=1 ;;
        -y|--yes)     ASSUME_YES=1 ;;
        --all)        INCLUDE_ALL=1 ;;
        --port)       PORT="${2:?--port needs a value}"; shift ;;
        --timeout)    GRACE="${2:?--timeout needs a value}"; shift ;;
        -h|--help)    usage ;;
        *) echo "Unknown option: $1 (try --help)" >&2; exit 2 ;;
    esac
    shift
done

# Command patterns owned by the labeler and the stacks it launches.
PATTERNS=(
    'tools/map_label_gui\.py'
    'run_qbot_map_labeler\.sh'
    'run_qbot_navigation\.sh'
    'run_qbot_mapping\.sh'
    'qbot_platform_map_nav_bringup_launch\.py'
    'qbot_platform_manual_map_launch\.py'
    'qbot_platform_manual_drive_launch\.py'
    'go_to_label\.py'
<<<<<<< HEAD
    'manual_assistance\.py'
    'cmd_vel_arbiter\.py'
=======
>>>>>>> 4bac8506ff2599764401270175088b8d7fe35072
    'breadcrumb_return\.py'
    'map_saver_cli'
    'cartographer_node'
    'cartographer_occupancy_grid_node'
)

# Diagnostics and teleop from start_qbot.sh - only with --all.
EXTRA_PATTERNS=(
    'topic_health_collector\.py'
    'error_memory_collector\.py'
    'health_to_logs\.py'
    'diagnose_with_memory\.py'
    'ros2 run teleop follower'
)

if [ "$INCLUDE_ALL" -eq 1 ]; then
    PATTERNS+=("${EXTRA_PATTERNS[@]}")
fi

PATTERN_RE="$(IFS='|'; echo "${PATTERNS[*]}")"

# Never kill ourselves, our shell, the terminal, or anything else above us.
protected=" $$ "
_walk=$$
while [ "$_walk" -gt 1 ]; do
    _walk="$(ps -o ppid= -p "$_walk" 2>/dev/null | tr -d ' ')"
    [ -n "$_walk" ] || break
    protected="$protected$_walk "
done

is_protected() { case "$protected" in *" $1 "*) return 0 ;; *) return 1 ;; esac; }

# Cmdlines that only mention a pattern rather than being the process itself.
is_bystander() {
    local cmd="$1"
    case "$cmd" in
        *"$SELF_PATH"*|*stop_qbot_processes.sh*) return 0 ;;
    esac
    # shell -c wrappers (how tooling and agents run commands)
    if printf '%s' "$cmd" | grep -Eq '^[^ ]*(ba|z|da)?sh +-[A-Za-z]*c '; then return 0; fi
    # search/inspect/edit tools that take a filename as an argument
    if printf '%s' "$cmd" | grep -Eq '^[^ ]*/?(grep|egrep|fgrep|rg|ag|pgrep|pkill|ps|awk|sed|tail|head|less|more|cat|vi|vim|nvim|nano|emacs|code|python3? -m pdb)\b'; then return 0; fi
    return 1
}

MY_UID="$(id -u)"
declare -a K_PID K_PGID K_ETIME K_CMD
N_CANDIDATES=0
seen=" "

add_candidate() {
    local pid="$1" pgid="$2" etime="$3" cmd="$4"
    case "$seen" in *" $pid "*) return ;; esac
    seen="$seen$pid "
    K_PID+=("$pid"); K_PGID+=("$pgid"); K_ETIME+=("$etime"); K_CMD+=("$cmd")
    N_CANDIDATES=$((N_CANDIDATES + 1))
}

<<<<<<< HEAD
stop_driver_model() {
    command -v quarc_run >/dev/null 2>&1 || return 0
    if quarc_run -q -t tcpip://localhost:17000 qbot_platform_driver_physical \
        >/dev/null 2>&1; then
        echo "QUARC QBot driver model stopped."
    else
        # quarc_run also returns nonzero when there was no model to stop.
        echo "QUARC QBot driver model is already stopped or not reachable."
    fi
}

=======
>>>>>>> 4bac8506ff2599764401270175088b8d7fe35072
# 1. Pattern matches owned by this user.
while read -r pid ppid pgid euid etime cmd; do
    [ -n "${cmd:-}" ] || continue
    [ "$euid" = "$MY_UID" ] || continue
    is_protected "$pid" && continue
    is_bystander "$cmd" && continue
    printf '%s' "$cmd" | grep -Eq "$PATTERN_RE" || continue
    add_candidate "$pid" "$pgid" "$etime" "$cmd"
done < <(ps -eo pid=,ppid=,pgid=,euid=,etime=,args= 2>/dev/null)

# 2. Whatever is holding the labeler port, pattern or not.
port_holders() {
    local pids=""
    if command -v ss >/dev/null 2>&1; then
        pids="$(ss -lptnH "sport = :$PORT" 2>/dev/null | grep -oE 'pid=[0-9]+' | cut -d= -f2)"
    fi
    if [ -z "$pids" ] && command -v lsof >/dev/null 2>&1; then
        pids="$(lsof -t -i ":$PORT" -sTCP:LISTEN 2>/dev/null)"
    fi
    if [ -z "$pids" ] && command -v fuser >/dev/null 2>&1; then
        pids="$(fuser -n tcp "$PORT" 2>/dev/null | tr -s ' ' '\n' | grep -E '^[0-9]+$')"
    fi
    printf '%s\n' $pids | sort -u | grep -E '^[0-9]+$'
}

while read -r pid; do
    [ -n "$pid" ] || continue
    is_protected "$pid" && continue
    read -r pgid euid etime cmd < <(ps -o pgid=,euid=,etime=,args= -p "$pid" 2>/dev/null)
    [ -n "${cmd:-}" ] || continue
    [ "$euid" = "$MY_UID" ] || continue
    is_bystander "$cmd" && continue
    add_candidate "$pid" "$pgid" "$etime" "$cmd"
done < <(port_holders)

if [ "$N_CANDIDATES" -eq 0 ]; then
    echo "Nothing to stop - no QBot processes running and port $PORT is free."
<<<<<<< HEAD
    if [ "$DRY_RUN" -eq 1 ]; then
        echo "Dry run - would also request a clean QUARC driver-model stop."
    else
        stop_driver_model
    fi
=======
>>>>>>> 4bac8506ff2599764401270175088b8d7fe35072
    exit 0
fi

echo "QBot processes that would block a restart:"
printf '  %-8s %-8s %-10s %s\n' PID PGID ELAPSED COMMAND
for i in "${!K_PID[@]}"; do
    printf '  %-8s %-8s %-10s %.90s\n' "${K_PID[$i]}" "${K_PGID[$i]}" "${K_ETIME[$i]}" "${K_CMD[$i]}"
done
echo

if [ "$DRY_RUN" -eq 1 ]; then
    echo "Dry run - nothing was signalled."
    exit 0
fi

if [ "$ASSUME_YES" -ne 1 ]; then
    if [ -r /dev/tty ] && [ -t 1 ]; then
        read -r -p "Stop these $N_CANDIDATES process(es)? [y/N] " reply < /dev/tty
        case "$reply" in [yY]|[yY][eE][sS]) ;; *) echo "Aborted."; exit 1 ;; esac
    else
        echo "Refusing to kill without confirmation. Re-run with --yes (or --dry-run)." >&2
        exit 1
    fi
fi

# Process groups first: the run scripts are session leaders (pgid == pid), so
# signalling the group takes their ros2 launch children down with them.
# NOTE: do not name this GROUPS - that is a bash special variable holding the
# user's supplementary group IDs, and assignments to it are silently discarded.
declare -a KILL_PGIDS
for i in "${!K_PID[@]}"; do
    if [ "${K_PID[$i]}" = "${K_PGID[$i]}" ]; then KILL_PGIDS+=("${K_PGID[$i]}"); fi
done

# A group is only safe to signal if every member is ours and none is protected.
group_is_safe() {
    local pgid="$1" members entry pid euid
    [ "$pgid" -gt 1 ] 2>/dev/null || return 1
    is_protected "$pgid" && return 1
    members="$(ps -eo pgid=,pid=,euid= 2>/dev/null | awk -v g="$pgid" '$1==g {print $2":"$3}')"
    [ -n "$members" ] || return 1
    for entry in $members; do
        pid="${entry%%:*}"; euid="${entry##*:}"
        [ "$euid" = "$MY_UID" ] || return 1
        is_protected "$pid" && return 1
    done
    return 0
}

signal_all() {
    local sig="$1" g pid
    for g in ${KILL_PGIDS[@]+"${KILL_PGIDS[@]}"}; do
        group_is_safe "$g" || continue
        kill "-$sig" -- "-$g" 2>/dev/null
    done
    for pid in "${K_PID[@]}"; do
        is_protected "$pid" && continue
        kill -0 "$pid" 2>/dev/null && kill "-$sig" "$pid" 2>/dev/null
    done
}

alive_pids() {
    local pid out=""
    for pid in "${K_PID[@]}"; do
        kill -0 "$pid" 2>/dev/null && out="$out $pid"
    done
    printf '%s' "${out# }"
}

echo "Sending SIGTERM (letting ROS shut down cleanly)..."
signal_all TERM

waited=0
while [ "$waited" -lt "$GRACE" ]; do
    [ -z "$(alive_pids)" ] && break
    sleep 1
    waited=$((waited + 1))
done

survivors="$(alive_pids)"
if [ -n "$survivors" ]; then
    echo "Still alive after ${GRACE}s: $survivors - sending SIGKILL..."
    signal_all KILL
    sleep 1
fi

# Reap anything that was reparented but still holds the port.
leftover="$(port_holders | tr '\n' ' ' | sed 's/ *$//')"
if [ -n "$leftover" ]; then
    for pid in $leftover; do
        is_protected "$pid" && continue
        echo "Port $PORT still held by PID $pid - sending SIGKILL..."
        kill -9 "$pid" 2>/dev/null
    done
    sleep 1
fi

failed=0
remaining="$(alive_pids)"
if [ -n "$remaining" ]; then
    echo "WARNING: could not stop: $remaining" >&2
    failed=1
fi

if [ -n "$(port_holders)" ]; then
    echo "WARNING: port $PORT is still in use." >&2
    failed=1
fi

<<<<<<< HEAD
# The real-time driver model can outlive a failed launch process. Explicitly
# stop it so the next navigation or mapping startup can download a clean copy.
stop_driver_model

=======
>>>>>>> 4bac8506ff2599764401270175088b8d7fe35072
if [ "$failed" -eq 0 ]; then
    echo "All clear - QBot processes stopped and port $PORT is free."
fi
exit "$failed"
