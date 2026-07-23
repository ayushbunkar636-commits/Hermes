#!/usr/bin/env bash
set -euo pipefail

OPENCLAW_ROOT="${OPENCLAW_STATE_DIR:-${HOME}/.openclaw-backlink}"
PIPELINE="${OPENCLAW_ROOT}/workspace-bl-orchestrator/skills/pipeline"
LOG_DIR="${OPENCLAW_ROOT}/logs"
# PID file must live on an ephemeral, container-local path (NOT the mounted logs/),
# so a stale PID from a previous container can never be read back and cause a
# false "already running" crash loop on restart.
DAEMON_PID_FILE="/tmp/nexus_daemon.pid"

mkdir -p "$LOG_DIR"

log() { echo "[entrypoint $(date -Is)] $*"; }

patch_bifrost_url() {
  local url="${BIFROST_BASE_URL:-http://host.docker.internal:8888/v1}"
  export BIFROST_BASE_URL="$url"
  local cfg="${OPENCLAW_ROOT}/openclaw.json"
  python3 - "$cfg" "$url" <<'PY'
import json
import sys

path, url = sys.argv[1], sys.argv[2]
with open(path, encoding="utf-8") as f:
    data = json.load(f)
data.setdefault("env", {})["BIFROST_BASE_URL"] = url
data["models"]["providers"]["local-bifrost"]["baseUrl"] = url
with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
PY
  log "BIFROST_BASE_URL=${url} (patched openclaw.json)"
}

seed_assets_if_needed() {
  local assets="${OPENCLAW_ROOT}/assets"
  local seed="/home/openclaw/.openclaw-backlink-asset-seed"
  mkdir -p "$assets" "${OPENCLAW_ROOT}/.backups/openclaw-json"
  if [[ -d "$seed" ]]; then
    local f base
    for f in "$seed"/*; do
      [[ -f "$f" ]] || continue
      base="$(basename "$f")"
      if [[ ! -f "${assets}/${base}" ]]; then
        cp -a "$f" "${assets}/${base}"
        log "seeded asset: ${base}"
      fi
    done
  fi
}

verify_mounts() {
  local db="${OPENCLAW_ROOT}/data/backlink.db"
  if [[ ! -f "$db" ]]; then
    log "ERROR: ${db} missing — run ./export-data.sh first"
    exit 1
  fi
  local projects whitelist leads
  projects="$(sqlite3 "$db" "SELECT COUNT(*) FROM projects;" 2>/dev/null || echo "?")"
  whitelist="$(sqlite3 "$db" "SELECT COUNT(*) FROM whitelist_sites;" 2>/dev/null || echo "?")"
  leads="$(sqlite3 "$db" "SELECT COUNT(*) FROM harvest_leads;" 2>/dev/null || echo "?")"
  log "backlink.db OK — projects=${projects} whitelist=${whitelist} harvest_leads=${leads}"
}

check_bifrost() {
  local url="${BIFROST_BASE_URL:-http://host.docker.internal:8888/v1}"
  if curl -sf "${url%/v1}/v1/models" -o /dev/null 2>/dev/null || curl -sf "${url}/models" -o /dev/null 2>/dev/null; then
    log "Bifrost reachable at ${url}"
  else
    log "WARNING: Bifrost not reachable at ${url} — start news-agent bifrost first (port 8888)"
  fi
}

start_gateway() {
  log "Starting openclaw gateway --profile backlink (background)..."
  mkdir -p "$LOG_DIR"
  openclaw --profile backlink gateway >>"${LOG_DIR}/gateway.log" 2>&1 &
  echo "$!" > "${LOG_DIR}/gateway.pid" 2>/dev/null || true
}

start_daemon() {
  log "Starting nexus_daemon via run_daemon.sh..."
  export BL_DAEMON_LOG_DIR="$LOG_DIR"
  export BL_DAEMON_PID_FILE="$DAEMON_PID_FILE"
  cd "$PIPELINE"
  exec bash run_daemon.sh
}

shutdown() {
  log "Shutting down..."
  [[ -f "${LOG_DIR}/gateway.pid" ]] && kill "$(cat "${LOG_DIR}/gateway.pid")" 2>/dev/null || true
  if [[ -f "$DAEMON_PID_FILE" ]]; then
    local spid
    spid="$(cat "$DAEMON_PID_FILE" 2>/dev/null || true)"
    [[ -n "$spid" ]] && kill "$spid" 2>/dev/null || true
  fi
  pkill -f nexus_daemon.py 2>/dev/null || true
  exit 0
}

trap shutdown SIGTERM SIGINT

if [[ ! -f "${OPENCLAW_ROOT}/openclaw.json" ]]; then
  echo "ERROR: No openclaw.json in ${OPENCLAW_ROOT}"
  exit 1
fi

patch_bifrost_url
verify_mounts
seed_assets_if_needed
check_bifrost
start_gateway
start_daemon
