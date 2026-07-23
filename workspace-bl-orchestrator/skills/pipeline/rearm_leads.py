#!/usr/bin/env python3
"""rearm_leads.py — Controlled dedup re-arming for stale high-value threads."""
from __future__ import annotations

import os
import sys

_PIPELINE_DIR = os.path.dirname(os.path.abspath(__file__))
if _PIPELINE_DIR not in sys.path:
    sys.path.insert(0, _PIPELINE_DIR)

import whitelist_db as wdb  # noqa: E402
from pipeline_log import plog_verbose  # noqa: E402

REARM_TTL_DAYS = int(os.environ.get("BL_REARM_TTL_DAYS", "21"))
REARM_LIMIT = int(os.environ.get("BL_REARM_LIMIT", "5"))


def process_rearm(project_id: int, *, db_path: str | None = None) -> int:
    """Revive eligible seen leads back to NEW. Returns count revived."""
    db_path = db_path or wdb.DEFAULT_DB_PATH
    candidates = wdb.get_rearm_candidates(
        project_id, ttl_days=REARM_TTL_DAYS, limit=REARM_LIMIT, db_path=db_path,
    )
    revived = 0
    for lead in candidates:
        if wdb.revive_lead(project_id, lead["url_key"], db_path=db_path):
            revived += 1
            plog_verbose("scan", "rearm_revived", url_key=lead["url_key"][:120])
    if revived:
        plog_verbose("scan", "rearm_done", project_id=project_id, revived=revived)
    return revived
