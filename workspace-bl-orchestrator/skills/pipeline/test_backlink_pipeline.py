#!/usr/bin/env python3
"""Tests for backlink pipeline scripts (no network, no LLM)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest


PIPELINE = os.path.expanduser("~/.openclaw-backlink/workspace-bl-orchestrator/skills/pipeline")


def run_cmd(args: list[str], *, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, env=env)


@unittest.skip("Skipped: tests for old discovery/audit pipeline scripts (merge_discovery, validate_discovery, verify_artifacts) removed in whitelist rebuild")
class BacklinkPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="bl-test-")
        self.run_id = "20990101-120000"
        self.run_dir = os.path.join(self.tmp, f"backlink-run-{self.run_id}")
        os.makedirs(f"{self.run_dir}/discovery", exist_ok=True)
        os.makedirs(f"{self.run_dir}/audit", exist_ok=True)
        os.makedirs(f"{self.run_dir}/content/images", exist_ok=True)
        os.makedirs(f"{self.run_dir}/delivery", exist_ok=True)

        self.manifest = {
            "run_id": self.run_id,
            "run_dir": self.run_dir,
            "pipeline": "backlink",
            "project": {
                "niche": "SaaS tools",
                "project_url": "https://example.com",
                "project_name": "Example SaaS",
                "project_description": "Project management SaaS",
            },
            "artifacts": {
                "discovery_raw": f"{self.run_dir}/discovery/raw.json",
                "discovery_validated": f"{self.run_dir}/discovery/validated.json",
                "audit_results": f"{self.run_dir}/audit/results.json",
                "content_posts": f"{self.run_dir}/content/posts.json",
                "content_images_dir": f"{self.run_dir}/content/images",
                "delivery_card": f"{self.run_dir}/delivery/card.json",
            },
            "steps": {},
        }
        manifest_path = f"{self.run_dir}/manifest.json"
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, indent=2)
        self.manifest_path = manifest_path
        import time
        with open(f"{self.run_dir}/.run_started", "w") as f:
            f.write(str(time.time() - 10))

    def test_init_run_script(self) -> None:
        result = run_cmd(
            [
                "bash",
                f"{PIPELINE}/init_run.sh",
                "--niche",
                "crypto wallets",
                "--project-url",
                "https://test.example.com",
                "--project-name",
                "TestWallet",
            ]
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("[INIT] Backlink run bundle ready", result.stdout)
        self.assertTrue(os.path.isfile("/tmp/backlink-run-env.sh"))

    def test_validate_discovery_and_audit_and_content(self) -> None:
        discovery = {
            "status": "ok",
            "niche": "SaaS tools",
            "project_url": "https://example.com",
            "sites": [
                {
                    "url": "https://blog.example.org/write-for-us",
                    "domain": "blog.example.org",
                    "type": "guest_post",
                    "title": "Write for Us",
                    "relevance_notes": "SaaS audience",
                    "submission_url": "https://blog.example.org/submit",
                    "target_title": "Write for Us - Example Blog",
                    "target_excerpt": "We accept original SaaS articles from industry experts.",
                    "opportunity_context": "Editorial guest post page actively seeking SaaS content.",
                    "opportunity_freshness": "evergreen",
                    "posting_action": "outreach_email",
                    "guidelines_snippet": "Original content only",
                }
            ],
        }
        with open(self.manifest["artifacts"]["discovery_raw"], "w", encoding="utf-8") as f:
            json.dump(discovery, f)

        r1 = run_cmd(
            ["python3", f"{PIPELINE}/validate_discovery.py", "--manifest", self.manifest_path]
        )
        self.assertEqual(r1.returncode, 0, r1.stdout + r1.stderr)
        self.assertIn("DISCOVERY_VALID", r1.stdout)

        audit = {
            "status": "ok",
            "audited_sites": [
                {
                    "url": "https://blog.example.org/write-for-us",
                    "domain": "blog.example.org",
                    "type": "guest_post",
                    "submission_url": "https://blog.example.org/submit",
                    "target_title": "Write for Us - Example Blog",
                    "target_excerpt": "We accept original SaaS articles from industry experts.",
                    "opportunity_context": "Editorial guest post page actively seeking SaaS content.",
                    "opportunity_freshness": "evergreen",
                    "posting_action": "outreach_email",
                    "score": 8.5,
                    "domain_authority": 45,
                    "dofollow": True,
                    "spam_score": "low",
                    "relevance_score": 9,
                    "traffic_estimate": "medium",
                    "freshness_score": 6,
                    "contextual_fit": 9,
                    "posting_ease": "manual_review",
                    "recommendation": "high_priority",
                    "audit_notes": "Strong SaaS blog",
                }
            ],
        }
        with open(self.manifest["artifacts"]["audit_results"], "w", encoding="utf-8") as f:
            json.dump(audit, f)

        r2 = run_cmd(
            ["python3", f"{PIPELINE}/validate_audit.py", "--manifest", self.manifest_path]
        )
        self.assertEqual(r2.returncode, 0, r2.stdout + r2.stderr)
        self.assertIn("AUDIT_VALID", r2.stdout)

        posts = {
            "status": "ok",
            "niche": "SaaS tools",
            "project_url": "https://example.com",
            "posts": [
                {
                    "site_url": "https://blog.example.org/write-for-us",
                    "site_domain": "blog.example.org",
                    "type": "guest_post",
                    "title": "Why SaaS Teams Need Better PM Tools",
                    "content": "Great tools matter. See [Example SaaS](https://example.com) for details.",
                    "backlink_url": "https://example.com",
                    "backlink_anchor_text": "Example SaaS",
                    "image_path": None,
                    "submission_instructions": "Email editor@example.org",
                    "submission_url": "https://blog.example.org/submit",
                    "target_title": "Write for Us - Example Blog",
                    "target_excerpt": "We accept original SaaS articles from industry experts.",
                    "opportunity_context": "Editorial guest post page actively seeking SaaS content.",
                    "opportunity_freshness": "evergreen",
                    "posting_action": "outreach_email",
                    "posting_steps": [
                        "Open https://blog.example.org/submit",
                        "Paste the article below",
                        "Send to editor@example.org",
                    ],
                }
            ],
        }
        with open(self.manifest["artifacts"]["content_posts"], "w", encoding="utf-8") as f:
            json.dump(posts, f)

        r3 = run_cmd(
            ["python3", f"{PIPELINE}/validate_content.py", "--manifest", self.manifest_path]
        )
        self.assertEqual(r3.returncode, 0, r3.stdout + r3.stderr)
        self.assertIn("CONTENT_VALID", r3.stdout)

    def test_verify_artifacts_stages(self) -> None:
        self.test_validate_discovery_and_audit_and_content()

        for stage in ("pre_audit", "pre_content", "pre_delivery"):
            r = run_cmd(
                [
                    "python3",
                    f"{PIPELINE}/verify_artifacts.py",
                    "--stage",
                    stage,
                    "--manifest",
                    self.manifest_path,
                ]
            )
            self.assertEqual(r.returncode, 0, f"{stage}: {r.stdout}{r.stderr}")
            self.assertIn(f"ARTIFACTS_OK: {stage}", r.stdout)

    def test_update_manifest_step(self) -> None:
        r = run_cmd(
            [
                "bash",
                f"{PIPELINE}/update_manifest_step.sh",
                "--manifest",
                self.manifest_path,
                "--step",
                "discovery",
                "--status",
                "succeeded",
            ]
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        with open(self.manifest_path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["steps"]["discovery"]["status"], "succeeded")

    def test_backlink_db_and_feedback_no_reply(self) -> None:
        db_path = os.path.join(self.tmp, "test_backlink.db")
        env = os.environ.copy()
        env["PYTHONPATH"] = PIPELINE

        from backlink_db import init_db, insert_opportunity, lookup_by_alert_id, set_status  # noqa: E402

        init_db(db_path)
        card = {
            "run_id": self.run_id,
            "alert_id": f"bl-{self.run_id}-blog-example-org",
            "niche": "SaaS tools",
            "project_url": "https://example.com",
            "site_url": "https://blog.example.org/write-for-us",
            "site_domain": "blog.example.org",
            "content_title": "Test",
            "content_md": "Content with https://example.com link",
            "backlink_url": "https://example.com",
            "backlink_anchor_text": "Example",
            "telegram_group": "-1003760909509",
            "telegram_message_id": 12345,
            "card_sent_at": "2099-01-01T00:00:00+00:00",
            "run_dir": self.run_dir,
        }
        opp_id = insert_opportunity(card, db_path)
        self.assertGreater(opp_id, 0)

        r = run_cmd(
            [
                "python3",
                f"{PIPELINE}/handle_card_feedback.py",
                "--payload",
                f"bl_approve:{card['alert_id']}",
                "--chat-id",
                "-1003760909509",
                "--user-id",
                "1",
                "--no-reply",
                "--db-path",
                db_path,
            ],
            env=env,
        )
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("APPROVE_OK", r.stdout)
        opp = lookup_by_alert_id(card["alert_id"], db_path)
        assert opp is not None
        self.assertEqual(opp.status, "approved")

    def test_build_cards_from_manifest(self) -> None:
        self.test_validate_discovery_and_audit_and_content()
        sys.path.insert(0, PIPELINE)
        import build_and_send_card as bsc  # noqa: E402

        cards, delivery_path, project_url = bsc.build_cards_from_manifest(self.manifest_path)
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["site_domain"], "blog.example.org")
        self.assertEqual(cards[0]["target_title"], "Write for Us - Example Blog")
        self.assertEqual(cards[0]["submission_url"], "https://blog.example.org/submit")
        self.assertEqual(len(cards[0]["posting_steps"]), 3)
        caption = bsc.build_caption(cards[0])
        self.assertIn("Target Title:", caption)
        self.assertIn("Content to Post", caption)
        self.assertIn("How to post:", caption)
        self.assertIn("DIRECT LINK", caption)
        self.assertIn("inline", str(bsc.build_inline_keyboard(cards[0])))

    def test_validate_discovery_new_types_and_flags(self) -> None:
        discovery = {
            "status": "ok",
            "niche": "crypto",
            "project_url": "https://example.com",
            "sites": [
                {
                    "url": "https://reddit.com/r/crypto/comments/abc/thread",
                    "domain": "reddit.com",
                    "type": "qa_community",
                    "submission_url": "https://reddit.com/r/crypto/comments/abc/thread",
                    "target_title": "Best crypto tracker%s",
                    "target_excerpt": "Looking for reliable memecoin price tracking tools.",
                    "opportunity_context": "Active question seeking exactly what the project offers.",
                    "opportunity_freshness": "2026-06-08 (posted ~2h ago)",
                    "posting_action": "reply",
                },
                {
                    "url": "https://example.org/",
                    "domain": "example.org",
                    "type": "directory",
                    "submission_url": "https://example.org/",
                },
            ],
        }
        with open(self.manifest["artifacts"]["discovery_raw"], "w", encoding="utf-8") as f:
            json.dump(discovery, f)

        r = run_cmd(
            ["python3", f"{PIPELINE}/validate_discovery.py", "--manifest", self.manifest_path]
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("DISCOVERY_VALID", r.stdout)
        self.assertIn("context_missing", r.stdout)
        self.assertIn("url_precision_low", r.stdout)

        with open(self.manifest["artifacts"]["discovery_validated"], encoding="utf-8") as f:
            validated = json.load(f)
        self.assertIn("context_missing", validated["validation_flags"])
        self.assertIn("url_precision_low", validated["validation_flags"])
        self.assertTrue(validated["sites"][1]["context_missing"])

    def test_db_migration_and_opportunity_fields(self) -> None:

        db_path = os.path.join(self.tmp, "migrate_backlink.db")
        old_schema = """
        CREATE TABLE opportunities (
          id SERIAL PRIMARY KEY,
          run_id TEXT NOT NULL, alert_id TEXT NOT NULL, niche TEXT, project_url TEXT,
          project_name TEXT, site_url TEXT NOT NULL, site_domain TEXT, site_type TEXT,
          audit_score REAL, domain_authority INTEGER, dofollow INTEGER, recommendation TEXT,
          audit_notes TEXT, content_title TEXT, content_md TEXT, backlink_url TEXT,
          backlink_anchor_text TEXT, image_path TEXT, submission_instructions TEXT,
          telegram_group TEXT NOT NULL, telegram_message_id INTEGER NOT NULL,
          card_sent_at TEXT, run_dir TEXT, status TEXT DEFAULT 'pending',
          created_at TEXT DEFAULT (timezone('utc', now()))
        );
        """
        conn = sqlite3.connect(db_path)
        conn.executescript(old_schema)
        conn.execute(
            "INSERT INTO opportunities (run_id, alert_id, site_url, telegram_group, telegram_message_id) "
            "VALUES ('r1','bl-old','https://x.com','grp',1)"
        )
        conn.commit()
        conn.close()

        sys.path.insert(0, PIPELINE)
        from backlink_db import init_db, insert_opportunity, lookup_by_alert_id  # noqa: E402

        init_db(db_path)
        opp_id = insert_opportunity(
            {
                "run_id": "r2",
                "alert_id": "bl-r2-test",
                "site_url": "https://reddit.com/r/crypto/comments/abc",
                "submission_url": "https://reddit.com/r/crypto/comments/abc",
                "target_title": "Best tracker%s",
                "target_excerpt": "Need a memecoin tracker.",
                "opportunity_context": "Active thread.",
                "opportunity_freshness": "2026-06-08",
                "posting_action": "reply",
                "posting_steps": ["Open URL", "Reply", "Paste"],
                "telegram_group": "grp",
                "telegram_message_id": 2,
            },
            db_path,
        )
        self.assertGreater(opp_id, 0)
        opp = lookup_by_alert_id("bl-r2-test", db_path)
        assert opp is not None
        self.assertEqual(opp.target_title, "Best tracker%s")
        self.assertEqual(opp.posting_action, "reply")
        self.assertIn("Open URL", opp.posting_steps or "")

        conn = sqlite3.connect(db_path)
        count = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        conn.close()
        self.assertEqual(count, 2)


# ---------------------------------------------------------------------------
# Search skill tests (all offline — no network)
# ---------------------------------------------------------------------------

SEARCH_SKILL = os.path.expanduser("~/.openclaw-backlink/workspace-bl-orchestrator/skills/search")


class SearchSkillParserTests(unittest.TestCase):
    """Offline parser tests for search.py — no network calls."""

    def setUp(self) -> None:
        sys.path.insert(0, SEARCH_SKILL)

    def test_parse_searxng_json(self) -> None:
        from search import parse_searxng_json  # noqa: E402

        fixture = json.dumps({
            "results": [
                {"title": "Crypto Blog", "url": "https://cryptoblog.io/write-for-us", "content": "Guest posts welcome"},
                {"title": "No URL", "url": "", "content": "nothing"},
            ]
        }).encode()
        results = parse_searxng_json(fixture)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Crypto Blog")
        self.assertEqual(results[0]["url"], "https://cryptoblog.io/write-for-us")
        self.assertEqual(results[0]["snippet"], "Guest posts welcome")
        self.assertEqual(results[0]["source_engine"], "searxng")

    def test_parse_ddg_lite_html(self) -> None:
        from search import parse_ddg_lite_html  # noqa: E402

        fixture = b"""
        <html><body>
        <table>
        <tr><td><a class="result-link" href="https://example.com/page">Example Page</a></td></tr>
        <tr><td class="result-snippet">A great SaaS resource page.</td></tr>
        </table>
        </body></html>
        """
        results = parse_ddg_lite_html(fixture)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://example.com/page")
        self.assertIn("Example", results[0]["title"])
        self.assertEqual(results[0]["source_engine"], "ddg_lite")

    def test_parse_ddg_html(self) -> None:
        from search import parse_ddg_html  # noqa: E402

        fixture = b"""
        <html><body>
        <a class="result__a" href="https://saassite.io/guest-post">SaaS Guest Post</a>
        <a class="result__snippet">Write for our SaaS blog.</a>
        </body></html>
        """
        results = parse_ddg_html(fixture)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://saassite.io/guest-post")
        self.assertIn("SaaS", results[0]["title"])
        self.assertEqual(results[0]["source_engine"], "ddg_html")

    def test_unwrap_ddg_redirect(self) -> None:
        from search import unwrap_ddg_redirect  # noqa: E402

        encoded = "https://duckduckgo.com/l/%suddg=https%3A%2F%2Fexample.com%2Fpage&rut=abc"
        self.assertEqual(unwrap_ddg_redirect(encoded), "https://example.com/page")

    def test_normalize_strips_tracking(self) -> None:
        from search import normalize_url  # noqa: E402

        url = "https://example.com/page%sutm_source=test&utm_campaign=bl&ref=nav"
        self.assertEqual(normalize_url(url), "https://example.com/page")

    def test_cross_provider_dedupe(self) -> None:
        """Duplicate URLs from different providers collapse to one result."""
        from search import parse_searxng_json, parse_ddg_html, normalize_url  # noqa: E402

        searxng_raw = json.dumps({
            "results": [{"title": "Same Page", "url": "https://example.com/page", "content": "desc"}]
        }).encode()
        ddg_raw = b'<a class="result__a" href="https://example.com/page">Same Page</a>'

        searxng_results = parse_searxng_json(searxng_raw)
        ddg_results = parse_ddg_html(ddg_raw)

        all_results = searxng_results + ddg_results
        seen: set[str] = set()
        deduped = []
        for r in all_results:
            if r["url"] not in seen:
                seen.add(r["url"])
                deduped.append(r)
        self.assertEqual(len(deduped), 1)


class SearchSkillFailLoudTests(unittest.TestCase):
    """Test that search.py exits nonzero with SEARCH_UNAVAILABLE when all providers fail."""

    def test_fail_loud_unreachable_host(self) -> None:
        """Point all providers at unreachable host; assert nonzero exit + SEARCH_UNAVAILABLE."""
        env = os.environ.copy()
        env["BL_SEARXNG_MIRRORS"] = "http://127.0.0.1:19999"
        env["BL_SEARCH_TIMEOUT"] = "1"
        env["BL_SEARCH_RETRIES"] = "1"
        # Override ddg endpoints so they also fail (point to non-routable address via env)
        # The script will still try ddg_lite/ddg_html at their real URLs but with 1s timeout
        # which may or may not succeed; we use a patched script approach via subprocess with
        # a tiny timeout + unreachable mirror so at least searxng fails loudly.
        result = subprocess.run(
            [sys.executable, os.path.join(SEARCH_SKILL, "search.py"), "--query", "test query"],
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        # If DDG is also unavailable (network restricted), we get nonzero + SEARCH_UNAVAILABLE.
        # If DDG happens to return results, exit 0 is also acceptable (search succeeded on Tier 2).
        if result.returncode != 0:
            self.assertIn("SEARCH_UNAVAILABLE", result.stderr)
            self.assertEqual(result.stdout.strip(), "", "stdout must be empty on failure")


@unittest.skip("Skipped: validate_discovery.py deleted in whitelist rebuild — replaced by validate_scan.py")
class DiscoveryValidatorTests(unittest.TestCase):
    """Offline tests for validate_discovery.py new behaviours."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="bl-validator-test-")
        self.run_dir = os.path.join(self.tmp, "run-99")
        os.makedirs(f"{self.run_dir}/discovery", exist_ok=True)
        self.manifest = {
            "run_id": "run-99",
            "run_dir": self.run_dir,
            "project": {"niche": "crypto", "project_url": "https://example.com"},
            "artifacts": {
                "discovery_raw": f"{self.run_dir}/discovery/raw.json",
                "discovery_validated": f"{self.run_dir}/discovery/validated.json",
            },
            "steps": {},
        }
        self.manifest_path = f"{self.run_dir}/manifest.json"
        with open(self.manifest_path, "w") as f:
            json.dump(self.manifest, f)

    def _write_raw(self, data: dict) -> None:
        with open(self.manifest["artifacts"]["discovery_raw"], "w") as f:
            json.dump(data, f)

    def test_status_error_emits_discovery_error(self) -> None:
        self._write_raw({
            "status": "error",
            "reason": "search_unavailable",
            "niche": "crypto",
            "project_url": "https://example.com",
            "message": "All tiers returned zero results.",
            "sites": [],
        })
        r = subprocess.run(
            [sys.executable, f"{PIPELINE}/validate_discovery.py", "--manifest", self.manifest_path],
            capture_output=True, text=True
        )
        self.assertEqual(r.returncode, 1)
        self.assertIn("DISCOVERY_ERROR", r.stdout)
        self.assertIn("search_unavailable", r.stdout)

    def test_discovered_via_accepted_non_blocking(self) -> None:
        """discovered_via on a site must not cause DISCOVERY_INVALID."""
        self._write_raw({
            "status": "ok",
            "niche": "crypto",
            "project_url": "https://example.com",
            "sites": [
                {
                    "url": "https://cryptoblog.io/write-for-us",
                    "domain": "cryptoblog.io",
                    "type": "guest_post",
                    "submission_url": "https://cryptoblog.io/write-for-us",
                    "target_title": "Write for us",
                    "target_excerpt": "We accept crypto guest posts.",
                    "opportunity_context": "Active editorial page.",
                    "opportunity_freshness": "evergreen",
                    "posting_action": "outreach_email",
                    "discovered_via": "competitor:coindesk.com",
                }
            ],
        })
        r = subprocess.run(
            [sys.executable, f"{PIPELINE}/validate_discovery.py", "--manifest", self.manifest_path],
            capture_output=True, text=True
        )
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("DISCOVERY_VALID", r.stdout)
        with open(self.manifest["artifacts"]["discovery_validated"]) as f:
            validated = json.load(f)
        self.assertEqual(validated["sites"][0].get("discovered_via"), "competitor:coindesk.com")


