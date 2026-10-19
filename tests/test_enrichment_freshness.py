import unittest
from datetime import datetime, timezone

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


if __name__ == "__main__":
    unittest.main()
