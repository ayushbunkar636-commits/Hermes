#!/usr/bin/env python3
"""
build_platform_queue.py — Build a ranked platform search queue from platforms.json.

Pure, offline, testable. No network calls.

CLI usage:
  python3 build_platform_queue.py --niche "crypto wallets" [--out /tmp/queue.json] [--extra "bitcointalk.org,0.75"]

Output JSON:
  [
    {"domain": "reddit.com", "tier": 1, "weight": 1.0, "freshness": "day", "site_operator": "site:reddit.com",
     "label": "Reddit", "types": [...], "notes": "...", "niche_queries": [...]},
    ...
  ]

The agent may APPEND niche-specific platforms by editing the output file before using it,
or pass --extra "domain,weight" items directly.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


PLATFORMS_JSON = os.path.join(os.path.dirname(__file__), "platforms.json")


def load_platforms(path: str = PLATFORMS_JSON) -> list[dict]:
    """Load and return the tier data from platforms.json."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("tiers", [])


def build_niche_queries(platform: dict, niche: str) -> list[str]:
    """Generate concrete search queries for this platform + niche combination."""
    op = platform.get("site_operator", f"site:{platform['domain']}")
    types = platform.get("types", [])
    queries: list[str] = []

    # Primary query: site-scoped niche search
    queries.append(f"{op} {niche}")

    # Discussion/forum-first: add opinion and comparison queries for discussion platforms
    if "forum" in types or "qa_community" in types:
        queries.append(f"{op} {niche} opinions")
        queries.append(f"{op} anyone using {niche}")
        queries.append(f"{op} {niche} vs")
        queries.append(f"{op} {niche} recommend")
        queries.append(f"{op} {niche} worth it")
    if "qa_community" in types:
        queries.append(f"{op} {niche} best tools")
        queries.append(f"{op} {niche} help")
    if "content_syndication" in types:
        queries.append(f"{op} {niche} write for us")
        queries.append(f"{op} {niche} guest post")
    if "product_listing" in types:
        queries.append(f"{op} {niche} alternatives")
    if "directory" in types:
        queries.append(f"{op} {niche} submit")
    if "resource_page" in types:
        queries.append(f"{op} {niche} resources list")

    # Dedupe while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            deduped.append(q)
    return deduped


def build_queue(
    niche: str,
    platforms_path: str = PLATFORMS_JSON,
    extra: list[tuple[str, float]] | None = None,
) -> list[dict[str, Any]]:
    """
    Build ordered queue (highest tier first, then by weight desc within same tier).
    extra: list of (domain, weight) tuples to append as niche-specific platforms.
    Returns list of platform dicts with niche_queries filled in.
    """
    tiers = load_platforms(platforms_path)

    queue: list[dict[str, Any]] = []
    for tier_data in sorted(tiers, key=lambda t: t["tier"]):
        tier_num = tier_data["tier"]
        tier_weight = tier_data["weight"]
        for platform in tier_data.get("platforms", []):
            # Allow per-platform weight override
            weight = platform.get("weight_override", tier_weight)
            entry: dict[str, Any] = {
                "domain": platform["domain"],
                "tier": tier_num,
                "weight": weight,
                "site_operator": platform.get("site_operator", f"site:{platform['domain']}"),
                "label": platform.get("label", platform["domain"]),
                "types": platform.get("types", []),
                "notes": platform.get("notes", ""),
                "niche_queries": build_niche_queries(platform, niche),
            }
            queue.append(entry)

    # Append extra niche-specific platforms (agent-provided)
    if extra:
        for domain, w in extra:
            domain = domain.strip().lower()
            if not domain:
                continue
            entry = {
                "domain": domain,
                "tier": 5,
                "weight": w,
                "site_operator": f"site:{domain}",
                "label": domain,
                "types": ["forum", "qa_community"],
                "notes": "Agent-appended niche-specific platform.",
                "niche_queries": [
                    f"site:{domain} {niche}",
                    f"site:{domain} {niche} opinions",
                    f"site:{domain} anyone using {niche}",
                ],
            }
            queue.append(entry)

    # Sort: tier asc, weight desc
    queue.sort(key=lambda e: (e["tier"], -e["weight"]))
    return queue


def main() -> None:
    parser = argparse.ArgumentParser(description="Build ranked platform search queue")
    parser.add_argument("--niche", required=True, help="Niche/topic string (e.g. 'crypto wallets')")
    parser.add_argument("--out", help="Write JSON queue to this file path")
    parser.add_argument(
        "--extra",
        default="",
        help="Comma-separated extra platforms: 'domain1,weight1;domain2,weight2'",
    )
    args = parser.parse_args()

    extra: list[tuple[str, float]] = []
    if args.extra:
        for item in args.extra.split(";"):
            parts = item.strip().split(",")
            if len(parts) == 2:
                try:
                    extra.append((parts[0].strip(), float(parts[1].strip())))
                except ValueError:
                    pass

    queue = build_queue(args.niche, extra=extra or None)
    output = json.dumps(queue, indent=2)
    print(output)
    if args.out:
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(output)


if __name__ == "__main__":
    main()
