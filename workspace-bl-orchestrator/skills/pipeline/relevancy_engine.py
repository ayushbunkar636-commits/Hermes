import sys
import os
import json
import logging
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pipeline'))
import config
from hermes_client import run_agent

logger = logging.getLogger("relevancy_engine")
logging.basicConfig(level=logging.INFO)

def get_project_sitemap(project_id: int) -> List[Dict]:
    conn = config.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT url, title, page_type FROM project_sitemaps WHERE project_id = %s", (project_id,))
    rows = c.fetchall()
    conn.close()
    return [{"url": r[0], "title": r[1], "type": r[2]} for r in rows]

def get_latest_trend() -> Optional[Dict]:
    conn = config.get_db_connection()
    c = conn.cursor()
    c.execute("SELECT trend_query, trend_context FROM daily_trends WHERE status = 'active' ORDER BY discovered_at DESC LIMIT 1")
    row = c.fetchone()
    conn.close()
    if row:
        return {"query": row[0], "context": row[1]}
    return None

def generate_relevancy_map(project_niche: str, sitemap: List[Dict], trend: Dict) -> Dict:
    """
    Uses the LLM as the Selection Engine to map a trend to the niche, 
    generate an angle, and pick the best deep links (Pillar + Post).
    """
    
    # We pass the sitemap catalog to the LLM to act as the Vector/Semantic search engine
    sitemap_json = json.dumps(sitemap[:50], indent=2) # Send up to 50 pages to fit context
    
    prompt = f"""
You are the Hermes Relevancy Engine. Your job is to perform Trend-Jacking.

CLIENT NICHE: {project_niche}
CURRENT GLOBAL TREND: {trend['query']} (Context: {trend['context']})

AVAILABLE CLIENT SITEMAP (JSON):
{sitemap_json}

TASKS:
1. Generate a "Thought Leadership" angle that naturally bridges the CURRENT GLOBAL TREND with the CLIENT NICHE.
2. Select ONE "pillar" page from the sitemap that relates to the long-term topic.
3. Select ONE "post" page from the sitemap that matches the timely angle.
If you cannot find a perfect match, pick the closest relevant pages.

Respond EXACTLY in this JSON format:
{{
    "angle": "Your generated viral angle here...",
    "pillar_url": "URL chosen from sitemap",
    "post_url": "URL chosen from sitemap"
}}
"""

    logger.info(f"Generating relevancy map for niche '{project_niche}' and trend '{trend['query'][:30]}...'")
    try:
        response_dict = run_agent("relevancy_engine", prompt)
        
        if isinstance(response_dict, dict) and "response" in response_dict:
            response = response_dict["response"]
        else:
            response = response_dict
            
        # Parse JSON string
        if isinstance(response, str):
            if "```json" in response:
                response = response.split("```json")[1].split("```")[0].strip()
            elif "```" in response:
                response = response.split("```")[1].strip()
            return json.loads(response)
            
        if isinstance(response, dict):
            return response
            
        return {}
    except Exception as e:
        logger.error(f"Failed to generate relevancy map: {e}")
        return {}

def test_relevancy_engine():
    # Mock data for testing
    dummy_sitemap = [
        {"url": "https://clientfruits.com/services/global-shipping", "title": "Global Fruit Logistics and Shipping", "type": "pillar"},
        {"url": "https://clientfruits.com/blog/2026-supply-chain-issues", "title": "How Supply Chain Issues Impact Freshness", "type": "post"},
        {"url": "https://clientfruits.com/about", "title": "About Us", "type": "pillar"}
    ]
    trend = {"query": "Suez Canal Blocked Again Due to Regional Conflict", "context": "Massive shipping delays reported worldwide."}
    
    result = generate_relevancy_map("Exotic Fruit Importer", dummy_sitemap, trend)
    print("--- RELEVANCY ENGINE OUTPUT ---")
    print(json.dumps(result, indent=2))

if __name__ == "__main__":
    test_relevancy_engine()
