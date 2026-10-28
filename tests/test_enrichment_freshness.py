import unittest
from datetime import datetime, timezone
from types import SimpleNamespace

from src.enrichment import freshness_note

from src.enrichment import is_recent


class MoverNewsFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)

    def test_recent_rss_date_is_accepted(self):
        self.assertTrue(is_recent("Mon, 19 Oct 2026 08:00:00 GMT", now=self.now))

    def test_recent_iso_date_is_accepted(self):
        self.assertTrue(is_recent("2026-10-19T08:00:00Z", now=self.now))

    def test_old_article_is_rejected(self):
        self.assertFalse(is_recent("Thu, 08 Oct 2026 08:00:00 GMT", now=self.now))

    def test_missing_or_unparseable_date_is_rejected(self):
        self.assertFalse(is_recent("", now=self.now))
        self.assertFalse(is_recent("date unavailable", now=self.now))
        self.assertFalse(is_recent("not-a-date", now=self.now))

    def test_implausibly_future_dated_article_is_rejected(self):
        self.assertFalse(is_recent("Mon, 19 Oct 2026 16:00:00 GMT", now=self.now))

    def test_small_future_skew_is_tolerated(self):
        self.assertTrue(is_recent("Mon, 19 Oct 2026 13:00:00 GMT", now=self.now))

    def test_market_report_flags_stale_instrument_even_when_all_dates_match(self):
        now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
        rows = [
            SimpleNamespace(ticker="OLD", name="Old instrument", data_timestamp="2026-10-19"),
            SimpleNamespace(ticker="OLD2", name="Another old instrument", data_timestamp="2026-10-19"),
        ]
        note = freshness_note(rows, now)
        self.assertIn("2 instrument(s)", note)
        self.assertIn("plus de 7 jours", note)
        self.assertIn("Old instrument", note)

    def test_market_report_flags_future_dated_prices(self):
        now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
        rows = [SimpleNamespace(ticker="FUT", name="Future instrument", data_timestamp="2026-10-31")]
        note = freshness_note(rows, now)
        self.assertIn("dans le futur", note)
        self.assertIn("Future instrument", note)

    def test_market_report_warns_when_market_dates_are_mixed(self):
        now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
        rows = [
            SimpleNamespace(ticker="A", name="A", data_timestamp="2026-10-27"),
            SimpleNamespace(ticker="B", name="B", data_timestamp="2026-10-28"),
        ]
        note = freshness_note(rows, now)
        self.assertIn("pas synchronisés", note)


if __name__ == "__main__":
    unittest.main()
