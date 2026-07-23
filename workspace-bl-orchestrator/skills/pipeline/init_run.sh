#!/usr/bin/env bash
# =============================================================================
# init_run.sh — Initialize one isolated run-bundle for a backlink pipeline execution
# =============================================================================
# Usage:
#
#   bash ~/.openclaw-backlink/workspace-bl-orchestrator/skills/pipeline/init_run.sh \
#     --niche "SaaS tools" --project-url "https://example.com" \
#     [--project-name "Example SaaS"] [--project-description "..."]
#   source /tmp/backlink-run-env.sh
#
# After sourcing /tmp/backlink-run-env.sh the shell has:
#   $RUN_ID, $RUN_DIR, $BACKLINK_RUN_DIR, $PIPELINE_MANIFEST
#   $BL_NICHE, $BL_PROJECT_URL, $BL_PROJECT_NAME, $BL_PROJECT_DESCRIPTION
#   $BL_PROJECT_ID  (SQLite projects.id — 0 if DB not yet initialized)
# =============================================================================

set -euo pipefail

NICHE=""
PROJECT_URL=""
PROJECT_NAME=""
PROJECT_DESCRIPTION=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --niche) NICHE="$2"; shift 2 ;;
        --project-url) PROJECT_URL="$2"; shift 2 ;;
        --project-name) PROJECT_NAME="$2"; shift 2 ;;
        --project-description) PROJECT_DESCRIPTION="$2"; shift 2 ;;
        *) echo "[init_run] Unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$NICHE" || -z "$PROJECT_URL" ]]; then
    echo "[init_run] --niche and --project-url are required" >&2
    exit 1
fi

RUN_ID="$(date +%Y%m%d-%H%M%S)"
RUN_DIR="/tmp/backlink-run-${RUN_ID}"

# Create all run subdirs (new: finder/ scan/ score/)
mkdir -p \
  "${RUN_DIR}/finder" \
  "${RUN_DIR}/scan" \
  "${RUN_DIR}/score" \
  "${RUN_DIR}/content/images" \
  "${RUN_DIR}/delivery"

# Touch placeholder files
touch \
  "${RUN_DIR}/finder/new_sites.json" \
  "${RUN_DIR}/scan/opportunities.json" \
  "${RUN_DIR}/scan/deduped.json" \
  "${RUN_DIR}/score/scored.json" \
  "${RUN_DIR}/score/evictions.json" \
  "${RUN_DIR}/content/posts.json" \
  "${RUN_DIR}/delivery/card.json"

date +%s > "${RUN_DIR}/.run_started"

# Upsert project row in DB and capture project_id
PROJECT_ID=$(python3 - <<PYEOF 2>/dev/null || echo "0"
import sys, os
sys.path.insert(0, os.path.expanduser('~/.openclaw-backlink/workspace-bl-orchestrator/skills/pipeline'))
from whitelist_db import upsert_project, DEFAULT_DB_PATH
pid = upsert_project("${PROJECT_URL}", "${NICHE}", "${PROJECT_NAME}", db_path=DEFAULT_DB_PATH)
print(pid)
PYEOF
)

python3 - <<PYEOF
import json, datetime, os
from zoneinfo import ZoneInfo

run_id = "${RUN_ID}"
run_dir = "${RUN_DIR}"
niche = """${NICHE}"""
project_url = """${PROJECT_URL}"""
project_name = """${PROJECT_NAME}"""
project_description = """${PROJECT_DESCRIPTION}"""
project_id = int("${PROJECT_ID}" or "0")

_tz = ZoneInfo(os.environ.get("BL_TIMEZONE", "Asia/Kolkata"))
_created = datetime.datetime.now(_tz).isoformat()

manifest = {
    "run_id": run_id,
    "run_dir": run_dir,
    "pipeline": "backlink_whitelist",
    "created_at": _created,
    "current_step": "init",
    "project": {
        "niche": niche,
        "project_url": project_url,
        "project_name": project_name or niche,
        "project_description": project_description,
        "project_id": project_id,
    },
    "artifacts": {
        "finder_new_sites":    f"{run_dir}/finder/new_sites.json",
        "scan_opportunities":  f"{run_dir}/scan/opportunities.json",
        "scan_deduped":        f"{run_dir}/scan/deduped.json",
        "score_scored":        f"{run_dir}/score/scored.json",
        "score_evictions":     f"{run_dir}/score/evictions.json",
        "content_queue":       f"{run_dir}/content_queue.json",
        "content_posts":       f"{run_dir}/content/posts.json",
        "content_images_dir":  f"{run_dir}/content/images",
        "delivery_card":       f"{run_dir}/delivery/card.json",
    },
    "steps": {},
    "checks": {},
    "results": {},
}

tmp = f"{run_dir}/manifest.json.tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
os.replace(tmp, f"{run_dir}/manifest.json")
PYEOF

_symlink() {
    local legacy="$1"
    local target="$2"
    rm -f "$legacy" 2>/dev/null || true
    ln -sf "$target" "$legacy"
}

_symlink "/tmp/backlink-content-posts.json"     "${RUN_DIR}/content/posts.json"
_symlink "/tmp/backlink-pipeline-manifest.json"  "${RUN_DIR}/manifest.json"
_symlink "/tmp/backlink-feature.jpg"             "${RUN_DIR}/content/images/feature.jpg"

echo "${RUN_DIR}" > /tmp/backlink-active-run

cat > /tmp/backlink-run-env.sh <<ENVEOF
export RUN_ID="${RUN_ID}"
export RUN_DIR="${RUN_DIR}"
export BACKLINK_RUN_DIR="${RUN_DIR}"
export PIPELINE_MANIFEST="${RUN_DIR}/manifest.json"
export BL_NICHE="${NICHE}"
export BL_PROJECT_URL="${PROJECT_URL}"
export BL_PROJECT_NAME="${PROJECT_NAME:-${NICHE}}"
export BL_PROJECT_DESCRIPTION="${PROJECT_DESCRIPTION}"
export BL_PROJECT_ID="${PROJECT_ID}"
ENVEOF

# Clean up run dirs older than 7 days
find /tmp -maxdepth 1 -name 'backlink-run-*' -type d -mtime +7 -exec rm -rf {} + 2>/dev/null || true

echo "[INIT] Backlink run bundle ready: ${RUN_DIR}"
echo "[INIT] RUN_ID=${RUN_ID}"
echo "[INIT] PROJECT_ID=${PROJECT_ID}"
echo "[INIT] Niche: ${NICHE}"
echo "[INIT] Project: ${PROJECT_URL}"
echo "[INIT] Source env: source /tmp/backlink-run-env.sh"