class BrowserConfigSanityTests(unittest.TestCase):
    """Non-network sanity checks for browser config (symlink resolution logic)."""

    def test_symlink_resolves_to_highest_playwright_version(self) -> None:
        """Simulate the symlink creation logic and verify it picks the latest version."""
        import glob as _glob
        chrome_paths = sorted(
            _glob.glob(os.path.expanduser("~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")),
            key=lambda p: [int(x) if x.isdigit() else x for x in p.split(os.sep)],
        )
        if not chrome_paths:
            self.skipTest("No Playwright Chromium found — skip browser-config sanity")
        expected_latest = chrome_paths[-1]
        symlink_path = os.path.expanduser("~/.openclaw-backlink/bin/chromium")
        if os.path.islink(symlink_path):
            resolved = os.path.realpath(symlink_path)
            self.assertEqual(resolved, expected_latest,
                             f"Symlink points to {resolved} but latest is {expected_latest}")
        else:
            self.skipTest("Symlink not yet created — skip browser-config sanity")


# ---------------------------------------------------------------------------
# search.py DDG-first + freshness tests
# ---------------------------------------------------------------------------

class SearchSkillFreshnessTests(unittest.TestCase):
    """Offline tests for freshness param and DDG-only default in search.py."""

    def setUp(self) -> None:
        sys.path.insert(0, SEARCH_SKILL)

    def test_freshness_map_values(self) -> None:
        from search import FRESHNESS_MAP  # noqa: E402
        self.assertEqual(FRESHNESS_MAP["day"], "d")
        self.assertEqual(FRESHNESS_MAP["week"], "w")
        self.assertEqual(FRESHNESS_MAP["month"], "m")

    def test_freshness_added_to_ddg_html_url(self) -> None:
        """_try_ddg_html with freshness=day should include df=d in the URL."""
        import search as _s  # noqa: E402
        captured: list[str] = []
        original_get = _s._http_get

        def fake_get(url: str, **kwargs) -> bytes:
            captured.append(url)
            raise ConnectionError("offline")

        _s._http_get = fake_get
        try:
            _s._try_ddg_html("test query", timeout=1, retries=1, freshness="day")
        except SystemExit:
            pass
        except Exception:
            pass
        finally:
            _s._http_get = original_get

        self.assertTrue(any("df=d" in u for u in captured), f"df=d not found in: {captured}")

    def test_freshness_added_to_ddg_lite_post(self) -> None:
        """_try_ddg_lite with freshness=week should include df=w in POST data."""
        import search as _s  # noqa: E402
        captured_data: list[dict] = []
        original_post = _s._http_post

        def fake_post(url: str, data: dict, **kwargs) -> bytes:
            captured_data.append(data)
            raise ConnectionError("offline")

        _s._http_post = fake_post
        try:
            _s._try_ddg_lite("test query", timeout=1, retries=1, freshness="week")
        except Exception:
            pass
        finally:
            _s._http_post = original_post

        self.assertTrue(any(d.get("df") == "w" for d in captured_data), f"df=w not found in: {captured_data}")

    def test_searxng_used_as_fallback_when_ddg_empty(self) -> None:
        """When DDG returns empty results, SearXNG built-in fallback is called (always-on)."""
        import search as _s  # noqa: E402
        import search_tool as _st  # noqa: E402
        searxng_called: list[str] = []
        original_try = _s._try_searxng
        original_st_search = _st.search

        def fake_searxng(query, mirror, timeout, retries):
            searxng_called.append(mirror)
            return []

        _s._try_searxng = fake_searxng
        _st.search = lambda *a, **k: []
        original_get = _s._http_get
        original_post = _s._http_post

        def empty_get(url: str, **kwargs) -> bytes:
            # Return valid HTML with no results (empty, not throttled)
            return b"<html><body>No results found.</body></html>"

        def empty_post(url: str, data: dict, **kwargs) -> bytes:
            return b"<html><body>No results found.</body></html>"

        _s._http_get = empty_get
        _s._http_post = empty_post

        # Remove env override if present
        env_backup = os.environ.pop("BL_SEARXNG_MIRRORS", None)
        html_backup = os.environ.get("BL_ENABLE_DDG_HTML")
        os.environ["BL_ENABLE_DDG_HTML"] = "1"
        try:
            try:
                _s.search("test", max_results=1, timeout=1, retries=1)
            except SystemExit:
                pass
        finally:
            _s._try_searxng = original_try
            _st.search = original_st_search
            _s._http_get = original_get
            _s._http_post = original_post
            if env_backup is not None:
                os.environ["BL_SEARXNG_MIRRORS"] = env_backup
            elif "BL_SEARXNG_MIRRORS" in os.environ:
                os.environ.pop("BL_SEARXNG_MIRRORS")
            if html_backup is None:
                os.environ.pop("BL_ENABLE_DDG_HTML", None)
            else:
                os.environ["BL_ENABLE_DDG_HTML"] = html_backup

        self.assertGreater(len(searxng_called), 0, "SearXNG should be called as always-on fallback when DDG returns empty")

    def test_cli_freshness_arg(self) -> None:
        """CLI --freshness day arg is accepted without error (help text check)."""
        result = subprocess.run(
            [sys.executable, os.path.join(SEARCH_SKILL, "search.py"), "--help"],
            capture_output=True, text=True
        )
        self.assertIn("freshness", result.stdout)
        self.assertIn("day", result.stdout)


