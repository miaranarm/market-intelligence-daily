"""Régressions ciblées : fraîcheur et attribution des nouvelles aux instruments."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from src import enrichment


class NewsAttributionTests(unittest.TestCase):
    def test_ticker_substring_does_not_count_as_entity(self):
        mover = {"ticker": "CAT", "name": "Caterpillar"}
        item = {"title": "Education sector rises", "summary": "Enterprise software rises"}
        self.assertEqual(enrichment.relevance_score(item, mover), 0)

    def test_entity_and_direction_in_headline_are_strong_match(self):
        mover = {"ticker": "AVGO", "name": "Broadcom"}
        item = {"title": "Broadcom shares plunge after guidance", "summary": ""}
        self.assertGreaterEqual(enrichment.relevance_score(item, mover), 3)

    def test_entity_in_summary_and_direction_in_summary_is_not_headline_grade(self):
        mover = {"ticker": "AVGO", "name": "Broadcom"}
        item = {"title": "Chipmakers face a difficult week", "summary": "Broadcom shares fell after its guidance"}
        self.assertEqual(enrichment.relevance_score(item, mover), 2)

    def test_generic_market_headline_does_not_explain_specific_instrument(self):
        mover = {"ticker": "^GSPC", "name": "S&P 500"}
        item = {"title": "Global stocks fall as investors await data", "summary": "Markets were weaker."}
        self.assertEqual(enrichment.relevance_score(item, mover), 0)


class NewsFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)

    def test_recent_timestamp_is_accepted(self):
        self.assertTrue(enrichment.is_recent("Mon, 19 Oct 2026 09:00:00 GMT", now=self.now))

    def test_missing_or_unparseable_timestamp_is_rejected(self):
        self.assertFalse(enrichment.is_recent("", now=self.now))
        self.assertFalse(enrichment.is_recent("not-a-date", now=self.now))

    def test_old_news_is_rejected(self):
        self.assertFalse(enrichment.is_recent("Tue, 13 Oct 2026 09:00:00 GMT", now=self.now))

    def test_implausibly_future_news_is_rejected(self):
        self.assertFalse(enrichment.is_recent("Mon, 19 Oct 2026 18:00:00 GMT", now=self.now))


if __name__ == "__main__":
    unittest.main()
