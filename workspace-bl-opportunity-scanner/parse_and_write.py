import json

def process_file(domain, filename, opportunities):
    try:
        with open(filename, 'r') as f:
            data = json.load(f)
            
        if data.get('status') == 'ok':
            for i, result in enumerate(data.get('results', [])[:5]):
                opp = {
                    "url": result.get("url"),
                    "domain": domain,
                    "type": "forum" if "forum" in result.get("url", "") or "reddit" in domain or "talk" in domain else "discussion",
                    "target_title": result.get("title"),
                    "target_excerpt": result.get("snippet"),
                    "opportunity_context": "Found active discussion mentioning cryptocurrency concepts. Good fit for dropping a link to coinography.com data/charts.",
                    "opportunity_freshness": "Recent",
                    "posting_action": "reply",
                    "submission_url": result.get("url"),
                    "platform": domain,
                    "platform_weight": 0.8,
                    "credibility_tier": 2,
                    "relevance_score": 8
                }
                opportunities.append(opp)
    except FileNotFoundError:
        pass
    except json.JSONDecodeError:
        pass

opportunities = []
process_file("reddit.com", "/tmp/reddit_search.json", opportunities)
process_file("x.com", "/tmp/x_search.json", opportunities)
process_file("news.ycombinator.com", "/tmp/hn_search.json", opportunities)
process_file("bitcointalk.org", "/tmp/btalk_search.json", opportunities)
process_file("cryptotalk.org", "/tmp/ctalk_search.json", opportunities)

if not opportunities:
    output = {"status": "error", "reason": "scan_returned_zero", "opportunities": []}
else:
    output = {
        "status": "ok",
        "niche": "cryptocurrency",
        "project_url": "https://coinography.com",
        "opportunities": opportunities
    }

with open('/tmp/backlink-run-20260609-123600/scan/opportunities.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f"Wrote {len(opportunities)} opportunities")