# ---------------------------------------------------------------------------
# build_platform_queue tests
# ---------------------------------------------------------------------------

PLATFORMS_SKILL = os.path.expanduser("~/.openclaw-backlink/workspace-bl-orchestrator/skills/platforms")


class PlatformQueueTests(unittest.TestCase):
    """Offline tests for build_platform_queue.py."""

    def setUp(self) -> None:
        sys.path.insert(0, PLATFORMS_SKILL)

    def test_queue_tier_order(self) -> None:
        from build_platform_queue import build_queue  # noqa: E402
        queue = build_queue("crypto wallets")
        tiers = [e["tier"] for e in queue]
        self.assertEqual(tiers, sorted(tiers), "Queue must be sorted by tier ascending")

    def test_reddit_is_first(self) -> None:
        from build_platform_queue import build_queue  # noqa: E402
        queue = build_queue("crypto wallets")
        self.assertEqual(queue[0]["domain"], "reddit.com")

    def test_tier1_has_high_weight(self) -> None:
        from build_platform_queue import build_queue  # noqa: E402
        queue = build_queue("crypto wallets")
        tier1 = [e for e in queue if e["tier"] == 1]
        for e in tier1:
            self.assertGreaterEqual(e["weight"], 0.9, f"{e['domain']} tier-1 weight should be >= 0.9")

    def test_niche_queries_contain_niche(self) -> None:
        from build_platform_queue import build_queue  # noqa: E402
        queue = build_queue("memecoin tracker")
        for entry in queue:
            has_niche = any("memecoin tracker" in q for q in entry["niche_queries"])
            self.assertTrue(has_niche, f"{entry['domain']} has no niche query with 'memecoin tracker'")

    def test_extra_platforms_appended_as_tier5(self) -> None:
        from build_platform_queue import build_queue  # noqa: E402
        # Use a niche-specific domain not in platforms.json
        queue = build_queue("crypto", extra=[("niche-crypto-forum.io", 0.65)])
        extra = [e for e in queue if e["domain"] == "niche-crypto-forum.io"]
        self.assertEqual(len(extra), 1)
        self.assertEqual(extra[0]["tier"], 5)
        self.assertEqual(extra[0]["weight"], 0.65)

    def test_cli_output_is_valid_json(self) -> None:
        result = subprocess.run(
            [sys.executable, os.path.join(PLATFORMS_SKILL, "build_platform_queue.py"), "--niche", "crypto"],
            capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)


# ---------------------------------------------------------------------------
# merge_discovery tests
# ---------------------------------------------------------------------------

