#!/usr/bin/env python3
"""nexus_daemon.py — The 24/7 Harvest Loop ("Farmer" heartbeat)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

from pipeline_tz import now_sqlite  # noqa: E402
from pipeline_log import plog_info, plog_verbose, plog_trace, truncate, level_enabled  # noqa: E402

import whitelist_db as wdb  # noqa: E402
import backlink_db as bdb  # noqa: E402
from harvester_registry import harvest_site, STATUS_OK, STATUS_BLOCKED  # noqa: E402
from rearm_leads import process_rearm  # noqa: E402
from vocab_miner import mine_project_vocab  # noqa: E402
from harvesters._common import extract_domains_from_text  # noqa: E402
from quality_gate import gate_leads  # noqa: E402
from score_opportunities import score_opportunity  # noqa: E402
from compliance_engine import check_compliance  # noqa: E402
from harvest_draft import draft_and_send  # noqa: E402
from resend_pending import resend_one_opportunity  # noqa: E402
import config
import hermes_client

# V2.0 Relevancy Engine imports (graceful fallback if not yet installed)
try:
    _SEARCH_SKILLS_DIR = os.path.abspath(os.path.join(_PIPELINE_DIR, '..', 'search'))
    if _SEARCH_SKILLS_DIR not in sys.path:
        sys.path.insert(0, _SEARCH_SKILLS_DIR)
    from trend_ingestion import ingest_trends
    from sitemap_scanner import scan_project_sitemap
    from relevancy_engine import generate_relevancy_map, get_project_sitemap, get_latest_trend
    _V2_ENABLED = True
except ImportError:
    _V2_ENABLED = False

# Phase 10: Health metrics
_consecutive_errors = 0

DB_PATH = os.environ.get("BL_DB_PATH", config.BL_DB_PATH)
AIR_GAP_SECONDS = int(os.environ.get("BL_AIR_GAP_SECONDS", "30"))
SITES_PER_TICK = int(os.environ.get("BL_SITES_PER_TICK", "5"))
SCAN_MAX_PER_SITE = int(os.environ.get("BL_SCAN_MAX_PER_SITE", "20"))
MAX_AGE_DAYS = int(os.environ.get("BL_MAX_AGE_DAYS", "14"))
BLOCK_BACKOFF_HOURS = float(os.environ.get("BL_BLOCK_BACKOFF_HOURS", "0.25"))
BLOCK_BACKOFF_MAX_HOURS = float(os.environ.get("BL_BLOCK_BACKOFF_MAX_HOURS", "4"))
GATE_TOP_N = int(os.environ.get("BL_GATE_TOP_N", "20"))
GATE_THRESHOLD = float(os.environ.get("BL_GATE_THRESHOLD", "6.0"))
SCORE_FLOOR = float(os.environ.get("BL_SCORE_FLOOR", "0"))
DRAFT_BATCH_MIN = int(os.environ.get("BL_DRAFT_BATCH_MIN", "1"))
DRAFT_BATCH_MAX = int(os.environ.get("BL_DRAFT_BATCH_MAX", "5"))
DRAFT_STUCK_MINUTES = int(os.environ.get("BL_DRAFT_STUCK_MINUTES", "30"))
RESURFACE_HOURS = float(os.environ.get("BL_RESURFACE_HOURS", "24"))
SEARCH_CACHE = os.environ.get("BL_SEARCH_CACHE", "/tmp/backlink-daemon-search-cache.json")
DELIVERY_INTERVAL_MIN = int(os.environ.get("BL_DELIVERY_INTERVAL_MIN", "60"))
OPENWEB_EVERY_TICKS = int(os.environ.get("BL_OPENWEB_EVERY_TICKS", "4"))
COMPETITOR_EVERY_TICKS = int(os.environ.get("BL_COMPETITOR_EVERY_TICKS", "8"))
PRIORITY_REFRESH_EVERY_TICKS = int(os.environ.get("BL_PRIORITY_REFRESH_EVERY_TICKS", "20"))
LOW_YIELD_THRESHOLD = int(os.environ.get("BL_LOW_YIELD_THRESHOLD", "3"))
HUNTER_EVERY_TICKS = int(os.environ.get("BL_HUNTER_EVERY_TICKS", "6"))
VOCAB_EVERY_TICKS = int(os.environ.get("BL_VOCAB_EVERY_TICKS", "12"))
DOMAIN_PROMOTE_EVERY_TICKS = int(os.environ.get("BL_DOMAIN_PROMOTE_EVERY_TICKS", "10"))
FINDER_OUTPUT = os.environ.get(
    "BL_FINDER_OUTPUT",
    os.path.expanduser("~/.openclaw-backlink/data/finder/new_sites.json"),
)
OPENWEB_MAX = int(os.environ.get("BL_OPENWEB_MAX", "15"))
COMPETITOR_MAX = int(os.environ.get("BL_COMPETITOR_MAX", "12"))
TREND_INGEST_EVERY_TICKS = int(os.environ.get("BL_TREND_INGEST_EVERY_TICKS", "2880"))  # ~24h at 30s gap
SITEMAP_SCAN_EVERY_TICKS = int(os.environ.get("BL_SITEMAP_SCAN_EVERY_TICKS", "2880"))  # ~24h at 30s gap

_SEARCH_DIR = os.path.abspath(os.path.join(_PIPELINE_DIR, "..", "search"))
if _SEARCH_DIR not in sys.path:
    sys.path.insert(0, _SEARCH_DIR)

_last_delivery_ts: dict[int, float] = {}
_tick_counter = 0


def log(msg: str) -> None:
    """Legacy summary log line (unchanged format at info level)."""
    if not level_enabled("info"):
        return
    ts = now_sqlite()
    print(f"[nexus {ts}] {msg}", flush=True)
    
    # Live Activity Tracker logging
    try:
        log_path = os.path.expanduser("~/.openclaw-backlink/data/activity_log.json")
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        
        events = []
        if os.path.exists(log_path):
            with open(log_path, 'r', encoding='utf-8') as f:
                try:
                    events = json.load(f)
                except:
                    events = []
        
        events.append({"timestamp": ts, "message": msg})
        if len(events) > 20:
            events = events[-20:]
            
        with open(log_path, 'w', encoding='utf-8') as f:
            json.dump(events, f)
    except Exception:
        pass


def _funnel_snapshot(db_path: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    with wdb._connect(db_path) as conn:
        for row in conn.execute("SELECT status, COUNT(*) FROM harvest_leads GROUP BY status"):
            counts[row[0] or "unknown"] = int(row[1])
        pending = conn.execute(
            "SELECT COUNT(*) FROM opportunities WHERE status = 'pending'"
        ).fetchone()[0]
    counts["pending_cards"] = int(pending)
    return counts


def _log_funnel() -> None:
    snap = _funnel_snapshot(DB_PATH)
    plog_verbose("tick", "tick_funnel", **snap)


def _project_config(project_row: dict) -> dict:
    raw = project_row.get("config_json") or project_row.get("project_config_json")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def _project_terms(project_row: dict, cfg: dict | None = None) -> list[str]:
    from discover import clean_terms  # noqa: E402
    cfg = cfg if cfg is not None else _project_config(project_row)
    niche = project_row.get("niche") or project_row.get("project_niche") or ""
    keywords = cfg.get("target_keywords") or []
    return clean_terms(niche, keywords if isinstance(keywords, list) else [])


def _hunter_extra_queries(project: dict, cfg: dict, *, force: bool = False) -> list[str]:
    """LLM query planner — runs on low yield or on cadence (flywheel)."""
    pid = project["id"]
    recent = wdb.count_recent_leads(pid, hours=24, db_path=DB_PATH)
    if not force and recent >= LOW_YIELD_THRESHOLD:
        return []
    try:
        from opportunity_hunter import plan_queries  # noqa: E402
        desc = cfg.get("description") or cfg.get("project_description") or ""
        keywords = cfg.get("target_keywords") or []
        competitors = cfg.get("competitors") or []
        vocab = wdb.get_vocab_terms(pid, db_path=DB_PATH)
        merged_kw = list(keywords if isinstance(keywords, list) else [])
        for v in vocab[:10]:
            if v not in merged_kw:
                merged_kw.append(v)
        return plan_queries(
            project_id=pid,
            niche=project.get("niche") or "",
            description=desc,
            keywords=merged_kw,
            competitors=competitors if isinstance(competitors, list) else [],
            force_refresh=force,
        )
    except Exception as e:  # noqa: BLE001
        log(f"hunter: skipped for project={project.get('project_url')}: {e}")
        return []


def _scan_one_site(site: dict) -> None:
    site_id = site["id"]
    domain = site["domain"]
    niche = site.get("project_niche") or ""
    interval = int(site.get("scan_interval_minutes") or 15)
    project_id = site["project_id"]
    cfg = _project_config(site)
    project_stub = {"id": project_id, "niche": niche, "project_url": site.get("project_url")}
    force_hunter = _tick_counter % HUNTER_EVERY_TICKS == 0
    extra = _hunter_extra_queries(project_stub, cfg, force=force_hunter)

    log(f"scan: visiting {domain} (project={site.get('project_url')})")
    try:
        status, leads, new_cursor, template_stats, adapter = harvest_site(
            site,
            niche=niche,
            cfg=cfg,
            db_path=DB_PATH,
            max_results=SCAN_MAX_PER_SITE,
            max_age_days=MAX_AGE_DAYS,
            extra_queries=extra or None,
        )
        wdb.set_harvest_cursor(site_id, new_cursor, db_path=DB_PATH)
        if template_stats:
            wdb.record_query_stats(project_id, domain, template_stats, db_path=DB_PATH)
    except Exception as e:  # noqa: BLE001
        log(f"scan: ERROR on {domain}: {e} -> backoff")
        wdb.mark_site_blocked(
            site_id, BLOCK_BACKOFF_HOURS, max_backoff_hours=BLOCK_BACKOFF_MAX_HOURS, db_path=DB_PATH,
        )
        return

    if status == STATUS_BLOCKED:
        backoff = wdb.mark_site_blocked(
            site_id, BLOCK_BACKOFF_HOURS, max_backoff_hours=BLOCK_BACKOFF_MAX_HOURS, db_path=DB_PATH,
        )
        log(f"scan: BLOCKED on {domain} -> cooldown {backoff:.2f}h")
        return

    inserted = 0
    if status == STATUS_OK and leads:
        inserted = wdb.insert_leads(project_id, site_id, leads, db_path=DB_PATH)
        for lead in leads:
            text = f"{lead.get('target_title') or ''} {lead.get('target_excerpt') or ''}"
            for cand in extract_domains_from_text(text):
                if cand != domain:
                    wdb.queue_domain_candidate(project_id, cand, lead.get("url") or "", db_path=DB_PATH)
        process_rearm(project_id, db_path=DB_PATH)
    wdb.mark_site_scanned_success(site_id, interval, leads_inserted=inserted, db_path=DB_PATH)
    log(f"scan: {status} on {domain} via {adapter} -> {len(leads)} found, {inserted} new (reschedule +{interval}m)")
    plog_verbose(
        "scan", "scan_inserted",
        domain=domain, project=site.get("project_url"), found=len(leads), inserted=inserted,
    )


def phase_scan() -> None:
    due = wdb.get_due_sites(limit=SITES_PER_TICK, db_path=DB_PATH)
    if not due:
        log("scan: no sites due")
        return
    for site in due:
        plog_verbose(
            "tick", "due_sites",
            domain=site.get("domain"),
            project=site.get("project_url"),
            priority=site.get("scan_priority"),
            next_scan_due=site.get("next_scan_due"),
        )
        try:
            _scan_one_site(site)
        except Exception as e:  # noqa: BLE001
            log(f"scan: UNCAUGHT on site {site.get('domain')}: {e}")


def phase_score() -> None:
    new_leads = wdb.get_leads_by_status("NEW", limit=200, db_path=DB_PATH)
    if not new_leads:
        return
    usability_cache: dict[tuple[int, str], float] = {}
    project_terms_cache: dict[int, list[str]] = {}
    scored = 0
    for lead in new_leads:
        pid = lead["project_id"]
        domain = (lead.get("domain") or "").lower().lstrip("www.")
        ckey = (pid, domain)
        if ckey not in usability_cache:
            host = 50.0
            for s in wdb.get_active_whitelist(pid, db_path=DB_PATH):
                if s["domain"] == domain and s.get("current_usability_score") is not None:
                    host = float(s["current_usability_score"])
                    break
            usability_cache[ckey] = host
        if pid not in project_terms_cache:
            proj = wdb.get_active_projects(db_path=DB_PATH)
            match = next((p for p in proj if p["id"] == pid), None)
            project_terms_cache[pid] = _project_terms(match or {"niche": ""}, _project_config(match or {}))
        terms = project_terms_cache.get(pid, [])
        # Pass the full lead dictionary to score_opportunity so it has access to SEO metrics
        # and it will mutate the dict to add score_breakdown, confidence, reasoning
        opp = dict(lead)
        score = score_opportunity(opp, usability_cache[ckey], terms=terms or None)
        rel = opp.get("relevance_score")
        
        # Merge the mutated breakdown back into the lead so compliance engine can see it
        lead["score_breakdown"] = opp.get("score_breakdown", {})
        lead["confidence"] = opp.get("confidence", 0)
        lead["reasoning"] = opp.get("reasoning", [])
        lead["score_100"] = score
        wdb.update_lead(
            lead["id"],
            {"score_100": score, "status": "SCORED", "relevance_score": rel},
            db_path=DB_PATH,
        )
        plog_verbose(
            "score", "score_lead",
            lead_id=lead["id"],
            url=truncate(lead.get("url") or "", 120),
            score_100=score,
            relevance=rel,
        )
        scored += 1
    if scored:
        log(f"score: {scored} leads scored -> SCORED")


def phase_gate() -> None:
    for project in wdb.get_active_projects(db_path=DB_PATH):
        pid = project["id"]
        scored = wdb.get_leads_by_status("SCORED", limit=GATE_TOP_N, project_id=pid, db_path=DB_PATH)
        scored = [l for l in scored if (l.get("score_100") or 0) >= SCORE_FLOOR]
        
        # Phase 6: Google Guidelines Compliance Engine
        compliant_leads = []
        for l in scored:
            is_compliant, reason = check_compliance(l)
            if is_compliant:
                compliant_leads.append(l)
            else:
                # Mark as rejected immediately
                wdb.update_lead(
                    l["id"],
                    {"status": "REJECTED", "gate_reason": reason, "gate_score": 0.0},
                    db_path=DB_PATH
                )
                plog_verbose("compliance", "lead_rejected", lead_id=l["id"], reason=reason)
                
        scored = compliant_leads
        
        if not scored:
            continue
        cfg = _project_config(project)
        desc = cfg.get("description") or cfg.get("project_description") or ""
        judged = gate_leads(
            scored, niche=project.get("niche") or "", project_desc=desc,
            project_url=project.get("project_url") or "",
            threshold=GATE_THRESHOLD,
        )
        passed = 0
        for lead in judged:
            new_status = "GATED" if lead.get("gate_passed") else "REJECTED"
            if new_status == "GATED":
                passed += 1
                bdb.add_notification("approval", "Opportunity Approved", f"A new opportunity ({lead.get('site_url', '')}) passed the AI Quality Gate with score {lead.get('score', 0)}.", db_path=DB_PATH)
            wdb.update_lead(
                lead["id"],
                {
                    "gate_score": lead.get("gate_score"),
                    "gate_reason": (lead.get("gate_reason") or "")[:200],
                    "status": new_status,
                    "discussion_intent": lead.get("discussion_intent"),
                    "question_type": lead.get("question_type"),
                    "buying_intent": "true" if lead.get("has_commercial_intent") else "false",
                },
                db_path=DB_PATH,
            )
        log(f"gate: project={project.get('project_url')} judged={len(judged)} passed={passed}")


def phase_openweb() -> None:
    """Non site-scoped discovery beyond the whitelist."""
    try:
        from openweb_hunt import hunt_openweb  # noqa: E402
    except ImportError as e:
        log(f"openweb: import failed: {e}")
        return
    for project in wdb.get_active_projects(db_path=DB_PATH):
        pid = project["id"]
        cfg = _project_config(project)
        niche = project.get("niche") or ""
        keywords = cfg.get("target_keywords") or []
        extra = _hunter_extra_queries(project, cfg)
        try:
            leads = hunt_openweb(
                niche,
                keywords=keywords if isinstance(keywords, list) else [],
                extra_queries=extra or None,
                max_results=OPENWEB_MAX,
                max_age_days=MAX_AGE_DAYS,
            )
        except Exception as e:  # noqa: BLE001
            log(f"openweb: ERROR project={project.get('project_url')}: {e}")
            continue
        if not leads:
            continue
        inserted = wdb.insert_leads(pid, None, leads, db_path=DB_PATH)
        if inserted:
            log(f"openweb: project={project.get('project_url')} found={len(leads)} new={inserted}")


def phase_competitor() -> None:
    """Competitor-seeded discovery with smart filtering."""
    try:
        from competitor_hunt import hunt_competitors  # noqa: E402
    except ImportError as e:
        log(f"competitor: import failed: {e}")
        return
    for project in wdb.get_active_projects(db_path=DB_PATH):
        cfg = _project_config(project)
        competitors = cfg.get("competitors") or []
        if not competitors:
            continue
        pid = project["id"]
        niche = project.get("niche") or ""
        keywords = cfg.get("target_keywords") or []
        try:
            leads = hunt_competitors(
                niche,
                competitors if isinstance(competitors, list) else [],
                keywords=keywords if isinstance(keywords, list) else [],
                max_results=COMPETITOR_MAX,
                max_age_days=MAX_AGE_DAYS + 7,
            )
        except Exception as e:  # noqa: BLE001
            log(f"competitor: ERROR project={project.get('project_url')}: {e}")
            continue
        if not leads:
            continue
        inserted = wdb.insert_leads(pid, None, leads, db_path=DB_PATH)
        if inserted:
            log(f"competitor: project={project.get('project_url')} found={len(leads)} new={inserted}")


def phase_vocab() -> None:
    """Mine recent leads for vocabulary terms fed back into query_planner."""
    for project in wdb.get_active_projects(db_path=DB_PATH):
        try:
            n = mine_project_vocab(project["id"], db_path=DB_PATH)
            if n:
                log(f"vocab: project={project.get('project_url')} promoted {n} term(s)")
        except Exception as e:  # noqa: BLE001
            log(f"vocab: ERROR {e}")


# ── V2.0 Cron Phases ────────────────────────────────────────────────────────

def phase_trend_ingest() -> None:
    """V2.0: Fetch global trending news and save to daily_trends table."""
    if not _V2_ENABLED:
        return
    try:
        log("v2-trends: ingesting global trends from RSS...")
        ingest_trends()
        log("v2-trends: trend ingestion complete")
    except Exception as e:  # noqa: BLE001
        log(f"v2-trends: ERROR {e}")


def phase_sitemap_scan() -> None:
    """V2.0: Refresh sitemap knowledge base for all active projects."""
    if not _V2_ENABLED:
        return
    for project in wdb.get_active_projects(db_path=DB_PATH):
        pid = project.get("id")
        purl = project.get("project_url", "")
        if not pid or not purl:
            continue
        try:
            log(f"v2-sitemap: scanning {purl}")
            scan_project_sitemap(pid, purl)
        except Exception as e:  # noqa: BLE001
            log(f"v2-sitemap: ERROR for {purl}: {e}")


def phase_trend_query() -> None:
    """V2.0: Generate trend-based search queries and inject into discover phase."""
    if not _V2_ENABLED:
        return
    trend = get_latest_trend()
    if not trend:
        return
    for project in wdb.get_active_projects(db_path=DB_PATH):
        pid = project.get("id")
        niche = project.get("niche") or ""
        purl = project.get("project_url", "")
        if not pid or not niche:
            continue
        try:
            sitemap = get_project_sitemap(pid)
            if not sitemap:
                continue
            rel_map = generate_relevancy_map(niche, sitemap, trend)
            angle = rel_map.get("angle", "")
            if not angle:
                continue
            # Inject angle as an extra vocab term so the query planner uses it next tick
            trend_term = f"{trend['query']} {niche}"
            existing = wdb.get_vocab_terms(pid, db_path=DB_PATH)
            if trend_term not in existing:
                wdb.upsert_vocab_term(pid, trend_term, db_path=DB_PATH)
                log(f"v2-query: injected trend term for {purl}: '{trend_term[:60]}'")
        except Exception as e:  # noqa: BLE001
            log(f"v2-query: ERROR for {purl}: {e}")

# ─────────────────────────────────────────────────────────────────────────────


def phase_domain_promote() -> None:
    """Promote graph-follow domain candidates + merge periodic finder output."""
    for project in wdb.get_active_projects(db_path=DB_PATH):
        pid = project["id"]
        try:
            added = wdb.promote_domain_candidates(pid, limit=3, db_path=DB_PATH)
            if added:
                log(f"domains: promoted {added} candidate(s) for {project.get('project_url')}")
        except Exception as e:  # noqa: BLE001
            log(f"domains: promote ERROR {e}")
    if os.path.isfile(FINDER_OUTPUT):
        try:
            from merge_new_sites import merge  # noqa: E402
            niche = ""
            for project in wdb.get_active_projects(db_path=DB_PATH):
                niche = project.get("niche") or ""
                merge(FINDER_OUTPUT, project.get("project_url") or "", niche, db_path=DB_PATH)
            log(f"domains: merged finder output from {FINDER_OUTPUT}")
        except Exception as e:  # noqa: BLE001
            log(f"domains: finder merge skipped: {e}")


def phase_refresh_priorities() -> None:
    """Recompute scan_priority from yield; never deactivates sites."""
    for project in wdb.get_active_projects(db_path=DB_PATH):
        try:
            n = wdb.refresh_scan_priorities(project["id"], db_path=DB_PATH)
            log(f"priority: refreshed {n} site(s) for {project.get('project_url')}")
        except Exception as e:  # noqa: BLE001
            log(f"priority: ERROR {e}")


def phase_draft() -> None:
    for project in wdb.get_active_projects(db_path=DB_PATH):
        pid = project["id"]
        if DELIVERY_INTERVAL_MIN > 0:
            last_ts = _last_delivery_ts.get(pid, 0.0)
            elapsed_min = (time.time() - last_ts) / 60.0
            if last_ts > 0 and elapsed_min < DELIVERY_INTERVAL_MIN:
                continue
        gated = wdb.get_leads_by_status("GATED", limit=DRAFT_BATCH_MAX, project_id=pid, db_path=DB_PATH)
        if len(gated) < DRAFT_BATCH_MIN:
            continue
        log(f"draft: project={project.get('project_url')} drafting {len(gated)} GATED leads")
        result = draft_and_send(project, gated, db_path=DB_PATH, log_fn=log)
        if result.error:
            log(f"draft: FAILED for {project.get('project_url')}: {result.error}")
            bdb.add_notification("error", "Telegram Draft Failed", f"Failed to send cards for {project.get('project_url')}: {result.error}", db_path=DB_PATH)
            continue
        if result.sent > 0:
            _last_delivery_ts[pid] = time.time()
            log(f"draft: SENT {result.sent} card(s) for {project.get('project_url')}")
            bdb.add_notification("telegram", "Telegram Cards Delivered", f"Successfully delivered {result.sent} card(s) to the Telegram group.", db_path=DB_PATH)


def phase_resurface() -> None:
    """Disabled: Prevent re-sending duplicate pending cards to Telegram."""
    return
    resent = 0
    for opp in stale:
        try:
            if resend_one_opportunity(opp, db_path=DB_PATH):
                resent += 1
                log(f"resurface: re-sent {opp.alert_id} for {opp.site_url}")
                plog_verbose(
                    "resurface", "resurface_ok",
                    alert_id=opp.alert_id,
                    site_url=truncate(opp.site_url or "", 120),
                    card_sent_at=opp.card_sent_at,
                )
            else:
                log(f"resurface: skipped {opp.alert_id} (no content or send failed)")
                plog_verbose(
                    "resurface", "resurface_skip",
                    alert_id=opp.alert_id,
                    reason="no_content_or_send_failed",
                )
        except Exception as e:  # noqa: BLE001
            log(f"resurface: ERROR {opp.alert_id}: {e}")
    if resent:
        log(f"resurface: {resent} stale pending card(s) re-sent")


def tick() -> None:
    global _tick_counter
    _tick_counter += 1
    
    # Record heartbeat
    try:
        bdb.update_heartbeat(db_path=DB_PATH)
    except Exception as e:
        log(f"heartbeat error: {e}")

    phases = [("scan", phase_scan), ("score", phase_score), ("gate", phase_gate)]
    if _tick_counter % OPENWEB_EVERY_TICKS == 0:
        phases.append(("openweb", phase_openweb))
    if _tick_counter % COMPETITOR_EVERY_TICKS == 0:
        phases.append(("competitor", phase_competitor))
    if _tick_counter % VOCAB_EVERY_TICKS == 0:
        phases.append(("vocab", phase_vocab))

    # Domain promotion check
    if _tick_counter % DOMAIN_PROMOTE_EVERY_TICKS == 0:
        phase_domain_promote()
        
    # Pending reminders check (roughly every hour)
    if _tick_counter % int(max(1, 3600 / AIR_GAP_SECONDS)) == 0:
        try:
            log("triggering send_reminders.py")
            subprocess.Popen([sys.executable, os.path.join(_PIPELINE_DIR, "send_reminders.py")])
        except Exception as e:
            log(f"failed to trigger reminders: {e}")

    if _tick_counter % PRIORITY_REFRESH_EVERY_TICKS == 0:
        phases.append(("priority", phase_refresh_priorities))

    # V2.0 cron phases
    if _V2_ENABLED:
        if _tick_counter % TREND_INGEST_EVERY_TICKS == 0:
            phases.append(("v2-trends", phase_trend_ingest))
        if _tick_counter % SITEMAP_SCAN_EVERY_TICKS == 0:
            phases.append(("v2-sitemap", phase_sitemap_scan))
        if _tick_counter % OPENWEB_EVERY_TICKS == 0:  # same cadence as openweb search
            phases.append(("v2-query", phase_trend_query))

    phases.extend([
        ("resurface", phase_resurface),
        ("draft", phase_draft),
    ])
    phase_names = [p[0] for p in phases]
    plog_verbose("tick", "tick_start", tick=_tick_counter, phases=",".join(phase_names))
    tick_start = time.time()
    global _consecutive_errors
    for name, fn in phases:
        phase_start = time.time()
        plog_trace("tick", "phase_begin", phase=name)
        try:
            fn()
            _consecutive_errors = 0
        except Exception as e:  # noqa: BLE001
            log(f"{name}: UNCAUGHT ERROR {e}")
            _consecutive_errors += 1
            if _consecutive_errors >= 5:
                hermes_client.notify_telegram("⚠️ *EMERGENCY: DAEMON FAILING*", f"The Nexus Daemon has encountered 5 consecutive uncaught errors. Latest error in phase `{name}`: `{e}`")
                _consecutive_errors = 0  # reset to avoid spamming
        plog_trace(
            "tick", "phase_end",
            phase=name, duration_ms=int((time.time() - phase_start) * 1000),
        )
    plog_verbose("tick", "tick_end", tick=_tick_counter, duration_ms=int((time.time() - tick_start) * 1000))
    _log_funnel()


def main() -> int:
    parser = argparse.ArgumentParser(description="Nexus Farmer daemon (24/7 harvest loop)")
    parser.add_argument("--once", action="store_true", help="Run a single tick and exit")
    parser.add_argument("--max-ticks", type=int, default=0, dest="max_ticks")
    parser.add_argument("--air-gap", type=int, default=AIR_GAP_SECONDS, dest="air_gap")
    args = parser.parse_args()

    wdb.init_whitelist_db(DB_PATH)
    bdb.init_db(DB_PATH)
    recovered = wdb.recover_stuck_drafted(DRAFT_STUCK_MINUTES, db_path=DB_PATH)
    if recovered:
        log(f"daemon: recovered {recovered} stuck DRAFTED lead(s) -> GATED")
    log(
        f"daemon start: db={DB_PATH} air_gap={args.air_gap}s sites_per_tick={SITES_PER_TICK} "
        f"scan_max={SCAN_MAX_PER_SITE} backoff={BLOCK_BACKOFF_HOURS}h "
        f"draft_batch={DRAFT_BATCH_MIN}-{DRAFT_BATCH_MAX} delivery_every={DELIVERY_INTERVAL_MIN}m"
    )

    ticks = 0
    while True:
        try:
            settings = bdb.get_settings(db_path=DB_PATH)
            if "schedule_frequency_minutes" in settings:
                args.air_gap = int(settings["schedule_frequency_minutes"]) * 60
            if "min_score" in settings:
                global GATE_THRESHOLD
                GATE_THRESHOLD = float(settings["min_score"])
        except Exception as e:
            log(f"failed to fetch DB settings: {e}")
            
        tick()
        ticks += 1
        
        # Phase 10: Daemon Heartbeat
        try:
            with open(".daemon_heartbeat.json", "w", encoding="utf-8") as hf:
                json.dump({
                    "last_tick_time": time.time(),
                    "total_ticks": ticks,
                    "status": "alive"
                }, hf)
        except Exception as e:
            log(f"failed to write heartbeat: {e}")
            
        if args.once or (args.max_ticks and ticks >= args.max_ticks):
            log(f"daemon stop after {ticks} tick(s)")
            return 0
        time.sleep(args.air_gap)


if __name__ == "__main__":
    sys.exit(main())
