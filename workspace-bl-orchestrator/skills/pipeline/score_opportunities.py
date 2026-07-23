#!/usr/bin/env python3
"""score_opportunities.py — Canonical deterministic 0-100 scoring for opportunities and sites.

Two-level scoring:
  1. Per-opportunity score (0-100) — used for best-to-worst ranking.
     Formula:
       platform_weight_score = platform_weight * 30   (0-30)
       recency_score_part    = recency_score   * 30   (0-30; from opportunity_freshness field)
       niche_overlap_part    = niche_overlap   * 20   (0-20; derived from relevance_score if present)
       host_usability_part   = (host_usability / 100) * 10  (0-10; from whitelist DB)
       freshness_bonus_part  = freshness_bonus * 10   (0-10; extra boost for <24h posts)
       total = clamp(sum, 0, 100)

  2. Site usability score (0-100) — used for eviction decisions.
     Computed from rolling 30-day feedback_events + site_score_history:
       approve_rate  = approvals / max(approvals + rejects, 1)
       delivery_rate = opportunities_emitted / max(scan_count, 1)   (proxy for scan productivity)
       freshness_rate = 1.0 if last_scanned <= 7 days ago else 0.5
       usability = clamp((approve_rate*50) + (delivery_rate*25) + (freshness_rate*25), 0, 100)

Reads:   $RUN_DIR/scan/deduped.json
Writes:  $RUN_DIR/score/scored.json
         (also updates whitelist_sites.current_usability_score + appends site_score_history)

Usage:
    python3 score_opportunities.py \
        --deduped    $RUN_DIR/scan/deduped.json \
        --scored-out $RUN_DIR/score/scored.json \
        --project-url "https://memecoinist.com" \
        --niche "crypto memecoins" \
        [--db ~/.openclaw-backlink/data/backlink.db]

Prints:
    SCORE_OK: scored=N sites_updated=M
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

_PIPELINE_DIR = os.path.dirname(__file__)
sys.path.insert(0, _PIPELINE_DIR)
_SEARCH_DIR = os.path.abspath(os.path.join(_PIPELINE_DIR, "..", "search"))
if _SEARCH_DIR not in sys.path:
    sys.path.insert(0, _SEARCH_DIR)

from whitelist_db import (
    DEFAULT_DB_PATH,
    init_whitelist_db,
    upsert_project,
    get_active_whitelist,
    get_recent_scores,
    append_score_history,
    update_site_usability_score,
    touch_last_scanned,
    _connect,
)

# Regexes for parsing freshness strings like "~2 hours ago", "~3 days ago"
_AGO_RE = re.compile(r"(\d+)\s*(second|minute|hour|day|week|month|year)s%s\s*ago", re.I)


def _parse_recency_hours(freshness_str: str) -> float | None:
    m = _AGO_RE.search(str(freshness_str))
    if not m:
        return None
    n = int(m.group(1))
    unit = m.group(2).lower()
    mapping = {
        "second": 1 / 3600, "minute": 1 / 60, "hour": 1.0,
        "day": 24.0, "week": 168.0, "month": 720.0, "year": 8760.0,
    }
    return n * mapping.get(unit, 720.0)


def _recency_score(hours: float | None) -> float:
    """0-1 recency score (higher = more recent)."""
    if hours is None:
        return 0.5
    if hours <= 2:
        return 1.0
    if hours <= 24:
        return 0.9
    if hours <= 72:
        return 0.75
    if hours <= 168:
        return 0.6
    if hours <= 720:
        return 0.4
    return 0.2


def _freshness_bonus(hours: float | None) -> float:
    """Extra 0-1 bonus for very fresh (<24h) posts."""
    if hours is None:
        return 0.0
    return 1.0 if hours <= 24 else 0.0


def score_opportunity(opp: dict, host_usability: float, terms: list[str] | None = None) -> float:
    """Compute 0-100 per-opportunity score. Professional SEO Scoring."""
    platform_weight = float(opp.get("platform_weight") or 0.55)
    freshness_str = str(opp.get("opportunity_freshness") or "")
    hours = _parse_recency_hours(freshness_str)

    # Niche overlap from title/excerpt when terms provided; else use stored relevance.
    if terms:
        from discover import niche_overlap_score  # noqa: E402 — search dir on path via caller
        title = str(opp.get("target_title") or "")
        excerpt = str(opp.get("target_excerpt") or "")
        relevance = niche_overlap_score(title, excerpt, terms)
        if relevance is None:
            relevance = 5.0
        opp["relevance_score"] = relevance
    else:
        stored = opp.get("relevance_score")
        if stored is not None:
            relevance = float(stored)
        else:
            relevance = 5.0

    # 1. Domain Metrics (40 points)
    # Fallback to platform_weight if domain_authority is not present
    da = opp.get("domain_authority")
    if da is not None:
        authority_score = (da / 100.0) * 40
    else:
        authority_score = platform_weight * 40
        
    # 2. Semantic Relevance (30 points)
    relevance_score = (relevance / 10.0) * 30
    
    # 3. Link Quality (20 points)
    is_dofollow = opp.get("is_dofollow")
    if is_dofollow is None:
        is_dofollow = True
    obl = opp.get("outbound_link_count")
    if obl is None:
        obl = 0
    
    link_quality_base = 20 if is_dofollow else 10 # 50% penalty for nofollow
    obl_penalty = min(10, obl / 10.0) # -1 point per 10 OBL, max 10 points lost
    link_quality_score = max(0.0, link_quality_base - obl_penalty)
    
    # 4. Freshness (10 points)
    freshness_score = _recency_score(hours) * 10

    raw = authority_score + relevance_score + link_quality_score + freshness_score
    total_score = round(max(0.0, min(100.0, raw)), 2)
    
    # Confidence Metric (re-weighted)
    confidence = int(min(100, max(0, (relevance_score / 30 * 40) + (authority_score / 40 * 30) + (link_quality_score / 20 * 30))))
    
    breakdown = {
        "authority": round(authority_score, 2),
        "relevance": round(relevance_score, 2),
        "link_quality": round(link_quality_score, 2),
        "freshness": round(freshness_score, 2)
    }
    
    reasoning = []
    if authority_score >= 30:
        reasoning.append("High Authority Domain")
    if relevance_score >= 25:
        reasoning.append("Strong semantic overlap")
    if link_quality_score >= 15:
        reasoning.append("High Link Equity (Dofollow, Low OBL)")
    elif link_quality_score <= 10:
        reasoning.append("Low Link Equity (Nofollow or High OBL)")
    if freshness_score >= 8:
        reasoning.append("Recent active discussion")
        
    if not reasoning:
        reasoning.append("Standard opportunity")
        
    opp["score_breakdown"] = breakdown
    opp["confidence"] = confidence
    opp["reasoning"] = reasoning
    
    return total_score


def compute_site_usability(
    whitelist_site_id: int,
    db_path: str,
) -> tuple[float, dict]:
    """Compute 0-100 site usability from recent feedback + history. Returns (score, stats_dict)."""
    recent = get_recent_scores(whitelist_site_id, limit=30, days=30, db_path=db_path)

    total_approvals = sum(r["approvals"] for r in recent)
    total_rejects = sum(r["rejects"] for r in recent)
    total_emitted = sum(r["opportunities_emitted"] for r in recent)
    scan_count = len(recent)

    approve_rate = total_approvals / max(total_approvals + total_rejects, 1)
    delivery_rate = min(total_emitted / max(scan_count * 5, 1), 1.0)  # cap at 1; 5 opps/scan is "full"

    # freshness: was the site scanned recently%s
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT julianday('now') - julianday(last_scanned_at) AS days_since
            FROM whitelist_sites WHERE id = %s
            """,
            (whitelist_site_id,),
        ).fetchone()
    days_since = float(row["days_since"]) if (row and row["days_since"] is not None) else 999
    freshness_rate = 1.0 if days_since <= 7 else 0.5

    usability = round(
        max(0.0, min(100.0, (approve_rate * 50) + (delivery_rate * 25) + (freshness_rate * 25))),
        2,
    )
    stats = {
        "approvals": total_approvals,
        "rejects": total_rejects,
        "opportunities_emitted": total_emitted,
        "scan_count": scan_count,
        "approve_rate": round(approve_rate, 3),
        "delivery_rate": round(delivery_rate, 3),
        "freshness_rate": freshness_rate,
    }
    return usability, stats


