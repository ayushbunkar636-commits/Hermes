#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="${OPENCLAW_SRC:-${HOME}/.openclaw-backlink}"
DEST="${SCRIPT_DIR}/build-context"
CONTAINER_ROOT="/home/openclaw/.openclaw-backlink"
BIFROST_URL="${BIFROST_PATCH_URL:-http://host.docker.internal:8888/v1}"

if [[ ! -f "${SRC}/openclaw.json" ]]; then
  echo "ERROR: ${SRC}/openclaw.json not found"
  exit 1
fi

echo "Preparing Backlink Docker build context..."
echo "  from: ${SRC}"
echo "  to:   ${DEST}"
echo ""

rm -rf "$DEST"
mkdir -p "$DEST"

rsync -a \
  --exclude='data/' \
  --exclude='logs/' \
  --exclude='browser/' \
  --exclude='node_modules/' \
  --exclude='agents/' \
  --exclude='docker/' \
  --exclude='.pytest_cache/' \
  --exclude='identity/' \
  --exclude='devices/' \
  --exclude='telegram/' \
  --exclude='nohup.out' \
  "${SRC}/" "${DEST}/"

mkdir -p "${DEST}/logs" "${DEST}/data" "${DEST}/assets"

find "$DEST" -type f \( \
  -name '*.json' -o -name '*.sh' -o -name '*.md' -o -name '*.py' -o -name '*.service' \
\) -not -path '*/node_modules/*' \
  -exec grep -l '/home/bhard' {} + 2>/dev/null \
  | while read -r f; do
      sed -i \
        -e "s|/home/bhard/.openclaw-backlink|${CONTAINER_ROOT}|g" \
        -e "s|/home/bhard/.openclaw/assets|${CONTAINER_ROOT}/assets|g" \
        -e "s|/home/bhard/.openclaw|${CONTAINER_ROOT}|g" \
        -e 's|/home/bhard/.npm-global/bin|/usr/local/bin|g' \
        "$f" || true
    done

if [[ -f "${DEST}/openclaw.json" ]]; then
  sed -i 's|"executablePath": "[^"]*"|"executablePath": "/usr/bin/chromium"|' "${DEST}/openclaw.json"
  sed -i 's|"bind": "loopback"|"bind": "0.0.0.0"|' "${DEST}/openclaw.json"
  python3 - "${DEST}/openclaw.json" "$BIFROST_URL" <<'PY'
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
fi

find "$DEST" -type f \( -name '*.json' -o -name '*.sh' -o -name '*.md' -o -name '*.py' \) \
  -not -path '*/node_modules/*' \
  -exec grep -lE '192\.168\.32\.1:8888|172\.30\.176\.1:8888|http://bifrost:8080/v1' {} + 2>/dev/null \
  | while read -r f; do
      sed -i \
        -e "s|http://192\.168\.32\.1:8888/v1|${BIFROST_URL}|g" \
        -e "s|http://172\.30\.176\.1:8888/v1|${BIFROST_URL}|g" \
        -e "s|http://bifrost:8080/v1|${BIFROST_URL}|g" \
        "$f" || true
    done

# Seed logo from news-agent if backlink has no assets
if [[ ! -f "${DEST}/assets/logo.png" ]] && [[ -f "${HOME}/.openclaw/assets/logo.png" ]]; then
  cp -a "${HOME}/.openclaw/assets/logo.png" "${DEST}/assets/logo.png"
  echo "Seeded logo.png from ~/.openclaw/assets"
fi

echo ""
echo "Build context ready at ${DEST}"
echo "Next: ./export-data.sh && docker compose build"
