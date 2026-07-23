#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DB="${SCRIPT_DIR}/backlink-data/data/backlink.db"
FAIL=0

echo "=== Backlink Agent Docker verify ==="

if [[ ! -f "$DB" ]]; then
  echo "FAIL: $DB not found — run ./export-data.sh"
  exit 1
fi

PROJECTS="$(sqlite3 "$DB" "SELECT COUNT(*) FROM projects;" 2>/dev/null || echo "?")"
WHITELIST="$(sqlite3 "$DB" "SELECT COUNT(*) FROM whitelist_sites;" 2>/dev/null || echo "?")"
LEADS="$(sqlite3 "$DB" "SELECT COUNT(*) FROM harvest_leads;" 2>/dev/null || echo "?")"
echo "DB projects:       ${PROJECTS}"
echo "DB whitelist:      ${WHITELIST}"
echo "DB harvest_leads:  ${LEADS}"

if docker compose ps --status running 2>/dev/null | grep -q backlink-agent; then
  echo "Container: running"
  if docker compose exec -T backlink-agent pgrep -f nexus_daemon.py >/dev/null 2>&1; then
    echo "nexus_daemon: OK"
  else
    echo "FAIL: nexus_daemon not running"
    FAIL=1
  fi
  if docker compose exec -T backlink-agent pgrep -f "openclaw.*gateway" >/dev/null 2>&1; then
    echo "gateway: OK"
  elif docker compose exec -T backlink-agent curl -sf http://127.0.0.1:19789/ >/dev/null 2>&1; then
    echo "gateway: OK (UI responding)"
  else
    echo "WARN: gateway not running yet"
  fi
  BIFROST_URL="$(docker compose exec -T backlink-agent printenv BIFROST_BASE_URL 2>/dev/null | tr -d '\r' || true)"
  if [[ -n "$BIFROST_URL" ]]; then
    echo "BIFROST_BASE_URL: ${BIFROST_URL}"
  fi
else
  echo "WARN: container not running — start with: docker compose up -d"
fi

echo "=== done ==="
exit $FAIL
