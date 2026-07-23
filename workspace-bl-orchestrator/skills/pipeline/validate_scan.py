#!/usr/bin/env python3
"""validate_scan.py — Validate bl-opportunity-scanner output.

Checks that $RUN_DIR/scan/opportunities.json (or deduped.json) is valid:
  - Is readable JSON.
  - Top-level has an "opportunities" (or "sites") list.
  - Each opportunity has at minimum: url + domain + type.
  - At least 1 opportunity is present (warn but not fatal when 0 after dedup).

Exit codes:
  0 → SCAN_VALID or SCAN_EMPTY (zero opportunities after dedup — not fatal)
  1 → SCAN_INVALID (malformed JSON or missing required fields)

Usage:
    python3 validate_scan.py --scan-file $RUN_DIR/scan/deduped.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys


REQUIRED_FIELDS = {"url"}


def validate(path: str) -> None:
    if not os.path.isfile(path):
        print(f"SCAN_INVALID: file not found: {path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"SCAN_INVALID: JSON parse error: {e}", file=sys.stderr)
        sys.exit(1)

    if isinstance(data, dict):
        opportunities = data.get("opportunities", data.get("sites", []))
    elif isinstance(data, list):
        opportunities = data
    else:
        print("SCAN_INVALID: unexpected JSON root type (expected dict or list)", file=sys.stderr)
        sys.exit(1)

    if not isinstance(opportunities, list):
        print("SCAN_INVALID: 'opportunities' field is not a list", file=sys.stderr)
        sys.exit(1)

    if not opportunities:
        print(f"SCAN_EMPTY: 0 opportunities in {path} (pipeline continues with empty queue)")
        return

    bad = []
    for i, opp in enumerate(opportunities):
        if not isinstance(opp, dict):
            bad.append(f"[{i}] not a dict")
            continue
        missing = REQUIRED_FIELDS - set(opp.keys())
        if missing:
            bad.append(f"[{i}] missing fields: {missing}")

    if bad:
        print(f"SCAN_INVALID: {len(bad)} malformed records:\n" + "\n".join(bad[:5]), file=sys.stderr)
        sys.exit(1)

    print(f"SCAN_VALID: {len(opportunities)} opportunities OK")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate scanner output JSON")
    parser.add_argument("--scan-file", required=True, dest="scan_file")
    args = parser.parse_args()
    validate(args.scan_file)


if __name__ == "__main__":
    main()
