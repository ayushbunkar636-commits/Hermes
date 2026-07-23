#!/usr/bin/env python3
"""merge_new_sites.py — Ingest bl-site-finder output into the whitelist DB.

Input JSON format (written by bl-site-finder to $RUN_DIR/finder/new_sites.json):
  [
    {
      "domain": "example.com",
      "credibility_notes": "Active crypto forum with 50k+ monthly visitors",
      "source_evidence_url": "https://reddit.com/r/crypto/comments/xyz/example_mentioned"
    },
    ...
  ]

Idempotent: INSERT INTO on (project_id, domain) — safe to re-run.
Caps at MAX_NEW_SITES_PER_RUN (5) to prevent whitelist bloat.

Usage:
    python3 merge_new_sites.py \
        --finder-output $RUN_DIR/finder/new_sites.json \
        --project-url "https://memecoinist.com" \
        --niche "crypto memecoins" \
        [--db ~/.openclaw-backlink/data/backlink.db]

Prints:
    MERGE_SITES_OK: added=N skipped=M project_id=X
    MERGE_SITES_EMPTY: finder output had no valid domains
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_PIPELINE_DIR = os.path.dirname(__file__)
sys.path.insert(0, _PIPELINE_DIR)

from whitelist_db import DEFAULT_DB_PATH, init_whitelist_db, upsert_project, upsert_whitelist_site, count_active_sites

MAX_NEW_SITES_PER_RUN = 5


def merge(
    finder_output_path: str,
    project_url: str,
    niche: str,
    db_path: str = DEFAULT_DB_PATH,
) -> tuple[int, int]:
    """Merge finder output into whitelist. Returns (added, skipped)."""
    if not os.path.isfile(finder_output_path):
        print(f"MERGE_SITES_ERROR: file not found: {finder_output_path}", file=sys.stderr)
        sys.exit(1)

    with open(finder_output_path, encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        sites = raw.get("sites", raw.get("new_sites", []))
    elif isinstance(raw, list):
        sites = raw
    else:
        sites = []

    valid = []
    for entry in sites:
        if not isinstance(entry, dict):
            continue
        domain = str(entry.get("domain") or "").strip().lstrip("www.").lower()
        if not domain or "." not in domain:
            continue
        valid.append(domain)

    if not valid:
        print("MERGE_SITES_EMPTY: finder output had no valid domains")
        return 0, len(sites)

    init_whitelist_db(db_path)
    project_id = upsert_project(project_url, niche, db_path=db_path)
    before = count_active_sites(project_id, db_path=db_path)

    added = 0
    for domain in valid[:MAX_NEW_SITES_PER_RUN]:
        upsert_whitelist_site(project_id, domain, added_by="finder", db_path=db_path)
        added += 1

    after = count_active_sites(project_id, db_path=db_path)
    net_added = after - before
    skipped = added - net_added
    return net_added, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge bl-site-finder output into whitelist DB")
    parser.add_argument("--finder-output", required=True, dest="finder_output")
    parser.add_argument("--project-url", required=True, dest="project_url")
    parser.add_argument("--niche", default="")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, dest="db_path")
    args = parser.parse_args()

    project_id = upsert_project(args.project_url, args.niche, db_path=args.db_path)
    added, skipped = merge(args.finder_output, args.project_url, args.niche, db_path=args.db_path)
    print(f"MERGE_SITES_OK: added={added} skipped={skipped} project_id={project_id}")


if __name__ == "__main__":
    main()
