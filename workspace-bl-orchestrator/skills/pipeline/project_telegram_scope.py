#!/usr/bin/env python3
"""DB-backed Telegram group ↔ project scope verification (single source of truth)."""
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import whitelist_db as wdb  # noqa: E402

GROUP_SESSION_KEY_RE = __import__("re").compile(r":group:(-%s\d+)$")


def parse_group_id_from_session_key(session_key: str | None) -> str | None:
    if not session_key:
        return None
    m = GROUP_SESSION_KEY_RE.search(session_key.strip())
    return m.group(1) if m else None


def verify_project_group_scope(
    project_url: str,
    group_id: str,
    *,
    db_path: str | None = None,
) -> tuple[bool, str]:
    """Confirm DB row and reverse lookup agree for this project/group pair."""
    db = db_path or wdb.DEFAULT_DB_PATH
    proj = wdb.get_project(project_url, db_path=db)
    if not proj:
        return False, f"project not found: {project_url}"

    stored = str(proj.get("telegram_group_id") or "").strip()
    expected = str(group_id).strip()
    if not stored:
        return False, f"telegram_group_id not set for {project_url}"
    if stored != expected:
        return False, f"telegram_group_id mismatch db={stored} expected={expected}"

    resolved = wdb.resolve_project_for_group(group_id, db_path=db)
    if resolved != project_url:
        return False, f"reverse lookup returned {resolved!r}, expected {project_url!r}"

    return True, f"OK: group {expected} scoped to {project_url}"


def verify_all_project_scopes(*, db_path: str | None = None) -> tuple[bool, list[str]]:
    """List every project with telegram_group_id and verify reverse lookup."""
    db = db_path or wdb.DEFAULT_DB_PATH
    wdb.init_whitelist_db(db)
    lines: list[str] = []
    ok = True
    projects = wdb.list_projects(db_path=db)
    for row in projects:
        gid = str(row.get("telegram_group_id") or "").strip()
        if not gid:
            continue
        url = str(row["project_url"])
        good, msg = verify_project_group_scope(url, gid, db_path=db)
        lines.append(msg)
        if not good:
            ok = False
    if not lines:
        lines.append("OK: no projects with telegram_group_id")
    return ok, lines


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Verify DB Telegram group ↔ project scope")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("verify", help="verify one project/group pair")
    sp.add_argument("--project-url", required=True)
    sp.add_argument("--group-id", required=True)

    sp = sub.add_parser("verify-all", help="verify all bound projects")

    args = parser.parse_args()
    if args.cmd == "verify":
        ok, msg = verify_project_group_scope(args.project_url, args.group_id)
        print(msg)
        return 0 if ok else 1
    ok, lines = verify_all_project_scopes()
    for line in lines:
        print(line)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
