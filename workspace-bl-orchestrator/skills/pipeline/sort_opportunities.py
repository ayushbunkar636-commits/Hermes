#!/usr/bin/env python3
"""sort_opportunities.py — Sort scored opportunities best-to-worst and cap for content gen.

Reads $RUN_DIR/score/scored.json (from score_opportunities.py).
Sorts descending by score_100. Caps to --top-n (default 30) entries.
Writes content_queue.json (the input bl-content receives).

The output preserves all fields from scored.json but adds:
  rank  (1-based, 1=best)

Usage:
    python3 sort_opportunities.py \
        --scored    $RUN_DIR/score/scored.json \
        --out       $RUN_DIR/content_queue.json \
        [--top-n 30]

Prints:
    SORT_OK: total=N emitting=M (top_score=X.X lowest_score=Y.Y)
    SORT_EMPTY: no opportunities to sort (not fatal — pipeline sends zero cards)
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def sort_and_cap(
    scored_path: str,
    out_path: str,
    top_n: int = 30,
) -> tuple[int, int]:
    """Sort and cap. Returns (total_input, total_emitted)."""
    if not os.path.isfile(scored_path):
        print(f"SORT_ERROR: file not found: {scored_path}", file=sys.stderr)
        sys.exit(1)

    with open(scored_path, encoding="utf-8") as f:
        raw = json.load(f)

    if isinstance(raw, dict):
        opportunities = raw.get("opportunities", raw.get("sites", []))
        meta = {k: v for k, v in raw.items() if k not in ("opportunities", "sites")}
    else:
        opportunities = raw
        meta = {}

    total = len(opportunities)

    if not opportunities:
        out = {**meta, "status": "ok", "opportunities": []}
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        return 0, 0

    # Sort descending by score_100 (fall back to 0 if missing)
    sorted_opps = sorted(opportunities, key=lambda o: float(o.get("score_100") or 0), reverse=True)
    capped = sorted_opps[:top_n]

    # Add rank field (1-based)
    for i, opp in enumerate(capped, start=1):
        opp["rank"] = i

    out = {**meta, "status": "ok", "opportunities": capped}
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)

    return total, len(capped)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sort scored opportunities best-to-worst and cap")
    parser.add_argument("--scored", required=True, help="Path to score/scored.json")
    parser.add_argument("--out", required=True, help="Output path for content_queue.json")
    parser.add_argument("--top-n", type=int, default=30, dest="top_n")
    args = parser.parse_args()

    total, emitted = sort_and_cap(args.scored, args.out, top_n=args.top_n)

    if emitted == 0:
        print("SORT_EMPTY: no opportunities to sort")
    else:
        with open(args.out, encoding="utf-8") as f:
            data = json.load(f)
        opps = data.get("opportunities", [])
        top = opps[0].get("score_100", 0) if opps else 0
        low = opps[-1].get("score_100", 0) if opps else 0
        print(f"SORT_OK: total={total} emitting={emitted} top_score={top} lowest_score={low}")


if __name__ == "__main__":
    main()
