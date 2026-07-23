#!/usr/bin/env python3
"""check_whitelist_health.py — Check if the project whitelist needs new sites.

Always exits 0. The orchestrator branches on stdout:
  WHITELIST_HEALTHY: count=N project_id=X   → skip bl-site-finder
  WHITELIST_NEEDS_FINDER: count=N min=5 project_id=X  → spawn bl-site-finder
  WHITELIST_EMPTY: project_id=X             → seed first, then spawn finder

Policy: NEEDS_FINDER when active_count < MIN_WHITELIST (5) OR when
  weekly top-up cadence is due (--topup-days N; default 7; set 0 to disable).

Usage:
    python3 check_whitelist_health.py \
        --project-url "https://memecoinist.com" \
        --niche "crypto memecoins" \
        [--topup-days 7] \
        [--db ~/.openclaw-backlink/data/backlink.db]
"""
from __future__ import annotations

import argparse
import os
import sys

_PIPELINE_DIR = os.path.dirname(__file__)
sys.path.insert(0, _PIPELINE_DIR)

from whitelist_db import (
    DEFAULT_DB_PATH,
    MIN_WHITELIST,
    init_whitelist_db,
    upsert_project,
    count_active_sites,
    _connect,
)


def last_finder_run_days_ago(project_id: int, db_path: str) -> float | None:
    """Return days since last successful pipeline run that included a finder step, or None."""
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT julianday('now') - julianday(started_at) AS days_ago
            FROM pipeline_runs
            WHERE project_id = %s AND status = 'success'
            ORDER BY started_at DESC LIMIT 1
            """,
            (project_id,),
        ).fetchone()
    return float(row["days_ago"]) if row else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whitelist health for a project")
    parser.add_argument("--project-url", required=True, dest="project_url")
    parser.add_argument("--niche", default="", help="Niche (used to upsert project row)")
    parser.add_argument("--topup-days", type=int, default=7, dest="topup_days",
                        help="Trigger finder after this many days even if count is healthy. 0=disabled.")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, dest="db_path")
    args = parser.parse_args()

    init_whitelist_db(args.db_path)
    project_id = upsert_project(args.project_url, args.niche, db_path=args.db_path)
    active = count_active_sites(project_id, db_path=args.db_path)

    if active == 0:
        print(f"WHITELIST_EMPTY: project_id={project_id}")
        sys.exit(0)

    if active < MIN_WHITELIST:
        print(f"WHITELIST_NEEDS_FINDER: count={active} min={MIN_WHITELIST} project_id={project_id}")
        sys.exit(0)

    # Weekly top-up cadence check
    if args.topup_days > 0:
        days_ago = last_finder_run_days_ago(project_id, args.db_path)
        if days_ago is None or days_ago >= args.topup_days:
            print(f"WHITELIST_NEEDS_FINDER: count={active} min={MIN_WHITELIST} project_id={project_id} reason=topup_cadence")
            sys.exit(0)

    print(f"WHITELIST_HEALTHY: count={active} project_id={project_id}")


if __name__ == "__main__":
    main()
