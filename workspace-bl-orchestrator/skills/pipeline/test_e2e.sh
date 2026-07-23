#!/usr/bin/env bash
# End-to-end backlink pipeline test (deterministic scripts only, no LLM/Telegram network).
set -euo pipefail

PIPELINE="$HOME/.openclaw/workspace-bl-orchestrator/skills/pipeline"
NICHE="SaaS project management"
PROJECT_URL="https://example-saas.com"
PROJECT_NAME="Example SaaS"

echo "=== E2E Backlink Pipeline Test ==="

bash "$PIPELINE/init_run.sh" \
  --niche "$NICHE" \
  --project-url "$PROJECT_URL" \
  --project-name "$PROJECT_NAME" \
  --project-description "Team collaboration SaaS"

source /tmp/backlink-run-env.sh
echo "Run: $RUN_ID"
echo "Dir: $RUN_DIR"

# Simulate finder output
python3 - <<PYEOF
import json
data = {
  "status": "ok",
  "niche": "$NICHE",
  "project_url": "$PROJECT_URL",
  "sites": [
    {
      "url": "https://startupblog.example/write-for-us",
      "domain": "startupblog.example",
      "type": "guest_post",
      "title": "Write for Us - Startup Blog",
      "relevance_notes": "SaaS and startup audience",
      "submission_url": "https://startupblog.example/submit",
      "guidelines_snippet": "1500+ words, original content"
    },
    {
      "url": "https://toolsdir.example/list-your-saas",
      "domain": "toolsdir.example",
      "type": "directory",
      "title": "SaaS Directory",
      "relevance_notes": "Software listing site",
      "submission_url": "https://toolsdir.example/add",
      "guidelines_snippet": "Free listing with description"
    }
  ]
}
with open("$RUN_DIR/discovery/raw.json", "w") as f:
    json.dump(data, f, indent=2)
print("Wrote discovery/raw.json")
PYEOF

python3 "$PIPELINE/validate_discovery.py" --manifest "$PIPELINE_MANIFEST"
python3 "$PIPELINE/check_recent_sites.py" \
  --current "$RUN_DIR/discovery/validated.json" \
  --registry "$HOME/.openclaw/workspace-bl-orchestrator/state/recent_sites.json" \
  --window-days 30 || true
python3 "$PIPELINE/update_recent_sites.py" \
  --current "$RUN_DIR/discovery/validated.json" \
  --registry "$HOME/.openclaw/workspace-bl-orchestrator/state/recent_sites.json" \
  --run-id "$RUN_ID" \
  --status discovered
python3 "$PIPELINE/verify_artifacts.py" --stage pre_audit --manifest "$PIPELINE_MANIFEST"
bash "$PIPELINE/update_manifest_step.sh" --manifest "$PIPELINE_MANIFEST" --step discovery --status succeeded

# Simulate scanner output
python3 - <<PYEOF
import json
sites = [
  {
    "url": "https://startupblog.example/write-for-us",
    "domain": "startupblog.example",
    "type": "guest_post",
    "score": 8.2,
    "domain_authority": 42,
    "dofollow": True,
    "spam_score": "low",
    "relevance_score": 9,
    "traffic_estimate": "medium",
    "recommendation": "high_priority",
    "audit_notes": "Strong guest post opportunity for SaaS niche"
  },
  {
    "url": "https://toolsdir.example/list-your-saas",
    "domain": "toolsdir.example",
    "type": "directory",
    "score": 6.5,
    "domain_authority": 28,
    "dofollow": True,
    "spam_score": "low",
    "relevance_score": 7,
    "traffic_estimate": "low",
    "recommendation": "medium",
    "audit_notes": "Decent directory listing"
  }
]
with open("$RUN_DIR/audit/results.json", "w") as f:
    json.dump({"status": "ok", "audited_sites": sites}, f, indent=2)
print("Wrote audit/results.json")
PYEOF

python3 "$PIPELINE/validate_audit.py" --manifest "$PIPELINE_MANIFEST"
python3 "$PIPELINE/verify_artifacts.py" --stage pre_content --manifest "$PIPELINE_MANIFEST"
bash "$PIPELINE/update_manifest_step.sh" --manifest "$PIPELINE_MANIFEST" --step audit --status succeeded

# Simulate content agent output
python3 - <<PYEOF
import json
posts = {
  "status": "ok",
  "niche": "$NICHE",
  "project_url": "$PROJECT_URL",
  "posts": [
    {
      "site_url": "https://startupblog.example/write-for-us",
      "site_domain": "startupblog.example",
      "type": "guest_post",
      "title": "How SaaS Teams Scale Project Delivery",
      "content": "Modern teams need better workflows. [Example SaaS]($PROJECT_URL) helps teams ship faster with clear ownership and async collaboration.",
      "backlink_url": "$PROJECT_URL",
      "backlink_anchor_text": "Example SaaS",
      "image_path": None,
      "submission_instructions": "Submit via startupblog.example/submit"
    },
    {
      "site_url": "https://toolsdir.example/list-your-saas",
      "site_domain": "toolsdir.example",
      "type": "directory",
      "title": "Example SaaS - Project Management Tool",
      "content": "Example SaaS is a project management platform for remote teams. URL: $PROJECT_URL",
      "backlink_url": "$PROJECT_URL",
      "backlink_anchor_text": "Example SaaS",
      "image_path": None,
      "submission_instructions": "Add listing at toolsdir.example/add"
    }
  ]
}
with open("$RUN_DIR/content/posts.json", "w") as f:
    json.dump(posts, f, indent=2)
print("Wrote content/posts.json")
PYEOF

python3 "$PIPELINE/validate_content.py" --manifest "$PIPELINE_MANIFEST"
python3 "$PIPELINE/verify_artifacts.py" --stage pre_delivery --manifest "$PIPELINE_MANIFEST"
bash "$PIPELINE/update_manifest_step.sh" --manifest "$PIPELINE_MANIFEST" --step content --status succeeded

# Build cards (dry - will fail telegram without network but builds delivery JSON)
python3 "$PIPELINE/build_and_send_card.py" --manifest "$PIPELINE_MANIFEST" || true

bash "$PIPELINE/update_manifest_step.sh" --manifest "$PIPELINE_MANIFEST" --step delivery --status succeeded
bash "$PIPELINE/cleanup_run_artifacts.sh" --manifest "$PIPELINE_MANIFEST"

echo ""
echo "=== E2E PASSED ==="
echo "Manifest steps:"
python3 -c "import json; m=json.load(open('$PIPELINE_MANIFEST')); print(json.dumps(m.get('steps',{}), indent=2))"
echo "Delivery card:"
python3 -c "import json; p='$RUN_DIR/delivery/card.json'; print(json.load(open(p)) if __import__('os').path.isfile(p) else 'no card file')"
