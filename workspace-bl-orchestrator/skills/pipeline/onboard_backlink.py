#!/usr/bin/env python3
"""
onboard_backlink.py — Deterministic, LLM-free engine for adding a backlink project.

Two front-ends share this engine:
  - Terminal wizard:           onboard_backlink.py wizard
  - Telegram /onboard flow:    backlink-onboarder plugin calls start / step / cancel

Always fail-open on the Telegram side; prints OK:/ERROR: for logging. Never wakes an LLM.

Subcommands:
    wizard                          Interactive terminal run through all steps
    start   --chat-id --user-id     Begin (or resume) a Telegram onboarding session
    step    --chat-id --user-id --input <text or callback>
    status  --chat-id [--user-id]   Show current step + answers for a session
    cancel  --chat-id --user-id     Abort and clear a session
    finalize --answers <file.json> [--apply-bind] [--dry-run-bind]
                                     Non-interactive write from collected answers
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
from typing import Callable

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)

import whitelist_db as wdb  # noqa: E402
from project_telegram_scope import verify_all_project_scopes, verify_project_group_scope  # noqa: E402
from telegram_api import telegram_request  # noqa: E402

OPENCLAW_JSON = os.path.expanduser("~/.openclaw-backlink/openclaw.json")
MANAGE_SCRIPT = os.path.join(HERE, "manage_projects.py")
BIND_SCRIPT = os.path.join(HERE, "bind_telegram_group.py")
TELEGRAM_ACCOUNT = "backlink"


def _db_path() -> str:
    return os.environ.get("BL_DB_PATH", wdb.DEFAULT_DB_PATH)

SUPERGROUP_RE = re.compile(r"^-100\d+$")

STEP_ORDER = [
    "group_id",
    "project_url",
    "niche",
    "name",
    "description",
    "extra_domains",
    "preview",
]

DESCRIPTION_MIN_LEN = 10
EXTRA_DOMAINS_MAX = 20
DEFAULT_SEED_LABEL = "tiers 1–2 (~8 sites: Reddit, X, HN, BitcoinTalk, …)"

INTRO_TEXT = (
    "\U0001F517 <b>New backlink project onboarding</b>\n\n"
    "Before we start, in Telegram:\n"
    "1. Create a new Telegram group for this project\n"
    "2. Convert it to a <b>supergroup</b> (add members, set a public link, or send media)\n"
    "3. Add <b>this bot</b> to the group as <b>admin</b>\n"
    "4. Forward any message from that group to <b>@userinfobot</b> — paste the "
    "<code>-100XXXXXXXXXX</code> id it gives you\n\n"
    "Reply with that group id to continue. Send /cancel anytime to abort."
)


class OnboardError(Exception):
    """User-facing validation error — re-prompt the same step."""


def _load_json(path: str, default: dict | None = None) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else (default or {})
    except (OSError, json.JSONDecodeError):
        return default or {}


def load_bot_token(account_id: str = TELEGRAM_ACCOUNT) -> str:
    openclaw = _load_json(OPENCLAW_JSON)
    telegram = (openclaw.get("channels") or {}).get("telegram") or {}
    account = (telegram.get("accounts") or {}).get(account_id) or {}
    return str(account.get("botToken") or "").strip()


def send_telegram_message(
    chat_id: str, text: str, *, keyboard: dict | None = None
) -> int | None:
    token = load_bot_token()
    if not token:
        print("ERROR: no Telegram bot token configured for account 'backlink'")
        return None
    data: dict = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if keyboard:
        data["reply_markup"] = json.dumps(keyboard)
    try:
        result = telegram_request(token, "sendMessage", data=data)
    except RuntimeError as e:
        print(f"ERROR: sendMessage failed: {e}")
        return None
    return (result.get("result") or {}).get("message_id")


def confirm_keyboard() -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": "\u2705 Confirm & create project", "callback_data": "ob_confirm:yes"},
                {"text": "\u274C Cancel", "callback_data": "ob_confirm:no"},
            ]
        ]
    }


def normalize_project_url(raw: str) -> str:
    val = raw.strip()
    if not val:
        raise OnboardError("Project URL is required.")
    if not val.startswith(("http://", "https://")):
        val = "https://" + val
    parsed = urllib.parse.urlparse(val)
    if not parsed.netloc:
        raise OnboardError("That doesn't look like a valid URL (e.g. https://example.com).")
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parsed.path.rstrip("/")
    return f"{scheme}://{netloc}{path}"


def _normalize_domain_token(raw: str) -> str | None:
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


def parse_extra_domains(raw: str, *, max_domains: int = EXTRA_DOMAINS_MAX) -> list[str]:
    """Parse comma/whitespace-separated domains or URLs into normalized hostnames."""
    val = raw.strip()
    if val.lower() in ("skip", "none", "-", ""):
        return []
    tokens = re.split(r"[\s,;]+", val)
    out: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        dom = _normalize_domain_token(token)
        if dom and dom not in seen:
            seen.add(dom)
            out.append(dom)
    if not out:
        raise OnboardError(
            "Could not parse any domains. Example: quora.com, coindesk.com — or send skip."
        )
    if len(out) > max_domains:
        raise OnboardError(f"At most {max_domains} extra domains; you sent {len(out)}.")
    return out


def h_group_id(answers: dict, raw: str) -> None:
    gid = raw.strip()
    if not SUPERGROUP_RE.match(gid):
        raise OnboardError(
            "That doesn't look like a supergroup id (expected -100XXXXXXXXXX). "
            "Forward a group message to @userinfobot and paste the id it gives you."
        )
    existing = wdb.resolve_project_for_group(gid, db_path=_db_path())
    if existing:
        raise OnboardError(
            f"Group {gid} is already bound to project {existing}. Use a different group."
        )
    answers["group_id"] = gid


def h_project_url(answers: dict, raw: str) -> None:
    url = normalize_project_url(raw)
    if wdb.get_project(url, db_path=_db_path()):
        raise OnboardError(f"Project {url} already exists. Use a different URL.")
    answers["project_url"] = url


def h_niche(answers: dict, raw: str) -> None:
    niche = raw.strip()
    if not niche or len(niche) > 120:
        raise OnboardError("Niche must be 1-120 characters (e.g. 'crypto,blockchain').")
    answers["niche"] = niche


def h_name(answers: dict, raw: str) -> None:
    name = raw.strip()
    if not name or len(name) > 60:
        raise OnboardError("Name must be 1-60 characters.")
    answers["name"] = name


def h_description(answers: dict, raw: str) -> None:
    val = raw.strip()
    if val.lower() in ("skip", "none", "-", "") or len(val) < DESCRIPTION_MIN_LEN:
        raise OnboardError(
            f"Description is required (at least {DESCRIPTION_MIN_LEN} characters). "
            "Describe what the site does — used for scoring and draft quality."
        )
    if len(val) > 500:
        raise OnboardError("Description must be at most 500 characters.")
    answers["description"] = val


def h_extra_domains(answers: dict, raw: str) -> None:
    val = raw.strip()
    if val.lower() in ("skip", "none", "-", ""):
        answers["extra_domains"] = []
    else:
        answers["extra_domains"] = parse_extra_domains(val)


def h_preview(answers: dict, raw: str) -> None:
    choice = raw.strip().lower().replace("ob_confirm:", "")
    if choice not in ("yes", "no"):
        raise OnboardError("Reply with the Confirm or Cancel button.")
    if choice == "no":
        raise OnboardError("__CANCELLED__")
    answers["confirmed"] = True


STEP_HANDLERS: dict[str, Callable[[dict, str], None]] = {
    "group_id": h_group_id,
    "project_url": h_project_url,
    "niche": h_niche,
    "name": h_name,
    "description": h_description,
    "extra_domains": h_extra_domains,
    "preview": h_preview,
}


def build_preview_text(answers: dict) -> str:
    desc = answers.get("description") or "%s"
    extras = answers.get("extra_domains") or []
    if extras:
        extra_line = ", ".join(extras)
    else:
        extra_line = "\u26A0\uFE0F none added — defaults only (you can add more later via CLI)"
    return (
        "\U0001F517 <b>Review before creating the backlink project</b>\n\n"
        f"Group: <code>{answers.get('group_id', '%s')}</code>\n"
        f"URL: <code>{answers.get('project_url', '%s')}</code>\n"
        f"Niche: {answers.get('niche', '%s')}\n"
        f"Name: {answers.get('name', '%s')}\n"
        f"Description: {desc}\n\n"
        f"<b>Default sources:</b> {DEFAULT_SEED_LABEL}\n"
        f"<b>Extra domains:</b> {extra_line}\n\n"
        "Confirm to register the project, seed the whitelist, and bind the Telegram group."
    )


def prompt_for(step: str, answers: dict) -> tuple[str, dict | None]:
    if step == "group_id":
        return INTRO_TEXT, None
    if step == "project_url":
        return "What's the project's <b>website URL</b>%s (e.g. https://example.com)", None
    if step == "niche":
        return "What's the <b>niche</b>%s (comma-separated keywords, e.g. 'crypto,blockchain')", None
    if step == "name":
        return "What's the project's <b>display name</b>%s (e.g. 'Coinography')", None
    if step == "description":
        return (
            "One-line <b>description</b> of the site "
            f"(required, min {DESCRIPTION_MIN_LEN} chars — used for scoring and drafts)",
            None,
        )
    if step == "extra_domains":
        return (
            "<b>Source domains (recommended)</b>\n\n"
            f"We auto-add {DEFAULT_SEED_LABEL}.\n"
            "<b>Add more now</b> to get better cards sooner — paste comma-separated domains "
            "(e.g. <code>quora.com, coindesk.com, medium.com</code>) or send "
            "<code>skip</code> to use defaults only.",
            None,
        )
    if step == "preview":
        return build_preview_text(answers), confirm_keyboard()
    raise OnboardError(f"unknown step '{step}'")


def run_manage_add(answers: dict) -> tuple[bool, str]:
    cmd = [
        sys.executable,
        MANAGE_SCRIPT,
        "add",
        "--project-url", answers["project_url"],
        "--niche", answers["niche"],
        "--name", answers.get("name") or "",
        "--group-id", answers["group_id"],
        "--group-name", answers.get("name") or answers["project_url"],
    ]
    cmd.extend(["--description", answers["description"]])
    extras = answers.get("extra_domains") or []
    if extras:
        cmd.extend(["--extra-domains", ",".join(extras)])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()


def run_db_group_bind(answers: dict, *, apply: bool) -> tuple[bool, str]:
    """Verify Telegram group scope in DB (manage_projects add already writes telegram_group_id)."""
    if not apply:
        return True, (
            "SCOPE_DRY_RUN: would verify DB telegram_group_id "
            f"({answers['group_id']} -> {answers['project_url']})"
        )
    return verify_project_group_scope(
        answers["project_url"],
        answers["group_id"],
        db_path=_db_path(),
    )


def run_bind(answers: dict, *, apply: bool) -> tuple[bool, str]:
    """Legacy openclaw.json patch (optional). Onboard uses run_db_group_bind instead."""
    cmd = [
        sys.executable,
        BIND_SCRIPT,
        "--project-url", answers["project_url"],
        "--group-id", answers["group_id"],
        "--name", answers.get("name") or answers["project_url"],
        "--group-name", answers.get("name") or answers["project_url"],
        "--skip-db",
    ]
    if apply:
        cmd.append("--apply")
    else:
        cmd.append("--dry-run")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode == 0, out.strip()


def finalize(answers: dict, *, apply_bind: bool) -> tuple[bool, str]:
    required = ("group_id", "project_url", "niche", "name", "description")
    missing = [k for k in required if not answers.get(k)]
    if missing:
        return False, f"ERROR: missing required fields: {', '.join(missing)}"

    ok, out = run_manage_add(answers)
    if not ok:
        return False, f"ERROR: project registration failed:\n{out}"

    ok_scope, scope_out = run_db_group_bind(answers, apply=apply_bind)
    all_ok, all_lines = verify_all_project_scopes(db_path=_db_path())
    scope_block = (
        f"\n\n<b>Telegram scope (database)</b>\n"
        f"Group <code>{answers['group_id']}</code> → "
        f"<code>{answers['project_url']}</code>\n"
        f"{scope_out}"
    )
    if all_lines:
        scope_block += "\n" + "\n".join(all_lines[:5])
    summary = (
        f"OK: backlink project registered.\n{out}{scope_block}\n\n"
        "LinkNexus in this group is scoped via the database (no openclaw.json edit needed)."
    )
    if not ok_scope:
        summary = (
            f"<b>FAILED — Telegram scope not verified</b>\n\n{summary}"
        )
        return False, summary
    if not all_ok:
        summary += "\nWARN: some project scopes failed verify-all check."
    return True, summary


def cmd_start(args: argparse.Namespace) -> int:
    chat_id, user_id = args.chat_id, args.user_id
    existing = wdb.get_onboard_session(chat_id, user_id, db_path=_db_path())
    if existing and existing.step != "preview":
        answers = json.loads(existing.answers_json or "{}")
        text, keyboard = prompt_for(existing.step, answers)
        msg_id = send_telegram_message(chat_id, "(resuming) " + text, keyboard=keyboard)
        wdb.upsert_onboard_session(
            chat_id, user_id, existing.step,
            answers_json=existing.answers_json,
            prompt_message_id=msg_id,
            db_path=_db_path(),
        )
        print(f"OK: resumed session for {chat_id}/{user_id} at step {existing.step}")
        return 0

    first_step = STEP_ORDER[0]
    text, keyboard = prompt_for(first_step, {})
    msg_id = send_telegram_message(chat_id, text, keyboard=keyboard)
    wdb.upsert_onboard_session(
        chat_id, user_id, first_step, answers_json="{}", prompt_message_id=msg_id, db_path=_db_path(),
    )
    print(f"OK: started onboarding session for {chat_id}/{user_id}")
    return 0


def cmd_step(args: argparse.Namespace) -> int:
    chat_id, user_id, raw_input = args.chat_id, args.user_id, args.input
    session = wdb.get_onboard_session(chat_id, user_id, db_path=_db_path())
    if not session:
        print("ERROR: no active session")
        return 1

    answers = json.loads(session.answers_json or "{}")
    step = session.step
    handler = STEP_HANDLERS.get(step)
    if not handler:
        print(f"ERROR: no handler for step {step}")
        return 0

    try:
        handler(answers, raw_input)
    except OnboardError as e:
        if str(e) == "__CANCELLED__":
            wdb.clear_onboard_session(chat_id, user_id, db_path=_db_path())
            send_telegram_message(chat_id, "Onboarding cancelled.")
            print("OK: cancelled by user at preview")
            return 0
        send_telegram_message(chat_id, f"\u26A0\uFE0F {e}")
        print(f"OK: validation error at step {step}: {e}")
        return 0

    if step == "preview":
        ok, summary = finalize(answers, apply_bind=True)
        send_telegram_message(chat_id, summary if len(summary) < 3800 else summary[:3800] + "\n…(truncated)")
        wdb.clear_onboard_session(chat_id, user_id, db_path=_db_path())
        print(summary)
        return 0

    idx = STEP_ORDER.index(step)
    next_step = STEP_ORDER[idx + 1]
    text, keyboard = prompt_for(next_step, answers)
    msg_id = send_telegram_message(chat_id, text, keyboard=keyboard)
    wdb.upsert_onboard_session(
        chat_id, user_id, next_step,
        answers_json=json.dumps(answers),
        prompt_message_id=msg_id,
        db_path=_db_path(),
    )
    print(f"OK: advanced {chat_id}/{user_id} to step {next_step}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    session = wdb.get_onboard_session(args.chat_id, args.user_id or "", db_path=_db_path())
    if not session and args.user_id is None:
        session = wdb.get_any_onboard_session_for_chat(args.chat_id, db_path=_db_path())
    if not session:
        print("OK: no active session")
        return 0
    print(f"OK: step={session.step} answers={session.answers_json}")
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    wdb.clear_onboard_session(args.chat_id, args.user_id, db_path=_db_path())
    send_telegram_message(args.chat_id, "Onboarding cancelled.")
    print("OK: session cancelled")
    return 0


def cli_prompt_plain(step: str, answers: dict) -> str:
    text, _ = prompt_for(step, answers)
    return re.sub(r"<[^>]+>", "", text)


def cmd_wizard(args: argparse.Namespace) -> int:
    print("=== Backlink Project Onboarding Wizard ===\n")
    answers: dict = {}
    for step in STEP_ORDER:
        while True:
            print("\n" + cli_prompt_plain(step, answers))
            if step == "preview":
                raw = input("Confirm%s [yes/no]: ").strip().lower()
                if raw not in ("yes", "no", "y", "n"):
                    print("Enter yes or no.")
                    continue
                raw = "ob_confirm:yes" if raw in ("yes", "y") else "ob_confirm:no"
            else:
                raw = input("> ").strip()
            try:
                STEP_HANDLERS[step](answers, raw)
                break
            except OnboardError as e:
                if str(e) == "__CANCELLED__":
                    print("Cancelled.")
                    return 0
                print(f"! {e}")

    apply_bind = not getattr(args, "dry_run_bind", False)
    ok, summary = finalize(answers, apply_bind=apply_bind)
    print("\n" + summary)
    return 0 if ok else 1


def cmd_finalize(args: argparse.Namespace) -> int:
    with open(args.answers, encoding="utf-8") as f:
        answers = json.load(f)
    apply_bind = args.apply_bind and not args.dry_run_bind
    ok, summary = finalize(answers, apply_bind=apply_bind)
    print(summary)
    return 0 if ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backlink project onboarding (no LLM)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("wizard", help="interactive terminal wizard")
    sp.add_argument("--dry-run-bind", action="store_true", help="skip gateway bind on finalize")
    sp.set_defaults(func=cmd_wizard)

    for name, fn in (
        ("start", cmd_start),
        ("step", cmd_step),
        ("cancel", cmd_cancel),
        ("status", cmd_status),
    ):
        sp = sub.add_parser(name)
        sp.add_argument("--chat-id", required=True)
        sp.add_argument("--user-id", default="")
        if name == "step":
            sp.add_argument("--input", required=True)
            sp.add_argument("--reply-to-message-id", default="")
        sp.set_defaults(func=fn)

    sp = sub.add_parser("finalize", help="write project from answers JSON file")
    sp.add_argument("--answers", required=True)
    sp.add_argument("--apply-bind", action="store_true")
    sp.add_argument("--dry-run-bind", action="store_true")
    sp.set_defaults(func=cmd_finalize)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.cmd in ("start", "step", "cancel", "status") and not args.user_id:
        parser.error(f"{args.cmd} requires --user-id")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
