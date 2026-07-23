#!/usr/bin/env bash
# run_daemon.sh — Supervised launcher for the Nexus Farmer daemon.
#
# Keeps nexus_daemon.py alive (auto-restart on crash) and writes logs to a file.
# Use this for "always on" without systemd. For systemd, see the unit template
# printed by `--install-help`.
#
#   bash run_daemon.sh              # run in foreground (Ctrl-C to stop)
#   nohup bash run_daemon.sh &      # detach (background, survives logout)
#   bash run_daemon.sh --install-help
#
# Verbose pipeline logging (optional):
#   export BL_LOG_LEVEL=verbose   # full stage detail in nexus_daemon.log
#   export BL_LOG_SNIPPET=160     # max chars for titles/URLs in log lines
# Levels: off | info (default) | verbose | trace
#
# Stop a backgrounded instance: kill the PID in $PID_FILE.
# Restart when already running: bash run_daemon.sh --force
set -uo pipefail

# Flywheel defaults (override via env):
#   BL_DELIVERY_INTERVAL_MIN=60 BL_SITES_PER_TICK=5 BL_SCAN_MAX_PER_SITE=20 BL_SCAN_QUERY_LIMIT=8
export BL_DELIVERY_INTERVAL_MIN="${BL_DELIVERY_INTERVAL_MIN:-60}"
#   BL_MAX_AGE_DAYS=14 BL_SEARCH_QUERY_DELAY=4 BL_QUERY_EXPLORE_RATIO=0.2
#   BL_REARM_TTL_DAYS=21 BL_HUNTER_EVERY_TICKS=6 BL_VOCAB_EVERY_TICKS=12
export TZ="${BL_TIMEZONE:-Asia/Kolkata}"
# Search reliability (ddgs auto is primary; html/lite often blocked from home/WSL IPs)
export BL_DDG_TIMEOUT="${BL_DDG_TIMEOUT:-20}"
export BL_DDG_RETRIES="${BL_DDG_RETRIES:-3}"
export BL_DDG_BACKENDS="${BL_DDG_BACKENDS:-auto}"
export BL_ENABLE_DDG_HTML="${BL_ENABLE_DDG_HTML:-0}"
export BL_SEARCH_QUERY_DELAY="${BL_SEARCH_QUERY_DELAY:-5}"
# export BL_LOG_LEVEL=verbose

PIPELINE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${BL_DAEMON_LOG_DIR:-$HOME/.openclaw-backlink/logs}"
LOG_FILE="$LOG_DIR/nexus_daemon.log"
PID_FILE="${BL_DAEMON_PID_FILE:-$HOME/.openclaw-backlink/logs/nexus_daemon.pid}"
RESTART_DELAY="${BL_DAEMON_RESTART_DELAY:-10}"

mkdir -p "$LOG_DIR"

if [[ "${1:-}" == "--install-help" ]]; then
  cat <<EOF
To run the Nexus daemon as a user systemd service:

  mkdir -p ~/.config/systemd/user
  cat > ~/.config/systemd/user/nexus-daemon.service <<UNIT
  [Unit]
  Description=OpenClaw Backlink Nexus Farmer daemon
  After=network-online.target

  [Service]
  ExecStart=/usr/bin/env bash $PIPELINE_DIR/run_daemon.sh
  Restart=always
  RestartSec=10

  [Install]
  WantedBy=default.target
  UNIT

  systemctl --user daemon-reload
  systemctl --user enable --now nexus-daemon.service
  systemctl --user status nexus-daemon.service

Logs: $LOG_FILE  (or: journalctl --user -u nexus-daemon -f)
EOF
  exit 0
fi

# Single-instance guard (prevents duplicate daemons hammering DDG / interleaved logs).
FORCE=0
DAEMON_ARGS=()
for arg in "$@"; do
  if [[ "$arg" == "--force" ]]; then
    FORCE=1
  else
    DAEMON_ARGS+=("$arg")
  fi
done

_stop_supervisor_tree() {
  local pid="$1"
  if ! kill -0 "$pid" 2>/dev/null; then
    return 0
  fi
  # Kill child nexus_daemon.py if present, then the supervisor shell.
  local children
  children=$(pgrep -P "$pid" 2>/dev/null || true)
  if [[ -n "$children" ]]; then
    kill $children 2>/dev/null || true
    sleep 1
    kill -9 $children 2>/dev/null || true
  fi
  kill "$pid" 2>/dev/null || true
  sleep 1
  kill -9 "$pid" 2>/dev/null || true
}

# A PID is only "us running already" if it is a live process, is NOT this very
# shell, and its command line actually is the supervisor/daemon. Plain `kill -0`
# is not enough: in a container the daemon is PID 1, so a stale pid file
# containing "1" would always match an unrelated PID 1 and wedge startup.
_pid_is_daemon() {
  local pid="$1"
  [[ -z "$pid" || "$pid" == "$$" ]] && return 1
  kill -0 "$pid" 2>/dev/null || return 1
  local cmd=""
  [[ -r "/proc/$pid/cmdline" ]] && cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true)"
  [[ "$cmd" == *run_daemon.sh* || "$cmd" == *nexus_daemon.py* ]]
}

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if _pid_is_daemon "$OLD_PID"; then
    if [[ "$FORCE" -eq 1 ]]; then
      echo "[run_daemon] --force: stopping existing supervisor pid=$OLD_PID" >&2
      _stop_supervisor_tree "$OLD_PID"
    else
      echo "[run_daemon] already running (supervisor pid=$OLD_PID). Use --force to replace." >&2
      exit 1
    fi
  else
    # Stale/foreign pid file (e.g. leftover from a previous container). Clear it.
    rm -f "$PID_FILE" 2>/dev/null || true
  fi
fi

echo $$ > "$PID_FILE"
echo "[run_daemon] starting; logs -> $LOG_FILE (pid $$)"

# Prefer the backlink venv python if present, else system python3.
PYTHON="${BL_PYTHON:-python3}"

while true; do
  echo "[run_daemon] launching nexus_daemon.py at $(date +%FT%T%z)" >> "$LOG_FILE"
  "$PYTHON" "$PIPELINE_DIR/nexus_daemon.py" "${DAEMON_ARGS[@]}" >> "$LOG_FILE" 2>&1
  code=$?
  echo "[run_daemon] nexus_daemon.py exited code=$code; restart in ${RESTART_DELAY}s" >> "$LOG_FILE"
  sleep "$RESTART_DELAY"
done
