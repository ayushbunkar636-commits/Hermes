#!/usr/bin/env python3
"""harvest_draft.py — Shared draft + Telegram send pipeline for daemon and CLI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

import whitelist_db as wdb

try:
    from relevancy_engine import generate_relevancy_map, get_project_sitemap, get_latest_trend
    _RELEVANCY_ENABLED = True
except ImportError:
    _RELEVANCY_ENABLED = False

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)
from pipeline_tz import now_compact  # noqa: E402
from pipeline_log import plog_verbose, truncate  # noqa: E402
_VALIDATE_SCRIPT = os.path.join(_PIPELINE_DIR, "validate_content.py")
_CARD_SCRIPT = os.path.join(_PIPELINE_DIR, "build_and_send_card.py")

INK_TIMEOUT = int(os.environ.get("BL_INK_TIMEOUT", "1200"))
DRAFT_MAX_RETRIES = int(os.environ.get("BL_DRAFT_MAX_RETRIES", "3"))
PROFILE = os.environ.get("BL_PROFILE", "backlink")


@dataclass
class DraftResult:
    sent: int
    run_id: str | None
    urls: list[str]
    error: str | None = None


def _project_config(project_row: dict) -> dict:
    raw = project_row.get("config_json") or project_row.get("project_config_json")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def lead_to_opportunity(lead: dict) -> dict:
    raw = {}
    if lead.get("raw_json"):
        try:
            raw = json.loads(lead["raw_json"])
        except (json.JSONDecodeError, TypeError):
            raw = {}
    
    # Extract clean text from raw_html for context
    page_text = ""
    html = raw.get("raw_html", "")
    if html and BeautifulSoup:
        try:
            soup = BeautifulSoup(html, "html.parser")
            page_text = soup.get_text(separator=" ", strip=True)[:4000]
        except Exception:
            pass
            
    return {
        "url": lead["url"],
        "site_url": lead["url"],
        "submission_url": raw.get("submission_url") or lead["url"],
        "domain": lead.get("domain"),
        "site_domain": lead.get("domain"),
        "type": lead.get("type") or "forum",
        "target_title": lead.get("target_title") or "",
        "target_excerpt": lead.get("target_excerpt") or "",
        "page_text": page_text, # Full extracted context
        "discussion_intent": lead.get("discussion_intent") or "",
        "question_type": lead.get("question_type") or "",
        "opportunity_context": lead.get("opportunity_context") or "",
        "opportunity_freshness": lead.get("opportunity_freshness") or "unknown",
        "posting_action": lead.get("posting_action") or "reply",
        "platform": lead.get("platform"),
        "platform_weight": lead.get("platform_weight"),
        "credibility_tier": lead.get("credibility_tier"),
        "relevance_score": lead.get("relevance_score"),
        "score_100": lead.get("score_100"),
        "gate_score": lead.get("gate_score"),
    }


def build_run_bundle(project: dict, leads: list[dict]) -> tuple[str, str, str]:
    ts = now_compact()
    run_id = f"farm-{project['id']}-{ts}"
    run_dir = f"/tmp/backlink-run-{run_id}"
    os.makedirs(os.path.join(run_dir, "content"), exist_ok=True)
    queue_path = os.path.join(run_dir, "content_queue.json")
    opportunities = [lead_to_opportunity(l) for l in leads]
    for rank, opp in enumerate(opportunities, start=1):
        opp["rank"] = rank
    with open(queue_path, "w", encoding="utf-8") as f:
        json.dump({
            "status": "ok",
            "niche": project.get("niche") or "",
            "project_url": project["project_url"],
            "opportunities": opportunities,
        }, f, indent=2, ensure_ascii=False)
    manifest_path = os.path.join(run_dir, "manifest.json")
    posts_path = os.path.join(run_dir, "content", "posts.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump({
            "run_id": run_id,
            "run_dir": run_dir,
            "project": {
                "niche": project.get("niche") or "",
                "project_url": project["project_url"],
                "project_name": project.get("name") or project.get("niche") or "",
            },
            "artifacts": {"content_queue": queue_path, "content_posts": posts_path},
        }, f, indent=2, ensure_ascii=False)
    return run_dir, manifest_path, run_id


def invoke_ink(project: dict, run_dir: str, manifest_path: str, *, log_fn: Callable[[str], None] | None = None) -> bool:
    log = log_fn or (lambda _m: None)
    cfg = _project_config(project)
    desc = cfg.get("description") or cfg.get("project_description") or ""
    tone = cfg.get("tone") or ""
    name = project.get("name") or project.get("niche") or ""
    queue_path = os.path.join(run_dir, "content_queue.json")
    posts_path = os.path.join(run_dir, "content", "posts.json")
    
    queue_content = ""
    try:
        with open(queue_path, "r", encoding="utf-8") as f:
            queue_content = f.read()
    except Exception as e:
        log(f"draft: Could not read queue {e}")
        
    # ── V2.0 Relevancy Engine: Try to get trend angle + dual deep links ────────
    relevancy_context = ""
    dual_link_instruction = f"Project URL (homepage fallback): {project['project_url']}"
    if _RELEVANCY_ENABLED:
        try:
            niche = project.get('niche') or ''
            project_id = project.get('id')
            sitemap = get_project_sitemap(project_id) if project_id else []
            trend = get_latest_trend()
            if sitemap and trend:
                rel_map = generate_relevancy_map(niche, sitemap, trend)
                if rel_map.get('angle') and rel_map.get('pillar_url'):
                    relevancy_context = (
                        f"\n=== TREND-JACKING CONTEXT (V2.0) ===\n"
                        f"TRENDING TOPIC: {trend['query']}\n"
                        f"VIRAL ANGLE: {rel_map['angle']}\n"
                        f"Use this angle as the HOOK of your reply — connect it to the discussion naturally.\n"
                    )
                    pillar = rel_map.get('pillar_url', project['project_url'])
                    post = rel_map.get('post_url', '')
                    if post and post != pillar:
                        dual_link_instruction = (
                            f"HUB & SPOKE DUAL-LINK STRATEGY (MANDATORY):\n"
                            f"1. TIMELY POST (use inline in reply body): {post}\n"
                            f"   Anchor text: Reference to the timely blog post naturally.\n"
                            f"2. PILLAR PAGE (use once at the end as 'further reading'): {pillar}\n"
                            f"   Anchor text: Reference to the core service page naturally.\n"
                            f"Insert BOTH links naturally. Do NOT use 'check this out' or ad-like phrasing."
                        )
                    else:
                        dual_link_instruction = f"Project URL: {pillar}"
        except Exception as _re:
            pass  # Relevancy engine failed silently — fall back to standard mode
    # ─────────────────────────────────────────────────────────────────────────────

    task = (
        "You are an expert SEO Content Writer and Community Member following Google's EEAT (Experience, Expertise, Authoritativeness, Trustworthiness) guidelines.\n"
        "Create submission-ready, highly valuable backlink content for each opportunity in the JSON queue.\n\n"
        "RULES FOR EEAT AND NATURAL LINKING:\n"
        "1. Experience: Write from a first-person perspective ('I had this issue', 'In my experience').\n"
        "2. Value First: Provide an actionable, direct answer to the user's question BEFORE mentioning any link.\n"
        "3. Natural Citation: Integrate the project link organically as a reference or tool you used, NOT as an advertisement.\n"
        "4. Ban Spam: NEVER use phrases like 'Check out this link', 'I found a great tool', or 'Click here'.\n"
        "5. Tone Match: Adjust your tone to match the 'discussion_intent' and 'question_type' of the thread.\n\n"
        f"{relevancy_context}"
        f"RUN_DIR={run_dir}\n"
        f"Queue (JSON list containing page_text, title, intent, etc.):\n{queue_content}\n\n"
        f"{dual_link_instruction}\n"
        f"Niche: {project.get('niche') or ''}\n"
        f"Project name: {name}\n"
        f"Project description: {desc}\n"
        f"Tone/style preference: {tone} (Adapt to discussion_intent as needed)\n"
        f"Manifest: {manifest_path}\n"
        f"Write all posts to: {posts_path}\n"
        "Do not web_fetch blocked domains (reddit.com, x.com, twitter.com) — use target_title, page_text, and target_excerpt.\n"
        "Each post's site_url MUST equal the opportunity url it answers.\n"
        "You MUST return a raw JSON object with this exact schema:\n"
        "{\n"
        '  "status": "ok",\n'
        '  "posts": [\n'
        '    {\n'
        '      "site_url": "the opportunity url",\n'
        '      "site_domain": "the opportunity domain",\n'
        '      "type": "the opportunity type (e.g. forum, blog)",\n'
        '      "title": "a good title for the post",\n'
        '      "content": "the full post content",\n'
        '      "backlink_url": "the primary link URL used",\n'
        '      "backlink_anchor_text": "the anchor text used in the post",\n'
        '      "image_path": "path/to/image.jpg (if applicable, else omit)"\n'
        '    }\n'
        '  ]\n'
        "}\n"
        "Do NOT return Markdown blocks. Yield JSON only."
    )
    import hermes_client
    plog_verbose("draft", "ink_invoke", run_dir=run_dir, manifest=manifest_path)
    try:
        res = hermes_client.run_worker(
            worker_id="bl-content",
            task_payload={"task": task, "run_dir": run_dir, "manifest": manifest_path},
            timeout_seconds=INK_TIMEOUT
        )
        if res and res.get("status") == "failed":
            log(f"draft: Hermes worker returned error: {res.get('error')}")
            return False
    except Exception as e:
        log(f"draft: ERROR Hermes worker failed: {e}")
        return False
    if not os.path.isfile(posts_path):
        log("draft: Ink produced no posts.json")
        return False
    try:
        val = subprocess.run(
            ["python3", _VALIDATE_SCRIPT, "--manifest", manifest_path],
            capture_output=True, text=True, timeout=120,
        )
        if val.returncode != 0:
            err = (val.stdout or val.stderr or "").strip()
            log(f"draft: content validation failed: {err[:300]}")
            return False
    except Exception as e:  # noqa: BLE001
        log(f"draft: validate_content error: {e}")
        return False
    plog_verbose("draft", "validate_ok", manifest=manifest_path)
    try:
        with open(posts_path, encoding="utf-8") as f:
            posts = json.load(f).get("posts") or []
    except (OSError, json.JSONDecodeError):
        return False
    if posts:
        plog_verbose("draft", "ink_ok", run_dir=run_dir, posts=len(posts))
    return len(posts) > 0


def mark_draft_failure(
    lead_ids: list[int],
    leads: list[dict],
    *,
    reason: str,
    db_path: str,
) -> None:
    by_id = {l["id"]: l for l in leads}
    for lid in lead_ids:
        lead = by_id.get(lid, {})
        attempts = int(lead.get("draft_attempts") or 0) + 1
        if attempts >= DRAFT_MAX_RETRIES:
            wdb.update_lead(lid, {
                "status": "FAILED",
                "draft_attempts": attempts,
                "gate_reason": reason,
                "run_id": None,
            }, db_path=db_path)
        else:
            wdb.update_lead(lid, {
                "status": "GATED",
                "draft_attempts": attempts,
                "gate_reason": reason,
                "run_id": None,
            }, db_path=db_path)


def send_cards(manifest_path: str, *, log_fn: Callable[[str], None] | None = None) -> int:
    log = log_fn or (lambda _m: None)
    try:
        proc = subprocess.run(
            ["python3", _CARD_SCRIPT, "--manifest", manifest_path, "--ordered"],
            capture_output=True, text=True, timeout=300,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        sent = 0
        for line in out.splitlines():
            if line.startswith("CARDS_SUMMARY:"):
                for tok in line.split():
                    if tok.startswith("sent="):
                        try:
                            sent = int(tok.split("=", 1)[1])
                        except ValueError:
                            sent = 0
                log(f"cards: {line.strip()}")
                break
        else:
            log("cards: no CARDS_SUMMARY in output")
        return sent
    except Exception as e:  # noqa: BLE001
        log(f"cards: ERROR {e}")
        return 0


def draft_and_send(
    project: dict,
    leads: list[dict],
    *,
    db_path: str,
    log_fn: Callable[[str], None] | None = None,
) -> DraftResult:
    log = log_fn or (lambda _m: None)
    if not leads:
        return DraftResult(sent=0, run_id=None, urls=[], error="no_leads")

    run_dir, manifest_path, run_id = build_run_bundle(project, leads)
    lead_ids = [l["id"] for l in leads]
    urls = [l.get("url") or "" for l in leads]
    plog_verbose(
        "draft", "draft_start",
        run_id=run_id,
        project_url=project["project_url"],
        urls=truncate(", ".join(urls), 200),
        count=len(leads),
    )
    for lid in lead_ids:
        wdb.update_lead(lid, {"status": "DRAFTED", "run_id": run_id}, db_path=db_path)

    if not invoke_ink(project, run_dir, manifest_path, log_fn=log):
        mark_draft_failure(lead_ids, leads, reason="draft_failed", db_path=db_path)
        return DraftResult(sent=0, run_id=run_id, urls=urls, error="draft_failed")

    sent = send_cards(manifest_path, log_fn=log)
    if sent > 0:
        for lid in lead_ids:
            wdb.update_lead(lid, {"status": "SENT", "draft_attempts": 0}, db_path=db_path)
        return DraftResult(sent=sent, run_id=run_id, urls=urls)

    mark_draft_failure(lead_ids, leads, reason="card_send_failed", db_path=db_path)
    return DraftResult(sent=0, run_id=run_id, urls=urls, error="card_send_failed")
