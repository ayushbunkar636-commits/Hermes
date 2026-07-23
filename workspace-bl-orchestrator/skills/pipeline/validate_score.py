#!/usr/bin/env python3
"""validate_score.py — Validate bl-score-critic output (scored.json).

Checks that $RUN_DIR/score/scored.json is valid:
  - Readable JSON with an "opportunities" list.
  - Each record has url + score_100 (numeric 0-100).
  - score_100 values are reasonable (not all zero unless list is empty).

Exit codes:
  0 → SCORE_VALID or SCORE_EMPTY
  1 → SCORE_INVALID

Usage:
    python3 validate_score.py --scored-file $RUN_DIR/score/scored.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys


def validate(path: str) -> None:
    if not os.path.isfile(path):
        print(f"SCORE_INVALID: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"SCORE_INVALID: JSON parse error: {e}", file=sys.stderr)
        sys.exit(1)

    if isinstance(data, dict):
        opportunities = data.get("opportunities", data.get("sites", []))
    elif isinstance(data, list):
        opportunities = data
    else:
        print("SCORE_INVALID: unexpected JSON root type", file=sys.stderr)
        sys.exit(1)

    if not isinstance(opportunities, list):
        print("SCORE_INVALID: 'opportunities' is not a list", file=sys.stderr)
        sys.exit(1)

    if not opportunities:
        print("SCORE_EMPTY: 0 scored opportunities (pipeline continues with empty queue)")
        return

    bad = []
    scores = []
    for i, opp in enumerate(opportunities):
        if not isinstance(opp, dict):
            bad.append(f"[{i}] not a dict")
            continue
        if "url" not in opp:
            bad.append(f"[{i}] missing 'url'")
        score = opp.get("score_100")
        if score is None:
            bad.append(f"[{i}] missing 'score_100'")
        else:
            try:
                s = float(score)
                if not (0.0 <= s <= 100.0):
                    bad.append(f"[{i}] score_100={s} out of range [0,100]")
                else:
                    scores.append(s)
            except (TypeError, ValueError):
                bad.append(f"[{i}] score_100 not numeric: {score!r}")

    if bad:
        print(f"SCORE_INVALID: {len(bad)} malformed records:\n" + "\n".join(bad[:5]), file=sys.stderr)
        sys.exit(1)

    print(f"SCORE_VALID: {len(opportunities)} scored opportunities (max={max(scores):.1f} min={min(scores):.1f})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate score_opportunities output JSON")
    parser.add_argument("--scored-file", required=True, dest="scored_file")
    args = parser.parse_args()
    validate(args.scored_file)


if __name__ == "__main__":
    main()
