#!/usr/bin/env python3
"""001_phase2_seo_data_model.py - Adds advanced SEO tracking columns."""

import os
import sys

# Ensure pipeline dir is in path to import config
_DIR = os.path.dirname(os.path.abspath(__file__))
_PIPELINE = os.path.dirname(_DIR)
if _PIPELINE not in sys.path:
    sys.path.insert(0, _PIPELINE)

import config

def apply_migration():
    print("Connecting to database...")
    conn = config.get_db_connection()
    c = conn.cursor()

    columns_to_add = [
        # Domain Metrics for projects
        ("projects", "domain_authority", "INTEGER"),
        ("projects", "domain_rating", "INTEGER"),
        ("projects", "trust_flow", "INTEGER"),
        ("projects", "citation_flow", "INTEGER"),
        ("projects", "organic_keywords", "INTEGER"),
        ("projects", "organic_traffic", "INTEGER"),
        ("projects", "referring_domains", "INTEGER"),
        ("projects", "indexed_pages", "INTEGER"),

        # Domain Metrics for whitelist_sites
        ("whitelist_sites", "domain_authority", "INTEGER"),
        ("whitelist_sites", "domain_rating", "INTEGER"),
        ("whitelist_sites", "trust_flow", "INTEGER"),
        ("whitelist_sites", "citation_flow", "INTEGER"),
        ("whitelist_sites", "organic_keywords", "INTEGER"),
        ("whitelist_sites", "organic_traffic", "INTEGER"),
        ("whitelist_sites", "referring_domains", "INTEGER"),

        # Page Metrics for harvest_leads
        ("harvest_leads", "url_rating", "INTEGER"),
        ("harvest_leads", "page_authority", "INTEGER"),
        ("harvest_leads", "estimated_traffic", "INTEGER"),
        ("harvest_leads", "page_language", "TEXT"),
        ("harvest_leads", "country", "TEXT"),
        ("harvest_leads", "page_age_days", "INTEGER"),

        # Link Metrics for harvest_leads
        ("harvest_leads", "is_dofollow", "BOOLEAN"),
        ("harvest_leads", "is_sponsored", "BOOLEAN"),
        ("harvest_leads", "is_ugc", "BOOLEAN"),
        ("harvest_leads", "is_redirect", "BOOLEAN"),
        ("harvest_leads", "has_canonical", "BOOLEAN"),
        ("harvest_leads", "anchor_text", "TEXT"),
        ("harvest_leads", "link_position", "TEXT"),
        ("harvest_leads", "outbound_link_count", "INTEGER"),

        # Discussion Metrics for harvest_leads
        ("harvest_leads", "discussion_intent", "TEXT"),
        ("harvest_leads", "question_type", "TEXT"),
        ("harvest_leads", "buying_intent", "TEXT"),
        ("harvest_leads", "engagement_score", "REAL"),
        ("harvest_leads", "comment_count", "INTEGER"),
    ]

    print("Checking existing columns...")
    # Fetch all columns for these 3 tables to avoid "column already exists" errors
    c.execute("""
        SELECT table_name, column_name 
        FROM information_schema.columns 
        WHERE table_name IN ('projects', 'whitelist_sites', 'harvest_leads')
    """)
    existing = set((row['table_name'], row['column_name']) for row in c.fetchall())

    added_count = 0
    for table, col, dtype in columns_to_add:
        if (table, col) not in existing:
            print(f"Adding {table}.{col} ({dtype})...")
            # Safe because table/col names are hardcoded above
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {dtype}")
            added_count += 1
        else:
            print(f"Skipping {table}.{col} (already exists).")

    conn.commit()
    conn.close()
    print(f"Migration complete! Added {added_count} new SEO columns.")

if __name__ == "__main__":
    apply_migration()
