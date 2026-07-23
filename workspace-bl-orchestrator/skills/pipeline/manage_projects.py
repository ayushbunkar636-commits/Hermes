#!/usr/bin/env python3
"""manage_projects.py — Deterministic project + source management CLI.

This is the orchestrator's "fat tool": all human-initiated management actions
run through here as ONE predefined, safe command per action. The orchestrator
agent stays thin — it parses the request, fills the args, runs the subcommand,
and reports the printed result. No LLM logic lives here.

Subcommands (run `manage_projects.py <cmd> --help` for args):
  add         Create/register a project (+ optional whitelist seed)
  edit        Update a project's personalization (config_json) / interval / niche
  pause       Pause a project (daemon stops scanning it)
  resume      Resume a paused project
  delete      Delete a project and all its sites/leads (irreversible)
  list        List all projects with lead/site counts
  status      Detailed status for one project (sites, cooldowns, lead pipeline)
  sources     Show a project's whitelist + scan schedule
  scan-now    Force all of a project's sites due immediately (next tick scans)
  send-cards  On-demand draft + Telegram send for GATED leads (bypasses delivery interval)
  resend-pending  Repost unacted pending cards from DB (no re-draft)
  list-pending  List pending editorial cards without sending
  find-sites  Deterministic open-web discovery of new source domains (no LLM)

Every subcommand prints a single `OK:` / `ERROR:` summary line plus optional
JSON, so the agent can confirm success and relay details to the user.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import urllib.parse

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
_SEARCH_DIR = os.path.abspath(os.path.join(_PIPELINE_DIR, "..", "search"))
for _p in (_PIPELINE_DIR, _SEARCH_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import whitelist_db as wdb  # noqa: E402
import seed_whitelist  # noqa: E402
import backlink_db as bdb  # noqa: E402
from quality_gate import gate_leads  # noqa: E402
from harvest_draft import draft_and_send  # noqa: E402
from resend_pending import resend_pending_cards  # noqa: E402
from pipeline_tz import format_display, format_sqlite_display, format_utc_sqlite_display  # noqa: E402

DB = wdb.DEFAULT_DB_PATH
BIND_SCRIPT = os.path.join(_PIPELINE_DIR, "bind_telegram_group.py")
GATE_TOP_N = int(os.environ.get("BL_GATE_TOP_N", "20"))
GATE_THRESHOLD = float(os.environ.get("BL_GATE_THRESHOLD", "6.0"))
SCORE_FLOOR = float(os.environ.get("BL_SCORE_FLOOR", "0"))
SEND_CARDS_MAX = 10
RESEND_MAX = 10

# Domains that are never useful as backlink sources (search-engine/aggregator noise).
_FIND_BLOCKLIST = frozenset({
    "google.com", "bing.com", "duckduckgo.com", "yahoo.com", "youtube.com",
    "wikipedia.org", "amazon.com", "facebook.com", "instagram.com",
    "translate.google.com", "policies.google.com", "support.google.com",
})


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]


def _normalize_domain(raw: str) -> str | None:
    val = raw.strip()
    if not val:
        return None
    if not val.startswith(("http://", "https://")):
        val = "https://" + val.split("/")[0]
    parsed = urllib.parse.urlparse(val)
    host = (parsed.netloc or parsed.path.split("/")[0]).lower().strip()
    if host.startswith("www."):
        host = host[4:]
    if not host or "." not in host:
        return None
    return host


def _parse_extra_domains(value: str | None) -> list[str]:
    if not value:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for token in _csv(value):
        dom = _normalize_domain(token)
        if dom and dom not in seen:
            seen.add(dom)
            out.append(dom)
    return out


def _print_ok(summary: str, payload: dict | None = None) -> int:
    print(f"OK: {summary}")
    if payload is not None:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


def _print_err(summary: str) -> int:
    print(f"ERROR: {summary}", file=sys.stderr)
    return 1


def _build_config(args) -> dict:
    cfg: dict = {}
    if getattr(args, "description", None):
        cfg["description"] = args.description
    if getattr(args, "tone", None):
        cfg["tone"] = args.tone
    if getattr(args, "keywords", None):
        cfg["target_keywords"] = _csv(args.keywords)
    if getattr(args, "anchor", None):
        cfg["anchor_text"] = _csv(args.anchor)
    if getattr(args, "subreddits", None):
        cfg["subreddits"] = _csv(args.subreddits)
    if getattr(args, "competitors", None):
        cfg["competitors"] = _csv(args.competitors)
    return cfg


def _project_config(project_row: dict) -> dict:
    raw = project_row.get("config_json") or ""
    try:
        return json.loads(raw) if raw else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _apply_group_fields(args, project_url: str) -> None:
    """Persist telegram group columns when --group-id is provided."""
    group_id = getattr(args, "group_id", None)
    if not group_id:
        return
    group_name = getattr(args, "group_name", None) or getattr(args, "name", None) or ""
    card_prefix = getattr(args, "card_prefix", None)
    wdb.set_project_group(
        project_url,
        group_id,
        group_name,
        card_prefix=card_prefix,
        db_path=DB,
    )


def _bind_telegram_group(args, project_url: str) -> int:
    """Invoke bind_telegram_group.py when --bind is set with --group-id."""
    if not getattr(args, "bind", False):
        return 0
    group_id = getattr(args, "group_id", None)
    if not group_id:
        return _print_err("--bind requires --group-id")
    name = getattr(args, "name", None) or getattr(args, "group_name", None) or project_url
    cmd = [
        sys.executable,
        BIND_SCRIPT,
        "--project-url", project_url,
        "--group-id", str(group_id),
        "--name", str(name),
    ]
    if getattr(args, "group_name", None):
        cmd.extend(["--group-name", str(args.group_name)])
    if getattr(args, "card_prefix", None):
        cmd.extend(["--card-prefix", str(args.card_prefix)])
    if getattr(args, "apply", False):
        cmd.append("--apply")
        cmd.append("--skip-db")  # DB already updated by _apply_group_fields
    else:
        cmd.append("--dry-run")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    print(out.strip())
    if proc.returncode != 0:
        return proc.returncode
    return 0


def add_group_args(sp) -> None:
    sp.add_argument("--group-id", default=None, help="Telegram supergroup id for this project")
    sp.add_argument("--group-name", default=None, help="Human label for the Telegram group")
    sp.add_argument("--card-prefix", default=None, help="Optional card label prefix")
    sp.add_argument(
        "--bind",
        action="store_true",
        help="Wire openclaw.json group binding (requires --group-id; use --apply to write)",
    )
    sp.add_argument(
        "--apply",
        action="store_true",
        help="With --bind: write openclaw.json and restart gateway (default is dry-run)",
    )


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_add(args) -> int:
    cfg = _build_config(args)
    pid = wdb.add_or_update_project(
        args.project_url, args.niche, args.name or "", config=cfg or None,
        scan_interval_minutes=args.interval, status="active", db_path=DB,
    )
    try:
        _apply_group_fields(args, args.project_url)
    except ValueError as e:
        return _print_err(str(e))
    seeded = 0
    if not args.no_seed:
        tiers = [int(t) for t in _csv(args.tiers) if t.isdigit()] or [1, 2]
        seeded, _ = seed_whitelist.seed(args.project_url, args.niche, args.name or "", tiers=tiers, db_path=DB)
    before_extra = wdb.count_active_sites(pid, db_path=DB)
    for dom in _parse_extra_domains(getattr(args, "extra_domains", None)):
        wdb.upsert_whitelist_site(pid, dom, added_by="onboard", db_path=DB)
    extra_sites = wdb.count_active_sites(pid, db_path=DB) - before_extra
    total_sites = wdb.count_active_sites(pid, db_path=DB)
    rc = _bind_telegram_group(args, args.project_url)
    if rc != 0:
        return rc
    return _print_ok(
        f"project added id={pid} url={args.project_url} seeded_sites={seeded} "
        f"extra_sites={extra_sites} active_sites={total_sites}",
        {"project_id": pid, "active_sites": total_sites, "extra_sites": extra_sites, "config": cfg},
    )


def cmd_edit(args) -> int:
    proj = wdb.get_project(args.project_url, db_path=DB)
    if not proj:
        return _print_err(f"project not found: {args.project_url}")
    patch = _build_config(args)
    if patch:
        wdb.update_project_config(args.project_url, patch, db_path=DB)
    # niche / interval are columns, not config — update via add_or_update_project.
    if args.niche or args.interval is not None or args.name:
        wdb.add_or_update_project(
            args.project_url,
            args.niche or proj.get("niche") or "",
            args.name or proj.get("name") or "",
            config=None,
            scan_interval_minutes=args.interval if args.interval is not None else proj.get("scan_interval_minutes", 30),
            status=proj.get("status", "active"),
            db_path=DB,
        )
    try:
        _apply_group_fields(args, args.project_url)
    except ValueError as e:
        return _print_err(str(e))
    rc = _bind_telegram_group(args, args.project_url)
    if rc != 0:
        return rc
    new = wdb.get_project(args.project_url, db_path=DB)
    return _print_ok(f"project updated: {args.project_url}", {
        "niche": new.get("niche"), "scan_interval_minutes": new.get("scan_interval_minutes"),
        "telegram_group_id": new.get("telegram_group_id"),
        "telegram_group_name": new.get("telegram_group_name"),
        "config": json.loads(new.get("config_json") or "{}"),
    })


def cmd_pause(args) -> int:
    wdb.set_project_status(args.project_url, "paused", db_path=DB)
    return _print_ok(f"project paused: {args.project_url}")


def cmd_resume(args) -> int:
    wdb.set_project_status(args.project_url, "active", db_path=DB)
    return _print_ok(f"project resumed: {args.project_url}")


def cmd_delete(args) -> int:
    if not args.confirm:
        return _print_err("delete requires --confirm (irreversible: removes project, sites, leads)")
    wdb.delete_project(args.project_url, db_path=DB)
    return _print_ok(f"project deleted: {args.project_url}")


def cmd_list(args) -> int:
    projects = wdb.list_projects(db_path=DB)
    out = []
    for p in projects:
        out.append({
            "project_url": p["project_url"],
            "niche": p.get("niche"),
            "status": p.get("status"),
            "scan_interval_minutes": p.get("scan_interval_minutes"),
            "telegram_group_id": p.get("telegram_group_id"),
            "telegram_group_name": p.get("telegram_group_name"),
            "active_sites": wdb.count_active_sites(p["id"], db_path=DB),
            "leads": wdb.count_leads_by_status(p["id"], db_path=DB),
        })
    return _print_ok(f"{len(out)} project(s)", {"projects": out})


def cmd_status(args) -> int:
    p = wdb.get_project(args.project_url, db_path=DB)
    if not p:
        return _print_err(f"project not found: {args.project_url}")
    pid = p["id"]
    sites = wdb.get_active_whitelist(pid, db_path=DB)
    cooldown = [s for s in sites if (s.get("status") == "cooldown")]
    return _print_ok(f"status for {args.project_url}", {
        "status": p.get("status"),
        "niche": p.get("niche"),
        "scan_interval_minutes": p.get("scan_interval_minutes"),
        "telegram_group_id": p.get("telegram_group_id"),
        "telegram_group_name": p.get("telegram_group_name"),
        "card_prefix": p.get("card_prefix"),
        "config": json.loads(p.get("config_json") or "{}"),
        "active_sites": len(sites),
        "sites_in_cooldown": len(cooldown),
        "leads": wdb.count_leads_by_status(pid, db_path=DB),
    })


def cmd_sources(args) -> int:
    p = wdb.get_project(args.project_url, db_path=DB)
    if not p:
        return _print_err(f"project not found: {args.project_url}")
    sites = wdb.get_active_whitelist(p["id"], db_path=DB)
    rows = [{
        "domain": s["domain"],
        "status": s.get("status"),
        "added_by": s.get("added_by"),
        "next_scan_due": format_utc_sqlite_display(s.get("next_scan_due")),
        "failure_count": s.get("failure_count"),
        "cooldown_until": format_utc_sqlite_display(s.get("cooldown_until")),
        "usability": s.get("current_usability_score"),
        "scan_priority": s.get("scan_priority"),
    } for s in sites]
    return _print_ok(f"{len(rows)} source(s) for {args.project_url}", {"sources": rows})


def cmd_scan_now(args) -> int:
    p = wdb.get_project(args.project_url, db_path=DB)
    if not p:
        return _print_err(f"project not found: {args.project_url}")
    if p.get("status") != "active":
        return _print_err(f"project is {p.get('status')}; resume it before scanning")
    n = wdb.set_project_sites_due_now(p["id"], db_path=DB)
    return _print_ok(f"{n} site(s) set due now for {args.project_url}; daemon will scan them shortly")


def cmd_set_priority(args) -> int:
    p = wdb.get_project(args.project_url, db_path=DB)
    if not p:
        return _print_err(f"project not found: {args.project_url}")
    dom = wdb.resolve_whitelist_domain(p["id"], args.domain, db_path=DB)
    if not dom:
        return _print_err(f"domain not on whitelist: {args.domain}")
    ok = wdb.set_site_scan_priority(p["id"], dom, args.priority, db_path=DB)
    if not ok:
        return _print_err(f"could not set priority for {dom}")
    return _print_ok(
        f"scan_priority={args.priority} for {dom}",
        {"domain": dom, "scan_priority": args.priority},
    )


def cmd_scan_domain(args) -> int:
    """Synchronously scan one whitelisted domain and return opportunities."""
    from scan_tool import scan_single_url, STATUS_OK, STATUS_BLOCKED  # noqa: E402

    p = wdb.get_project(args.project_url, db_path=DB)
    if not p:
        return _print_err(f"project not found: {args.project_url}")
    if p.get("status") != "active":
        return _print_err(f"project is {p.get('status')}; resume it before scanning")
    pid = p["id"]
    dom = wdb.resolve_whitelist_domain(pid, args.domain, db_path=DB)
    if not dom:
        return _print_err(f"domain not on whitelist: {args.domain}")
    site = wdb.get_whitelist_site(pid, dom, db_path=DB)
    if not site:
        return _print_err(f"whitelist site not found: {dom}")

    cfg = _project_config(p)
    niche = p.get("niche") or ""
    subreddits = cfg.get("subreddits") or []
    keywords = cfg.get("target_keywords") or []
    competitors = cfg.get("competitors") or []
    extra: list[str] = []
    if competitors and args.use_competitor_queries:
        from query_expander import expand_competitor_queries  # noqa: E402
        extra = expand_competitor_queries(competitors, niche, keywords, limit=6)

    try:
        status, leads = scan_single_url(
            dom, niche,
            max_results=args.max,
            max_age_days=args.max_age_days,
            subreddits=subreddits if isinstance(subreddits, list) else [],
            keywords=keywords if isinstance(keywords, list) else [],
            extra_queries=extra or None,
        )
    except Exception as e:  # noqa: BLE001
        return _print_err(f"scan failed on {dom}: {e}")

    inserted = 0
    if status == STATUS_OK and leads:
        inserted = wdb.insert_leads(pid, site["id"], leads, db_path=DB)
    wdb.mark_site_scanned_success(
        site["id"], int(p.get("scan_interval_minutes") or 30), db_path=DB,
    )

    summary = {
        "domain": dom,
        "status": status,
        "found": len(leads),
        "inserted": inserted,
        "opportunities": [
            {
                "url": l.get("url"),
                "title": l.get("target_title"),
                "excerpt": (l.get("target_excerpt") or "")[:200],
                "freshness": l.get("opportunity_freshness"),
                "relevance_score": l.get("relevance_score"),
            }
            for l in leads[: args.max]
        ],
    }
    if status == STATUS_BLOCKED:
        print(f"ERROR: search blocked on {dom}", file=sys.stderr)
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 1
    return _print_ok(
        f"scan-domain {dom}: status={status} found={len(leads)} new={inserted}",
        summary,
    )


def cmd_reset_opportunities(args) -> int:
    if not args.confirm:
        return _print_err("reset-opportunities requires --confirm (wipes editorial + harvest pipeline data)")
    pid = None
    if args.project_url:
        p = wdb.get_project(args.project_url, db_path=DB)
        if not p:
            return _print_err(f"project not found: {args.project_url}")
        pid = p["id"]
    editorial = bdb.purge_editorial_data(args.project_url, db_path=DB)
    harvest = wdb.purge_harvest_pipeline(pid, db_path=DB)
    cooldowns = wdb.reset_all_cooldowns(pid, db_path=DB)
    return _print_ok(
        "opportunity pipeline reset (whitelist/projects preserved)",
        {"editorial": editorial, "harvest": harvest, "sites_reset": cooldowns},
    )


def cmd_reset_cooldowns(args) -> int:
    pid = None
    if args.project_url:
        p = wdb.get_project(args.project_url, db_path=DB)
        if not p:
            return _print_err(f"project not found: {args.project_url}")
        pid = p["id"]
    n = wdb.reset_all_cooldowns(pid, db_path=DB)
    return _print_ok(f"{n} site(s) cleared cooldown and set due now")


def cmd_retry_drafts(args) -> int:
    p = wdb.get_project(args.project_url, db_path=DB)
    if not p:
        return _print_err(f"project not found: {args.project_url}")
    n = wdb.reset_failed_leads(p["id"], to_status="GATED", db_path=DB)
    return _print_ok(f"{n} FAILED lead(s) reset to GATED for {args.project_url}")


def cmd_send_cards(args) -> int:
    p = wdb.get_project(args.project_url, db_path=DB)
    if not p:
        return _print_err(f"project not found: {args.project_url}")
    if (p.get("status") or "active") != "active":
        return _print_err(f"project is paused: {args.project_url}")

    count = max(1, min(int(args.count), SEND_CARDS_MAX))
    pid = p["id"]
    cfg = _project_config(p)
    desc = cfg.get("description") or cfg.get("project_description") or ""

    if args.gate_first:
        gated_now = wdb.get_leads_by_status("GATED", limit=count, project_id=pid, db_path=DB)
        if len(gated_now) < count:
            scored = wdb.get_leads_by_status("SCORED", limit=GATE_TOP_N, project_id=pid, db_path=DB)
            scored = [l for l in scored if (l.get("score_100") or 0) >= SCORE_FLOOR]
            if scored:
                judged = gate_leads(
                    scored,
                    niche=p.get("niche") or "",
                    project_desc=desc,
                    project_url=p.get("project_url") or "",
                    threshold=GATE_THRESHOLD,
                )
                for lead in judged:
                    new_status = "GATED" if lead.get("gate_passed") else "REJECTED"
                    wdb.update_lead(
                        lead["id"],
                        {
                            "gate_score": lead.get("gate_score"),
                            "gate_reason": (lead.get("gate_reason") or "")[:200],
                            "status": new_status,
                        },
                        db_path=DB,
                    )

    gated = wdb.get_leads_by_status("GATED", limit=count, project_id=pid, db_path=DB)
    if not gated:
        return _print_ok("no GATED leads ready", {"sent": 0, "urls": []})

    result = draft_and_send(p, gated, db_path=DB)
    if result.error:
        return _print_err(f"send-cards failed: {result.error}")
    if result.sent <= 0:
        return _print_err("send-cards failed: no cards sent")

    return _print_ok(
        f"sent {result.sent} card(s) for {args.project_url}",
        {"sent": result.sent, "run_id": result.run_id, "urls": result.urls},
    )


def cmd_resend_pending(args) -> int:
    p = wdb.get_project(args.project_url, db_path=DB)
    if not p:
        return _print_err(f"project not found: {args.project_url}")
    if (p.get("status") or "active") != "active":
        return _print_err(f"project is paused: {args.project_url}")

    count = max(1, min(int(args.count), RESEND_MAX))
    result = resend_pending_cards(args.project_url, count=count, db_path=DB)
    if result.sent == 0 and result.skipped == 0 and not result.errors:
        return _print_ok("no pending cards to resend", {"sent": 0, "skipped": 0, "alert_ids": []})

    summary = f"resent={result.sent} skipped={result.skipped}"
    if result.errors:
        summary += f" errors={len(result.errors)}"
    return _print_ok(
        summary,
        {
            "sent": result.sent,
            "skipped": result.skipped,
            "alert_ids": result.alert_ids,
            "skipped_reasons": result.skipped_reasons,
            "errors": result.errors,
        },
    )


def cmd_list_pending(args) -> int:
    p = wdb.get_project(args.project_url, db_path=DB)
    if not p:
        return _print_err(f"project not found: {args.project_url}")

    limit = max(1, min(int(args.limit), 50))
    rows = bdb.get_pending_opportunities(args.project_url, limit=limit, db_path=DB)
    cards = [
        {
            "alert_id": o.alert_id,
            "site_url": o.site_url,
            "title": o.target_title or o.content_title,
            "card_sent_at": format_sqlite_display(o.card_sent_at),
        }
        for o in rows
    ]
    return _print_ok(f"{len(cards)} pending card(s) for {args.project_url}", {"pending": cards})


def cmd_find_sites(args) -> int:
    """Deterministic open-web discovery: search, extract domains, insert new ones.

    No LLM. Finds community/forum/Q&A domains for the niche and adds the top N
    that are not already whitelisted. Optional richer qualification can still be
    done later by the bl-site-finder agent.
    """
    from search import search  # local import; network only when this runs

    p = wdb.get_project(args.project_url, db_path=DB)
    if not p:
        return _print_err(f"project not found: {args.project_url}")
    niche = args.niche or p.get("niche") or ""
    pid = p["id"]
    own_domain = urllib.parse.urlparse(args.project_url).netloc.lower().lstrip("www.")
    existing = {s["domain"] for s in wdb.get_active_whitelist(pid, db_path=DB)}

    queries = [
        f"{niche} forum",
        f"{niche} community",
        f"{niche} discussion board",
        f"site:reddit.com {niche}",
    ]
    found: dict[str, str] = {}
    blocked = True
    for q in queries:
        try:
            res = search(q, max_results=10)
            blocked = False
        except SystemExit:
            continue
        except Exception:
            continue
        for r in res.get("results", []):
            url = r.get("url") or ""
            dom = urllib.parse.urlparse(url).netloc.lower().lstrip("www.")
            if not dom or "." not in dom:
                continue
            if dom in _FIND_BLOCKLIST or dom == own_domain or dom in existing or dom in found:
                continue
            found[dom] = url

    if blocked:
        return _print_err("search providers unavailable (throttled); try again later")
    if not found:
        return _print_ok("no new source domains found", {"added": [], "discovered": 0})

    limit = max(1, args.max)
    added = []
    for dom in list(found)[:limit]:
        wdb.upsert_whitelist_site(pid, dom, added_by="finder", db_path=DB)
        added.append({"domain": dom, "evidence_url": found[dom]})
    return _print_ok(
        f"added {len(added)} new source(s) for {args.project_url} (due for scan now)",
        {"added": added, "discovered": len(found)},
    )


# ---------------------------------------------------------------------------
# Arg parsing
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backlink project + source management")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_cfg_args(sp):
        sp.add_argument("--name", default="")
        sp.add_argument("--description", default=None)
        sp.add_argument("--tone", default=None)
        sp.add_argument("--keywords", default=None, help="comma-separated target keywords")
        sp.add_argument("--anchor", default=None, help="comma-separated preferred anchor texts")
        sp.add_argument("--subreddits", default=None, help="comma-separated subreddit names for Reddit scans")
        sp.add_argument("--competitors", default=None, help="comma-separated competitor brands/domains")

    sp = sub.add_parser("add", help="register a project")
    sp.add_argument("--project-url", required=True, dest="project_url")
    sp.add_argument("--niche", required=True)
    sp.add_argument("--interval", type=int, default=30, help="scan interval minutes")
    sp.add_argument("--no-seed", action="store_true", help="do not seed whitelist from platforms.json")
    sp.add_argument("--tiers", default="1,2")
    sp.add_argument(
        "--extra-domains",
        default=None,
        dest="extra_domains",
        help="comma-separated extra whitelist domains (e.g. quora.com,medium.com)",
    )
    add_cfg_args(sp)
    add_group_args(sp)
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("edit", help="edit project personalization")
    sp.add_argument("--project-url", required=True, dest="project_url")
    sp.add_argument("--niche", default=None)
    sp.add_argument("--interval", type=int, default=None, help="scan interval minutes")
    add_cfg_args(sp)
    add_group_args(sp)
    sp.set_defaults(func=cmd_edit)

    for name, fn, helptext in (
        ("pause", cmd_pause, "pause a project"),
        ("resume", cmd_resume, "resume a project"),
        ("status", cmd_status, "detailed project status"),
        ("sources", cmd_sources, "list a project's sources + schedule"),
        ("scan-now", cmd_scan_now, "force a project's sites due now"),
    ):
        sp = sub.add_parser(name, help=helptext)
        sp.add_argument("--project-url", required=True, dest="project_url")
        sp.set_defaults(func=fn)

    sp = sub.add_parser("delete", help="delete a project (irreversible)")
    sp.add_argument("--project-url", required=True, dest="project_url")
    sp.add_argument("--confirm", action="store_true")
    sp.set_defaults(func=cmd_delete)

    sp = sub.add_parser("list", help="list all projects")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("find-sites", help="discover new source domains (deterministic)")
    sp.add_argument("--project-url", required=True, dest="project_url")
    sp.add_argument("--niche", default=None)
    sp.add_argument("--max", type=int, default=5)
    sp.set_defaults(func=cmd_find_sites)

    sp = sub.add_parser("reset-opportunities", help="wipe editorial + harvest pipeline (keep whitelist)")
    sp.add_argument("--project-url", default=None, dest="project_url", help="optional: one project only")
    sp.add_argument("--confirm", action="store_true")
    sp.set_defaults(func=cmd_reset_opportunities)

    sp = sub.add_parser("reset-cooldowns", help="clear site cooldowns and scan due now")
    sp.add_argument("--project-url", default=None, dest="project_url")
    sp.set_defaults(func=cmd_reset_cooldowns)

    sp = sub.add_parser("retry-drafts", help="reset FAILED harvest leads to GATED for re-drafting")
    sp.add_argument("--project-url", required=True, dest="project_url")
    sp.set_defaults(func=cmd_retry_drafts)

    sp = sub.add_parser("send-cards", help="on-demand Ink draft + Telegram send for GATED leads")
    sp.add_argument("--project-url", required=True, dest="project_url")
    sp.add_argument("--count", type=int, default=5, help="max cards to send (1-10, default 5)")
    sp.add_argument("--gate-first", action="store_true", help="gate top SCORED leads first if not enough GATED")
    sp.set_defaults(func=cmd_send_cards)

    sp = sub.add_parser("resend-pending", help="repost unacted pending cards from DB (no re-draft)")
    sp.add_argument("--project-url", required=True, dest="project_url")
    sp.add_argument("--count", type=int, default=5, help="max cards to resend (1-10, default 5)")
    sp.set_defaults(func=cmd_resend_pending)

    sp = sub.add_parser("list-pending", help="list pending editorial cards without sending")
    sp.add_argument("--project-url", required=True, dest="project_url")
    sp.add_argument("--limit", type=int, default=20, help="max rows (default 20)")
    sp.set_defaults(func=cmd_list_pending)

    sp = sub.add_parser("set-priority", help="pin scan priority for one whitelisted domain (0-100)")
    sp.add_argument("--project-url", required=True, dest="project_url")
    sp.add_argument("--domain", required=True, help="domain or alias: reddit, x, news.ycombinator.com")
    sp.add_argument("--priority", type=int, required=True, help="0-100; higher scans first")
    sp.set_defaults(func=cmd_set_priority)

    sp = sub.add_parser("scan-domain", help="scan one whitelisted site now and return opportunities")
    sp.add_argument("--project-url", required=True, dest="project_url")
    sp.add_argument("--domain", required=True, help="domain or alias: reddit, x, dev.to")
    sp.add_argument("--max", type=int, default=12)
    sp.add_argument("--max-age-days", type=int, default=7, dest="max_age_days")
    sp.add_argument("--use-competitor-queries", action="store_true", dest="use_competitor_queries")
    sp.set_defaults(func=cmd_scan_domain)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return args.func(args)
    except Exception as e:  # noqa: BLE001 — surface a clean error to the agent
        return _print_err(str(e))


if __name__ == "__main__":
    sys.exit(main())
