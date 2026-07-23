#!/usr/bin/env python3
"""vocab_miner.py — Mine harvest leads for new query vocabulary terms."""
from __future__ import annotations

import os
import re
import sys
from collections import Counter

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

import whitelist_db as wdb  # noqa: E402

STOP = frozenset(
    "a an the and or but in on at to for of is are was were be been being "
    "this that with from as it by not you your we our they their has have had "
    "can will just about into over after before more most other some such only "
    "also very when what how why who which".split()
)


def _tokenize(text: str) -> list[str]:
    words = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
    return [w for w in words if w not in STOP]


def _bigrams(tokens: list[str]) -> list[str]:
    return [f"{tokens[i]} {tokens[i+1]}" for i in range(len(tokens) - 1)]


def mine_project_vocab(
    project_id: int,
    *,
    db_path: str | None = None,
    hours: int = 72,
    limit: int = 15,
) -> int:
    """Extract and promote top terms from recent harvest_leads. Returns count promoted."""
    db_path = db_path or wdb.DEFAULT_DB_PATH
    wdb.init_whitelist_db(db_path)
    with wdb._connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT target_title, target_excerpt FROM harvest_leads
            WHERE project_id = %s AND created_at >= NOW() AT TIME ZONE 'UTC' + CAST(%s || '  hours' AS INTERVAL)
            """,
            (project_id, f"-{hours}"),
        ).fetchall()
        approved = conn.execute(
            """
            SELECT o.site_url, o.target_title, o.target_excerpt FROM opportunities o
            JOIN projects p ON p.id = o.project_id
            WHERE p.id = %s AND o.status = 'approved'
            LIMIT 50
            """,
            (project_id,),
        ).fetchall()

    counter: Counter[str] = Counter()
    for row in rows:
        text = f"{row['target_title'] or ''} {row['target_excerpt'] or ''}"
        tokens = _tokenize(text)
        for t in tokens:
            counter[t] += 1
        for bg in _bigrams(tokens):
            if len(bg) <= 40:
                counter[bg] += 2

    # Boost terms from approved opportunities (content + domain)
    for row in approved:
        content = f"{row['target_title'] or ''} {row['target_excerpt'] or ''}"
        tokens = _tokenize(content)
        for t in tokens:
            counter[t] += 5
        for bg in _bigrams(tokens):
            if len(bg) <= 40:
                counter[bg] += 6
        url_tokens = _tokenize(row["site_url"] or "")
        for t in url_tokens:
            counter[t] += 3

    top = counter.most_common(limit * 2)
    terms: list[tuple[str, float, str]] = []
    for term, freq in top:
        if freq < 2:
            continue
        score = min(100.0, float(freq) * 2.5)
        terms.append((term, score, "miner"))
        if len(terms) >= limit:
            break
    return wdb.upsert_vocab_terms(project_id, terms, db_path=db_path)

def seed_pdf_vocab_with_ai(project_id: int, pdf_text: str, db_path: str = None) -> int:
    import urllib.request
    import json
    import whitelist_db as wdb
    
    db_path = db_path or wdb.DEFAULT_DB_PATH
    base_url = os.environ.get("BIFROST_BASE_URL", "https://placing-reliability-container-oecd.trycloudflare.com/v1")
    model = os.environ.get("DEFAULT_MODEL", "vertex/gemini-2.5-flash")
    
    # Take first 4000 characters to prevent huge payloads
    text_sample = pdf_text[:4000]
    
    messages = [
        {"role": "system", "content": "You are a vocabulary miner. Extract 10 highly relevant search keywords/phrases from the given document that people might search for on Reddit/Quora when they need this product. Return ONLY a comma-separated list of keywords without any quotes, numbering, or extra text."},
        {"role": "user", "content": f"Document context:\n{text_sample}\n\nKeywords:"}
    ]
    
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.3,
        "max_tokens": 500,
    }
    
    try:
        url = f"{base_url.rstrip('/')}/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": "Bearer dummy"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
        data = json.loads(raw)
        result = data["choices"][0]["message"]["content"]
        
        # Parse comma separated keywords
        keywords = [k.strip().strip('"').strip("'") for k in result.split(",") if k.strip()]
        
        # Upsert vocab
        terms = [(kw, 90.0, "pdf_ai_seed") for kw in keywords if len(kw) > 3][:15]
        if terms:
            return wdb.upsert_vocab_terms(project_id, terms, db_path=db_path)
    except Exception as e:
        import logging
        logging.error(f"Failed to seed PDF vocab: {e}")
    return 0
