#!/usr/bin/env python3
"""lang_filter.py — Lightweight English-only filter for harvest leads."""
from __future__ import annotations

import re
import unicodedata

# Non-Latin scripts we reject (Cyrillic, CJK, Arabic, Greek, Hebrew, Devanagari, etc.)
_NON_LATIN_RE = re.compile(
    r"[\u0400-\u04FF"  # Cyrillic
    r"\u0500-\u052F"  # Cyrillic supplement
    r"\u0600-\u06FF"  # Arabic
    r"\u0750-\u077F"  # Arabic supplement
    r"\u0590-\u05FF"  # Hebrew
    r"\u0900-\u097F"  # Devanagari
    r"\u0370-\u03FF"  # Greek
    r"\u3040-\u30FF"  # Hiragana + Katakana
    r"\u4E00-\u9FFF"  # CJK unified
    r"\uAC00-\uD7AF"  # Hangul
    r"\u0E00-\u0E7F"  # Thai
    r"]"
)

# Latin letters including accented Latin (French, Spanish, German, etc.)
_LATIN_LETTER_RE = re.compile(r"[A-Za-z\u00C0-\u024F]")


def _letter_counts(text: str) -> tuple[int, int]:
    """Return (latin_letter_count, non_latin_script_count)."""
    latin = 0
    non_latin = 0
    for ch in text:
        if _LATIN_LETTER_RE.match(ch):
            latin += 1
        elif _NON_LATIN_RE.match(ch):
            non_latin += 1
        elif unicodedata.category(ch).startswith("L"):
            # Other letter scripts (e.g. extended Latin outside our range)
            name = unicodedata.name(ch, "")
            if "LATIN" in name:
                latin += 1
            else:
                non_latin += 1
    return latin, non_latin


def is_probably_english(title: str, snippet: str = "", *, max_non_latin_ratio: float = 0.05) -> bool:
    """Return True when title+snippet look English-only.

    Rejects when non-Latin script letters exceed a small share of all letters.
    Allows accented Latin. Empty text passes (no signal to reject).
    """
    text = f"{title or ''} {snippet or ''}".strip()
    if not text:
        return True
    latin, non_latin = _letter_counts(text)
    total = latin + non_latin
    if total == 0:
        return True
    if non_latin == 0:
        return True
    return (non_latin / total) <= max_non_latin_ratio
