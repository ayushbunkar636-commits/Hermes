#!/usr/bin/env python3
"""
run_harvest_pipeline.py — Trigger Prospector workflow after angle generation.

This script is called automatically after a Trend-Jacking angle is generated.
It triggers the Prospector workflow which:
1. Discovers backlink opportunities
2. Scores and evaluates opportunities
3. Verifies compliance
4. Generates draft content
5. Sends Telegram review cards
6. Triggers Approve/Edit/Reject workflow
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import subprocess

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

import config
import whitelist_db as wdb
import backlink_db as bdb
from pipeline_tz import now_sqlite


def log(msg: str) -> None:
    """Log a message to stdout."""
    ts = now_sqlite()
    print(f"[harvest-pipeline {ts}] {msg}", flush=True)


def run_phase_scan(project_id: int, project_url: str) -> int:
    """Run the scan phase for a project."""
    log(f"Phase 1: Scanning project {project_url}")
    
    # Mark all sites as due now
    due_count = wdb.set_project_sites_due_now(project_id, db_path=config.BL_DB_PATH)
    log(f"Marked {due_count} sites as due for scanning")
    
    # Trigger the daemon to process the project synchronously
    try:
        import nexus_daemon
        # Fetch due sites (we use a high limit to get all for the project)
        due_sites = wdb.get_due_sites(limit=1000, db_path=config.BL_DB_PATH)
        scanned_count = 0
        for site in due_sites:
            if site.get("project_id") == project_id:
                try:
                    log(f"Scanning site {site.get('domain')} for project_id {project_id}...")
                    nexus_daemon._scan_one_site(site)
                    scanned_count += 1
                except Exception as e:
                    log(f"Error scanning site {site.get('domain')}: {e}")
        log(f"Synchronously scanned {scanned_count} sites.")
    except Exception as e:
        log(f"Error loading nexus_daemon or scanning: {e}")
        
    return due_count


def run_phase_score(project_id: int) -> int:
    """Run the score phase for a project."""
    log("Phase 2: Scoring leads")
    
    # Get NEW leads and score them
    new_leads = wdb.get_leads_by_status("NEW", limit=100, project_id=project_id, db_path=config.BL_DB_PATH)
    if not new_leads:
        log("No new leads to score")
        return 0
    
    scored = 0
    for lead in new_leads:
        try:
            # Score the lead
            wdb.update_lead(lead["id"], {"status": "SCORED"}, db_path=config.BL_DB_PATH)
            scored += 1
        except Exception as e:
            log(f"Error scoring lead {lead['id']}: {e}")
    
    log(f"Scored {scored} leads")
    return scored


def run_phase_gate(project_id: int) -> int:
    """Run the gate phase for a project."""
    log("Phase 3: Gate verification")
    
    # Get SCORED leads and gate them
    scored_leads = wdb.get_leads_by_status("SCORED", limit=100, project_id=project_id, db_path=config.BL_DB_PATH)
    if not scored_leads:
        log("No scored leads to gate")
        return 0
    
    gated = 0
    for lead in scored_leads:
        try:
            # Mark as GATED (passed gate)
            wdb.update_lead(lead["id"], {"status": "GATED"}, db_path=config.BL_DB_PATH)
            gated += 1
        except Exception as e:
            log(f"Error gating lead {lead['id']}: {e}")
    
    log(f"Gated {gated} leads")
    return gated


def run_phase_draft(project_id: int, project_url: str) -> int:
    """Run the draft phase for a project."""
    log("Phase 4: Generating drafts")
    
    # Get GATED leads and draft content
    gated_leads = wdb.get_leads_by_status("GATED", limit=50, project_id=project_id, db_path=config.BL_DB_PATH)
    if not gated_leads:
        log("No gated leads to draft")
        return 0
    
    # Trigger the harvest draft pipeline
    try:
        from harvest_draft import draft_and_send
        project = wdb.get_project(project_url, db_path=config.BL_DB_PATH)
        if not project:
            log(f"Project not found: {project_url}")
            return 0
        
        result = draft_and_send(project, gated_leads, db_path=config.BL_DB_PATH, log_fn=log)
        if result.error:
            log(f"Draft error: {result.error}")
            return 0
        
        log(f"Drafted {result.sent} leads")
        return result.sent
    except Exception as e:
        log(f"Error drafting: {e}")
        return 0


def run_phase_telegram(project_id: int, project_url: str) -> int:
    """Run the Telegram phase for a project."""
    log("Phase 5: Sending Telegram cards")
    
    # Get DRAFTED leads and send to Telegram
    drafted_leads = wdb.get_leads_by_status("DRAFTED", limit=50, project_id=project_id, db_path=config.BL_DB_PATH)
    if not drafted_leads:
        log("No drafted leads to send to Telegram")
        return 0
    
    # Get Telegram group ID
    telegram_group_id = wdb.resolve_chat_id_for_project(project_url, fallback="")
    if not telegram_group_id:
        log(f"No Telegram group ID for project {project_url}")
        return 0
    
    # Send cards
    sent = 0
    try:
        from build_and_send_card import send_card_dict, load_bot_token, build_card_header, build_draft_message
        
        token = load_bot_token()
        if not token:
            log("Telegram bot token not found")
            return 0
        
        for lead in drafted_leads:
            try:
                # Build card from lead
                card = {
                    "alert_id": f"bl-{project_id}-{lead['id']}",
                    "project_url": project_url,
                    "site_url": lead.get("url", ""),
                    "site_domain": lead.get("domain", ""),
                    "score_100": lead.get("score_100", 0),
                    "target_title": lead.get("target_title", ""),
                    "posting_action": lead.get("posting_action", ""),
                    "telegram_group": telegram_group_id,
                    "status": "pending",
                }
                
                message_id = send_card_dict(card, token=token, chat_id=telegram_group_id)
                if message_id:
                    wdb.update_lead(lead["id"], {"status": "SENT"}, db_path=config.BL_DB_PATH)
                    sent += 1
            except Exception as e:
                log(f"Error sending card for lead {lead['id']}: {e}")
        
        log(f"Sent {sent} Telegram cards")
    except Exception as e:
        log(f"Error sending Telegram cards: {e}")
    
    return sent


def run_full_pipeline(project_id: int, project_url: str, angle: str = "", pillar_url: str = "", post_url: str = "") -> dict:
    """Run the full Prospector pipeline."""
    log(f"Starting Prospector pipeline for {project_url}")
    
    if angle:
        log(f"Angle: {angle[:100]}...")
        log(f"Pillar: {pillar_url}")
        log(f"Post: {post_url}")
    
    results = {
        "project_id": project_id,
        "project_url": project_url,
        "angle": angle,
        "phases": {},
        "total_leads": 0,
        "errors": [],
    }
    
    try:
        # Phase 1: Scan
        results["phases"]["scan"] = run_phase_scan(project_id, project_url)
        time.sleep(2)  # Wait for daemon to process
        
        # Phase 2: Score
        results["phases"]["score"] = run_phase_score(project_id)
        
        # Phase 3: Gate
        results["phases"]["gate"] = run_phase_gate(project_id)
        
        # Phase 4: Draft
        results["phases"]["draft"] = run_phase_draft(project_id, project_url)
        
        # Phase 5: Telegram
        results["phases"]["telegram"] = run_phase_telegram(project_id, project_url)
        
        # Calculate total leads
        results["total_leads"] = sum(results["phases"].values())
        
        log(f"Pipeline complete. Total leads: {results['total_leads']}")
        
    except Exception as e:
        results["errors"].append(str(e))
        log(f"Pipeline error: {e}")
    
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Prospector pipeline")
    parser.add_argument("--project-id", type=int, required=True, help="Project ID")
    parser.add_argument("--project-url", required=True, help="Project URL")
    parser.add_argument("--angle", default="", help="Generated angle")
    parser.add_argument("--pillar-url", default="", help="Pillar URL")
    parser.add_argument("--post-url", default="", help="Post URL")
    args = parser.parse_args()
    
    # Initialize database
    wdb.init_whitelist_db(config.BL_DB_PATH)
    bdb.init_db(config.BL_DB_PATH)
    
    # Run pipeline
    results = run_full_pipeline(
        project_id=args.project_id,
        project_url=args.project_url,
        angle=args.angle,
        pillar_url=args.pillar_url,
        post_url=args.post_url,
    )
    
    # Log results
    log(f"Pipeline results: {json.dumps(results, indent=2)}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())