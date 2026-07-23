#!/usr/bin/env python3
"""compliance_engine.py — Google Guidelines Compliance Engine."""

import json

def check_compliance(lead: dict) -> tuple[bool, str]:
    """
    Evaluates a lead against strict Google Spam Policies.
    Returns (True, "") if compliant.
    Returns (False, "reason") if it violates guidelines.
    """
    raw_json_str = lead.get("raw_json", "{}")
    try:
        raw_dict = json.loads(raw_json_str) if isinstance(raw_json_str, str) else raw_json_str
    except Exception:
        raw_dict = {}

    obl = int(raw_dict.get("outbound_link_count", 0))
    is_dofollow = raw_dict.get("is_dofollow", True)
    
    # Extract calculated metrics from the lead (since score_breakdown is not saved in Postgres)
    relevance = float(lead.get("relevance_score") or 0.0)
    
    da = lead.get("domain_authority")
    if da is not None:
        authority = (float(da) / 100.0) * 40
    else:
        platform_weight = float(lead.get("platform_weight") or 0.5)
        authority = platform_weight * 40
    
    # RULE 1: Link Farm Detection
    # If OBL > 100 on a dofollow page, it's highly likely a link farm or spam board
    if obl > 100 and is_dofollow:
        return False, f"compliance_failure: excessive_obl ({obl} links)"
        
    # RULE 2: Relevance Threshold
    # The database stores relevance_score on a 0-10 scale.
    # We want at least 3.33/10 (equivalent to the old 10/30 threshold)
    if relevance < 3.33:
        return False, f"compliance_failure: off_topic (relevance {relevance}/10.0)"
        
    # RULE 3: Authority Floor
    # If the domain authority/weight is < 5 out of 40, it's not worth placing
    if authority < 5.0:
        return False, f"compliance_failure: low_authority (auth {authority}/40)"
        
    return True, ""
