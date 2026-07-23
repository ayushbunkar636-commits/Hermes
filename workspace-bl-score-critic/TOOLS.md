# TOOLS.md — bl-score-critic

## Scoring script (your primary and only tool)

```bash
python3 /home/bhard/.openclaw-backlink/workspace-bl-orchestrator/skills/pipeline/score_opportunities.py \
  --deduped    <deduped_path> \
  --scored-out <scored_out_path> \
  --project-url "<project_url>" \
  --niche "<niche>" \
  --run-id "<run_id>" \
  --db ~/.openclaw-backlink/data/backlink.db
```

Exit 0 + `SCORE_OK:` → success. Exit non-zero → yield FAILURE.

## Rules

- This is your ONLY external call (besides reading the output file).
- No web access. No LLM gateways. Coding tools only.
