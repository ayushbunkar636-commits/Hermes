#!/usr/bin/env python3
"""seed_whitelist.py — Seed a project's whitelist from platforms.json tiers 1-2.

Run on day-1 of a project so the scanner immediately has sites to work with.
Safe to re-run: INSERT INTO on (project_id, domain) means duplicates are skipped.

Usage:
    python3 seed_whitelist.py \
        --project-url "https://memecoinist.com" \
        --niche "crypto memecoins" \
        [--project-name "Memecoinist"] \
        [--tiers 1,2] \
        [--db ~/.openclaw-backlink/data/backlink.db]

Prints:
    SEED_OK: seeded=N skipped=M project_id=X
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_PIPELINE_DIR = os.path.dirname(__file__)
_PLATFORMS_JSON = os.path.join(
    os.path.dirname(_PIPELINE_DIR), "platforms", "platforms.json"
)

sys.path.insert(0, _PIPELINE_DIR)
from whitelist_db import DEFAULT_DB_PATH, init_whitelist_db, upsert_project, upsert_whitelist_site, count_active_sites


def load_platforms(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("tiers", [])


def seed(
    project_url: str,
    niche: str,
    project_name: str = "",
    tiers: list[int] | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> tuple[int, int]:
    """Seed whitelist. Returns (seeded_count, skipped_count)."""
    if tiers is None:
        tiers = [1, 2]

    init_whitelist_db(db_path)
    project_id = upsert_project(project_url, niche, project_name, db_path=db_path)

    platforms = load_platforms(_PLATFORMS_JSON)
    before = count_active_sites(project_id, db_path=db_path)

    for tier_entry in platforms:
        if tier_entry.get("tier") not in tiers:
            continue
        for platform in tier_entry.get("platforms", []):
            domain = platform.get("domain", "").strip()
            if not domain:
                continue
            upsert_whitelist_site(project_id, domain, added_by="seed", db_path=db_path)

    after = count_active_sites(project_id, db_path=db_path)
    seeded = after - before
    return seeded, 0  # skipped count not precisely tracked (INSERT INTO)


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed project whitelist from platforms.json")
    parser.add_argument("--project-url", required=True, dest="project_url")
    parser.add_argument("--niche", required=True)
    parser.add_argument("--project-name", default="", dest="project_name")
    parser.add_argument("--tiers", default="1,2", help="Comma-separated tier numbers to seed from")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, dest="db_path")
    args = parser.parse_args()

    tiers = [int(t.strip()) for t in args.tiers.split(",") if t.strip().isdigit()]
    project_id = upsert_project(args.project_url, args.niche, args.project_name, db_path=args.db_path)
    seeded, skipped = seed(args.project_url, args.niche, args.project_name, tiers=tiers, db_path=args.db_path)
    total = count_active_sites(project_id, db_path=args.db_path)
    print(f"SEED_OK: seeded={seeded} project_id={project_id} total_active={total}")


if __name__ == "__main__":
    main()
