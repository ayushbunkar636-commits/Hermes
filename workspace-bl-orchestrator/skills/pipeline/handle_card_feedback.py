#!/usr/bin/env python3
"""
handle_card_feedback.py — Backlink card feedback: APPROVE, EDIT, REJECT.

Always exits 0 (fail-open).
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
import tempfile
import urllib.parse
import urllib.request

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from backlink_db import (  # noqa: E402
    DEFAULT_DB_PATH,
    Opportunity,
    clear_edit_session,
    get_edit_session_by_prompt,
    get_latest_version,
    init_db,
    lookup_by_alert_id,
    lookup_by_message_id,
    lookup_by_run_id,
    purge_editorial_data,
    record_feedback,
    resolve_opportunity_content,
    save_content_version,
    set_status,
    upsert_edit_session,
)
import whitelist_db as wdb  # noqa: E402
from vocab_miner import mine_project_vocab  # noqa: E402

OPENCLAW_JSON = os.path.expanduser("~/.openclaw-backlink/openclaw.json")
TELEGRAM_CONFIG = os.path.expanduser(
    "~/.openclaw-backlink/workspace-bl-orchestrator/config/telegram_card_config.json"
)

_RE_APPROVE = re.compile(r"^bl_approve:(.+)$")
_RE_REJECT = re.compile(r"^bl_reject:(.+)$")
_RE_EDIT = re.compile(r"^bl_edit:(.+)$")
_RE_EDIT_APPLY = re.compile(r"^bl_edit_apply:(.+)$")
_RE_EDIT_CANCEL = re.compile(r"^bl_edit_cancel:(.+)$")
_RE_TEXT_APPROVE = re.compile(r"^(%s:APPROVE|approve)\s*$")
_RE_TEXT_REJECT = re.compile(r"^(%s:REJECT|reject)\s*$")
_RE_TEXT_EDIT = re.compile(r"^(%s:EDIT|edit)\s*$")
_RE_ALERT = re.compile(r"\bbl-([A-Za-z0-9_-]+(%s:-[A-Za-z0-9_-]+)*)\b")


def normalize_md(text: str) -> str:
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


def format_diff_summary(baseline: str, edited: str) -> str:
    base_lines = normalize_md(baseline).splitlines()
    edit_lines = normalize_md(edited).splitlines()
    added = removed = 0
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base_lines, edit_lines).get_opcodes():
        if tag == "insert":
            added += j2 - j1
        elif tag == "delete":
            removed += i2 - i1
        elif tag == "replace":
            added += j2 - j1
            removed += i2 - i1
    return f"+{min(added, 99)} / −{min(removed, 99)} lines"


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


def telegram_request(token: str, method: str, data: dict | None = None, files: dict | None = None) -> dict:
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
    with urllib.request.urlopen(req, timeout=60) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "unknown Telegram error"))
    return result


def send_message(
    token: str,
    chat_id: str,
    text: str,
    *,
    reply_to_message_id: int | None = None,
    reply_markup: dict | None = None,
) -> int | None:
    payload: dict[str, str] = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_to_message_id is not None:
        payload["reply_to_message_id"] = str(reply_to_message_id)
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    result = telegram_request(token, "sendMessage", payload)
    return (result.get("result") or {}).get("message_id")


def send_document(
    token: str,
    chat_id: str,
    file_path: str,
    *,
    caption: str = "",
    reply_to_message_id: int | None = None,
) -> int | None:
    with open(file_path, "rb") as f:
        content = f.read()
    data: dict[str, str] = {"chat_id": chat_id}
    if caption:
        data["caption"] = caption
        data["parse_mode"] = "HTML"
    if reply_to_message_id is not None:
        data["reply_to_message_id"] = str(reply_to_message_id)
    result = telegram_request(
        token,
        "sendDocument",
        data=data,
        files={"document": (os.path.basename(file_path), content, "text/markdown")},
    )
    return (result.get("result") or {}).get("message_id")


def download_telegram_file(token: str, file_id: str) -> bytes:
    result = telegram_request(token, "getFile", {"file_id": file_id})
    file_path = (result.get("result") or {}).get("file_path")
    if not file_path:
        raise RuntimeError("getFile returned no path")
    url = f"https://api.telegram.org/file/bot{token}/{file_path}"
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read()


def build_edit_confirm_keyboard(alert_id: str) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "Apply edit", "callback_data": f"bl_edit_apply:{alert_id}"},
                {"text": "Cancel", "callback_data": f"bl_edit_cancel:{alert_id}"},
            ]
        ]
    }


def extract_alert_from_text(text: str) -> str | None:
    match = _RE_ALERT.search(text)
    return match.group(0) if match else None


def parse_input(payload: str | None, message_text: str | None) -> dict | None:
    if payload:
        p = payload.strip()
        for pattern, action in (
            (_RE_APPROVE, "approve"),
            (_RE_REJECT, "reject"),
            (_RE_EDIT_APPLY, "edit_apply"),
            (_RE_EDIT_CANCEL, "edit_cancel"),
            (_RE_EDIT, "edit"),
        ):
            m = pattern.match(p)
            if m:
                return {"action": action, "alert_id": m.group(1).strip()}

    if message_text:
        text = message_text.strip()
        alert_id = extract_alert_from_text(text)
        if _RE_TEXT_APPROVE.match(text):
            return {"action": "approve", "alert_id": alert_id}
        if _RE_TEXT_REJECT.match(text):
            return {"action": "reject", "alert_id": alert_id}
        if _RE_TEXT_EDIT.match(text):
            return {"action": "edit", "alert_id": alert_id}
    return None


def resolve_opportunity(
    *,
    chat_id: str | None,
    reply_to_message_id: str | None,
    run_id: str | None,
    alert_id: str | None,
    db_path: str,
) -> Opportunity | None:
    if alert_id:
        opp = lookup_by_alert_id(alert_id, db_path)
        if opp:
            return opp
    if run_id:
        opp = lookup_by_run_id(run_id, db_path)
        if opp:
            return opp
    if chat_id and reply_to_message_id:
        try:
            return lookup_by_message_id(chat_id, int(reply_to_message_id), db_path)
        except ValueError:
            return None
    return None


def resolve_content(opp: Opportunity, db_path: str) -> str | None:
    return resolve_opportunity_content(opp, db_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Handle backlink card feedback")
    parser.add_argument("--payload")
    parser.add_argument("--message-text")
    parser.add_argument("--chat-id")
    parser.add_argument("--user-id")
    parser.add_argument("--username", default="")
    parser.add_argument("--reply-to-message-id")
    parser.add_argument("--document-file-id")
    parser.add_argument("--document-name", default="")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--no-reply", action="store_true")
    args = parser.parse_args()

    init_db(args.db_path)
    chat_id = str(args.chat_id or "").strip()
    token = "" if args.no_reply else load_bot_token()
    reply_id: int | None = None
    if args.reply_to_message_id:
        try:
            reply_id = int(args.reply_to_message_id)
        except ValueError:
            reply_id = None
    source = "callback" if args.payload else "text"
    raw = args.payload or args.message_text

    if args.document_file_id and reply_id is not None:
        pair = get_edit_session_by_prompt(reply_id, args.db_path)
        if not pair:
            print("EDIT_INVALID: no session for this reply")
            return 0
        session, opp = pair
        if session.state != "awaiting_paste":
            print(f"EDIT_INVALID: session state {session.state}")
            return 0
        if not (args.document_name or "").lower().endswith(".md"):
            if token and chat_id:
                send_message(token, chat_id, "Please upload a <b>.md</b> file.", reply_to_message_id=reply_id)
            print("EDIT_USE_MARKDOWN")
            return 0
        try:
            content = download_telegram_file(token, args.document_file_id).decode("utf-8")
        except Exception as e:
            print(f"EDIT_FAILED: download {e}")
            return 0
        baseline = resolve_content(opp, args.db_path) or ""
        if normalize_md(content) == normalize_md(baseline):
            if token and chat_id:
                send_message(
                    token,
                    chat_id,
                    "No changes detected. Edit the file and upload again.",
                    reply_to_message_id=reply_id,
                )
            print("EDIT_UNCHANGED")
            return 0
        version_id = save_content_version(
            opp.id,
            "user_suggested",
            content,
            user_id=args.user_id,
            user_username=args.username or None,
            db_path=args.db_path,
        )
        upsert_edit_session(
            opp.id,
            args.user_id or "",
            "awaiting_confirm",
            prompt_message_id=session.prompt_message_id,
            suggested_version_id=version_id,
            db_path=args.db_path,
        )
        diff_summary = format_diff_summary(baseline, content)
        if token and chat_id:
            send_message(
                token,
                chat_id,
                f"Edit saved for <code>{opp.alert_id}</code> — <b>{diff_summary}</b> changed.\n\nApply edit%s",
                reply_to_message_id=reply_id,
                reply_markup=build_edit_confirm_keyboard(opp.alert_id),
            )
        print(f"EDIT_SAVED: {opp.alert_id} {diff_summary}")
        return 0

    if not args.payload and not args.message_text:
        print("INVALID: no payload or message-text", file=sys.stderr)
        return 0

    parsed = parse_input(args.payload, args.message_text)
    if parsed is None:
        print("INVALID: unrecognized command", file=sys.stderr)
        return 0

    opp = resolve_opportunity(
        chat_id=chat_id or None,
        reply_to_message_id=args.reply_to_message_id,
        run_id=parsed.get("run_id"),
        alert_id=parsed.get("alert_id"),
        db_path=args.db_path,
    )
    if not opp:
        print("OPPORTUNITY_NOT_FOUND")
        if token and chat_id:
            send_message(token, chat_id, "No backlink opportunity found. Reply to the card.", reply_to_message_id=reply_id)
        return 0

    action = parsed["action"]

    if action == "approve":
        set_status(opp.id, "approved", args.db_path)
        record_feedback(opp.id, "approve", user_id=args.user_id, user_username=args.username or None, source=source, raw_payload=raw, db_path=args.db_path)
        if opp.project_url and opp.site_url:
            wdb.mark_seen_for_project_url(opp.project_url, opp.site_url, db_path=args.db_path)
        try:
            pid = wdb.get_project_id(opp.project_url or "", db_path=args.db_path) if opp.project_url else None
            if pid:
                n = mine_project_vocab(pid, db_path=args.db_path)
                if n:
                    print(f"VOCAB_MINED: {n} term(s) from approved {opp.alert_id}")
        except Exception as e:  # noqa: BLE001
            print(f"VOCAB_MINE_SKIP: {e}")
        if token and chat_id:
            send_message(token, chat_id, f"Approved <code>{opp.alert_id}</code> for manual submission.", reply_to_message_id=reply_id)
        print(f"APPROVE_OK: {opp.alert_id}")
    elif action == "reject":
        set_status(opp.id, "rejected", args.db_path)
        record_feedback(opp.id, "reject", user_id=args.user_id, user_username=args.username or None, source=source, raw_payload=raw, db_path=args.db_path)
        if opp.project_url and opp.site_url:
            wdb.mark_seen_for_project_url(opp.project_url, opp.site_url, db_path=args.db_path)
        if token and chat_id:
            send_message(token, chat_id, f"Rejected <code>{opp.alert_id}</code>. Feedback saved.", reply_to_message_id=reply_id)
        print(f"REJECT_OK: {opp.alert_id}")
    elif action == "edit":
        content = resolve_content(opp, args.db_path)
        if not content:
            print("EDIT_FAILED: no content")
            return 0
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(content)
            tmp_path = f.name
        try:
            caption = (
                f"Edit <code>{opp.alert_id}</code>\n\n"
                "Download → edit → save → reply with corrected <b>.md</b> file."
            )
            prompt_id = send_document(token, chat_id, tmp_path, caption=caption, reply_to_message_id=reply_id)
        finally:
            os.unlink(tmp_path)
        if not prompt_id:
            print("EDIT_FAILED: sendDocument failed")
            return 0
        upsert_edit_session(opp.id, args.user_id or "", "awaiting_paste", prompt_message_id=prompt_id, db_path=args.db_path)
        print(f"EDIT_PROMPT_SENT: {opp.alert_id}")
    elif action == "edit_apply":
        suggested = get_latest_version(opp.id, "user_suggested", args.db_path)
        if not suggested:
            print("EDIT_FAILED: no suggested version")
            return 0
        save_content_version(opp.id, "applied", suggested.content_md, user_id=args.user_id, db_path=args.db_path)
        record_feedback(
            opp.id,
            "edit_apply",
            user_id=args.user_id,
            source=source,
            raw_payload=raw,
            edited_content=suggested.content_md,
            db_path=args.db_path,
        )
        clear_edit_session(opp.id, args.user_id or "", args.db_path)
        if token and chat_id:
            send_message(token, chat_id, f"Edit applied for <code>{opp.alert_id}</code>. Saved to database.", reply_to_message_id=reply_id)
        print(f"EDIT_APPLIED: {opp.alert_id}")
    elif action == "edit_cancel":
        clear_edit_session(opp.id, args.user_id or "", args.db_path)
        record_feedback(opp.id, "edit_cancel", user_id=args.user_id, source=source, raw_payload=raw, db_path=args.db_path)
        if token and chat_id:
            send_message(token, chat_id, f"Edit cancelled for <code>{opp.alert_id}</code>.", reply_to_message_id=reply_id)
        print(f"EDIT_CANCELLED: {opp.alert_id}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
