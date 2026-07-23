#!/usr/bin/env python3
"""read_tool.py — Read ONE link via Jina Reader (adapted from news Scout)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import threading
import time
from urllib.parse import urlparse

import resolve_url  # noqa: E402

DEFAULT_MIN_WORDS = 80
JINA_TIMEOUT = int(os.environ.get("JINA_TIMEOUT_S", "15"))
_HAS_JINA_KEY = bool(os.environ.get("JINA_API_KEY", "").strip())
_DEFAULT_INTERVAL = "0.15" if _HAS_JINA_KEY else "3.5"
MIN_INTERVAL_S = float(os.environ.get("JINA_MIN_INTERVAL_S", _DEFAULT_INTERVAL))
_THROTTLE_FILE = os.path.expanduser("~/.openclaw-backlink/data/jina_last_request")
_THROTTLE_LOCK = threading.Lock()

_CF_MARKERS = (
    "just a moment", "cf-ray", "challenge-platform", "checking your browser",
    "enable javascript and cookies", "attention required", "cf-challenge",
)


def _word_count(text: str) -> int:
    return len((text or "").split())


def _is_challenge(text: str) -> bool:
    if not text:
        return True
    low = text[:6000].lower()
    return sum(1 for m in _CF_MARKERS if m in low) >= 2


def _source_from_url(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host.split(".")[0].title() if host else "Unknown"
    except ValueError:
        return "Unknown"


def _clean_jina_markdown(text: str) -> str:
    if "Markdown Content:" in text:
        text = text.split("Markdown Content:", 1)[1]
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    kept: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        raw = block.strip()
        if not raw:
            continue
        links = len(re.findall(r"\]\(", raw))
        plain = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", raw)
        plain = re.sub(r"<[^>]+>", " ", plain)
        plain = re.sub(r"[#*_`>|]+", " ", plain)
        plain = re.sub(r"[ \t]+", " ", plain).strip()
        words = plain.split()
        if len(words) < 6:
            continue
        if links and links * 8 > len(words):
            continue
        if not re.search(r"[.!?]", plain) and len(words) < 25:
            continue
        kept.append(plain)
    return re.sub(r"\n{3,}", "\n\n", "\n\n".join(kept)).strip()


def _throttle() -> None:
    if MIN_INTERVAL_S <= 0:
        return
    with _THROTTLE_LOCK:
        try:
            os.makedirs(os.path.dirname(_THROTTLE_FILE), exist_ok=True)
            with open(_THROTTLE_FILE, "a+", encoding="utf-8") as f:
                f.seek(0)
                raw = f.read().strip()
                last = float(raw or "0")
                wait = MIN_INTERVAL_S - (time.time() - last)
                if wait > 0:
                    time.sleep(wait)
        except (OSError, ValueError):
            pass


def _mark_request_time() -> None:
    with _THROTTLE_LOCK:
        try:
            os.makedirs(os.path.dirname(_THROTTLE_FILE), exist_ok=True)
            with open(_THROTTLE_FILE, "w", encoding="utf-8") as f:
                f.write(str(time.time()))
        except OSError:
            pass


def _fetch_jina(url: str, min_words: int) -> tuple[str, str] | None:
    try:
        import requests
    except ImportError:
        return None
    headers = {
        "X-Return-Format": "markdown",
        "Accept": "text/plain, text/markdown, */*",
        "User-Agent": "Mozilla/5.0 (compatible; OpenClawBacklink/1.0)",
    }
    key = os.environ.get("JINA_API_KEY", "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    _throttle()
    resp = None
    try:
        resp = requests.get(f"https://r.jina.ai/{url}", headers=headers, timeout=JINA_TIMEOUT)
    except Exception as e:
        print(f"[read_tool] jina error: {e}", file=sys.stderr)
        return None
    finally:
        _mark_request_time()
    if resp is None or resp.status_code != 200 or not resp.text:
        return None
    content = _clean_jina_markdown(resp.text)
    if _word_count(content) < min_words or _is_challenge(content):
        return None
    return "jina", content


def _fetch_trafilatura(url: str, min_words: int) -> tuple[str, str] | None:
    try:
        import trafilatura
    except ImportError:
        return None
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded or _is_challenge(downloaded):
            return None
        text = trafilatura.extract(downloaded, output_format="markdown")
    except Exception:
        return None
    if not text:
        return None
    content = _clean_jina_markdown(text)
    if _word_count(content) < min_words or _is_challenge(content):
        return None
    return "trafilatura", content


def read_url(
    url: str,
    out_dir: str | None = None,
    source: str | None = None,
    *,
    min_words: int = DEFAULT_MIN_WORDS,
    write_file: bool = True,
) -> dict:
    """Fetch URL content. Returns {url, ok, words, content, tier, title_hint, excerpt_hint}."""
    resolved = resolve_url.resolve(url) or url
    if resolve_url.is_aggregator(resolved):
        rec = {"url": url, "source": source or _source_from_url(url),
               "ok": False, "words": 0, "content": "", "tier": "unresolved",
               "title_hint": "", "excerpt_hint": ""}
    else:
        got = _fetch_jina(resolved, min_words) or _fetch_trafilatura(resolved, min_words)
        if got:
            tier, content = got
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            title_hint = lines[0][:200] if lines else ""
            excerpt_hint = content[:500]
            rec = {
                "url": resolved, "source": source or _source_from_url(resolved),
                "ok": True, "words": _word_count(content), "content": content, "tier": tier,
                "title_hint": title_hint, "excerpt_hint": excerpt_hint,
            }
        else:
            rec = {
                "url": resolved, "source": source or _source_from_url(resolved),
                "ok": False, "words": 0, "content": "", "tier": "failed",
                "title_hint": "", "excerpt_hint": "",
            }

    if write_file and out_dir:
        os.makedirs(out_dir, exist_ok=True)
        digest = hashlib.sha1(resolved.encode("utf-8")).hexdigest()
        path = os.path.join(out_dir, f"{digest}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(rec, f, ensure_ascii=False)
        os.replace(tmp, path)
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description="Read one link via Jina for backlink discovery")
    ap.add_argument("--url", required=True)
    ap.add_argument("--out-dir", default=None)
    ap.add_argument("--source", default=None)
    ap.add_argument("--min-words", type=int, default=DEFAULT_MIN_WORDS, dest="min_words")
    args = ap.parse_args()

    rec = read_url(
        args.url,
        args.out_dir,
        args.source,
        min_words=args.min_words,
        write_file=bool(args.out_dir),
    )
    if rec["ok"]:
        print(f"READ_OK: words={rec['words']} tier={rec['tier']} {rec['url']}", file=sys.stderr)
    else:
        print(f"READ_SKIP: tier={rec['tier']} {rec['url']}", file=sys.stderr)
    return 0 if rec["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
