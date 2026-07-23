#!/usr/bin/env python3
"""migrate_recent_sites.py — One-shot ingest of state/recent_sites.json into whitelist_sites.

Reads the old JSON list from state/recent_sites.json (or --input path).
Inserts each unique domain into whitelist_sites with:
  added_by = 'manual'
  status   = 'active'

Idempotent: uses INSERT INTO on (project_id, domain). Safe to re-run.

Usage:
    python3 migrate_recent_sites.py \
        --project-url "https://memecoinist.com" \
        --niche "crypto memecoins" \
        [--input ~/.openclaw-backlink/workspace-bl-orchestrator/state/recent_sites.json] \
        [--db ~/.openclaw-backlink/data/backlink.db]

Prints:
    MIGRATE_OK: processed=N inserted=M skipped=K project_id=X
    MIGRATE_EMPTY: input file missing or empty
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_PIPELINE_DIR = os.path.dirname(__file__)
_DEFAULT_INPUT = os.path.join(
    os.path.dirname(_PIPELINE_DIR),  # workspace-bl-orchestrator/
    "state",
    "recent_sites.json",
)

sys.path.insert(0, _PIPELINE_DIR)

from whitelist_db import DEFAULT_DB_PATH, init_whitelist_db, upsert_project, upsert_whitelist_site, count_active_sites


def migrate(
    project_url: str,
    niche: str,
    input_path: str,
    db_path: str = DEFAULT_DB_PATH,
) -> tuple[int, int, int]:
    """Migrate recent_sites.json. Returns (processed, inserted, skipped)."""
    if not os.path.isfile(input_path):
        return 0, 0, 0

    with open(input_path, encoding="utf-8") as f:
        raw = json.load(f)

    if not isinstance(raw, list) or not raw:
        return 0, 0, 0

    init_whitelist_db(db_path)
    project_id = upsert_project(project_url, niche, db_path=db_path)
    before = count_active_sites(project_id, db_path=db_path)

    seen_domains: set[str] = set()
    processed = 0

    for entry in raw:
        if not isinstance(entry, dict):
            continue
        domain = str(entry.get("domain") or "").strip().lstrip("www.").lower()
        if not domain or "." not in domain:
            # Try parsing from URL field
            url = str(entry.get("url") or "").strip()
            if url:
                import urllib.parse
                try:
                    domain = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
                except Exception:
                    pass
        if not domain or "." not in domain:
            continue
        if domain in seen_domains:
            continue
        seen_domains.add(domain)
        upsert_whitelist_site(project_id, domain, added_by="manual", db_path=db_path)
        processed += 1

    after = count_active_sites(project_id, db_path=db_path)
    inserted = after - before
    skipped = processed - inserted
    return processed, inserted, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate recent_sites.json to whitelist DB")
    parser.add_argument("--project-url", required=True, dest="project_url")
    parser.add_argument("--niche", default="")
    parser.add_argument("--input", default=_DEFAULT_INPUT, dest="input_path")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, dest="db_path")
    args = parser.parse_args()

    processed, inserted, skipped = migrate(
        args.project_url, args.niche, args.input_path, db_path=args.db_path
    )

    if processed == 0:
        print("MIGRATE_EMPTY: input file missing or empty")
        return

    from whitelist_db import upsert_project
    project_id = upsert_project(args.project_url, args.niche, db_path=args.db_path)
    print(f"MIGRATE_OK: processed={processed} inserted={inserted} skipped={skipped} project_id={project_id}")


if __name__ == "__main__":
    main()
