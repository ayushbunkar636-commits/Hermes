#!/usr/bin/env bash
# =============================================================================
# update_manifest_step.sh — Record step completion in manifest.json
# =============================================================================
set -euo pipefail

MANIFEST=""
STEP=""
STATUS=""
NOTE=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --manifest) MANIFEST="$2"; shift 2 ;;
        --step)     STEP="$2";     shift 2 ;;
        --status)   STATUS="$2";   shift 2 ;;
        --note)     NOTE="$2";     shift 2 ;;
        *) echo "[update_manifest_step] Unknown arg: $1" >&2; exit 1 ;;
    esac
done

if [[ -z "$MANIFEST" || -z "$STEP" || -z "$STATUS" ]]; then
    echo "[update_manifest_step] --manifest, --step, and --status are required" >&2
    exit 1
fi

if [[ ! -f "$MANIFEST" ]]; then
    echo "[update_manifest_step] Manifest not found: $MANIFEST" >&2
    exit 1
fi

python3 - <<PYEOF
import json, os, datetime, sys
from zoneinfo import ZoneInfo

manifest_path = "${MANIFEST}"
step          = "${STEP}"
status        = "${STATUS}"
note          = "${NOTE}"

try:
    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
except Exception as e:
    print(f"[update_manifest_step] cannot parse manifest: {e}", file=sys.stderr)
    sys.exit(1)

_tz = ZoneInfo(os.environ.get("BL_TIMEZONE", "Asia/Kolkata"))
now = datetime.datetime.now(_tz).isoformat()

if "steps" not in manifest:
    manifest["steps"] = {}

step_record = manifest["steps"].get(step, {})
step_record["status"] = status
if status == "succeeded":
    step_record["finished_at"] = now
    if "started_at" not in step_record:
        step_record["started_at"] = now
elif status == "failed":
    step_record["failed_at"] = now
if note:
    step_record["note"] = note

manifest["steps"][step] = step_record
manifest["current_step"] = step

tmp = manifest_path + ".tmp"
with open(tmp, "w", encoding="utf-8") as f:
    json.dump(manifest, f, indent=2, ensure_ascii=False)
os.replace(tmp, manifest_path)

print(f"[MANIFEST] step={step} status={status}")
PYEOF
