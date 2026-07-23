#!/usr/bin/env python3
"""resend_pending.py — DB-first repost of unacted editorial cards."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import whitelist_db as wdb
from backlink_db import (
    DEFAULT_DB_PATH,
    Opportunity,
    clear_all_edit_sessions,
    get_pending_opportunities,
    resolve_opportunity_content,
    update_opportunity_delivery,
    now_sqlite,
)
from build_and_send_card import (
    load_bot_token,
    opportunity_to_card,
    send_card_dict,
)
from pipeline_log import plog_verbose, truncate  # noqa: E402


@dataclass
class ResendResult:
    sent: int = 0
    skipped: int = 0
    alert_ids: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    skipped_reasons: list[str] = field(default_factory=list)


def _enrich_score_from_lead(opp: Opportunity, db_path: str) -> tuple[float | None, int | None]:
    """Fallback score_100/rank from harvest_leads for legacy opportunity rows."""
    if opp.score_100 is not None and opp.rank is not None:
        return opp.score_100, opp.rank
    if not opp.project_url or not opp.site_url:
        return opp.score_100, opp.rank
    pid = wdb.get_project_id_by_url(opp.project_url, db_path=db_path)
    if pid is None:
        return opp.score_100, opp.rank
    lead = wdb.get_lead_by_url(pid, opp.site_url, db_path=db_path)
    if not lead:
        return opp.score_100, opp.rank
    score = opp.score_100 if opp.score_100 is not None else lead.get("score_100")
    rank = opp.rank if opp.rank is not None else None
    return score, rank


def resend_one_opportunity(opp: Opportunity, *, db_path: str = DEFAULT_DB_PATH) -> bool:
    """Repost one pending card; UPDATE same row. Returns True if sent."""
    content = resolve_opportunity_content(opp, db_path)
    if not content or not content.strip():
        return False

    token = load_bot_token()
    if not token:
        raise RuntimeError("Telegram bot token not found")

    score_100, rank = _enrich_score_from_lead(opp, db_path)
    card = opportunity_to_card(opp, content_md=content, score_100=score_100, rank=rank)
    chat_id = str(card.get("telegram_group") or "").strip()
    if not chat_id:
        raise RuntimeError(f"no telegram_group for opportunity {opp.id}")

    message_id = send_card_dict(card, token=token, chat_id=chat_id)
    if not message_id:
        return False

    update_opportunity_delivery(opp.id, int(message_id), now_sqlite(), db_path=db_path)
    clear_all_edit_sessions(opp.id, db_path=db_path)
    plog_verbose(
        "cards", "card_sent",
        alert_id=opp.alert_id,
        message_id=message_id,
        site_url=truncate(opp.site_url or "", 120),
        resend=True,
    )
    return True


def resend_pending_cards(
    project_url: str,
    *,
    count: int = 5,
    db_path: str = DEFAULT_DB_PATH,
) -> ResendResult:
    result = ResendResult()
    pending = get_pending_opportunities(project_url, limit=count, db_path=db_path)
    if not pending:
        return result

    for opp in pending:
        try:
            content = resolve_opportunity_content(opp, db_path)
            if not content or not content.strip():
                result.skipped += 1
                result.skipped_reasons.append(f"{opp.alert_id}: no_content")
                continue
            if resend_one_opportunity(opp, db_path=db_path):
                result.sent += 1
                result.alert_ids.append(opp.alert_id)
            else:
                result.skipped += 1
                result.skipped_reasons.append(f"{opp.alert_id}: send_failed")
        except Exception as e:  # noqa: BLE001
            result.errors.append(f"{opp.alert_id}: {e}")
    return result
