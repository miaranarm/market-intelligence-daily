"""Regression tests for market-news enrichment and stale-data safeguards."""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from src import enrichment


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


if __name__ == "__main__":
    unittest.main()
