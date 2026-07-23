#!/usr/bin/env python3
"""Unit tests for Farmer v2 discovery modules (no network)."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import ANY, patch

SEARCH = os.path.expanduser("~/.openclaw-backlink/workspace-bl-orchestrator/skills/search")
PIPELINE = os.path.expanduser("~/.openclaw-backlink/workspace-bl-orchestrator/skills/pipeline")
for p in (SEARCH, PIPELINE):
    if p not in sys.path:
        sys.path.insert(0, p)

from discover import clean_terms, niche_overlap_score  # noqa: E402
from query_expander import (  # noqa: E402
    expand_site_queries,
    expand_reddit_queries,
    expand_openweb_queries,
    expand_competitor_queries,
)
from x_filter import accept_x_url, is_x_thread_url  # noqa: E402
from score_opportunities import score_opportunity  # noqa: E402
import whitelist_db as wdb  # noqa: E402
import backlink_db as bdb  # noqa: E402


class CleanTermsTests(unittest.TestCase):
    def test_splits_comma_niche(self) -> None:
        terms = clean_terms("crypto,blockchain", ["web3"])
        self.assertIn("crypto", terms)
        self.assertIn("blockchain", terms)
        self.assertIn("web3", terms)

    def test_dedupes(self) -> None:
        terms = clean_terms("crypto", ["Crypto", "CRYPTO"])
        self.assertEqual(len(terms), 1)


class NicheOverlapTests(unittest.TestCase):
    def test_high_overlap(self) -> None:
        score = niche_overlap_score(
            "Best crypto wallets for beginners",
            "Discussion about bitcoin and blockchain security",
            ["crypto", "bitcoin", "blockchain"],
        )
        self.assertGreater(score, 6.0)

    def test_low_overlap(self) -> None:
        score = niche_overlap_score("Random cooking recipe", "Pasta tips", ["crypto"])
        self.assertLess(score, 4.0)


class QueryExpanderTests(unittest.TestCase):
    def test_site_queries_varied(self) -> None:
        qs = expand_site_queries("reddit.com", "crypto,blockchain", ["web3"], limit=6)
        self.assertGreaterEqual(len(qs), 3)
        self.assertTrue(all("site:reddit.com" in q for q in qs))

    def test_reddit_subreddit_queries(self) -> None:
        qs = expand_reddit_queries("saas", ["tools"], ["SaaS"], limit=4)
        self.assertTrue(any("/r/SaaS" in q for q in qs))

    def test_openweb_queries(self) -> None:
        qs = expand_openweb_queries("saas tools", limit=5)
        self.assertGreaterEqual(len(qs), 3)
        self.assertTrue(all("site:" not in q for q in qs))

    def test_competitor_queries(self) -> None:
        qs = expand_competitor_queries(["asana"], "saas", ["project management"], limit=4)
        self.assertTrue(any("asana" in q.lower() for q in qs))


class XFilterTests(unittest.TestCase):
    def test_accepts_status_url(self) -> None:
        url = "https://x.com/someuser/status/1234567890"
        self.assertTrue(is_x_thread_url(url))
        self.assertTrue(accept_x_url(url))

    def test_rejects_profile(self) -> None:
        url = "https://x.com/someuser"
        self.assertFalse(is_x_thread_url(url))
        self.assertFalse(accept_x_url(url))

    def test_non_x_passes(self) -> None:
        self.assertTrue(accept_x_url("https://reddit.com/r/test/comments/abc"))


class ScoreOpportunityTests(unittest.TestCase):
    def test_terms_change_score(self) -> None:
        opp = {
            "platform_weight": 0.9,
            "opportunity_freshness": "~2 hours ago",
            "target_title": "crypto bitcoin discussion",
            "target_excerpt": "blockchain web3",
        }
        high = score_opportunity(opp, 50.0, terms=["crypto", "bitcoin"])
        low = score_opportunity(
            {**opp, "target_title": "unrelated", "target_excerpt": "nothing"},
            50.0,
            terms=["crypto", "bitcoin"],
        )
        self.assertGreater(high, low)


class WhitelistPriorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name
        wdb.init_whitelist_db(self.db)
        self.pid = wdb.add_or_update_project(
            "https://test-priority.example.com", "saas", "Test", db_path=self.db,
        )
        wdb.upsert_whitelist_site(self.pid, "reddit.com", db_path=self.db)
        wdb.upsert_whitelist_site(self.pid, "x.com", db_path=self.db)

    def tearDown(self) -> None:
        os.unlink(self.db)

    def test_set_priority(self) -> None:
        ok = wdb.set_site_scan_priority(self.pid, "reddit.com", 95, db_path=self.db)
        self.assertTrue(ok)
        site = wdb.get_whitelist_site(self.pid, "reddit.com", db_path=self.db)
        self.assertEqual(site["scan_priority"], 95)

    def test_resolve_domain_alias(self) -> None:
        dom = wdb.resolve_whitelist_domain(self.pid, "reddit", db_path=self.db)
        self.assertEqual(dom, "reddit.com")

    def test_get_due_sites_orders_by_priority(self) -> None:
        wdb.set_project_sites_due_now(self.pid, db_path=self.db)
        wdb.set_site_scan_priority(self.pid, "reddit.com", 90, db_path=self.db)
        wdb.set_site_scan_priority(self.pid, "x.com", 10, db_path=self.db)
        due = wdb.get_due_sites(limit=2, db_path=self.db)
        self.assertGreaterEqual(len(due), 2)
        self.assertEqual(due[0]["domain"], "reddit.com")


class ScanPathTests(unittest.TestCase):

    def test_scan_subreddits_returns_lead(self) -> None:
        import reddit_scan  # noqa: E402

        fake_results = [{
            "url": "https://www.reddit.com/r/Bitcoin/comments/abc123/test_thread/",
            "title": "Best crypto wallet%s",
            "snippet": "Looking for bitcoin wallet recommendations 2 hours ago",
        }]

        def fake_search(query, max_results=10, mode="site"):
            return fake_results

        def fake_enrich(url, title, snippet, **kwargs):
            return True, title, snippet

        with patch.object(reddit_scan, "search", fake_search), patch.object(
            reddit_scan, "verify_and_enrich", fake_enrich,
        ):
            status, leads = reddit_scan.scan_subreddits(
                "crypto",
                subreddits=["Bitcoin"],
                keywords=["bitcoin"],
                max_results=5,
            )

        self.assertEqual(status, "ok")
        self.assertEqual(len(leads), 1)
        self.assertIn("/comments/", leads[0]["url"])
        self.assertIsNotNone(leads[0].get("relevance_score"))

    def test_scan_single_url_x_filters_profiles(self) -> None:
        import scan_tool  # noqa: E402
        from harvesters import generic_search as gs  # noqa: E402

        thread_url = "https://x.com/user/status/999888777"
        profile_url = "https://x.com/user"

        def fake_search(query, max_results=10, cache_path=None, raise_on_failure=False):
            return {
                "status": "ok",
                "results": [
                    {"url": thread_url, "title": "crypto thread", "snippet": "bitcoin discussion"},
                    {"url": profile_url, "title": "User (@user) / Posts / X", "snippet": "Posts"},
                ],
            }

        def fake_enrich(url, title, snippet, **kwargs):
            return True, title, snippet

        with patch.object(gs, "search", fake_search), patch.object(
            gs, "verify_and_enrich", fake_enrich,
        ), patch("query_planner.random.random", return_value=0.99):
            status, leads = scan_tool.scan_single_url(
                "x.com", "crypto",
                max_results=5,
                keywords=["bitcoin"],
            )

        self.assertEqual(status, "ok")
        urls = [l["url"] for l in leads]
        self.assertIn(thread_url, urls)
        self.assertNotIn(profile_url, urls)
        self.assertTrue(all("/status/" in u for u in urls))


class SearchToolNormalizeTests(unittest.TestCase):
    """Regression: malformed ddgs items must not crash search()."""

    def test_mixed_dict_and_string_items(self) -> None:
        import search_tool  # noqa: E402

        raw = [
            {"title": "Good hit", "href": "https://news.ycombinator.com/item%sid=1", "body": "snippet"},
            "malformed-string-item",
            {"title": "Another", "url": "https://news.ycombinator.com/item%sid=2", "snippet": "text"},
        ]

        with patch.object(search_tool, "_raw_search", return_value=raw):
            results = search_tool.search(
                "site:news.ycombinator.com crypto",
                max_results=10,
                mode="site",
            )

        self.assertEqual(len(results), 2)
        urls = {r["url"] for r in results}
        self.assertIn("https://news.ycombinator.com/item%sid=1", urls)
        self.assertIn("https://news.ycombinator.com/item%sid=2", urls)


class GateAgentPathTests(unittest.TestCase):
    def test_gate_leads_agent_path_applies_scores(self) -> None:
        import quality_gate as qg  # noqa: E402

        leads = [
            {"id": 1, "url": "https://reddit.com/a", "target_title": "crypto Q", "target_excerpt": "help"},
            {"id": 2, "url": "https://reddit.com/b", "target_title": "spam", "target_excerpt": "buy now"},
        ]

        def fake_invoke(run_dir, batch_path, result_path, **kwargs):
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump({
                    "status": "ok",
                    "scores": [
                        {"i": 0, "score": 8.0, "reason": "on-topic"},
                        {"i": 1, "score": 2.0, "reason": "spammy"},
                    ],
                }, f)
            return True

        with patch.object(qg, "_invoke_gate_agent", side_effect=fake_invoke):
            judged = qg.gate_leads(
                leads, niche="crypto", project_desc="charts", project_url="https://example.com",
                threshold=6.0, use_agent=True,
            )

        self.assertTrue(judged[0]["gate_passed"])
        self.assertFalse(judged[1]["gate_passed"])
        self.assertEqual(judged[0]["gate_score"], 8.0)


class GateAgentFallbackTests(unittest.TestCase):
    def test_gate_leads_falls_back_to_api(self) -> None:
        import quality_gate as qg  # noqa: E402

        leads = [{"id": 1, "url": "https://x.com/u/status/1", "target_title": "t", "target_excerpt": "e"}]

        with patch.object(qg, "_invoke_gate_agent", return_value=False), patch.object(
            qg, "_gate_via_api",
            return_value=[{**leads[0], "gate_score": 7.0, "gate_reason": "ok", "gate_passed": True}],
        ):
            judged = qg.gate_leads(leads, niche="crypto", use_agent=True)

        self.assertTrue(judged[0]["gate_passed"])
        self.assertEqual(judged[0]["gate_score"], 7.0)

    def test_gate_leads_fail_open_when_all_fail(self) -> None:
        import quality_gate as qg  # noqa: E402

        leads = [{"id": 1, "url": "https://example.com", "target_title": "t", "target_excerpt": "e"}]

        with patch.object(qg, "_invoke_gate_agent", return_value=False), patch.object(
            qg, "_gate_via_api", return_value=None,
        ):
            judged = qg.gate_leads(leads, niche="crypto", use_agent=True)

        self.assertTrue(judged[0]["gate_passed"])
        self.assertIn("gate_unavailable", judged[0]["gate_reason"])


class SendCardsCommandTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name
        wdb.init_whitelist_db(self.db)
        self.pid = wdb.add_or_update_project(
            "https://send-cards.example.com", "crypto", "Test", db_path=self.db,
        )
        wdb.insert_leads(self.pid, None, [{
            "url": "https://reddit.com/r/test/comments/abc",
            "url_key": "https://reddit.com/r/test/comments/abc",
            "domain": "reddit.com",
            "target_title": "crypto thread",
            "target_excerpt": "discussion",
            "type": "forum",
        }], db_path=self.db)
        lead = wdb.get_leads_by_status("NEW", project_id=self.pid, db_path=self.db)[0]
        wdb.update_lead(lead["id"], {"status": "GATED", "score_100": 80}, db_path=self.db)

    def tearDown(self) -> None:
        os.unlink(self.db)

    def test_send_cards_no_gated(self) -> None:
        import manage_projects as mp  # noqa: E402
        from harvest_draft import DraftResult  # noqa: E402

        wdb.update_lead(
            wdb.get_leads_by_status("GATED", project_id=self.pid, db_path=self.db)[0]["id"],
            {"status": "SENT"},
            db_path=self.db,
        )
        with patch.object(mp, "DB", self.db):
            code = mp.cmd_send_cards(argparse.Namespace(
                project_url="https://send-cards.example.com", count=5, gate_first=False,
            ))
        self.assertEqual(code, 0)

    def test_send_cards_drafts_when_gated(self) -> None:
        import manage_projects as mp  # noqa: E402
        from harvest_draft import DraftResult  # noqa: E402

        fake = DraftResult(sent=1, run_id="farm-1-test", urls=["https://reddit.com/r/test/comments/abc"])

        with patch.object(mp, "DB", self.db), patch.object(mp, "draft_and_send", return_value=fake):
            code = mp.cmd_send_cards(argparse.Namespace(
                project_url="https://send-cards.example.com", count=5, gate_first=False,
            ))
        self.assertEqual(code, 0)


class ResendPendingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name
        bdb.init_db(self.db)
        wdb.init_whitelist_db(self.db)
        self.project_url = "https://resend-test.example.com"
        wdb.add_or_update_project(self.project_url, "crypto", "Test", db_path=self.db)

    def tearDown(self) -> None:
        os.unlink(self.db)

    def _insert_pending(self, *, content_md: str = "Draft body", status: str = "pending", card_sent_at: str | None = None) -> bdb.Opportunity:
        card = {
            "run_id": "farm-1-test",
            "alert_id": "bl-farm-1-test-reddit-com",
            "project_url": self.project_url,
            "site_url": "https://reddit.com/r/test/comments/abc",
            "site_domain": "reddit.com",
            "content_md": content_md,
            "score_100": 87.5,
            "rank": 2,
            "telegram_group": "-100123",
            "telegram_message_id": 100,
            "card_sent_at": card_sent_at or bdb.now_sqlite(),
            "status": status,
        }
        bdb.insert_opportunity(card, db_path=self.db)
        return bdb.lookup_by_alert_id("bl-farm-1-test-reddit-com", db_path=self.db)

    def test_resolve_opportunity_content_prefers_content_md(self) -> None:
        opp = self._insert_pending(content_md="canonical draft")
        bdb.save_content_version(opp.id, "published_snapshot", "legacy snap", db_path=self.db)
        self.assertEqual(bdb.resolve_opportunity_content(opp, self.db), "canonical draft")

    def test_resolve_opportunity_content_legacy_snapshot(self) -> None:
        card = {
            "run_id": "farm-2",
            "alert_id": "bl-farm-2-empty",
            "project_url": self.project_url,
            "site_url": "https://example.com/thread",
            "site_domain": "example.com",
            "content_md": "",
            "telegram_group": "-100123",
            "telegram_message_id": 101,
            "card_sent_at": bdb.now_sqlite(),
        }
        bdb.insert_opportunity(card, db_path=self.db)
        opp = bdb.lookup_by_alert_id("bl-farm-2-empty", db_path=self.db)
        bdb.save_content_version(opp.id, "published_snapshot", "only snapshot", db_path=self.db)
        self.assertEqual(bdb.resolve_opportunity_content(opp, self.db), "only snapshot")

    def test_first_send_no_published_snapshot(self) -> None:
        card = {
            "run_id": "farm-3",
            "alert_id": "bl-farm-3-test",
            "project_url": self.project_url,
            "site_url": "https://example.com/a",
            "site_domain": "example.com",
            "content_md": "hello",
            "telegram_group": "-100123",
            "telegram_message_id": 102,
            "card_sent_at": bdb.now_sqlite(),
        }
        bdb.insert_opportunity(card, db_path=self.db)
        opp = bdb.lookup_by_alert_id("bl-farm-3-test", db_path=self.db)
        snap = bdb.get_latest_version(opp.id, "published_snapshot", db_path=self.db)
        self.assertIsNone(snap)

    def test_opportunity_to_card_preserves_score_and_rank(self) -> None:
        import build_and_send_card as bsc  # noqa: E402

        opp = self._insert_pending()
        card = bsc.opportunity_to_card(opp, content_md="draft text")
        self.assertEqual(card["score_100"], 87.5)
        self.assertEqual(card["rank"], 2)
        self.assertEqual(card["content_md"], "draft text")

    def test_resend_updates_same_row(self) -> None:
        from resend_pending import resend_one_opportunity  # noqa: E402
        import resend_pending as rp  # noqa: E402

        opp = self._insert_pending()
        with patch.object(rp, "send_card_dict", return_value=999), patch.object(rp, "load_bot_token", return_value="fake"):
            self.assertTrue(resend_one_opportunity(opp, db_path=self.db))
        updated = bdb.lookup_by_alert_id(opp.alert_id, db_path=self.db)
        self.assertEqual(updated.telegram_message_id, 999)
        with bdb._connect(self.db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0]
        self.assertEqual(count, 1)

    def test_resend_pending_excludes_approved(self) -> None:
        from resend_pending import resend_pending_cards  # noqa: E402
        import resend_pending as rp  # noqa: E402

        pending = self._insert_pending()
        approved_card = {
            "run_id": "farm-4",
            "alert_id": "bl-farm-4-approved",
            "project_url": self.project_url,
            "site_url": "https://example.com/b",
            "site_domain": "example.com",
            "content_md": "other",
            "telegram_group": "-100123",
            "telegram_message_id": 103,
            "card_sent_at": bdb.now_sqlite(),
            "status": "approved",
        }
        bdb.insert_opportunity(approved_card, db_path=self.db)
        with patch.object(rp, "send_card_dict", return_value=888), patch.object(rp, "load_bot_token", return_value="fake"):
            result = resend_pending_cards(self.project_url, count=5, db_path=self.db)
        self.assertEqual(result.sent, 1)
        self.assertEqual(result.alert_ids, [pending.alert_id])

    def test_stale_pending_sqlite_datetime(self) -> None:
        opp = self._insert_pending(card_sent_at="2020-01-01 00:00:00")
        stale = bdb.get_stale_pending_opportunities(24.0, project_url=self.project_url, db_path=self.db)
        self.assertEqual(len(stale), 1)
        self.assertEqual(stale[0].id, opp.id)

    def test_stale_pending_uses_ist_cutoff(self) -> None:
        import pipeline_tz as ptz  # noqa: E402

        recent = ptz.now_sqlite()
        opp = self._insert_pending(card_sent_at=recent)
        stale = bdb.get_stale_pending_opportunities(24.0, project_url=self.project_url, db_path=self.db)
        self.assertEqual(stale, [])
        self.assertEqual(opp.id, bdb.lookup_by_alert_id(opp.alert_id, db_path=self.db).id)

    def test_resend_pending_cli_no_pending(self) -> None:
        import manage_projects as mp  # noqa: E402

        with patch.object(mp, "DB", self.db):
            code = mp.cmd_resend_pending(argparse.Namespace(
                project_url=self.project_url, count=5,
            ))
        self.assertEqual(code, 0)


class PipelineLogTests(unittest.TestCase):
    def test_info_suppresses_verbose(self) -> None:
        import contextlib
        import pipeline_log as pl  # noqa: E402
        from io import StringIO

        pl.reset_level_for_tests("info")
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            pl.plog_verbose("scan", "search_query", query="site:example.com test")
        self.assertEqual(buf.getvalue(), "")

    def test_verbose_emits_stage_line(self) -> None:
        import contextlib
        import pipeline_log as pl  # noqa: E402
        from io import StringIO

        pl.reset_level_for_tests("verbose")
        buf = StringIO()
        with contextlib.redirect_stdout(buf):
            pl.plog_verbose("gate", "gate_lead", url="https://example.com", passed=True)
        out = buf.getvalue()
        self.assertIn("[gate|verbose]", out)
        self.assertIn("gate_lead", out)
        self.assertIn("passed=true", out)

    def test_truncate_and_format_fields(self) -> None:
        import pipeline_log as pl  # noqa: E402

        long = "x" * 200
        self.assertTrue(pl.truncate(long, 50).endswith("…"))
        self.assertIn("score=87.5", pl.format_fields(score=87.5, reason="ok"))

    def test_scan_logs_search_query_at_verbose(self) -> None:
        import contextlib
        import pipeline_log as pl  # noqa: E402
        import scan_tool as st  # noqa: E402
        from io import StringIO

        pl.reset_level_for_tests("verbose")
        buf = StringIO()
        fake_lead = {
            "url": "https://example.com/thread/1", "url_key": "example.com/thread/1",
            "target_title": "t", "target_excerpt": "s",
        }

        def _fake_harvest(domain, niche, **kwargs):
            pl.plog_verbose("scan", "search_query", query="site:example.com crypto", status="ok", raw=1)
            return "ok", [fake_lead], {}, {"site|crypto|plain": 1}

        with patch("harvester_registry.get_harvester", return_value=("generic_search", _fake_harvest)):
            with contextlib.redirect_stdout(buf):
                st.scan_single_url("example.com", "crypto", max_results=3)
        out = buf.getvalue()
        self.assertIn("[scan|verbose]", out)
        self.assertIn("search_query", out)

    def tearDown(self) -> None:
        import pipeline_log as pl  # noqa: E402

        pl.reset_level_for_tests("info")


class PipelineTzTests(unittest.TestCase):
    def test_now_sqlite_is_ist_offset_from_utc(self) -> None:
        import pipeline_tz as ptz  # noqa: E402
        from datetime import datetime, timezone

        utc = datetime.now(timezone.utc)
        ist_naive = datetime.strptime(ptz.now_sqlite(), ptz._SQLITE_FMT)
        utc_naive = utc.replace(tzinfo=None)
        delta = ist_naive - utc_naive
        self.assertGreaterEqual(delta.total_seconds(), 5 * 3600 + 29 * 60)
        self.assertLessEqual(delta.total_seconds(), 5 * 3600 + 31 * 60)

    def test_format_display_legacy_iso_utc_to_ist(self) -> None:
        import pipeline_tz as ptz  # noqa: E402

        out = ptz.format_display("2026-06-24T10:00:00+00:00")
        self.assertIn("IST", out)
        self.assertIn("Jun 2026", out)
        self.assertIn("3:30 PM", out)

    def test_format_utc_sqlite_display_converts_whitelist_times(self) -> None:
        import pipeline_tz as ptz  # noqa: E402

        out = ptz.format_utc_sqlite_display("2026-06-24 10:00:00")
        self.assertEqual(out, "2026-06-24 15:30:00 IST")

    def test_build_caption_footer_contains_ist(self) -> None:
        import build_and_send_card as bsc  # noqa: E402
        import pipeline_tz as ptz  # noqa: E402

        card = {
            "alert_id": "bl-test",
            "niche": "crypto",
            "project_url": "https://example.com",
            "site_domain": "reddit.com",
            "content_md": "draft",
            "card_sent_at": ptz.now_sqlite(),
        }
        caption = bsc.build_caption(card)
        self.assertIn("Sent:", caption)
        self.assertIn("IST", caption)


class TwoMessageCardTests(unittest.TestCase):
    def test_format_draft_plain_strips_markdown(self) -> None:
        import build_and_send_card as bsc  # noqa: E402

        raw = "**Bold point** and [Coinography](https://coinography.com)"
        plain = bsc.format_draft_plain(raw)
        self.assertNotIn("**", plain)
        self.assertIn("Bold point", plain)
        self.assertIn("Coinography — https://coinography.com", plain)

    def test_build_draft_message_includes_full_content(self) -> None:
        import build_and_send_card as bsc  # noqa: E402

        long_body = "- " + ("Growing focus on stablecoin infrastructure. " * 20)
        card = {
            "content_md": long_body,
            "backlink_url": "https://coinography.com",
            "backlink_anchor_text": "Coinography",
        }
        draft_msg = bsc.build_draft_message(card)
        self.assertIn("<pre>", draft_msg)
        self.assertIn("Growing focus on stablecoin infrastructure.", draft_msg)
        self.assertNotIn("Growing focu…", draft_msg)
        header = bsc.build_card_header(card)
        self.assertIn("see reply below", header)
        self.assertNotIn("Growing focus", header)

    def test_send_card_dict_sends_header_and_draft_back_to_back(self) -> None:
        import build_and_send_card as bsc  # noqa: E402

        card = {
            "run_id": "r1",
            "alert_id": "bl-r1-test",
            "content_md": "Full draft text for copy paste.",
            "site_domain": "example.com",
        }
        with patch.object(bsc, "send_telegram_card", return_value=42) as send_card, patch.object(
            bsc, "send_telegram_draft_reply", return_value=43
        ) as send_draft:
            msg_id = bsc.send_card_dict(card, token="tok", chat_id="-100")
        self.assertEqual(msg_id, 42)
        send_card.assert_called_once()
        send_draft.assert_called_once_with("tok", "-100", 42, ANY)
        draft_arg = send_draft.call_args[0][3]
        self.assertIn("Full draft text for copy paste.", draft_arg)


class FlywheelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        self.db = self.tmp.name
        wdb.init_whitelist_db(self.db)
        self.pid = wdb.upsert_project("https://flywheel.test", "crypto blockchain", db_path=self.db)
        self.site_id = wdb.upsert_whitelist_site(self.pid, "example.com", db_path=self.db)

    def tearDown(self) -> None:
        os.unlink(self.db)

    def test_harvest_cursor_roundtrip(self) -> None:
        wdb.set_harvest_cursor(self.site_id, {"pool_offset": 4, "after": "t3_x"}, db_path=self.db)
        cur = wdb.get_harvest_cursor(self.site_id, db_path=self.db)
        self.assertEqual(cur["pool_offset"], 4)
        self.assertEqual(cur["after"], "t3_x")

    def test_query_planner_rotates_keywords(self) -> None:
        from query_planner import plan_site_queries  # noqa: E402

        batch1, c1 = plan_site_queries(
            "example.com", "crypto", ["bitcoin", "web3"],
            batch_size=4, cursor={},
        )
        batch2, c2 = plan_site_queries(
            "example.com", "crypto", ["bitcoin", "web3"],
            batch_size=4, cursor=c1,
        )
        self.assertEqual(len(batch1), 4)
        self.assertNotEqual(c1.get("pool_offset"), c2.get("pool_offset"))
        tids = {t for t, _ in batch1 + batch2}
        self.assertTrue(any("bitcoin" in t or "web3" in t or "crypto" in t for t in tids))

    def test_bandit_prefers_high_yield_template(self) -> None:
        from query_planner import plan_site_queries  # noqa: E402

        stats = {"site|bitcoin|plain": {"runs": 10, "new_leads": 8}}
        with patch("query_planner.random.random", return_value=0.99):
            batch, _ = plan_site_queries(
                "example.com", "crypto", ["bitcoin", "web3"],
                stats=stats, batch_size=3, cursor={},
            )
        tids = [t for t, _ in batch]
        self.assertIn("site|bitcoin|plain", tids)

    def test_registry_routes_domains(self) -> None:
        from harvester_registry import get_harvester  # noqa: E402

        self.assertEqual(get_harvester("reddit.com")[0], "reddit_api")
        self.assertEqual(get_harvester("reddit.com/r/CryptoMarkets")[0], "reddit_api")
        self.assertEqual(get_harvester("reddit.com/r/web3")[0], "reddit_api")
        self.assertEqual(get_harvester("news.ycombinator.com")[0], "hn_algolia")
        self.assertEqual(get_harvester("example.com")[0], "generic_search")

    def test_subreddit_parsed_from_domain(self) -> None:
        from harvester_registry import _subreddit_from_domain  # noqa: E402

        self.assertEqual(_subreddit_from_domain("reddit.com/r/CryptoMarkets"), "cryptomarkets")
        self.assertEqual(_subreddit_from_domain("reddit.com/r/web3/extra"), "web3")
        self.assertIsNone(_subreddit_from_domain("reddit.com"))

    def test_generic_search_blocked_when_all_queries_fail(self) -> None:
        from harvesters import generic_search as gs  # noqa: E402

        with patch.object(gs, "search", return_value={"status": "error", "results": []}):
            with patch.object(gs, "plan_site_queries", return_value=([("t1", "site:example.com x")], {})):
                status, leads, _, _ = gs.harvest("example.com", "crypto", keywords=["x"])
        self.assertEqual(status, gs.STATUS_BLOCKED)
        self.assertEqual(leads, [])

    def test_rearm_respects_editorial_lock(self) -> None:
        key = "example.com/thread/locked"
        wdb.mark_seen_editorial(self.pid, key, db_path=self.db)
        with wdb._connect(self.db) as conn:
            conn.execute(
                """
                INSERT INTO harvest_leads (project_id, whitelist_site_id, url, url_key, domain, status)
                VALUES (%s, %s, %s, %s, 'example.com', 'SENT')
                """,
                (self.pid, self.site_id, f"https://{key}", key),
            )
            conn.commit()
        self.assertFalse(wdb.revive_lead(self.pid, key, db_path=self.db))

    def test_rearm_revives_eligible_lead(self) -> None:
        key = "example.com/thread/old"
        with wdb._connect(self.db) as conn:
            conn.execute(
                """
                INSERT INTO harvest_leads (project_id, whitelist_site_id, url, url_key, domain, status)
                VALUES (%s, %s, %s, %s, 'example.com', 'SENT')
                """,
                (self.pid, self.site_id, f"https://{key}", key),
            )
            conn.execute(
                """
                INSERT INTO seen_opportunities (project_id, url_key, first_seen_at, editorial_locked)
                VALUES (%s, %s, NOW() AT TIME ZONE 'UTC' + INTERVAL '-30 days', 0)
                """,
                (self.pid, key),
            )
            conn.commit()
        self.assertTrue(wdb.revive_lead(self.pid, key, db_path=self.db))
        leads = wdb.get_leads_by_status("NEW", project_id=self.pid, db_path=self.db)
        self.assertEqual(len(leads), 1)

    def test_vocab_terms_upsert(self) -> None:
        n = wdb.upsert_vocab_terms(
            self.pid, [("defi yield", 12.0, "test"), ("defi yield", 20.0, "test2")], db_path=self.db,
        )
        self.assertEqual(n, 2)
        terms = wdb.get_vocab_terms(self.pid, db_path=self.db)
        self.assertIn("defi yield", terms)

    def test_query_stats_record(self) -> None:
        wdb.record_query_stats(self.pid, "example.com", {"site|crypto|plain": 2}, db_path=self.db)
        stats = wdb.get_query_stats(self.pid, "example.com", db_path=self.db)
        self.assertEqual(stats["site|crypto|plain"]["new_leads"], 2)

    def test_combinatorial_pool_covers_modifiers(self) -> None:
        from query_expander import build_site_template_pool  # noqa: E402

        pool = build_site_template_pool("example.com", ["crypto"])
        tids = {t for t, _ in pool}
        self.assertIn("site|crypto|discussion", tids)
        self.assertIn("site|crypto|plain", tids)


if __name__ == "__main__":
    unittest.main()
