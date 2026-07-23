import sys
import os
import requests
import xml.etree.ElementTree as ET
import logging

# Add pipeline directory to path for config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pipeline'))
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("trend_ingestion")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

TRENDS_RSS_URL = "https://www.reddit.com/r/worldnews/top/.rss?t=day"

def fetch_daily_trends() -> list[dict]:
    """Fetch top trending global news from Reddit RSS."""
    logger.info(f"Fetching trends from {TRENDS_RSS_URL}")
    try:
        resp = requests.get(TRENDS_RSS_URL, headers=HEADERS, timeout=15)
        if resp.status_code >= 400:
            logger.error(f"Failed to fetch trends. HTTP {resp.status_code}")
            return []
            
        root = ET.fromstring(resp.content)
        trends = []
        
        # Atom feed uses namespace
        ns = {'atom': 'http://www.w3.org/2005/Atom'}
        for entry in root.findall('.//atom:entry', ns):
            title = entry.find('atom:title', ns)
            
            trend_title = title.text if title is not None else ""
            # Context is less important here, the headline is the trend
            trend_context = "Breaking global news trend."
            
            if trend_title:
                trends.append({
                    "query": trend_title.strip(),
                    "context": trend_context
                })
                
        return trends[:10] # Return top 10 trends
    except Exception as e:
        logger.error(f"Error fetching trends: {e}")
        return []

def ingest_trends():
    """Fetch trends and save to the PostgreSQL database."""
    trends = fetch_daily_trends()
    if not trends:
        logger.warning("No trends fetched.")
        return
        
    conn = config.get_db_connection()
    c = conn.cursor()
    
    new_trends_added = 0
    for t in trends:
        try:
            # We use ON CONFLICT DO NOTHING to avoid inserting duplicates
            c.execute("""
                INSERT INTO daily_trends (trend_query, trend_context)
                VALUES (%s, %s)
                ON CONFLICT (trend_query) DO NOTHING
            """, (t['query'], t['context']))
            
            if c.rowcount > 0:
                new_trends_added += 1
                
        except Exception as e:
            logger.error(f"Error saving trend {t['query']}: {e}")
            conn.rollback()
            
    conn.commit()
    c.close()
    conn.close()
    
    logger.info(f"Trend ingestion complete. Added {new_trends_added} new trends today.")

if __name__ == "__main__":
    ingest_trends()
