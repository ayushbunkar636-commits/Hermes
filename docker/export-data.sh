#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${OPENCLAW_SRC:-${HOME}/.openclaw-backlink}"
DEST="${SCRIPT_DIR}/backlink-data"

echo "Exporting persistent Backlink Agent data..."
echo "  from: ${SRC}"
echo "  to:   ${DEST}"
echo ""

mkdir -p "${DEST}/data" "${DEST}/telegram" "${DEST}/identity" "${DEST}/devices" \
  "${DEST}/logs" "${DEST}/backups" "${DEST}/assets" \
  "${DEST}/workspace-bl-orchestrator/config"

if [[ -f "${SRC}/data/backlink.db" ]]; then
  cp -a "${SRC}/data/backlink.db" "${DEST}/data/"
  rsync -a --exclude='backlink.db' "${SRC}/data/" "${DEST}/data/" 2>/dev/null || true
fi

[[ -d "${SRC}/telegram" ]] && rsync -a "${SRC}/telegram/" "${DEST}/telegram/"
[[ -d "${SRC}/identity" ]] && rsync -a "${SRC}/identity/" "${DEST}/identity/"
[[ -d "${SRC}/devices" ]] && rsync -a "${SRC}/devices/" "${DEST}/devices/"

if [[ -d "${SRC}/workspace-bl-orchestrator/config" ]]; then
  rsync -a "${SRC}/workspace-bl-orchestrator/config/" "${DEST}/workspace-bl-orchestrator/config/"
fi

[[ -d "${SRC}/.backups" ]] && rsync -a "${SRC}/.backups/" "${DEST}/backups/" 2>/dev/null || true

if [[ -f "${SRC}/exec-approvals.json" ]]; then
  cp -a "${SRC}/exec-approvals.json" "${DEST}/exec-approvals.json"
else
  echo '{"version":1,"socket":{"path":""},"defaults":{},"agents":{}}' > "${DEST}/exec-approvals.json"
fi

# Logo for image generation
if [[ -d "${SRC}/assets" ]] && ls "${SRC}/assets/"* >/dev/null 2>&1; then
  rsync -a "${SRC}/assets/" "${DEST}/assets/"
elif [[ -f "${HOME}/.openclaw/assets/logo.png" ]]; then
  cp -a "${HOME}/.openclaw/assets/logo.png" "${DEST}/assets/logo.png"
fi

mkdir -p "${DEST}/logs"
rm -rf "${DEST}/logs/"* 2>/dev/null || true
chmod 777 "${DEST}/logs"

echo ""
echo "Exported files:"
ls -lh "${DEST}/data/backlink.db" 2>/dev/null || true
ls "${DEST}/assets/" 2>/dev/null || true

echo ""
sqlite3 "${DEST}/data/backlink.db" \
  "SELECT 'projects', COUNT(*) FROM projects
   UNION ALL SELECT 'whitelist_sites', COUNT(*) FROM whitelist_sites
   UNION ALL SELECT 'harvest_leads', COUNT(*) FROM harvest_leads;" 2>/dev/null || echo "(DB check skipped)"

echo ""
echo "Done. Next: docker compose build"
