#!/usr/bin/env python3
"""evict_underperformers.py — Bench whitelist sites that continuously underperform.

Eligibility for eviction:
  1. Site has >= 5 score snapshots (cold-start guard — no eviction on sparse data).
  2. The last 3 snapshots all scored < 30/100 (continuously underperforming).
  3. Evicting this site would NOT drop active_count below MIN_WHITELIST=5 (hard floor).

Action: set status='benched' (not 'evicted' — the human can manually reinstate).
Writes:  $RUN_DIR/score/evictions.json  (list of benched domains + reasons).

Usage:
    python3 evict_underperformers.py \
        --project-url "https://memecoinist.com" \
        [--evictions-out $RUN_DIR/score/evictions.json] \
        [--db ~/.openclaw-backlink/data/backlink.db]

Prints:
    EVICT_OK: evicted=N kept=M active_after=K
    EVICT_FLOOR_HIT: would have evicted N but floor protects them
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_PIPELINE_DIR = os.path.dirname(__file__)
sys.path.insert(0, _PIPELINE_DIR)

from whitelist_db import (
    DEFAULT_DB_PATH,
    MIN_WHITELIST,
    init_whitelist_db,
    upsert_project,
    get_project_id,
    get_active_whitelist,
    get_recent_scores,
    count_active_sites,
    set_site_status,
)

UNDERPERFORM_THRESHOLD = 30.0   # score < this is considered underperforming
MIN_SNAPSHOTS = 5               # need this many history rows before eligible
LAST_N_BAD = 3                  # all of last N must be below threshold


def find_candidates(project_id: int, db_path: str) -> list[dict]:
    """Return list of site dicts that are eligible for eviction."""
    active = get_active_whitelist(project_id, db_path=db_path)
    candidates = []
    for site in active:
        wl_id = site["id"]
        scores = get_recent_scores(wl_id, limit=50, days=90, db_path=db_path)
        if len(scores) < MIN_SNAPSHOTS:
            continue  # cold-start guard
        last_n = scores[:LAST_N_BAD]
        if len(last_n) < LAST_N_BAD:
            continue
        if all(r["score_0_100"] < UNDERPERFORM_THRESHOLD for r in last_n):
            avg = sum(r["score_0_100"] for r in last_n) / LAST_N_BAD
            candidates.append({**site, "_avg_last3": round(avg, 2)})
    return candidates


def evict(
    project_url: str,
    evictions_out: str | None = None,
    db_path: str = DEFAULT_DB_PATH,
) -> tuple[int, int]:
    """Bench underperformers. Returns (evicted_count, floor_protected_count)."""
    init_whitelist_db(db_path)
    project_id = get_project_id(project_url, db_path=db_path)
    if project_id is None:
        # Project not registered yet — nothing to evict
        return 0, 0
    candidates = find_candidates(project_id, db_path=db_path)

    evicted = []
    floor_protected = []

    for cand in candidates:
        active_now = count_active_sites(project_id, db_path=db_path)
        if active_now <= MIN_WHITELIST:
            floor_protected.append(cand)
            continue
        set_site_status(cand["id"], "benched", db_path=db_path)
        evicted.append({
            "domain": cand["domain"],
            "avg_last3_score": cand["_avg_last3"],
            "reason": f"Last {LAST_N_BAD} scores all < {UNDERPERFORM_THRESHOLD}",
        })

    if evictions_out:
        os.makedirs(os.path.dirname(os.path.abspath(evictions_out)), exist_ok=True)
        with open(evictions_out, "w", encoding="utf-8") as f:
            json.dump({
                "evicted": evicted,
                "floor_protected": [c["domain"] for c in floor_protected],
                "active_after": count_active_sites(project_id, db_path=db_path),
            }, f, indent=2, ensure_ascii=False)

    return len(evicted), len(floor_protected)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evict underperforming whitelist sites")
    parser.add_argument("--project-url", required=True, dest="project_url")
    parser.add_argument("--evictions-out", default=None, dest="evictions_out")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, dest="db_path")
    args = parser.parse_args()

    init_whitelist_db(args.db_path)
    evicted, protected = evict(args.project_url, evictions_out=args.evictions_out, db_path=args.db_path)
    project_id = get_project_id(args.project_url, db_path=args.db_path) or 0
    active_after = count_active_sites(project_id, db_path=args.db_path) if project_id else 0

    if protected:
        print(f"EVICT_FLOOR_HIT: evicted={evicted} floor_protected={protected} active_after={active_after}")
    else:
        print(f"EVICT_OK: evicted={evicted} active_after={active_after}")


if __name__ == "__main__":
    main()
