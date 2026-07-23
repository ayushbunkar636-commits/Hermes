#!/usr/bin/env python3
"""
bind_telegram_group.py — Atomically patch openclaw.json to wire a Telegram
group to a backlink project (groups ACL + systemPrompt + bl-orchestrator binding).
Also persists the group id in the projects table for card egress routing.

This is the ONLY place that programmatically edits openclaw.json for per-project
Telegram wiring. It NEVER removes or renames existing keys — only adds or
updates the new group/binding entries (idempotent: safe to re-run).

Safety:
  - Defaults to --dry-run (prints the exact patch, writes nothing).
  - --apply makes a timestamped backup before writing, writes atomically
    (temp file + os.replace), and validates the result is valid JSON before
    and after.
  - Gateway restart uses `openclaw --profile backlink gateway restart`.

Usage:
    python3 bind_telegram_group.py --project-url https://example.com \\
        --group-id -100123 --name Example --dry-run
    python3 bind_telegram_group.py --project-url https://example.com \\
        --group-id -100123 --name Example --apply
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import whitelist_db as wdb  # noqa: E402

OPENCLAW_JSON = os.path.expanduser("~/.openclaw-backlink/openclaw.json")
BACKUP_DIR = os.path.expanduser("~/.openclaw-backlink/.backups/openclaw-json")
ACCOUNT_ID = "backlink"
AGENT_ID = "bl-orchestrator"
OPENCLAW_PROFILE = "backlink"


def load_openclaw() -> dict:
    with open(OPENCLAW_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def backup_openclaw() -> str:
    os.makedirs(BACKUP_DIR, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = os.path.join(BACKUP_DIR, f"openclaw.json.bak.{ts}")
    with open(OPENCLAW_JSON, "rb") as src, open(dest, "wb") as dst:
        dst.write(src.read())
    return dest


def atomic_write_json(path: str, data: dict) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
        tmp = f.name
    os.replace(tmp, path)


def build_patch(
    cfg: dict,
    *,
    project_url: str,
    group_id: str,
    name: str,
) -> tuple[dict, list[str]]:
    """Return (patched_copy, human_readable_change_lines). Never mutates cfg."""
    new_cfg = copy.deepcopy(cfg)
    changes: list[str] = []

    telegram = new_cfg.setdefault("channels", {}).setdefault("telegram", {})
    accounts = telegram.setdefault("accounts", {})
    account = accounts.setdefault(ACCOUNT_ID, {})
    groups = account.setdefault("groups", {})

    system_prompt = (
        f"PROJECT_URL={project_url}. You operate EXCLUSIVELY for the {name} project in this group. "
        f"Never ask which project; never act on other projects here."
    )
    desired_group = {"requireMention": True, "systemPrompt": system_prompt}
    existing_group = groups.get(group_id)
    if existing_group != desired_group:
        groups[group_id] = desired_group
        changes.append(
            f'channels.telegram.accounts.{ACCOUNT_ID}.groups["{group_id}"] = '
            f"{{requireMention: true, systemPrompt: PROJECT_URL={project_url}...}}"
        )
    else:
        changes.append(f'(no change) groups["{group_id}"] already correct')

    bindings = new_cfg.setdefault("bindings", [])
    already_bound = any(
        (b.get("match") or {}).get("channel") == "telegram"
        and (b.get("match") or {}).get("accountId") == ACCOUNT_ID
        and ((b.get("match") or {}).get("peer") or {}).get("kind") == "group"
        and str(((b.get("match") or {}).get("peer") or {}).get("id")) == group_id
        for b in bindings
    )
    if not already_bound:
        catchall_idx = next(
            (
                i for i, b in enumerate(bindings)
                if (b.get("match") or {}).get("channel") == "telegram"
                and (b.get("match") or {}).get("accountId") == ACCOUNT_ID
                and "peer" not in (b.get("match") or {})
            ),
            None,
        )
        new_binding = {
            "agentId": AGENT_ID,
            "match": {
                "channel": "telegram",
                "accountId": ACCOUNT_ID,
                "peer": {"kind": "group", "id": group_id},
            },
        }
        if catchall_idx is not None:
            bindings.insert(catchall_idx, new_binding)
        else:
            bindings.append(new_binding)
        changes.append(f"bindings[] += {AGENT_ID} binding for group {group_id}")
    else:
        changes.append(f"(no change) bindings[] already has an entry for group {group_id}")

    return new_cfg, changes


def restart_gateway() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["openclaw", "--profile", OPENCLAW_PROFILE, "gateway", "restart"],
            capture_output=True,
            text=True,
            timeout=90,
        )
        out = (result.stdout or "") + (result.stderr or "")
        if result.returncode != 0:
            return False, f"'openclaw --profile {OPENCLAW_PROFILE} gateway restart' exited {result.returncode}:\n{out}"
        return True, out
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"could not run gateway restart: {e}"


def check_gateway_health(*, retries: int = 5, delay_sec: float = 2.0) -> tuple[bool, str]:
    for attempt in range(retries):
        try:
            result = subprocess.run(
                ["openclaw", "--profile", OPENCLAW_PROFILE, "gateway", "health"],
                capture_output=True,
                text=True,
                timeout=20,
            )
            if result.returncode == 0:
                return True, result.stdout
        except (OSError, subprocess.TimeoutExpired):
            pass
        if attempt < retries - 1:
            time.sleep(delay_sec)
    return False, "gateway health check did not succeed after restart"


def sync_project_group(
    project_url: str,
    group_id: str,
    group_name: str,
    *,
    card_prefix: str | None = None,
) -> None:
    """Persist group routing in SQLite (egress + reverse lookup)."""
    proj = wdb.get_project(project_url)
    if not proj:
        raise ValueError(f"project not found in DB: {project_url}")
    wdb.set_project_group(
        project_url,
        group_id,
        group_name,
        card_prefix=card_prefix,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-url", required=True, help="Canonical project URL (must exist in DB)")
    parser.add_argument("--group-id", required=True)
    parser.add_argument("--name", required=True, help="Human display name for the systemPrompt")
    parser.add_argument("--group-name", default="", help="Optional Telegram group label for DB")
    parser.add_argument("--card-prefix", default=None, help="Optional card label prefix")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Print the patch, write nothing (default)")
    mode.add_argument("--apply", action="store_true", help="Write openclaw.json + DB, backup first, restart gateway")
    parser.add_argument(
        "--skip-restart",
        action="store_true",
        help="With --apply: write config but skip gateway restart",
    )
    parser.add_argument(
        "--skip-db",
        action="store_true",
        help="With --apply: patch openclaw.json only (do not update projects table)",
    )
    parser.add_argument(
        "--skip-openclaw",
        action="store_true",
        help="With --apply: update DB only (no openclaw.json patch; DB-driven plugin scope)",
    )
    args = parser.parse_args()

    apply = args.apply and not args.dry_run
    group_name = (args.group_name or args.name or "").strip()
    skip_openclaw = args.skip_openclaw

    try:
        cfg = load_openclaw()
    except (OSError, json.JSONDecodeError) as e:
        print(f"BIND_ERROR: cannot read/parse {OPENCLAW_JSON}: {e}")
        return 1

    if apply and not args.skip_db:
        try:
            sync_project_group(
                args.project_url,
                args.group_id,
                group_name,
                card_prefix=args.card_prefix,
            )
        except ValueError as e:
            print(f"BIND_ERROR: {e}")
            return 1

    new_cfg, changes = build_patch(
        cfg,
        project_url=args.project_url,
        group_id=args.group_id,
        name=args.name,
    )

    if skip_openclaw:
        changes = [c for c in changes if not c.startswith("channels.") and "bindings" not in c]
        if not changes:
            changes = ["(skip-openclaw) openclaw.json unchanged — DB is source of truth"]

    try:
        json.loads(json.dumps(new_cfg))
    except (TypeError, ValueError) as e:
        print(f"BIND_ERROR: patched config failed JSON validation: {e}")
        return 1

    print(f"BIND_PLAN: {args.project_url} -> group {args.group_id}")
    for c in changes:
        print(f"  - {c}")
    if apply and not args.skip_db:
        print(f"  - DB: projects.telegram_group_id = {args.group_id}")
    if skip_openclaw:
        print("  - openclaw.json: skipped (--skip-openclaw; dynamic plugin scope from DB)")

    if not apply:
        print("\nBIND_DRY_RUN: no files were written. Re-run with --apply to write + restart the gateway.")
        return 0

    if skip_openclaw:
        print(f"BIND_OK: {args.project_url} group {args.group_id} stored in DB (no openclaw.json patch)")
        return 0

    try:
        backup_path = backup_openclaw()
        print(f"BIND_BACKUP: {backup_path}")
    except OSError as e:
        print(f"BIND_ERROR: backup failed, aborting before write: {e}")
        return 1

    try:
        atomic_write_json(OPENCLAW_JSON, new_cfg)
    except OSError as e:
        print(f"BIND_ERROR: write failed: {e}")
        return 1

    try:
        on_disk = load_openclaw()
        assert on_disk == new_cfg
    except (OSError, json.JSONDecodeError, AssertionError) as e:
        print(f"BIND_ERROR: post-write verification failed ({e}). Restore from backup: {backup_path}")
        return 1

    print(f"BIND_WRITTEN: {OPENCLAW_JSON} updated (backup at {backup_path})")

    if args.skip_restart:
        print("BIND_SKIP_RESTART: config written; restart the gateway manually to apply.")
        return 0

    ok, out = restart_gateway()
    print(out.strip())
    if not ok:
        print(
            f"BIND_INFO: gateway systemd restart unavailable (hot-reload may still apply). "
            f"Config written at {backup_path}."
        )
        healthy, health_out = check_gateway_health()
        if healthy:
            print("BIND_GATEWAY_HEALTHY: gateway reachable despite restart skip")
            print(f"BIND_OK: {args.project_url} bound to group {args.group_id}")
            return 0
        print(
            f"BIND_WARN: gateway not healthy: {health_out}. Restart manually: "
            f"openclaw --profile {OPENCLAW_PROFILE} gateway"
        )
        return 1

    healthy, health_out = check_gateway_health()
    if not healthy:
        print(
            f"BIND_WARN: gateway restarted but health check failed: {health_out}. Config is written and "
            f"backed up at {backup_path}."
        )
        return 1
    print("BIND_GATEWAY_HEALTHY: gateway restarted and responded to health check")

    print(f"BIND_OK: {args.project_url} bound to group {args.group_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
