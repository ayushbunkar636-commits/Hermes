#!/usr/bin/env python3
"""Resolve artifact paths from a backlink run manifest."""
from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, help="Path to manifest.json")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--key", help="Artifact key to resolve")
    group.add_argument("--run-dir", action="store_true", help="Print run_dir")
    group.add_argument("--run-id", action="store_true", help="Print run_id")
    args = parser.parse_args()

    manifest_path = os.path.realpath(args.manifest)
    if not os.path.exists(manifest_path):
        print(f"[ERROR] Manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"[ERROR] Cannot parse manifest: {e}", file=sys.stderr)
        return 1

    if args.run_dir:
        val = manifest.get("run_dir", "")
        if not val:
            print("[ERROR] run_dir not in manifest", file=sys.stderr)
            return 1
        print(val, end="")
        return 0

    if args.run_id:
        val = manifest.get("run_id", "")
        if not val:
            print("[ERROR] run_id not in manifest", file=sys.stderr)
            return 1
        print(val, end="")
        return 0

    artifacts = manifest.get("artifacts", {})
    path = artifacts.get(args.key, "")
    if not path:
        print(f"[ERROR] Artifact key '{args.key}' not in manifest artifacts", file=sys.stderr)
        print(f"  Available keys: {', '.join(sorted(artifacts.keys()))}", file=sys.stderr)
        return 1

    print(path, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
