#!/usr/bin/env python3
"""dedupe_opportunities.py — Filter scanner output against seen_opportunities table.

Reads $RUN_DIR/scan/opportunities.json, removes already-seen url_keys for this
project, writes the de-duped result to $RUN_DIR/scan/deduped.json, and records
the new url_keys in the DB.

URL key is normalised lowercase URL (scheme+host+path, query stripped).

Usage:
    python3 dedupe_opportunities.py \
        --scan-output $RUN_DIR/scan/opportunities.json \
        --deduped-out $RUN_DIR/scan/deduped.json \
        --project-url "https://memecoinist.com" \
        --niche "crypto memecoins" \
        [--db ~/.openclaw-backlink/data/backlink.db]

Prints:
    DEDUPE_OK: total=N new=M skipped=K
    DEDUPE_ALL_SEEN: no new opportunities after dedup (not a fatal error — pipeline continues with empty list)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.parse

_PIPELINE_DIR = os.path.dirname(__file__)
sys.path.insert(0, _PIPELINE_DIR)

from whitelist_db import DEFAULT_DB_PATH, init_whitelist_db, upsert_project, is_seen, mark_seen_batch


def normalise_url_key(url: str) -> str:
    """Lowercase normalised URL key: scheme+host+path (no query/fragment)."""
    try:
        p = urllib.parse.urlparse(url.strip())
        host = p.netloc.lower().lstrip("www.")
        path = p.path.rstrip("/") or "/"
        return f"{p.scheme}://{host}{path}"
    except Exception:
        return url.lower().strip()


def dedupe(
    scan_output_path: str,
    deduped_out_path: str,
    project_url: str,
    niche: str,
    db_path: str = DEFAULT_DB_PATH,
) -> tuple[int, int, int]:
    """Filter scan output. Returns (total, new, skipped)."""
    if not os.path.isfile(scan_output_path):
        print(f"DEDUPE_ERROR: file not found: {scan_output_path}", file=sys.stderr)
        sys.exit(1)

    with open(scan_output_path, encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        opportunities = raw.get("opportunities", raw.get("sites", []))
        meta = {k: v for k, v in raw.items() if k not in ("opportunities", "sites")}
    elif isinstance(raw, list):
        opportunities = raw
        meta = {}
    else:
        opportunities = []
        meta = {}

    init_whitelist_db(db_path)
    project_id = upsert_project(project_url, niche, db_path=db_path)

    new_opps = []
    new_keys = []
    skipped = 0

    for opp in opportunities:
        url = str(opp.get("url") or opp.get("submission_url") or "").strip()
        if not url:
            skipped += 1
            continue
        key = normalise_url_key(url)
        if is_seen(project_id, key, db_path=db_path):
            skipped += 1
            continue
        new_opps.append(opp)
        new_keys.append(key)

    # Record new keys so they're skipped on future runs
    if new_keys:
        mark_seen_batch(project_id, new_keys, db_path=db_path)

    output = {**meta, "status": "ok", "opportunities": new_opps}
    os.makedirs(os.path.dirname(os.path.abspath(deduped_out_path)), exist_ok=True)
    with open(deduped_out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    return len(opportunities), len(new_opps), skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Deduplicate scanner opportunities against seen DB")
    parser.add_argument("--scan-output", required=True, dest="scan_output")
    parser.add_argument("--deduped-out", required=True, dest="deduped_out")
    parser.add_argument("--project-url", required=True, dest="project_url")
    parser.add_argument("--niche", default="")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, dest="db_path")
    args = parser.parse_args()

    total, new, skipped = dedupe(
        args.scan_output, args.deduped_out, args.project_url, args.niche, db_path=args.db_path
    )

    if new == 0:
        print(f"DEDUPE_ALL_SEEN: total={total} new=0 skipped={skipped}")
    else:
        print(f"DEDUPE_OK: total={total} new={new} skipped={skipped}")


if __name__ == "__main__":
    main()
