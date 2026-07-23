#!/usr/bin/env python3
"""opportunity_hunter.py — Cheap-LLM query planner for low-yield projects."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pipeline_tz import now_sqlite
import whitelist_db as wdb
import backlink_db as bdb

_SEARCH_DIR = os.path.dirname(os.path.abspath(__file__))
_PIPELINE_DIR = os.path.abspath(os.path.join(_SEARCH_DIR, "..", "pipeline"))
if _SEARCH_DIR not in sys.path:
    sys.path.insert(0, _SEARCH_DIR)

from discover import clean_terms  # noqa: E402

DEFAULT_BASE_URL = os.environ.get("BIFROST_BASE_URL", "https://placing-reliability-container-oecd.trycloudflare.com/v1")
DEFAULT_MODEL = os.environ.get("BL_HUNTER_MODEL", os.environ.get("BL_GATE_MODEL", "vertex/gemini-2.5-flash"))
DEFAULT_TIMEOUT = int(os.environ.get("BL_HUNTER_TIMEOUT", "45"))
CACHE_DIR = os.path.expanduser("~/.openclaw-backlink/data/hunter_cache")
CACHE_TTL_HOURS = float(os.environ.get("BL_HUNTER_CACHE_HOURS", "24"))

_SYSTEM = (
    "You are a backlink opportunity query planner. Given a project niche, description, "
    "keywords, and competitors, output 8-12 diverse search queries that would find fresh "
    "forum threads, Q&A posts, Reddit discussions, or blog comment opportunities where "
    "someone could leave a helpful reply with a relevant link. "
    "Return STRICT JSON only: {\"queries\":[\"...\", ...]}. No prose."
)


def _cache_path(project_id: int) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"project_{project_id}.json")


def _load_cache(project_id: int) -> list[str] | None:
    path = _cache_path(project_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        ts = float(data.get("ts") or 0)
        if time.time() - ts > CACHE_TTL_HOURS * 3600:
            return None
        qs = data.get("queries") or []
        return [str(q) for q in qs if q]
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _save_cache(project_id: int, queries: list[str]) -> None:
    path = _cache_path(project_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"ts": time.time(), "queries": queries}, f, ensure_ascii=False)
    
    # Also save to PostgreSQL database for dashboard visibility
    try:
        import whitelist_db as wdb
        import os
        db_path = os.environ.get("BL_DB_PATH", os.path.expanduser("~/.openclaw-backlink/data/backlink.db"))
        
        with wdb._connect(db_path) as conn:
            row = conn.execute("SELECT config_json FROM projects WHERE id = %s", (project_id,)).fetchone()
            if row:
                try:
                    cfg = json.loads(row[0] or "{}")
                except:
                    cfg = {}
                cfg["recent_queries"] = queries
                cfg["last_query_time"] = time.time()
                
                conn.execute(
                    "UPDATE projects SET config_json = %s WHERE id = %s",
                    (json.dumps(cfg), project_id)
                )
                conn.commit()
    except Exception as e:
        print(f"Failed to save queries to db: {e}")


def _call_llm(prompt: str, model: str, base_url: str, timeout: int) -> str:
    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 800,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": "Bearer dummy"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"]


def _parse_queries(content: str) -> list[str]:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text
        text = text.lstrip("json").strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return []
    obj = json.loads(text[start : end + 1])
    return [str(q).strip() for q in (obj.get("queries") or []) if str(q).strip()]


def plan_queries(
    *,
    project_id: int,
    niche: str,
    description: str = "",
    keywords: list[str] | None = None,
    competitors: list[str] | None = None,
    force_refresh: bool = False,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    timeout: int = DEFAULT_TIMEOUT,
) -> list[str]:
    """Return cached or freshly planned search queries."""
    if not force_refresh:
        cached = _load_cache(project_id)
        if cached:
            return cached

    terms = clean_terms(niche, keywords)
    prompt = (
        f"NICHE: {niche}\n"
        f"DESCRIPTION: {description or '(none)'}\n"
        f"KEYWORDS: {', '.join(terms)}\n"
        f"COMPETITORS: {', '.join(competitors or [])}\n"
        "Generate 8-12 search queries."
    )
    try:
        content = _call_llm(prompt, model, base_url, timeout)
        queries = _parse_queries(content)
    except Exception:
        queries = []

    if not queries:
        # Deterministic fallback
        from query_expander import expand_openweb_queries  # noqa: E402
        queries = expand_openweb_queries(niche, keywords, limit=8)

    _save_cache(project_id, queries)
    return queries
