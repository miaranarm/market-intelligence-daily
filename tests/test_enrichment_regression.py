"""Regression tests for market-news enrichment and stale-data safeguards."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src import enrichment, market_report



class MarketReadthroughTests(unittest.TestCase):
    def test_crypto_story_is_not_misclassified_as_ai_infrastructure(self) -> None:
        item = {
            "title": "XRP Ledger lending feature prepares for launch",
            "summary": "Crypto funding changes as stablecoin and token lending activity expands.",
        }
        _, impact = market_report._news_fact_and_market_readthrough(item)
        self.assertIn("liquidations", impact)
        self.assertNotIn("centres de données", impact)


class NewsQualityTests(unittest.TestCase):
    def test_obvious_off_topic_story_is_rejected(self) -> None:
        item = {"title": "Smart glasses launch this week", "summary": "A new wearable device."}
        self.assertFalse(enrichment.is_market_relevant(item))

    def test_market_story_is_retained(self) -> None:
        item = {"title": "Central bank signals rate change", "summary": "Bond yields moved after the policy update."}
        self.assertTrue(enrichment.is_market_relevant(item))

    def test_title_only_story_has_no_substance(self) -> None:
        self.assertFalse(enrichment.has_substance({"title": "Markets fall", "summary": ""}))

    def test_story_with_useful_excerpt_has_substance(self) -> None:
        item = {"title": "Markets fall", "summary": "Investors repriced rate expectations after the central bank decision."}
        self.assertTrue(enrichment.has_substance(item))


class FreshnessTests(unittest.TestCase):
    def test_recent_story_is_current(self) -> None:
        now = datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc)
        published = (now - timedelta(hours=12)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        self.assertTrue(enrichment.is_recent(published, now=now))

    def test_old_story_is_rejected(self) -> None:
        now = datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc)
        published = (now - timedelta(days=8)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        self.assertFalse(enrichment.is_recent(published, now=now))

    def test_future_timestamp_within_clock_skew_is_tolerated(self) -> None:
        now = datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc)
        published = (now + timedelta(minutes=30)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        self.assertTrue(enrichment.is_recent(published, now=now))

    def test_future_timestamp_beyond_clock_skew_is_rejected(self) -> None:
        now = datetime(2026, 10, 19, 5, 0, tzinfo=timezone.utc)
        published = (now + timedelta(hours=8)).strftime("%a, %d %b %Y %H:%M:%S +0000")
        self.assertFalse(enrichment.is_recent(published, now=now))



class FeedParsingTests(unittest.TestCase):
    def test_rss_extracts_decoded_title_and_summary(self) -> None:
        xml = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title>Markets &amp; rates</title>
          <link>https://example.com/story</link>
          <description><![CDATA[<p>Inflation data moved bond yields.</p>]]></description>
          <pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate>
        </item></channel></rss>"""
        items = enrichment._parse_rss_items(xml, "Example", "TEST")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Markets & rates")
        self.assertEqual(items[0]["url"], "https://example.com/story")
        self.assertIn("Inflation data moved bond yields.", items[0]["summary"])

    def test_atom_prefers_alternate_link_over_self_link(self) -> None:
        xml = b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <title>Central bank decision</title>
          <link rel="self" href="https://example.com/api/story"/>
          <link rel="alternate" href="https://example.com/story"/>
          <summary>Rates remain unchanged.</summary>
          <updated>2026-10-19T08:00:00Z</updated>
        </entry></feed>"""
        items = enrichment._parse_rss_items(xml, "Example Atom", "RATE")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.com/story")
        self.assertEqual(items[0]["summary"], "Rates remain unchanged.")

    def test_non_http_links_are_ignored(self) -> None:
        xml = b"""<rss><channel><item><title>Broken link</title>
        <link>javascript:alert(1)</link></item></channel></rss>"""
        self.assertEqual(enrichment._parse_rss_items(xml, "Example", "TEST"), [])

if __name__ == "__main__":
    unittest.main()