def main() -> None:
    parser = argparse.ArgumentParser(description="Score opportunities 0-100 (deterministic)")
    parser.add_argument("--deduped", required=True, help="Path to scan/deduped.json")
    parser.add_argument("--scored-out", required=True, dest="scored_out")
    parser.add_argument("--project-url", required=True, dest="project_url")
    parser.add_argument("--niche", default="")
    parser.add_argument("--run-id", default="", dest="run_id")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, dest="db_path")
    args = parser.parse_args()

    if not os.path.isfile(args.deduped):
        print(f"SCORE_ERROR: file not found: {args.deduped}", file=sys.stderr)
        sys.exit(1)

    with open(args.deduped, encoding="utf-8") as f:
        raw = json.load(f)

    opportunities = raw.get("opportunities", raw.get("sites", [])) if isinstance(raw, dict) else raw

    init_whitelist_db(args.db_path)
    project_id = upsert_project(args.project_url, args.niche, db_path=args.db_path)

    # Build domain → whitelist_site_id + usability map
    active_sites = get_active_whitelist(project_id, db_path=args.db_path)
    domain_to_wl = {s["domain"]: s for s in active_sites}
    site_usability_cache: dict[str, float] = {}
    sites_updated = 0

    for site in active_sites:
        wl_id = site["id"]
        usability, stats = compute_site_usability(wl_id, args.db_path)
        site_usability_cache[site["domain"]] = usability

        # Update persistent usability score and append history row
        update_site_usability_score(wl_id, usability, db_path=args.db_path)
        append_score_history(
            wl_id,
            score_0_100=usability,
            approvals=stats["approvals"],
            rejects=stats["rejects"],
            opportunities_emitted=stats["opportunities_emitted"],
            db_path=args.db_path,
        )
        touch_last_scanned(wl_id, db_path=args.db_path)
        sites_updated += 1

    # Score each opportunity
    scored = []
    for opp in opportunities:
        domain = str(opp.get("domain") or opp.get("platform") or "").lower().lstrip("www.")
        host_usability = site_usability_cache.get(domain, 50.0)  # neutral fallback for unlisted
        opp_score = score_opportunity(opp, host_usability)
        scored.append({
            **opp,
            "score_100": opp_score,
            "host_usability": host_usability,
        })

    # Sanity check: if all scores are 0 fall back to recency ordering (same formula, just platform_weight=0.55)
    if scored and all(s["score_100"] == 0 for s in scored):
        for s in scored:
            opp_score = score_opportunity({**s, "platform_weight": 0.55}, 50.0)
            s["score_100"] = opp_score
            # breakdown is updated internally by score_opportunity since we passed a copy, we need to extract it
            # wait, if we passed a copy, we should get it back
            dummy = {**s, "platform_weight": 0.55}
            opp_score = score_opportunity(dummy, 50.0)
            s["score_100"] = opp_score
            s["score_breakdown"] = dummy.get("score_breakdown", {})
            s["confidence"] = dummy.get("confidence", 0)
            s["reasoning"] = dummy.get("reasoning", [])

    output = {
        "status": "ok",
        "project_url": args.project_url,
        "niche": args.niche,
        "run_id": args.run_id,
        "opportunities": scored,
        "sites_scored": sites_updated,
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.scored_out)), exist_ok=True)
    with open(args.scored_out, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"SCORE_OK: scored={len(scored)} sites_updated={sites_updated}")


if __name__ == "__main__":
    main()
