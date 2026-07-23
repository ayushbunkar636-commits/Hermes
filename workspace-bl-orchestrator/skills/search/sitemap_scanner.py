import sys
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urlparse, urljoin
import logging
import xml.etree.ElementTree as ET

# Add pipeline directory to path for config
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'pipeline'))
import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("sitemap_scanner")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def determine_page_type(url: str) -> str:
    """Guess if a page is a timeless pillar or a trending post based on URL structure."""
    url_lower = url.lower()
    post_indicators = ['/blog/', '/post/', '/news/', '/article/', '/202', '/update']
    for ind in post_indicators:
        if ind in url_lower:
            return 'post'
    return 'pillar'

def fetch_page_metadata(url: str) -> tuple[str, str]:
    """Fetch the page and extract <title> and <meta name='description'>."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code >= 400:
            return "", ""
        
        soup = BeautifulSoup(resp.text, 'html.parser')
        
        title = ""
        if soup.title:
            title = soup.title.string.strip()
            
        desc = ""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            desc = meta_desc['content'].strip()
            
        return title, desc
    except Exception as e:
        logger.warning(f"Failed to fetch metadata for {url}: {e}")
        return "", ""

def parse_sitemap(sitemap_url: str) -> list[str]:
    """Parse an XML sitemap and return a list of URLs."""
    try:
        resp = requests.get(sitemap_url, headers=HEADERS, timeout=10)
        if resp.status_code >= 400:
            logger.error(f"Failed to fetch sitemap {sitemap_url} (HTTP {resp.status_code})")
            return []
            
        urls = []
        try:
            root = ET.fromstring(resp.content)
            # Handle XML namespaces usually present in sitemaps
            namespaces = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
            for url_tag in root.findall('.//sm:url/sm:loc', namespaces):
                if url_tag.text:
                    urls.append(url_tag.text.strip())
            
            # Fallback if namespace is different or missing
            if not urls:
                for loc in root.findall('.//{*}loc'):
                    if loc.text:
                        urls.append(loc.text.strip())
                        
        except ET.ParseError:
            logger.error("Failed to parse sitemap XML.")
            
        return urls
    except Exception as e:
        logger.error(f"Error fetching sitemap {sitemap_url}: {e}")
        return []

def scan_project_sitemap(project_id: int, project_url: str):
    """Scan the project's sitemap and save pages to the DB. Fallback to homepage crawling if sitemap is missing."""
    parsed = urlparse(project_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    sitemap_url = urljoin(base_url, "/sitemap.xml")
    
    logger.info(f"Looking for sitemap at: {sitemap_url}")
    urls = parse_sitemap(sitemap_url)
    
    if not urls:
        alt_sitemap = urljoin(base_url, "/sitemap_index.xml")
        logger.info(f"Trying alternative sitemap: {alt_sitemap}")
        urls = parse_sitemap(alt_sitemap)
        
    if not urls:
        logger.warning(f"No sitemaps found. Falling back to scraping the homepage: {base_url}")
        try:
            resp = requests.get(base_url, headers=HEADERS, timeout=10)
            if resp.status_code < 400:
                soup = BeautifulSoup(resp.text, 'html.parser')
                for a_tag in soup.find_all('a', href=True):
                    href = a_tag['href']
                    full_link = urljoin(base_url, href)
                    if full_link.startswith(base_url):
                        # Remove fragments and queries
                        clean_link = full_link.split('#')[0].split('?')[0]
                        if clean_link not in urls and clean_link != base_url:
                            urls.append(clean_link)
        except Exception as e:
            logger.error(f"Failed to scrape homepage: {e}")
            
    if not urls:
        logger.warning(f"No URLs found at all for {project_url}.")
        return
        
    logger.info(f"Found {len(urls)} URLs in sitemap. Processing...")
    
    conn = config.get_db_connection()
    c = conn.cursor()
    
    processed = 0
    for url in urls:
        # Check if we already have it
        c.execute("SELECT id FROM project_sitemaps WHERE project_id = %s AND url = %s", (project_id, url))
        if c.fetchone():
            continue # Already processed
            
        page_type = determine_page_type(url)
        title, desc = fetch_page_metadata(url)
        
        # We only want to save pages that actually have some content/title
        if title:
            try:
                c.execute("""
                    INSERT INTO project_sitemaps (project_id, url, title, meta_description, page_type)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (project_id, url) DO NOTHING
                """, (project_id, url, title, desc, page_type))
                conn.commit()
                processed += 1
                logger.info(f"Saved [{page_type.upper()}]: {title[:50]}... ({url})")
            except Exception as e:
                conn.rollback()
                logger.error(f"Error saving {url} to DB: {e}")
                
    c.close()
    conn.close()
    logger.info(f"Sitemap scan complete. {processed} new pages added to Knowledge Base.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Hermes V2 Sitemap Scanner")
    parser.add_argument("project_url", help="The project URL to scan sitemap for")
    parser.add_argument("--project-id", type=int, default=1, dest="project_id", help="Project ID in PostgreSQL")
    args = parser.parse_args()
    
    print(f"Scanning sitemap for {args.project_url} (project_id={args.project_id})")
    scan_project_sitemap(args.project_id, args.project_url)
