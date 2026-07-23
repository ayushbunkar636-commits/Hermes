#!/usr/bin/env bash
# Remove /tmp symlinks and active-run pointer on terminal pipeline state.
set -euo pipefail

MANIFEST=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --manifest) MANIFEST="$2"; shift 2 ;;
        --archive)  shift ;;
        *) echo "[cleanup] Unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$MANIFEST" ]]; then
    echo "[cleanup] --manifest is required" >&2
    exit 1
fi

if [[ ! -f "$MANIFEST" ]]; then
    echo "[cleanup] Manifest not found: $MANIFEST — skipping cleanup" >&2
    exit 0
fi

LEGACY_PATHS=(
    "/tmp/backlink-discovery-raw.json"
    "/tmp/backlink-discovery-validated.json"
    "/tmp/backlink-audit-results.json"
    "/tmp/backlink-content-posts.json"
    "/tmp/backlink-pipeline-manifest.json"
    "/tmp/backlink-feature.jpg"
)

for path in "${LEGACY_PATHS[@]}"; do
    if [ -L "$path" ]; then
        rm -f "$path"
        echo "[cleanup] Removed symlink: $path"
    fi
done

if [ -f "/tmp/backlink-active-run" ]; then
    rm -f /tmp/backlink-active-run
    echo "[cleanup] Removed /tmp/backlink-active-run"
fi

echo "[cleanup] Done. RUN_DIR preserved for audit: $(python3 -c "import json; m=json.load(open('${MANIFEST}')); print(m.get('run_dir','?'))" 2>/dev/null || echo '?')"
