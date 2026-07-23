#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
DESKTOP_ZIP="/mnt/c/Users/bhard/Desktop/backlink-agent-deploy.zip"

log() { echo "[rebuild $(date -Is)] $*"; }

if ! docker info >/dev/null 2>&1; then
  echo "ERROR: Docker is not available. Start Docker Desktop, then re-run."
  exit 1
fi

chmod +x prepare-build-context.sh export-data.sh verify.sh package-for-boss.sh entrypoint.sh warm-plugins.sh

log "Step 1/5: prepare-build-context"
./prepare-build-context.sh

log "Step 2/5: export-data"
./export-data.sh

log "Step 3/5: docker compose build backlink-agent (may take 10–20 min)"
docker compose build backlink-agent

log "Step 4/5: restart stack"
docker compose up -d

log "Step 5/5: verify (non-fatal if daemon still starting)"
sleep 45
./verify.sh || true

log "Step 6/6: package + zip to Desktop"
./package-for-boss.sh
rm -f "${HOME}/backlink-agent-deploy.zip" "$DESKTOP_ZIP"
(cd "${SCRIPT_DIR}" && zip -r "${HOME}/backlink-agent-deploy.zip" backlink-agent-deploy/)
cp -f "${HOME}/backlink-agent-deploy.zip" "$DESKTOP_ZIP"
ls -lh "${HOME}/backlink-agent-deploy.zip" "$DESKTOP_ZIP"

powershell.exe -NoProfile -Command "Start-Process explorer.exe -ArgumentList '/select,C:\Users\bhard\Desktop\backlink-agent-deploy.zip'" 2>/dev/null || \
  powershell.exe -NoProfile -Command "Start-Process explorer.exe -ArgumentList 'C:\Users\bhard\Desktop'" 2>/dev/null || true

log "Done. Zip on Desktop: C:\\Users\\bhard\\Desktop\\backlink-agent-deploy.zip"
