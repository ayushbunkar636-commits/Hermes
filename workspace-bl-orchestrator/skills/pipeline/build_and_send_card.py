#!/usr/bin/env python3
"""
build_and_send_card.py — Build backlink opportunity cards and send to Telegram.

Usage:
    python3 build_and_send_card.py --manifest /path/to/manifest.json

Always exits 0 (fail-open). Prints CARD_SENT or CARD_FAILED per post.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from html import escape as html_escape
from typing import Any

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from backlink_db import init_db, insert_opportunity, now_sqlite  # noqa: E402
from pipeline_tz import format_display  # noqa: E402
from pipeline_log import plog_verbose, truncate  # noqa: E402
import whitelist_db as wdb  # noqa: E402

OPENCLAW_JSON = os.path.expanduser("~/.openclaw-backlink/openclaw.json")
TELEGRAM_CONFIG = os.path.expanduser(
    "~/.openclaw-backlink/workspace-bl-orchestrator/config/telegram_card_config.json"
)
TELEGRAM_CAPTION_MAX = 1024
TELEGRAM_MESSAGE_MAX = 4096
_DRAFT_MSG_PREFIX = "📝 <b>Content to Post</b> (copy below):\n\n<pre>"
_DRAFT_MSG_SUFFIX = "</pre>"


def load_json(path: str, default: dict | None = None) -> dict:
    if not path or not os.path.isfile(path):
        return default or {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else (default or {})
    except (OSError, json.JSONDecodeError):
        return default or {}


def load_bot_token() -> str:
    if os.environ.get("TELEGRAM_BOT_TOKEN"):
        return str(os.environ.get("TELEGRAM_BOT_TOKEN")).strip()

    tg_cfg = load_json(TELEGRAM_CONFIG)
    token = str(tg_cfg.get("bot_token") or "").strip()
    if token:
        return token

    openclaw = load_json(OPENCLAW_JSON)
    telegram = (openclaw.get("channels") or {}).get("telegram") or {}
    account_id = str(tg_cfg.get("telegram_account") or "backlink").strip()
    account = (telegram.get("accounts") or {}).get(account_id) or {}
    token = str(account.get("botToken") or "").strip()
    if token:
        return token
    return str(telegram.get("botToken") or "").strip()


def atomic_write_json(path: str, data) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8"
    ) as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        tmp = f.name
    os.replace(tmp, path)


def truncate(text: str, max_len: int) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def html_safe_truncate(html: str, max_len: int) -> str:
    """Truncate an HTML-parse_mode string without breaking entities or tags.

    Telegram rejects (HTTP 400) messages whose HTML is cut mid-entity (e.g.
    '&am') or mid-tag, or that leave an unbalanced <b>. This trims back to a safe
    boundary and closes any still-open <b> tags.
    """
    if len(html) <= max_len:
        return html
    cut = html[: max_len - 1]
    # Don't end inside an HTML entity (a trailing '&' with no closing ';').
    amp, semi = cut.rfind("&"), cut.rfind(";")
    if amp > semi:
        cut = cut[:amp]
    # Don't end inside a tag (a trailing '<' with no closing '>').
    lt, gt = cut.rfind("<"), cut.rfind(">")
    if lt > gt:
        cut = cut[:lt]
    cut = cut.rstrip() + "…"
    # Balance bold tags (the only tag we open in captions).
    opens, closes = cut.count("<b>"), cut.count("</b>")
    if opens > closes:
        cut += "</b>" * (opens - closes)
    return cut


def build_inline_keyboard(card: dict) -> dict:
    run_id = str(card.get("run_id") or "").strip()
    alert_id = str(card.get("alert_id") or "").strip()
    if not run_id or not alert_id:
        return {}
    return {
        "inline_keyboard": [
            [
                {"text": "Approve", "callback_data": f"bl_approve:{alert_id}"},
                {"text": "Edit", "callback_data": f"bl_edit:{alert_id}"},
                {"text": "Reject", "callback_data": f"bl_reject:{alert_id}"},
            ]
        ]
    }


def pick_chain_field(
    post: dict, audit: dict, discovery: dict, key: str, default: Any = ""
) -> Any:
    for source in (post, audit, discovery):
        value = source.get(key)
        if value not in (None, ""):
            return value
    return default


def normalize_posting_steps(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(step).strip() for step in value if str(step).strip()]
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(step).strip() for step in parsed if str(step).strip()]
        except json.JSONDecodeError:
            pass
        return [line.strip() for line in value.splitlines() if line.strip()]
    return []


def format_posting_steps(steps: list[str], max_steps: int = 5) -> str:
    if not steps:
        return "Follow submission instructions on the target page."
    shown = steps[:max_steps]
    lines = [f"{idx}. {step}" for idx, step in enumerate(shown, start=1)]
    if len(steps) > max_steps:
        lines.append("…")
    return "\n".join(lines)


def format_draft_plain(text: str) -> str:
    """Convert Ink markdown to plain copy-paste text."""
    text = (text or "").strip()
    if not text:
        return ""

    def _link_repl(match: re.Match[str]) -> str:
        label, url = match.group(1), match.group(2)
        return f"{label} — {url}" if label else url

    text = re.sub(r"\[([^\]]*)\]\(([^)]+)\)", _link_repl, text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"(%s<!\*)\*(%s!\*)([^*]+)(%s<!\*)\*(%s!\*)", r"\1", text)
    return text.strip()


def _card_score_display(card: dict) -> tuple[str, str, str, str]:
    score_100 = card.get("score_100")
    score = score_100 if score_100 is not None else card.get("audit_score")
    rank = card.get("rank")
    score_display = ""
    if score is not None:
        if score_100 is not None:
            score_display = f"{score_100}/100"
        else:
            score_display = f"{score}/10"
    rank_display = f" #{rank}" if rank else ""
    
    # Parse new fields
    confidence = card.get("confidence")
    if confidence is not None:
        if confidence >= 90:
            conf_label = "Very High"
        elif confidence >= 75:
            conf_label = "High"
        elif confidence >= 60:
            conf_label = "Medium"
        else:
            conf_label = "Low"
        confidence_display = f"{confidence}% ({conf_label})"
    else:
        confidence_display = "N/A"
    
    breakdown_text = ""
    bd = card.get("score_breakdown")
    if bd:
        if isinstance(bd, str):
            try:
                bd = json.loads(bd)
            except:
                bd = {}
        if isinstance(bd, dict):
            breakdown_text = (
                f"• Recency: {bd.get('recency', 0)}/30\\n"
                f"• Authority: {bd.get('authority', 0)}/30\\n"
                f"• Relevance: {bd.get('relevance', 0)}/20\\n"
                f"• Usability: {bd.get('usability', 0)}/10\\n"
                f"• Freshness: {bd.get('freshness', 0)}/10"
            )
            
    reasoning_text = ""
    rs = card.get("reasoning")
    if rs:
        if isinstance(rs, str):
            try:
                rs = json.loads(rs)
            except:
                rs = []
        if isinstance(rs, list):
            reasoning_text = "\\n".join(f"- {r}" for r in rs)
            
    return score_display, rank_display, confidence_display, breakdown_text, reasoning_text


def build_card_header(card: dict) -> str:
    """Metadata card (no draft body) — fits Telegram photo caption limit."""
    niche = html_escape(card.get("niche") or "")
    project_url = html_escape(card.get("project_url") or "")
    site_domain = html_escape(card.get("site_domain") or "")
    score_display, rank_display, confidence_display, breakdown_text, reasoning_text = _card_score_display(card)

    target_title = html_escape(
        truncate(card.get("target_title") or card.get("content_title") or "Backlink opportunity", 160)
    )
    opportunity_context = html_escape(truncate(card.get("opportunity_context") or "", 160))
    posting_action = html_escape(str(card.get("posting_action") or ""))
    posting_steps = html_escape(format_posting_steps(normalize_posting_steps(card.get("posting_steps"))))

    submission_url_raw = str(card.get("submission_url") or "").strip()
    submission_url = html_escape(submission_url_raw)
    go_here = submission_url if submission_url_raw else "(locate exact submission page)"

    lines = [
        f"<b>OPPORTUNITY{rank_display}</b>",
        f"<b>Title:</b> {target_title}",
        f"<b>Platform:</b> {site_domain}",
        f"<b>Score:</b> {score_display}  |  <b>Confidence:</b> {confidence_display}",
    ]
    
    if breakdown_text:
        lines.extend(["", "📊 <b>Breakdown:</b>", breakdown_text])
        
    impact_dict = card.get("business_impact")
    if impact_dict:
        if isinstance(impact_dict, str):
            try:
                impact_dict = json.loads(impact_dict)
            except:
                impact_dict = {}
        if isinstance(impact_dict, dict) and impact_dict:
            lines.extend([
                "",
                "📈 <b>Business Impact</b>",
                f"• Lead Quality: {impact_dict.get('lead_quality', 'N/A')}",
                f"• Priority: {impact_dict.get('priority', 'N/A')}",
                f"• Traffic: {impact_dict.get('traffic', 'N/A')}",
                f"• Revenue: {impact_dict.get('revenue', 'N/A')}",
                f"• SEO Impact: {impact_dict.get('seo', 'N/A')}",
            ])
            
    if reasoning_text:
        lines.extend(["", "💡 <b>Reason:</b>", reasoning_text])
        
    lines.extend([
        "",
        f"<b>Niche:</b> {niche} | <b>Project:</b> {project_url}",
        f"<b>Action:</b> {posting_action or 'submit'}",
    ])

    if not breakdown_text and target_title:
        lines.extend(["", "<b>Target Title:</b>", f"{target_title}"])

    if opportunity_context:
        lines.extend(["", "<b>Why this is a good opportunity:</b>", f"{opportunity_context}"])

    lines.extend(
        [
            "",
            "📝 <b>Content to Post:</b> see reply below ⬇️",
            "",
            "📋 <b>How to post:</b>",
            "",
            f"{posting_steps}",
            "",
            "🔗 <b>DIRECT LINK (Go here to post):</b>",
            f"{go_here}",
        ]
    )

    sent_label = html_escape(format_display(str(card.get("card_sent_at") or "")))
    lines.append(f"\n<i>Sent: {sent_label}</i>")

    caption = "\n".join(lines)
    if len(caption) > TELEGRAM_CAPTION_MAX:
        caption = html_safe_truncate(caption, TELEGRAM_CAPTION_MAX)
    return caption


def build_draft_message(card: dict) -> str:
    """Full copy-paste draft as a reply message (up to Telegram text limit)."""
    raw = str(card.get("content_preview") or card.get("content_md") or "").strip()
    if not raw:
        return ""

    draft = format_draft_plain(raw)
    backlink = str(card.get("backlink_url") or "").strip()
    anchor = str(card.get("backlink_anchor_text") or "").strip()
    if backlink and backlink not in draft:
        ref = f"{anchor} — {backlink}" if anchor else backlink
        draft = f"{draft}\n\nSource/Reference: {ref}"

    overhead = len(_DRAFT_MSG_PREFIX) + len(_DRAFT_MSG_SUFFIX)
    max_draft = TELEGRAM_MESSAGE_MAX - overhead - 20
    if len(draft) > max_draft:
        draft = draft[: max_draft - 1].rstrip() + "…"

    return f"{_DRAFT_MSG_PREFIX}{html_escape(draft)}{_DRAFT_MSG_SUFFIX}"


def build_caption(card: dict) -> str:
    """Backward-compatible alias — returns header only (draft is a separate message)."""
    return build_card_header(card)


def telegram_request(
    token: str, method: str, data: dict | None = None, files: dict | None = None
) -> dict:
    import config
    if data is not None and "chat_id" in data and config.TELEGRAM_CHAT_ID:
        data["chat_id"] = config.TELEGRAM_CHAT_ID
        
    url = f"https://api.telegram.org/bot{token}/{method}"
    if files:
        boundary = "----OpenClawBoundary"
        body_parts: list[bytes] = []
        for name, (filename, content, mime) in files.items():
            body_parts.append(f"--{boundary}\r\n".encode())
            body_parts.append(
                f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
            )
            body_parts.append(f"Content-Type: {mime}\r\n\r\n".encode())
            body_parts.append(content)
            body_parts.append(b"\r\n")
        if data:
            for key, val in data.items():
                body_parts.append(f"--{boundary}\r\n".encode())
                body_parts.append(f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode())
                body_parts.append(str(val).encode("utf-8"))
                body_parts.append(b"\r\n")
        body_parts.append(f"--{boundary}--\r\n".encode())
        body = b"".join(body_parts)
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
    else:
        encoded = urllib.parse.urlencode(data or {}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # Telegram puts the real reason in the response body; surface it so
        # failures are diagnosable instead of a bare "HTTP Error 400".
        try:
            body = e.read().decode("utf-8")
            desc = json.loads(body).get("description", body)
        except Exception:
            desc = str(e)
        raise RuntimeError(f"Telegram {method} HTTP {e.code}: {desc}") from e
    result = json.loads(raw)
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "unknown Telegram error"))
    return result


def send_telegram_card(
    token: str,
    chat_id: str,
    caption: str,
    image_path: str | None,
    reply_markup: str | None = None,
) -> int | None:
    base_data: dict[str, str] = {"chat_id": chat_id, "parse_mode": "HTML"}
    if reply_markup:
        base_data["reply_markup"] = reply_markup

    if image_path and os.path.isfile(image_path):
        size = os.path.getsize(image_path)
        if size > 10000:
            mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
            with open(image_path, "rb") as f:
                content = f.read()
            payload = {**base_data, "caption": caption}
            result = telegram_request(
                token,
                "sendPhoto",
                data=payload,
                files={"photo": (os.path.basename(image_path), content, mime)},
            )
            msg = result.get("result") or {}
            return msg.get("message_id")

    payload = {**base_data, "text": caption, "disable_web_page_preview": "false"}
    result = telegram_request(token, "sendMessage", data=payload)
    msg = result.get("result") or {}
    return msg.get("message_id")


def opportunity_to_card(
    opp: Any,
    *,
    content_md: str | None = None,
    score_100: float | None = None,
    rank: int | None = None,
) -> dict[str, Any]:
    """Map DB Opportunity row → card dict for build_caption / send."""
    draft = content_md if content_md is not None else (opp.content_md or "")
    image_path = opp.image_path
    if image_path and not os.path.isfile(image_path):
        image_path = None
    return {
        "run_id": opp.run_id,
        "run_dir": opp.run_dir,
        "alert_id": opp.alert_id,
        "niche": opp.niche,
        "project_url": opp.project_url,
        "project_name": opp.project_name,
        "site_url": opp.site_url,
        "site_domain": opp.site_domain,
        "site_type": opp.site_type,
        "audit_score": opp.audit_score,
        "score_100": score_100 if score_100 is not None else opp.score_100,
        "rank": rank if rank is not None else opp.rank,
        "domain_authority": opp.domain_authority,
        "dofollow": opp.dofollow,
        "recommendation": opp.recommendation,
        "audit_notes": opp.audit_notes,
        "content_title": opp.content_title,
        "content_md": draft,
        "content_preview": draft,
        "backlink_url": opp.backlink_url,
        "backlink_anchor_text": opp.backlink_anchor_text,
        "image_path": image_path,
        "submission_instructions": opp.submission_instructions,
        "submission_url": opp.submission_url,
        "target_title": opp.target_title,
        "target_excerpt": opp.target_excerpt,
        "opportunity_context": opp.opportunity_context,
        "opportunity_freshness": opp.opportunity_freshness,
        "posting_action": opp.posting_action,
        "posting_steps": opp.posting_steps,
        "telegram_group": opp.telegram_group,
        "status": opp.status,
        "score_breakdown": getattr(opp, "score_breakdown", None),
        "confidence": getattr(opp, "confidence", None),
        "reasoning": getattr(opp, "reasoning", None),
    }


def send_telegram_draft_reply(
    token: str,
    chat_id: str,
    reply_to_message_id: int,
    text: str,
) -> int | None:
    """Send full draft immediately after the header card (same burst, no delay)."""
    if not text.strip():
        return None
    payload: dict[str, str] = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_to_message_id": str(reply_to_message_id),
        "disable_web_page_preview": "true",
    }
    result = telegram_request(token, "sendMessage", data=payload)
    msg = result.get("result") or {}
    return msg.get("message_id")


def send_card_dict(card: dict[str, Any], *, token: str, chat_id: str) -> int | None:
    """Send header card + draft reply back-to-back; returns header message_id (for callbacks)."""
    header = build_card_header(card)
    draft_text = build_draft_message(card)
    keyboard = build_inline_keyboard(card)
    reply_markup = json.dumps(keyboard) if keyboard else None
    message_id = send_telegram_card(
        token,
        chat_id,
        header,
        card.get("image_path"),
        reply_markup=reply_markup,
    )
    if message_id and draft_text:
        send_telegram_draft_reply(token, chat_id, message_id, draft_text)
    return message_id


def merge_audit_by_url(audit_data: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for site in audit_data.get("audited_sites") or []:
        url = str(site.get("url") or "").strip()
        if url:
            out[url] = site
    return out


def merge_discovery_by_url(discovery_data: dict) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for site in discovery_data.get("sites") or []:
        url = str(site.get("url") or "").strip()
        if url:
            out[url] = site
    return out


def resolve_chat_id(project_url: str | None, fallback: str = "") -> str:
    """Per-project Telegram group id.

    Reads ``telegram_group_id`` from the projects table so each project
    routes cards to its own group. Falls back to the global config group.
    """
    if project_url:
        try:
            gid = wdb.resolve_chat_id_for_project(project_url, fallback=fallback)
            if gid:
                return gid
        except (ValueError, OSError):
            pass
    return str(fallback or "").strip()


def build_cards_from_manifest(manifest_path: str) -> tuple[list[dict], str, str]:
    manifest = load_json(manifest_path)
    if not manifest:
        raise ValueError(f"manifest missing or invalid: {manifest_path}")

    run_id = manifest.get("run_id", "")
    run_dir = manifest.get("run_dir", "")
    project = manifest.get("project") or {}
    artifacts = manifest.get("artifacts") or {}

    posts_path = artifacts.get("content_posts") or os.path.join(run_dir, "content", "posts.json")
    # New pipeline: use content_queue.json for enrichment; old fields fall back gracefully to empty dicts.
    content_queue_path = artifacts.get("content_queue") or os.path.join(run_dir, "content_queue.json")
    audit_path = artifacts.get("audit_results") or os.path.join(run_dir, "audit", "results.json")
    discovery_path = artifacts.get("discovery_validated") or os.path.join(
        run_dir, "discovery", "validated.json"
    )

    posts_data = load_json(posts_path)
    # Enrich with content_queue scored data (new pipeline) or audit/discovery data (legacy pipeline)
    content_queue_data = load_json(content_queue_path)
    audit_data = load_json(audit_path)
    # Merge scored opportunities from content_queue into the audit map
    merged_queue_map: dict[str, dict] = {}
    for opp in content_queue_data.get("opportunities", []):
        url = str(opp.get("url") or opp.get("submission_url") or "").strip()
        if url:
            merged_queue_map[url] = opp
    audit_map = {**merged_queue_map, **merge_audit_by_url(audit_data)}
    discovery_map = merge_discovery_by_url(load_json(discovery_path))

    cards: list[dict[str, Any]] = []
    for idx, post in enumerate(posts_data.get("posts") or []):
        site_url = str(post.get("site_url") or "")
        audit = audit_map.get(site_url, {})
        discovery = discovery_map.get(site_url, {})
        domain = post.get("site_domain") or audit.get("domain") or f"site-{idx+1}"
        alert_id = f"bl-{run_id}-{domain}".replace(".", "-")[:64]

        submission_url = pick_chain_field(post, audit, discovery, "submission_url", "")

        image_path = post.get("image_path")
        if image_path:
            image_path = os.path.realpath(str(image_path))

        card: dict[str, Any] = {
            "run_id": run_id,
            "run_dir": run_dir,
            "alert_id": alert_id,
            "niche": project.get("niche") or posts_data.get("niche"),
            "project_url": project.get("project_url") or posts_data.get("project_url"),
            "project_name": project.get("project_name") or project.get("niche"),
            "site_url": site_url,
            "site_domain": domain,
            "site_type": post.get("type") or audit.get("type"),
            "audit_score": audit.get("score"),
            "score_100": post.get("score_100") or audit.get("score_100"),
            "rank": post.get("rank") or audit.get("rank"),
            "domain_authority": audit.get("domain_authority"),
            "dofollow": audit.get("dofollow"),
            "recommendation": audit.get("recommendation"),
            "audit_notes": audit.get("audit_notes"),
            "content_title": post.get("title"),
            "content_md": post.get("content"),
            "content_preview": post.get("content"),
            "backlink_url": post.get("backlink_url"),
            "backlink_anchor_text": post.get("backlink_anchor_text"),
            "image_path": image_path if image_path and os.path.isfile(image_path) else None,
            "submission_instructions": post.get("submission_instructions"),
            "submission_url": submission_url,
            "target_title": pick_chain_field(post, audit, discovery, "target_title"),
            "target_excerpt": pick_chain_field(post, audit, discovery, "target_excerpt"),
            "opportunity_context": pick_chain_field(post, audit, discovery, "opportunity_context"),
            "opportunity_freshness": pick_chain_field(post, audit, discovery, "opportunity_freshness"),
            "posting_action": pick_chain_field(post, audit, discovery, "posting_action"),
            "posting_steps": pick_chain_field(post, audit, discovery, "posting_steps", []),
            "card_sent_at": now_sqlite(),
            "telegram_group": "",
            "telegram_message_id": None,
            "status": "pending",
            "score_breakdown": post.get("score_breakdown") or audit.get("score_breakdown"),
            "confidence": post.get("confidence") or audit.get("confidence"),
            "reasoning": post.get("reasoning") or audit.get("reasoning"),
        }
        cards.append(card)

    delivery_path = artifacts.get("delivery_card") or os.path.join(run_dir, "delivery", "card.json")
    project_url = str(
        project.get("project_url") or posts_data.get("project_url") or ""
    ).strip()
    return cards, delivery_path, project_url


def main() -> int:
    parser = argparse.ArgumentParser(description="Build and send backlink Telegram cards")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--ordered", action="store_true",
                        help="Cards are already sorted best-to-worst; preserve input order (default behaviour)")
    args = parser.parse_args()

    manifest_path = os.path.realpath(args.manifest)
    sent = 0
    failed = 0

    try:
        cards, delivery_path, project_url = build_cards_from_manifest(manifest_path)
        if not cards:
            raise ValueError("no posts to send")

        token = load_bot_token()
        if not token:
            raise ValueError("Telegram bot token not found in telegram_card_config.json or openclaw.json")

        tg_cfg = load_json(TELEGRAM_CONFIG)
        fallback_chat_id = os.environ.get("TELEGRAM_CHAT_ID") or str(tg_cfg.get("group_id") or "").strip()
        chat_id = resolve_chat_id(project_url or None, fallback=fallback_chat_id)
        if not chat_id:
            raise ValueError("group_id missing in telegram_card_config.json and no project group set")

        init_db()
        delivery_records = []

        for card in cards:
            try:
                card["telegram_group"] = chat_id
                card["card_sent_at"] = now_sqlite()
                message_id = send_card_dict(card, token=token, chat_id=chat_id)
                card["telegram_message_id"] = message_id
                insert_opportunity(card)
                delivery_records.append(card)
                sent += 1
                print(f"CARD_SENT: {card.get('alert_id')} message_id={message_id}")
                plog_verbose(
                    "cards", "card_sent",
                    alert_id=card.get("alert_id"),
                    message_id=message_id,
                    site_url=truncate(card.get("site_url") or "", 120),
                )
            except Exception as e:
                failed += 1
                card["send_error"] = str(e)
                delivery_records.append(card)
                print(f"CARD_FAILED: {card.get('alert_id')} {e}", file=sys.stderr)
                plog_verbose(
                    "cards", "card_failed",
                    alert_id=card.get("alert_id"),
                    error=truncate(str(e), 200),
                )

        atomic_write_json(
            delivery_path,
            {
                "run_id": cards[0].get("run_id"),
                "cards": delivery_records,
                "sent": sent,
                "failed": failed,
            },
        )
    except Exception as e:
        print(f"CARD_FAILED: {e}", file=sys.stderr)
        failed += 1

    print(f"CARDS_SUMMARY: sent={sent} failed={failed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
