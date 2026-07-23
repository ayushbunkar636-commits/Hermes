#!/usr/bin/env python3
"""seo_provider.py — Abstraction for Ahrefs/Semrush/Moz data providers."""
import hashlib
from typing import TypedDict
from urllib.parse import urlparse

class SEOMetrics(TypedDict):
    domain_authority: int
    domain_rating: int
    organic_traffic: int
    spam_score: int


class SEOProvider:
    """Base interface for an SEO metrics provider."""
    
    def get_domain_metrics(self, domain: str) -> SEOMetrics:
        raise NotImplementedError


class MockSEOProvider(SEOProvider):
    """
    A deterministic mock provider for testing scoring algorithms
    without burning real API credits.
    """
    
    def get_domain_metrics(self, domain: str) -> SEOMetrics:
        # Clean domain
        domain = domain.lower().replace("www.", "").strip()
        if not domain:
            return {"domain_authority": 0, "domain_rating": 0, "organic_traffic": 0, "spam_score": 0}
            
        # Hardcode some famous domains for realistic testing
        known_domains = {
            "reddit.com": {"da": 92, "dr": 94, "traffic": 150000000, "spam": 2},
            "quora.com": {"da": 93, "dr": 91, "traffic": 85000000, "spam": 4},
            "ycombinator.com": {"da": 90, "dr": 88, "traffic": 5000000, "spam": 1},
            "github.com": {"da": 95, "dr": 96, "traffic": 80000000, "spam": 1},
            "medium.com": {"da": 95, "dr": 94, "traffic": 45000000, "spam": 5},
            "stackoverflow.com": {"da": 93, "dr": 92, "traffic": 70000000, "spam": 1},
        }
        
        if domain in known_domains:
            k = known_domains[domain]
            return {
                "domain_authority": k["da"],
                "domain_rating": k["dr"],
                "organic_traffic": k["traffic"],
                "spam_score": k["spam"],
            }
            
        # Deterministic pseudo-random metrics based on domain hash
        h = int(hashlib.md5(domain.encode("utf-8")).hexdigest()[:8], 16)
        
        # da: bell curve between 5 and 65 for unknown domains
        da = 5 + (h % 60)
        
        # dr: usually tracks da closely
        dr = max(0, min(100, da + ((h % 11) - 5)))
        
        # traffic: highly variable
        traffic_multiplier = (h % 100) * 10
        traffic = max(0, (da - 10) * traffic_multiplier * 50)
        
        # spam: mostly low, sometimes high
        spam = 0 if (h % 4) != 0 else (h % 40)
        
        return {
            "domain_authority": da,
            "domain_rating": dr,
            "organic_traffic": traffic,
            "spam_score": spam,
        }

def get_provider() -> SEOProvider:
    """Factory to get the configured SEO provider."""
    # In Phase 8, we hardcode the mock provider. 
    # Later this will read config.json to return AhrefsProvider or SemrushProvider.
    return MockSEOProvider()
