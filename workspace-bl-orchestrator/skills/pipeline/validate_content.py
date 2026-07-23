#!/usr/bin/env python3
"""
validate_content.py — Validate content agent output.

Exit 0 + CONTENT_VALID: <N> posts
Exit 1 + CONTENT_INVALID: <reason>
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile


REQUIRED_POST_FIELDS = [
    "site_url",
    "site_domain",
    "type",
    "title",
    "content",
    "backlink_url",
    "backlink_anchor_text",
]


def atomic_write_json(path: str, data: dict) -> None:
    dir_ = os.path.dirname(os.path.abspath(path))
    os.makedirs(dir_, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=dir_, delete=False, suffix=".tmp", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        tmp = f.name
    os.replace(tmp, path)


def extract_json(text: str) -> dict | None:
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()

    manifest_path = os.path.realpath(args.manifest)
    if not os.path.exists(manifest_path):
        print(f"CONTENT_INVALID: manifest not found: {manifest_path}")
        return 1

    with open(manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    artifacts = manifest.get("artifacts", {})
    posts_path = artifacts.get("content_posts", "")
    project_url = (manifest.get("project") or {}).get("project_url", "")

    if not posts_path or not os.path.exists(posts_path):
        print(f"CONTENT_INVALID: content_posts not found: {posts_path}")
        return 1

    with open(posts_path, encoding="utf-8", errors="ignore") as f:
        text = f.read()

    if not text.strip():
        print("CONTENT_INVALID: content/posts.json is empty")
        return 1

    data = extract_json(text)
    if not data:
        print("CONTENT_INVALID: cannot parse JSON from content/posts.json")
        return 1

    if data.get("status") != "ok":
        print(f"CONTENT_INVALID: status is not ok: {data.get('status')}")
        return 1

    posts = data.get("posts")
    if not isinstance(posts, list) or len(posts) == 0:
        print("CONTENT_INVALID: posts must be a non-empty list")
        return 1

    for i, post in enumerate(posts):
        if not isinstance(post, dict):
            print(f"CONTENT_INVALID: posts[{i}] is not an object")
            return 1
        for field in REQUIRED_POST_FIELDS:
            if not post.get(field):
                print(f"CONTENT_INVALID: posts[{i}] missing {field}")
                return 1
        content = str(post.get("content", ""))
        if len(content.strip()) < 50:
            print(f"CONTENT_INVALID: posts[{i}] content too short")
            return 1
        backlink = str(post.get("backlink_url", ""))
        if project_url and project_url not in content and backlink != project_url:
            print(f"CONTENT_INVALID: posts[{i}] backlink not present in content")
            return 1
        image_path = post.get("image_path")
        if image_path and not os.path.isfile(str(image_path)):
            print(f"CONTENT_INVALID: posts[{i}] image_path missing on disk: {image_path}")
            return 1

    atomic_write_json(posts_path, data)
    print(f"CONTENT_VALID: {len(posts)} posts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
