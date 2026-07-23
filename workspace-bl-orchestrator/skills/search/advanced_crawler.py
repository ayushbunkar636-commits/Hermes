#!/usr/bin/env python3
"""advanced_crawler.py — Extracts full HTML and SEO metrics from target URLs."""
from __future__ import annotations

import re
import sys
import urllib.parse
from typing import Any
try:
    from seo_provider import get_provider
except ImportError:
    get_provider = None

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    requests = None
    BeautifulSoup = None

def _detect_dofollow_ugc(domain: str, html_text: str, bs_doc: Any) -> tuple[bool, bool, bool]:
    """Returns (is_dofollow, is_ugc, is_sponsored)."""
    # By default, we assume a link is dofollow unless specified otherwise
    # But for UGC platforms, they are almost always Nofollow + UGC
    domain = domain.lower()
    known_ugc_nofallows = [
        "reddit.com", "news.ycombinator.com", "stackexchange.com", 
        "stackoverflow.com", "quora.com", "twitter.com", "x.com",
        "medium.com", "dev.to", "hashnode.com"
    ]
    is_ugc = False
    is_dofollow = True
    is_sponsored = False
    
    for k in known_ugc_nofallows:
        if k in domain:
            is_ugc = True
            is_dofollow = False
            break

    # Check meta robots
    if bs_doc:
        meta_robots = bs_doc.find("meta", attrs={"name": re.compile(r"robots", re.I)})
        if meta_robots and meta_robots.get("content"):
            content = meta_robots.get("content").lower()
            if "nofollow" in content:
                is_dofollow = False

    return is_dofollow, is_ugc, is_sponsored


def crawl_url(url: str) -> dict:
    """Fetch full HTML and extract SEO metrics."""
    result = {
        "url": url,
        "page_language": None,
        "has_canonical": False,
        "canonical_url": None,
        "outbound_link_count": 0,
        "is_dofollow": True,
        "is_ugc": False,
        "is_sponsored": False,
        "full_html": "",
        "error": None,
        "title": "",
        "domain_authority": None,
        "domain_rating": None,
        "organic_traffic": None,
        "spam_score": None,
    }
    
    if not requests or not BeautifulSoup:
        result["error"] = "requests or beautifulsoup4 not installed"
        return result

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        html = resp.text
        result["full_html"] = html
        
        soup = BeautifulSoup(html, "html.parser")
        
        # Title
        if soup.title:
            result["title"] = soup.title.string

        # Language
        html_tag = soup.find("html")
        if html_tag and html_tag.get("lang"):
            result["page_language"] = html_tag.get("lang")

        # Canonical
        canonical = soup.find("link", rel="canonical")
        if canonical and canonical.get("href"):
            result["has_canonical"] = True
            result["canonical_url"] = canonical.get("href")

        # Outbound links
        base_domain = urllib.parse.urlparse(url).netloc.replace("www.", "")
        
        outbound_count = 0
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if href and href.startswith("http"):
                try:
                    p = urllib.parse.urlparse(href)
                    if p.netloc and base_domain not in p.netloc:
                        outbound_count += 1
                except Exception:
                    pass
        result["outbound_link_count"] = outbound_count

        # Dofollow/UGC checks
        dofollow, ugc, sponsored = _detect_dofollow_ugc(base_domain, html, soup)
        result["is_dofollow"] = dofollow
        result["is_ugc"] = ugc
        result["is_sponsored"] = sponsored
        
        # Inject SEO metrics via Provider
        if get_provider:
            try:
                provider = get_provider()
                metrics = provider.get_domain_metrics(base_domain)
                result.update(metrics)
            except Exception as e:
                result["error"] = f"seo_provider failed: {e}"

    except Exception as e:
        result["error"] = str(e)

    return result

if __name__ == "__main__":
    if len(sys.argv) > 1:
        import json
        print(json.dumps(crawl_url(sys.argv[1]), indent=2))
    else:
        print("Usage: python3 advanced_crawler.py <url>")