PIPELINE = os.path.expanduser("~/.openclaw-backlink/workspace-bl-orchestrator/skills/pipeline")


@unittest.skip("Skipped: merge_discovery.py deleted in whitelist rebuild — replaced by merge_new_sites.py")
class MergeDiscoveryTests(unittest.TestCase):
    """Offline tests for merge_discovery.py."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="bl-merge-test-")

    def _write(self, name: str, data: dict) -> str:
        path = os.path.join(self.tmp, name)
        with open(path, "w") as f:
            json.dump(data, f)
        return path

    def _run_merge(self, finder_data: dict, comp_data: dict) -> tuple[subprocess.CompletedProcess, str]:
        finder_path = self._write("finder.json", finder_data)
        comp_path = self._write("comp.json", comp_data)
        out_path = os.path.join(self.tmp, "merged.json")
        result = subprocess.run(
            [sys.executable, f"{PIPELINE}/merge_discovery.py",
             "--finder", finder_path, "--competitor", comp_path, "--out", out_path],
            capture_output=True, text=True
        )
        return result, out_path

    def _make_site(self, url: str, domain: str = "reddit.com", sub_url: str | None = None) -> dict:
        return {
            "url": url,
            "domain": domain,
            "type": "qa_community",
            "submission_url": sub_url or url,
            "target_title": "Test post",
            "target_excerpt": "Some real text.",
            "opportunity_context": "Active thread.",
            "opportunity_freshness": "2026-06-09",
            "posting_action": "reply",
        }

    def test_merge_ok_combines_sites(self) -> None:
        site1 = self._make_site("https://reddit.com/r/crypto/comments/abc/thread1")
        site2 = self._make_site("https://reddit.com/r/crypto/comments/xyz/thread2")
        finder_data = {"status": "ok", "niche": "crypto", "project_url": "https://example.com", "sites": [site1]}
        comp_data = {"status": "ok", "niche": "crypto", "project_url": "https://example.com", "sites": [site2]}
        result, out_path = self._run_merge(finder_data, comp_data)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("MERGE_OK", result.stdout)
        with open(out_path) as f:
            merged = json.load(f)
        self.assertEqual(merged["status"], "ok")
        self.assertEqual(len(merged["sites"]), 2)

    def test_cross_source_url_dedup(self) -> None:
        """Same submission_url from both finder and competitor → only one survives."""
        shared_url = "https://reddit.com/r/crypto/comments/abc/thread1"
        site = self._make_site(shared_url)
        finder_data = {"status": "ok", "niche": "crypto", "project_url": "https://example.com", "sites": [site]}
        comp_data = {"status": "ok", "niche": "crypto", "project_url": "https://example.com", "sites": [site]}
        result, out_path = self._run_merge(finder_data, comp_data)
        self.assertEqual(result.returncode, 0)
        with open(out_path) as f:
            merged = json.load(f)
        self.assertEqual(len(merged["sites"]), 1, "Duplicate URL should be deduped across sources")

    def test_one_error_one_ok(self) -> None:
        """If finder errors but competitor has sites, merge succeeds."""
        site = self._make_site("https://reddit.com/r/crypto/comments/abc")
        finder_data = {"status": "error", "reason": "search_unavailable", "sites": []}
        comp_data = {"status": "ok", "niche": "crypto", "project_url": "https://example.com", "sites": [site]}
        result, out_path = self._run_merge(finder_data, comp_data)
        self.assertEqual(result.returncode, 0)
        with open(out_path) as f:
            merged = json.load(f)
        self.assertEqual(merged["status"], "ok")
        self.assertEqual(len(merged["sites"]), 1)

    def test_both_error_propagates(self) -> None:
        finder_data = {"status": "error", "reason": "search_unavailable", "sites": []}
        comp_data = {"status": "error", "reason": "search_unavailable", "sites": []}
        result, out_path = self._run_merge(finder_data, comp_data)
        self.assertEqual(result.returncode, 1)
        self.assertIn("MERGE_ERROR", result.stdout)
        with open(out_path) as f:
            merged = json.load(f)
        self.assertEqual(merged["status"], "error")


# ---------------------------------------------------------------------------
# URL-level dedup tests
# ---------------------------------------------------------------------------

@unittest.skip("Skipped: check_recent_sites.py deleted in whitelist rebuild — replaced by dedupe_opportunities.py using SQLite seen_opportunities table")
class UrlLevelDedupTests(unittest.TestCase):
    """Offline tests for check_recent_sites.py URL-level filtering."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="bl-dedup-test-")
        self.registry_path = os.path.join(self.tmp, "recent_sites.json")
        self.validated_path = os.path.join(self.tmp, "validated.json")

    def _write_validated(self, sites: list[dict]) -> None:
        data = {"status": "ok", "niche": "crypto", "project_url": "https://example.com", "sites": sites}
        with open(self.validated_path, "w") as f:
            json.dump(data, f)

    def _write_registry(self, entries: list[dict]) -> None:
        with open(self.registry_path, "w") as f:
            json.dump(entries, f)

    def _make_site(self, sub_url: str, domain: str = "reddit.com") -> dict:
        return {"url": sub_url, "submission_url": sub_url, "domain": domain, "type": "qa_community"}

    def _run_check(self, window: int = 30) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, f"{PIPELINE}/check_recent_sites.py",
             "--current", self.validated_path,
             "--registry", self.registry_path,
             "--window-days", str(window)],
            capture_output=True, text=True
        )

    def _fresh_ts(self) -> str:
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat()

    def test_same_domain_different_url_passes(self) -> None:
        """reddit.com seen before → only that exact URL blocked, other reddit URLs pass."""
        used_url = "https://reddit.com/r/crypto/comments/abc/thread1"
        fresh_url = "https://reddit.com/r/crypto/comments/xyz/thread2"
        self._write_registry([
            {"domain": "reddit.com", "url": used_url, "submission_url": used_url, "timestamp": self._fresh_ts()}
        ])
        self._write_validated([
            self._make_site(used_url),   # duplicate
            self._make_site(fresh_url),  # should survive
        ])
        result = self._run_check()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SITE_FRESH", result.stdout)
        with open(self.validated_path) as f:
            data = json.load(f)
        urls = [s["submission_url"] for s in data["sites"]]
        self.assertIn(fresh_url, urls, "Fresh URL should remain")
        self.assertNotIn(used_url, urls, "Used URL should be filtered")

    def test_all_duplicates_exits_1(self) -> None:
        """If ALL opportunities are duplicates, exit 1 + SITE_DUPLICATE."""
        url = "https://reddit.com/r/crypto/comments/abc/thread"
        self._write_registry([
            {"domain": "reddit.com", "submission_url": url, "url": url, "timestamp": self._fresh_ts()}
        ])
        self._write_validated([self._make_site(url)])
        result = self._run_check()
        self.assertEqual(result.returncode, 1)
        self.assertIn("SITE_DUPLICATE", result.stdout)

    def test_empty_registry_passes_all(self) -> None:
        """No registry = no duplicates = all pass."""
        self._write_registry([])
        self._write_validated([
            self._make_site("https://reddit.com/r/defi/comments/1"),
            self._make_site("https://reddit.com/r/defi/comments/2"),
        ])
        result = self._run_check()
        self.assertEqual(result.returncode, 0)
        self.assertIn("SITE_FRESH", result.stdout)
        with open(self.validated_path) as f:
            data = json.load(f)
        self.assertEqual(len(data["sites"]), 2)

    def test_old_registry_entries_ignored(self) -> None:
        """Entries older than window-days are ignored (not counted as duplicates)."""
        from datetime import datetime, timedelta, timezone
        old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
        url = "https://reddit.com/r/crypto/comments/old/thread"
        self._write_registry([
            {"domain": "reddit.com", "submission_url": url, "url": url, "timestamp": old_ts}
        ])
        self._write_validated([self._make_site(url)])
        result = self._run_check(window=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("SITE_FRESH", result.stdout)


# ---------------------------------------------------------------------------
# search.py throttle detection + rate-limit survival (all offline)
# ---------------------------------------------------------------------------

class SearchThrottleTests(unittest.TestCase):
    """Offline tests for DDG throttle detection and empty-is-not-retryable."""

    def setUp(self) -> None:
        sys.path.insert(0, SEARCH_SKILL)

    def test_throttle_detects_challenge_page(self) -> None:
        import search as _s
        challenge = b"<html><body>bots use duckduckgo too. Select all squares</body></html>"
        self.assertTrue(_s.is_ddg_throttled(challenge))

    def test_throttle_detects_empty_body(self) -> None:
        import search as _s
        self.assertTrue(_s.is_ddg_throttled(b""))
        self.assertTrue(_s.is_ddg_throttled(b"x" * 50))

    def test_throttle_false_on_normal_html(self) -> None:
        import search as _s
        normal = b"<html><body>" + b"some search results content here" * 30 + b"</body></html>"
        self.assertFalse(_s.is_ddg_throttled(normal))

    def test_builtin_searxng_mirrors_always_present(self) -> None:
        """Built-in SearXNG mirror list must be non-empty — it's the always-on fallback."""
        import search as _s
        self.assertGreater(len(_s._BUILTIN_SEARXNG_MIRRORS), 0)

    def test_empty_result_no_full_backoff(self) -> None:
        """HTTP-200-but-empty should return ([], False) after 1 attempt, not retry up to retries+1."""
        import search as _s
        call_count = [0]
        orig = _s._http_get

        def count_get(url: str, **kwargs) -> bytes:
            call_count[0] += 1
            # Valid HTML but no result__a links (empty results page)
            return b"<html><body><div>No results found.</div></body></html>" + b"x" * 200

        _s._http_get = count_get
        try:
            results, throttled = _s._try_ddg_html("test", timeout=1, retries=2)
            self.assertEqual(results, [])
            self.assertFalse(throttled)
            # Should NOT retry — advance immediately on empty
            self.assertEqual(call_count[0], 1, "Must not retry on empty (only 1 call expected)")
        finally:
            _s._http_get = orig

    def test_throttle_sets_flag_no_retry(self) -> None:
        """Throttle page returns ([], True) without looping."""
        import search as _s
        call_count = [0]
        orig = _s._http_get

        def throttle_get(url: str, **kwargs) -> bytes:
            call_count[0] += 1
            return b"<html><body>bots use duckduckgo too, select squares containing duck</body></html>"

        _s._http_get = throttle_get
        try:
            results, throttled = _s._try_ddg_html("test", timeout=1, retries=2, cooldown=0)
            self.assertEqual(results, [])
            self.assertTrue(throttled)
            self.assertEqual(call_count[0], 1, "Must not retry on throttle")
        finally:
            _s._http_get = orig

    def test_searxng_called_when_ddg_empty(self) -> None:
        """When DDG returns empty (not throttled), SearXNG built-in fallback is engaged."""
        import search as _s
        import search_tool as _st
        searxng_mirrors_called: list[str] = []
        orig_searxng = _s._try_searxng
        orig_get = _s._http_get
        orig_post = _s._http_post
        orig_st_search = _st.search

        def empty_get(url: str, **kwargs) -> bytes:
            return b"<html><body><div>No results here at all.</div></body></html>" + b"x" * 200

        def empty_post(url: str, data: dict, **kwargs) -> bytes:
            return b"<html><body><div>No results here at all.</div></body></html>" + b"x" * 200

        def spy_searxng(query, mirror, timeout, retries):
            searxng_mirrors_called.append(mirror)
            return []

        _st.search = lambda *a, **k: []
        _s._http_get = empty_get
        _s._http_post = empty_post
        _s._try_searxng = spy_searxng
        env_backup = os.environ.pop("BL_SEARXNG_MIRRORS", None)
        html_backup = os.environ.get("BL_ENABLE_DDG_HTML")
        os.environ["BL_ENABLE_DDG_HTML"] = "1"
        try:
            try:
                _s.search("test", max_results=1, timeout=1, retries=1)
            except SystemExit:
                pass
        finally:
            _s._http_get = orig_get
            _s._http_post = orig_post
            _s._try_searxng = orig_searxng
            _st.search = orig_st_search
            if env_backup is not None:
                os.environ["BL_SEARXNG_MIRRORS"] = env_backup
            elif "BL_SEARXNG_MIRRORS" in os.environ:
                os.environ.pop("BL_SEARXNG_MIRRORS")
            if html_backup is None:
                os.environ.pop("BL_ENABLE_DDG_HTML", None)
            else:
                os.environ["BL_ENABLE_DDG_HTML"] = html_backup

        self.assertGreater(len(searxng_mirrors_called), 0,
                           "SearXNG must be called as always-on fallback when DDG empty")

    def test_cache_key_differentiates_freshness(self) -> None:
        import search as _s
        self.assertNotEqual(_s._cache_key("q", None), _s._cache_key("q", "week"))
        self.assertEqual(_s._cache_key("q", "day"), _s._cache_key("q", "day"))

    def test_freshness_none_by_default_in_cli(self) -> None:
        """search.py CLI should accept no --freshness flag (default None)."""
        result = subprocess.run(
            [sys.executable, os.path.join(SEARCH_SKILL, "search.py"), "--help"],
            capture_output=True, text=True,
        )
        self.assertIn("freshness", result.stdout)
        # Default must say None or show no required freshness
        self.assertNotIn("required", result.stdout.lower().split("freshness")[1][:80])


# ---------------------------------------------------------------------------
# discover.py offline tests (all network isolated via monkey-patching)
# ---------------------------------------------------------------------------

DISCOVER_SKILL = os.path.expanduser("~/.openclaw-backlink/workspace-bl-orchestrator/skills/search")


class DiscoverRecencyTests(unittest.TestCase):
    """Pure offline tests for recency parsing and ranking logic in discover.py."""

    def setUp(self) -> None:
        sys.path.insert(0, DISCOVER_SKILL)

    def test_parse_days_ago(self) -> None:
        from discover import parse_recency_hours
        self.assertEqual(parse_recency_hours("posted 3 days ago"), 72.0)

    def test_parse_hours_ago(self) -> None:
        from discover import parse_recency_hours
        self.assertEqual(parse_recency_hours("2 hours ago"), 2.0)

    def test_parse_weeks_ago(self) -> None:
        from discover import parse_recency_hours
        self.assertEqual(parse_recency_hours("1 week ago"), 168.0)

    def test_parse_minutes_ago(self) -> None:
        from discover import parse_recency_hours
        result = parse_recency_hours("30 minutes ago")
        self.assertAlmostEqual(result, 30 / 60, places=4)

    def test_parse_returns_none_on_no_match(self) -> None:
        from discover import parse_recency_hours
        self.assertIsNone(parse_recency_hours("some unrelated text"))

    def test_recency_score_just_posted(self) -> None:
        from discover import recency_score
        self.assertEqual(recency_score(1.0), 1.0)

    def test_recency_score_today(self) -> None:
        from discover import recency_score
        self.assertEqual(recency_score(12.0), 0.9)

    def test_recency_score_this_week(self) -> None:
        from discover import recency_score
        score = recency_score(48.0)
        self.assertGreaterEqual(score, 0.7)
        self.assertLess(score, 1.0)

    def test_recency_score_unknown_is_neutral(self) -> None:
        from discover import recency_score
        self.assertEqual(recency_score(None), 0.5)

    def test_recency_score_old_is_low(self) -> None:
        from discover import recency_score
        self.assertLess(recency_score(8760.0), 0.3)

    def test_rank_score_fresh_discussion_beats_stale_directory(self) -> None:
        from discover import rank_score
        fresh = rank_score(0.95, 1.0, "forum")
        stale = rank_score(0.40, 0.2, "directory")
        self.assertGreater(fresh, stale)

    def test_rank_score_discussion_type_bonus(self) -> None:
        from discover import rank_score
        with_bonus = rank_score(0.7, 0.5, "forum")
        without = rank_score(0.7, 0.5, "guest_post")
        self.assertGreater(with_bonus, without)


class DiscoverBlockedDomainsTests(unittest.TestCase):
    def setUp(self) -> None:
        sys.path.insert(0, DISCOVER_SKILL)

    def test_reddit_in_blocked(self) -> None:
        from discover import BLOCKED_FETCH_DOMAINS, _is_blocked_domain
        self.assertIn("reddit.com", BLOCKED_FETCH_DOMAINS)
        self.assertTrue(_is_blocked_domain("https://reddit.com/r/crypto/comments/abc"))
        self.assertTrue(_is_blocked_domain("https://www.reddit.com/r/crypto"))

    def test_x_in_blocked(self) -> None:
        from discover import _is_blocked_domain
        self.assertTrue(_is_blocked_domain("https://x.com/some_thread"))
        self.assertTrue(_is_blocked_domain("https://twitter.com/status/123"))

    def test_medium_not_blocked(self) -> None:
        from discover import _is_blocked_domain
        self.assertFalse(_is_blocked_domain("https://medium.com/some-post"))


class DiscoverNetworkTests(unittest.TestCase):
    """All-network-mocked tests for discover.discover() logic."""

    def setUp(self) -> None:
        sys.path.insert(0, DISCOVER_SKILL)
        sys.path.insert(0, SEARCH_SKILL)

    def _simple_queue(self, domain: str = "reddit.com", tier: int = 1,
                      weight: float = 0.95, types: list | None = None) -> list[dict]:
        return [{
            "domain": domain,
            "tier": tier,
            "weight": weight,
            "types": types or ["forum"],
            "niche_queries": [f"site:{domain} test niche"],
        }]

    def _mock_discover(self, queue, niche, search_results_per_platform, *, all_live=True,
                       use_trafilatura=False):
        """Run discover() with fully mocked network (search + liveness)."""
        import discover as disc
        orig_search = disc.search
        orig_check = disc.check_urls_concurrent

        def mock_search(query, **kwargs):
            domain = queue[0]["domain"] if queue else "unknown"
            return {"status": "ok", "query": query, "freshness": None,
                    "results": search_results_per_platform}

        def mock_liveness(urls, **kwargs):
            return {u: all_live for u in urls}

        disc.search = mock_search
        disc.check_urls_concurrent = mock_liveness
        try:
            return disc.discover(queue, niche, target=20, use_trafilatura=use_trafilatura,
                                 check_liveness=True)
        finally:
            disc.search = orig_search
            disc.check_urls_concurrent = orig_check

    def test_snippet_used_as_target_title_and_excerpt(self) -> None:
        """target_title comes from search title; target_excerpt from snippet."""
        results = self._mock_discover(
            self._simple_queue(),
            "crypto",
            [{"title": "Best crypto wallets%s",
              "url": "https://reddit.com/r/crypto/comments/abc/wallets",
              "snippet": "Looking for a wallet that tracks meme coins", "source_engine": "ddg_html"}],
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["target_title"], "Best crypto wallets%s")
        self.assertIn("meme coins", results[0]["target_excerpt"])

    def test_cross_platform_url_dedupe(self) -> None:
        """Same URL from two platform searches → only one candidate survives."""
        import discover as disc
        shared_url = "https://reddit.com/r/crypto/comments/abc/thread"
        queue = [
            {"domain": "reddit.com", "tier": 1, "weight": 0.95, "types": ["forum"],
             "niche_queries": ["site:reddit.com test"]},
            {"domain": "x.com", "tier": 1, "weight": 0.95, "types": ["forum"],
             "niche_queries": ["site:x.com test"]},
        ]
        orig_search = disc.search
        orig_check = disc.check_urls_concurrent

        def mock_search(query, **kwargs):
            return {"status": "ok", "query": query, "freshness": None, "results": [
                {"title": "Thread", "url": shared_url,
                 "snippet": "active 2 hours ago", "source_engine": "ddg_html"},
            ]}

        disc.search = mock_search
        disc.check_urls_concurrent = lambda urls, **kw: {u: True for u in urls}
        try:
            candidates = disc.discover(queue, "test", target=20, use_trafilatura=False,
                                       check_liveness=True)
        finally:
            disc.search = orig_search
            disc.check_urls_concurrent = orig_check

        urls = [c["url"] for c in candidates]
        self.assertEqual(len(urls), len(set(urls)), "No duplicate URLs allowed")
        self.assertEqual(len(candidates), 1, "Shared URL must appear only once")

    def test_recency_ranking_fresher_first(self) -> None:
        """Fresher candidates rank above older ones at the same platform weight."""
        import discover as disc
        queue = self._simple_queue()
        orig_search = disc.search
        orig_check = disc.check_urls_concurrent

        def mock_search(query, **kwargs):
            return {"status": "ok", "query": query, "freshness": None, "results": [
                {"title": "Old thread", "url": "https://reddit.com/r/t/comments/old/old",
                 "snippet": "posted 30 days ago old discussion", "source_engine": "ddg_html"},
                {"title": "Hot thread", "url": "https://reddit.com/r/t/comments/new/new",
                 "snippet": "posted 1 hour ago really hot", "source_engine": "ddg_html"},
            ]}

        disc.search = mock_search
        disc.check_urls_concurrent = lambda urls, **kw: {u: True for u in urls}
        try:
            candidates = disc.discover(queue, "test", target=20, use_trafilatura=False)
        finally:
            disc.search = orig_search
            disc.check_urls_concurrent = orig_check

        self.assertGreaterEqual(len(candidates), 2)
        fresh_idx = next(i for i, c in enumerate(candidates) if "new" in c["url"])
        old_idx = next(i for i, c in enumerate(candidates) if "old" in c["url"])
        self.assertLess(fresh_idx, old_idx, "Fresher post must rank before older one")

    def test_fail_loud_when_all_dead(self) -> None:
        """If all candidates fail enrichment, exits with code 1."""
        import discover as disc
        queue = self._simple_queue()
        orig_search = disc.search

        disc.search = lambda q, **kw: {"status": "ok", "query": q, "freshness": None, "results": [
            {"title": "Post", "url": "https://example.com/dead-thread",
             "snippet": "some text", "source_engine": "ddg_html"},
        ]}
        import lead_enrich
        orig_verify = lead_enrich.verify_and_enrich
        lead_enrich.verify_and_enrich = lambda *a, **kw: (False, "", "")
        try:
            with self.assertRaises(SystemExit) as ctx:
                disc.discover(queue, "test", target=5, use_trafilatura=False, check_liveness=True)
            self.assertEqual(ctx.exception.code, 1)
        finally:
            disc.search = orig_search
            lead_enrich.verify_and_enrich = orig_verify

    def test_redirect_accepted_as_live(self) -> None:
        """mock_liveness returning True (simulating curl -L 301→200) keeps the candidate."""
        results = self._mock_discover(
            self._simple_queue(),
            "test",
            [{"title": "Thread", "url": "https://reddit.com/r/crypto/comments/abc/thread",
              "snippet": "good thread 2 days ago", "source_engine": "ddg_html"}],
            all_live=True,
        )
        self.assertEqual(len(results), 1)

    def test_bare_homepages_filtered(self) -> None:
        """URLs with no meaningful path are excluded."""
        import discover as disc
        queue = self._simple_queue()
        orig_search = disc.search
        orig_check = disc.check_urls_concurrent

        disc.search = lambda q, **kw: {"status": "ok", "query": q, "freshness": None, "results": [
            {"title": "Homepage", "url": "https://reddit.com",
             "snippet": "main page", "source_engine": "ddg_html"},
            {"title": "Deep thread", "url": "https://reddit.com/r/crypto/comments/abc/deep",
             "snippet": "real discussion 3 days ago", "source_engine": "ddg_html"},
        ]}
        disc.check_urls_concurrent = lambda urls, **kw: {u: True for u in urls}
        try:
            candidates = disc.discover(queue, "test", target=20, use_trafilatura=False)
        finally:
            disc.search = orig_search
            disc.check_urls_concurrent = orig_check

        urls = [c["url"] for c in candidates]
        self.assertNotIn("https://reddit.com", urls, "Bare homepage must be filtered")
        self.assertIn("https://reddit.com/r/crypto/comments/abc/deep", urls)


# ---------------------------------------------------------------------------
# build_platform_queue: discussion-bias + crypto forum presence
# ---------------------------------------------------------------------------

class PlatformQueueDiscussionTests(unittest.TestCase):
    """Tests for discussion-first platform ordering and crypto forum inclusion."""

    def setUp(self) -> None:
        sys.path.insert(0, PLATFORMS_SKILL)

    def test_bitcointalk_in_queue(self) -> None:
        from build_platform_queue import build_queue
        queue = build_queue("crypto")
        domains = {e["domain"] for e in queue}
        self.assertIn("bitcointalk.org", domains, "BitcoinTalk must be in built-in platform list")

    def test_bitcointalk_is_high_credibility_tier(self) -> None:
        from build_platform_queue import build_queue
        queue = build_queue("crypto")
        bt = next(e for e in queue if e["domain"] == "bitcointalk.org")
        self.assertLessEqual(bt["tier"], 2, "BitcoinTalk should be tier ≤2 (high credibility)")

    def test_hacker_news_in_queue(self) -> None:
        from build_platform_queue import build_queue
        queue = build_queue("crypto")
        domains = [e["domain"] for e in queue]
        self.assertIn("news.ycombinator.com", domains)

    def test_reddit_discussion_queries_include_opinions(self) -> None:
        from build_platform_queue import build_queue
        queue = build_queue("memecoin tracker")
        reddit = next(e for e in queue if e["domain"] == "reddit.com")
        all_queries = " ".join(reddit["niche_queries"])
        self.assertIn("opinions", all_queries)

    def test_reddit_discussion_queries_include_vs(self) -> None:
        from build_platform_queue import build_queue
        queue = build_queue("memecoin tracker")
        reddit = next(e for e in queue if e["domain"] == "reddit.com")
        all_queries = " ".join(reddit["niche_queries"])
        self.assertIn(" vs", all_queries)

    def test_reddit_discussion_queries_include_anyone_using(self) -> None:
        from build_platform_queue import build_queue
        queue = build_queue("memecoin tracker")
        reddit = next(e for e in queue if e["domain"] == "reddit.com")
        all_queries = " ".join(reddit["niche_queries"])
        self.assertIn("anyone using", all_queries)

    def test_directories_lower_tier_than_discussions(self) -> None:
        from build_platform_queue import build_queue
        queue = build_queue("crypto")
        reddit_tier = next(e["tier"] for e in queue if e["domain"] == "reddit.com")
        g2_tier = next(e["tier"] for e in queue if e["domain"] == "g2.com")
        self.assertLess(reddit_tier, g2_tier,
                        "Reddit (discussion) must have lower tier number than G2 (directory)")

    def test_no_freshness_key_in_queue_entries(self) -> None:
        """freshness removed from queue — discover.py handles recency ranking."""
        from build_platform_queue import build_queue
        queue = build_queue("crypto")
        for entry in queue:
            self.assertNotIn("freshness", entry,
                             f"{entry['domain']} must not carry freshness key (removed)")


class WhitelistDBTests(unittest.TestCase):
    """Tests for the new whitelist DB and pipeline scripts."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="bl-wl-test-")
        self.db = os.path.join(self.tmp, "test.db")
        sys.path.insert(0, PIPELINE)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ------------------------------------------------------------------
    # Schema migration test: existing opportunities rows survive new schema
    # ------------------------------------------------------------------

    def test_existing_opportunities_survive_new_schema(self) -> None:
        """Initialising whitelist_db on top of an existing backlink_db must not drop rows."""
        from backlink_db import init_db, insert_opportunity
        from whitelist_db import init_whitelist_db

        # Create legacy db with one opportunity row (no telegram fields = fake values)
        init_db(self.db)
        card = {
            "run_id": "run-1",
            "alert_id": "bl-run-1-example-com",
            "site_url": "https://example.com/thread/1",
            "telegram_group": "-123456",
            "telegram_message_id": 999,
        }
        opp_id = insert_opportunity(card, db_path=self.db)
        self.assertGreater(opp_id, 0)

        # Now initialise whitelist tables on the same DB
        init_whitelist_db(self.db)

        # Original row must still be there
        conn = sqlite3.connect(self.db)
        count = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1, "Opportunity row must survive schema extension")

    # ------------------------------------------------------------------
    # Whitelist seed + health check round-trip
    # ------------------------------------------------------------------

    def test_seed_and_health_round_trip(self) -> None:
        from seed_whitelist import seed
        from check_whitelist_health import main as health_main
        from whitelist_db import init_whitelist_db, upsert_project, count_active_sites

        init_whitelist_db(self.db)
        project_url = "https://test.example.com"
        niche = "test niche"
        seeded, _ = seed(project_url, niche, db_path=self.db)
        pid = upsert_project(project_url, niche, db_path=self.db)
        active = count_active_sites(pid, db_path=self.db)
        self.assertGreaterEqual(active, 5, "Seeding tiers 1-2 must produce >= 5 sites")
        self.assertGreater(seeded, 0)

    def test_empty_project_reports_empty(self) -> None:
        import io
        from contextlib import redirect_stdout
        from whitelist_db import init_whitelist_db, upsert_project
        init_whitelist_db(self.db)
        upsert_project("https://empty.example.com", "empty", db_path=self.db)

        result = subprocess.run(
            [sys.executable, os.path.join(PIPELINE, "check_whitelist_health.py"),
             "--project-url", "https://empty.example.com",
             "--niche", "empty",
             "--topup-days", "0",
             "--db", self.db],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("WHITELIST_EMPTY", result.stdout)

    def test_healthy_whitelist_skips_finder(self) -> None:
        from seed_whitelist import seed
        from whitelist_db import init_whitelist_db

        init_whitelist_db(self.db)
        seed("https://healthy.example.com", "test", db_path=self.db)

        result = subprocess.run(
            [sys.executable, os.path.join(PIPELINE, "check_whitelist_health.py"),
             "--project-url", "https://healthy.example.com",
             "--niche", "test",
             "--topup-days", "0",  # disable cadence so only count matters
             "--db", self.db],
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("WHITELIST_HEALTHY", result.stdout)

    # ------------------------------------------------------------------
    # Scoring determinism: same input → identical 0-100 scores
    # ------------------------------------------------------------------

    def test_scoring_is_deterministic(self) -> None:
        from score_opportunities import score_opportunity

        opp = {
            "platform_weight": 0.95,
            "relevance_score": 8,
            "opportunity_freshness": "~2 hours ago",
        }
        score1 = score_opportunity(opp, host_usability=75.0)
        score2 = score_opportunity(opp, host_usability=75.0)
        self.assertEqual(score1, score2, "Scoring must be deterministic")
        self.assertGreater(score1, 0)
        self.assertLessEqual(score1, 100)

    def test_score_clamp_to_100(self) -> None:
        from score_opportunities import score_opportunity

        opp = {
            "platform_weight": 1.0,
            "relevance_score": 10,
            "opportunity_freshness": "~1 hour ago",
        }
        score = score_opportunity(opp, host_usability=100.0)
        self.assertLessEqual(score, 100.0)
        self.assertGreaterEqual(score, 0.0)

    def test_score_clamp_to_0(self) -> None:
        from score_opportunities import score_opportunity

        opp = {
            "platform_weight": 0.0,
            "relevance_score": 0,
            "opportunity_freshness": "~3 years ago",
        }
        score = score_opportunity(opp, host_usability=0.0)
        self.assertGreaterEqual(score, 0.0)

    def test_fresh_beats_stale(self) -> None:
        from score_opportunities import score_opportunity

        fresh_opp = {"platform_weight": 0.8, "relevance_score": 7, "opportunity_freshness": "~1 hour ago"}
        stale_opp = {"platform_weight": 0.8, "relevance_score": 7, "opportunity_freshness": "~6 months ago"}
        fresh_score = score_opportunity(fresh_opp, host_usability=50.0)
        stale_score = score_opportunity(stale_opp, host_usability=50.0)
        self.assertGreater(fresh_score, stale_score)

    # ------------------------------------------------------------------
    # Eviction floor invariant: never drops below MIN_WHITELIST
    # ------------------------------------------------------------------

    def test_eviction_floor_never_exceeded(self) -> None:
        from whitelist_db import (
            init_whitelist_db, upsert_project, upsert_whitelist_site,
            append_score_history, count_active_sites, MIN_WHITELIST,
        )
        from evict_underperformers import evict

        init_whitelist_db(self.db)
        pid = upsert_project("https://floor-test.example.com", "test", db_path=self.db)

        # Add exactly MIN_WHITELIST sites
        for i in range(MIN_WHITELIST):
            wl_id = upsert_whitelist_site(pid, f"site{i}.com", db_path=self.db)
            # Give each site 5 underperforming snapshots so they're eligible
            for _ in range(5):
                append_score_history(wl_id, score_0_100=10.0, db_path=self.db)

        before = count_active_sites(pid, db_path=self.db)
        self.assertEqual(before, MIN_WHITELIST)

        evicted_count, protected_count = evict(
            "https://floor-test.example.com", db_path=self.db
        )

        after = count_active_sites(pid, db_path=self.db)
        self.assertEqual(after, MIN_WHITELIST,
                         "Floor must prevent eviction when active_count equals MIN_WHITELIST")
        self.assertEqual(evicted_count, 0)
        self.assertGreater(protected_count, 0)

    def test_cold_start_guard_prevents_early_eviction(self) -> None:
        """Sites with < 5 score snapshots must not be evicted."""
        from whitelist_db import (
            init_whitelist_db, upsert_project, upsert_whitelist_site,
            append_score_history, count_active_sites,
        )
        from evict_underperformers import evict

        init_whitelist_db(self.db)
        pid = upsert_project("https://cold-start.example.com", "test", db_path=self.db)

        # Add 10 sites, each with only 2 bad snapshots (below MIN_SNAPSHOTS=5)
        for i in range(10):
            wl_id = upsert_whitelist_site(pid, f"coldsite{i}.com", db_path=self.db)
            for _ in range(2):
                append_score_history(wl_id, score_0_100=5.0, db_path=self.db)

        evicted_count, _ = evict("https://cold-start.example.com", db_path=self.db)
        self.assertEqual(evicted_count, 0,
                         "Cold-start guard: sites with <5 snapshots must not be evicted")

    # ------------------------------------------------------------------
    # Sort + top-n cap
    # ------------------------------------------------------------------

    def test_sort_best_to_worst(self) -> None:
        from sort_opportunities import sort_and_cap

        scored_path = os.path.join(self.tmp, "scored.json")
        out_path = os.path.join(self.tmp, "queue.json")

        opps = [
            {"url": "https://a.com/1", "score_100": 45.0},
            {"url": "https://b.com/1", "score_100": 87.5},
            {"url": "https://c.com/1", "score_100": 12.0},
            {"url": "https://d.com/1", "score_100": 65.0},
        ]
        with open(scored_path, "w") as f:
            json.dump({"status": "ok", "opportunities": opps}, f)

        total, emitted = sort_and_cap(scored_path, out_path, top_n=10)
        self.assertEqual(total, 4)
        self.assertEqual(emitted, 4)

        with open(out_path) as f:
            result = json.load(f)
        scores = [o["score_100"] for o in result["opportunities"]]
        self.assertEqual(scores, sorted(scores, reverse=True), "Must be sorted best-to-worst")

    def test_sort_top_n_cap(self) -> None:
        from sort_opportunities import sort_and_cap

        scored_path = os.path.join(self.tmp, "scored2.json")
        out_path = os.path.join(self.tmp, "queue2.json")

        opps = [{"url": f"https://x.com/{i}", "score_100": float(i)} for i in range(50)]
        with open(scored_path, "w") as f:
            json.dump({"status": "ok", "opportunities": opps}, f)

        total, emitted = sort_and_cap(scored_path, out_path, top_n=10)
        self.assertEqual(total, 50)
        self.assertEqual(emitted, 10)

        with open(out_path) as f:
            result = json.load(f)
        self.assertEqual(len(result["opportunities"]), 10)
        # Top-n should have the highest scores
        self.assertEqual(result["opportunities"][0]["score_100"], 49.0)

    def test_sort_adds_rank_field(self) -> None:
        from sort_opportunities import sort_and_cap

        scored_path = os.path.join(self.tmp, "scored3.json")
        out_path = os.path.join(self.tmp, "queue3.json")
        opps = [{"url": "https://a.com/1", "score_100": 80.0}, {"url": "https://b.com/1", "score_100": 60.0}]
        with open(scored_path, "w") as f:
            json.dump({"opportunities": opps}, f)

        sort_and_cap(scored_path, out_path, top_n=5)
        with open(out_path) as f:
            result = json.load(f)
        ranks = [o["rank"] for o in result["opportunities"]]
        self.assertEqual(ranks, [1, 2])

    # ------------------------------------------------------------------
    # recent_sites.json migration idempotency
    # ------------------------------------------------------------------

    def test_migrate_recent_sites_idempotent(self) -> None:
        from migrate_recent_sites import migrate
        from whitelist_db import init_whitelist_db, count_active_sites, upsert_project

        recent_sites_path = os.path.join(self.tmp, "recent_sites.json")
        recent_sites = [
            {"domain": "coingabbar.com", "url": "https://www.coingabbar.com", "niche": "crypto"},
            {"domain": "cryptotalk.org", "url": "https://cryptotalk.org", "niche": "crypto"},
        ]
        with open(recent_sites_path, "w") as f:
            json.dump(recent_sites, f)

        init_whitelist_db(self.db)
        project_url = "https://migrate-test.example.com"
        niche = "crypto"
        pid = upsert_project(project_url, niche, db_path=self.db)

        processed1, inserted1, _ = migrate(project_url, niche, recent_sites_path, db_path=self.db)
        count1 = count_active_sites(pid, db_path=self.db)

        # Run again — must be idempotent
        processed2, inserted2, _ = migrate(project_url, niche, recent_sites_path, db_path=self.db)
        count2 = count_active_sites(pid, db_path=self.db)

        self.assertEqual(count1, count2, "Second migration must not add duplicate rows")
        self.assertEqual(inserted2, 0, "Second migration must insert 0 (all already present)")
        self.assertGreater(inserted1, 0, "First migration must insert at least one domain")

    def test_migrate_missing_file_is_noop(self) -> None:
        from migrate_recent_sites import migrate
        from whitelist_db import init_whitelist_db

        init_whitelist_db(self.db)
        processed, inserted, _ = migrate(
            "https://x.example.com", "test",
            os.path.join(self.tmp, "nonexistent.json"),
            db_path=self.db,
        )
        self.assertEqual(processed, 0)
        self.assertEqual(inserted, 0)

    # ------------------------------------------------------------------
    # dedupe_opportunities round-trip
    # ------------------------------------------------------------------

    def test_dedupe_filters_seen_urls(self) -> None:
        from dedupe_opportunities import dedupe
        from whitelist_db import init_whitelist_db

        init_whitelist_db(self.db)

        scan_path = os.path.join(self.tmp, "opps.json")
        deduped_path = os.path.join(self.tmp, "deduped.json")

        opps = [
            {"url": "https://reddit.com/r/crypto/comments/abc", "domain": "reddit.com"},
            {"url": "https://reddit.com/r/crypto/comments/def", "domain": "reddit.com"},
        ]
        with open(scan_path, "w") as f:
            json.dump({"opportunities": opps}, f)

        project_url = "https://dedup-test.example.com"
        niche = "crypto"

        # First dedup: both are new
        total, new, skipped = dedupe(scan_path, deduped_path, project_url, niche, db_path=self.db)
        self.assertEqual(new, 2)
        self.assertEqual(skipped, 0)

        # Second dedup: both already seen
        total2, new2, skipped2 = dedupe(scan_path, deduped_path, project_url, niche, db_path=self.db)
        self.assertEqual(new2, 0)
        self.assertEqual(skipped2, 2)

        self.assertEqual(skipped2, 2)


class SearchToolAdaptationTests(unittest.TestCase):
    """Offline tests for backlink search_tool blocklist modes."""

    def setUp(self) -> None:
        sys.path.insert(0, SEARCH_SKILL)

    def test_site_mode_keeps_reddit(self) -> None:
        from search_tool import _normalize_item, _skip_domains
        skip = _skip_domains("site")
        item = _normalize_item(
            {"href": "https://www.reddit.com/r/saas/comments/abc", "title": "t", "body": "s"},
            skip,
        )
        self.assertIsNotNone(item)
        self.assertIn("reddit.com", item["domain"])

    def test_open_mode_skips_reddit(self) -> None:
        from search_tool import _normalize_item, _skip_domains
        skip = _skip_domains("open")
        item = _normalize_item(
            {"href": "https://www.reddit.com/r/saas/comments/abc", "title": "t", "body": "s"},
            skip,
        )
        self.assertIsNone(item)

    def test_lead_enrich_trusts_reddit_snippet(self) -> None:
        from lead_enrich import verify_and_enrich
        ok, title, excerpt = verify_and_enrich(
            "https://reddit.com/r/test/comments/abc",
            "Help with SaaS",
            "Looking for advice on marketing",
        )
        self.assertTrue(ok)
        self.assertEqual(title, "Help with SaaS")


class ResetOpportunitiesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.db = os.path.join(self.tmp, "test.db")

    def test_purge_keeps_whitelist(self) -> None:
        from whitelist_db import init_whitelist_db, add_or_update_project, upsert_whitelist_site, count_active_sites
        import backlink_db as bdb

        init_whitelist_db(self.db)
        bdb.init_db(self.db)
        pid = add_or_update_project("https://x.com", "niche", db_path=self.db)
        upsert_whitelist_site(pid, "reddit.com", db_path=self.db)
        bdb.purge_editorial_data(db_path=self.db)
        from whitelist_db import purge_harvest_pipeline
        purge_harvest_pipeline(db_path=self.db)
        self.assertEqual(count_active_sites(pid, db_path=self.db), 1)


class OnboardBacklinkTests(unittest.TestCase):
    """Tests for offline /onboard engine (no network, no gateway restart)."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="bl-onboard-test-")
        self.db = os.path.join(self.tmp, "test.db")
        sys.path.insert(0, PIPELINE)
        self._prev_db = os.environ.get("BL_DB_PATH")
        os.environ["BL_DB_PATH"] = self.db

    def tearDown(self) -> None:
        import shutil
        if self._prev_db is None:
            os.environ.pop("BL_DB_PATH", None)
        else:
            os.environ["BL_DB_PATH"] = self._prev_db
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_onboard_session_round_trip(self) -> None:
        from whitelist_db import (
            init_whitelist_db,
            upsert_onboard_session,
            get_onboard_session,
            clear_onboard_session,
        )

        init_whitelist_db(self.db)
        upsert_onboard_session("123", "456", "group_id", answers_json='{"x":1}', db_path=self.db)
        session = get_onboard_session("123", "456", db_path=self.db)
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session.step, "group_id")
        self.assertEqual(json.loads(session.answers_json), {"x": 1})
        clear_onboard_session("123", "456", db_path=self.db)
        self.assertIsNone(get_onboard_session("123", "456", db_path=self.db))

    def test_normalize_project_url(self) -> None:
        from onboard_backlink import normalize_project_url, OnboardError

        self.assertEqual(normalize_project_url("example.com"), "https://example.com")
        self.assertEqual(normalize_project_url("https://www.Example.com/"), "https://example.com")
        with self.assertRaises(OnboardError):
            normalize_project_url("")

    def test_group_id_rejects_duplicate(self) -> None:
        from onboard_backlink import h_group_id, OnboardError
        from whitelist_db import init_whitelist_db, add_or_update_project, set_project_group

        init_whitelist_db(self.db)
        add_or_update_project("https://existing.com", "niche", "Existing", db_path=self.db)
        set_project_group("https://existing.com", "-100999888777", "Existing", db_path=self.db)

        with self.assertRaises(OnboardError):
            h_group_id({}, "-100999888777")
        answers: dict = {}
        h_group_id(answers, "-100111222333")
        self.assertEqual(answers["group_id"], "-100111222333")

    def test_project_url_rejects_duplicate(self) -> None:
        from onboard_backlink import h_project_url, OnboardError
        from whitelist_db import init_whitelist_db, add_or_update_project

        init_whitelist_db(self.db)
        add_or_update_project("https://taken.com", "niche", "Taken", db_path=self.db)
        with self.assertRaises(OnboardError):
            h_project_url({}, "https://taken.com")

    def test_finalize_mocked(self) -> None:
        from unittest.mock import patch
        from onboard_backlink import finalize

        answers = {
            "group_id": "-100111222333",
            "project_url": "https://newproj.com",
            "niche": "saas",
            "name": "NewProj",
            "description": "A SaaS tool for teams",
            "extra_domains": ["quora.com"],
        }
        with patch("onboard_backlink.run_manage_add", return_value=(True, "OK: added")) as mock_add, \
             patch("onboard_backlink.run_db_group_bind", return_value=(True, "OK: group scoped")) as mock_scope, \
             patch("onboard_backlink.verify_all_project_scopes", return_value=(True, ["OK: all"])):
            ok, summary = finalize(answers, apply_bind=False)
        self.assertTrue(ok)
        self.assertIn("OK: added", summary)
        self.assertIn("database", summary.lower())
        mock_add.assert_called_once()
        mock_scope.assert_called_once_with(answers, apply=False)

    def test_description_required_rejects_skip(self) -> None:
        from onboard_backlink import h_description, OnboardError

        with self.assertRaises(OnboardError):
            h_description({}, "skip")
        with self.assertRaises(OnboardError):
            h_description({}, "too short")
        answers: dict = {}
        h_description(answers, "A meaningful one-line description of the site.")
        self.assertEqual(answers["description"], "A meaningful one-line description of the site.")

    def test_parse_extra_domains(self) -> None:
        from onboard_backlink import parse_extra_domains, OnboardError

        self.assertEqual(parse_extra_domains("skip"), [])
        self.assertEqual(
            parse_extra_domains("quora.com, https://www.coindesk.com/path"),
            ["quora.com", "coindesk.com"],
        )
        self.assertEqual(parse_extra_domains("quora.com quora.com"), ["quora.com"])
        with self.assertRaises(OnboardError):
            parse_extra_domains("not-a-valid-domain")

    def test_h_extra_domains_skip(self) -> None:
        from onboard_backlink import h_extra_domains

        answers: dict = {}
        h_extra_domains(answers, "skip")
        self.assertEqual(answers["extra_domains"], [])

    def test_cmd_add_extra_domains(self) -> None:
        from unittest.mock import patch
        import manage_projects
        from manage_projects import cmd_add
        from whitelist_db import init_whitelist_db, get_active_whitelist, get_project
        import argparse

        init_whitelist_db(self.db)
        args = argparse.Namespace(
            project_url="https://extratest.com",
            niche="crypto",
            name="ExtraTest",
            description="A crypto news and analysis site for testing.",
            tone=None,
            keywords=None,
            anchor=None,
            subreddits=None,
            competitors=None,
            interval=30,
            no_seed=True,
            tiers="1,2",
            extra_domains="quora.com,medium.com",
            group_id=None,
            group_name=None,
            card_prefix=None,
            bind=False,
            apply=False,
        )
        with patch.object(manage_projects, "DB", self.db):
            rc = cmd_add(args)
        self.assertEqual(rc, 0)
        proj = get_project("https://extratest.com", db_path=self.db)
        assert proj is not None
        domains = {s["domain"] for s in get_active_whitelist(proj["id"], db_path=self.db)}
        self.assertEqual(domains, {"quora.com", "medium.com"})

    def test_cmd_step_no_session_fail_open(self) -> None:
        from unittest.mock import patch
        from onboard_backlink import cmd_step
        import argparse

        args = argparse.Namespace(
            chat_id="123", user_id="456", input="hi",
            reply_to_message_id="",
        )
        with patch("onboard_backlink.send_telegram_message") as mock_send:
            rc = cmd_step(args)
        self.assertEqual(rc, 1)
        mock_send.assert_not_called()


class ProjectTelegramScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="bl-scope-test-")
        self.db = os.path.join(self.tmp, "test.db")
        sys.path.insert(0, PIPELINE)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_parse_group_id_from_session_key(self) -> None:
        from project_telegram_scope import parse_group_id_from_session_key

        self.assertEqual(
            parse_group_id_from_session_key("agent:bl-orchestrator:telegram:group:-1004320744048"),
            "-1004320744048",
        )
        self.assertIsNone(parse_group_id_from_session_key("agent:bl-orchestrator:main"))

    def test_verify_project_group_scope_round_trip(self) -> None:
        from project_telegram_scope import verify_project_group_scope, verify_all_project_scopes
        from whitelist_db import init_whitelist_db, add_or_update_project, set_project_group

        init_whitelist_db(self.db)
        add_or_update_project("https://scope.test", "niche", "ScopeTest", db_path=self.db)
        set_project_group("https://scope.test", "-100999888777", "ScopeTest", db_path=self.db)
        ok, msg = verify_project_group_scope(
            "https://scope.test", "-100999888777", db_path=self.db,
        )
        self.assertTrue(ok, msg)
        all_ok, lines = verify_all_project_scopes(db_path=self.db)
        self.assertTrue(all_ok)
        self.assertTrue(any("scope.test" in line for line in lines))


if __name__ == "__main__":
    unittest.main(verbosity=2)
