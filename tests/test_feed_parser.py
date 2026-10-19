import unittest

from src.enrichment import _parse_rss_items


class FeedParserTests(unittest.TestCase):
    def test_parses_rss_20_items_and_decodes_title_entities(self):
        xml = b"""<?xml version="1.0"?>
        <rss version="2.0"><channel><item>
          <title>Stocks rise &amp; bonds rally</title>
          <link>https://example.com/story</link>
          <pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate>
          <description>Markets &amp; investors react.</description>
        </item></channel></rss>"""
        items = _parse_rss_items(xml, "Example", "SPY")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Stocks rise & bonds rally")
        self.assertEqual(items[0]["url"], "https://example.com/story")
        self.assertEqual(items[0]["summary"], "Markets & investors react.")
        self.assertEqual(items[0]["published"], "Mon, 19 Oct 2026 08:00:00 GMT")

    def test_parses_namespaced_atom_entry_and_prefers_alternate_link(self):
        xml = b"""<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom"><entry>
          <title>Central bank signals a policy change</title>
          <link rel="self" href="https://example.com/api/story"/>
          <link rel="alternate" href="https://example.com/story"/>
          <updated>2026-10-19T08:00:00Z</updated>
          <summary>Investors reassess interest-rate expectations.</summary>
        </entry></feed>"""
        items = _parse_rss_items(xml, "Example Atom", "EURUSD")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.com/story")
        self.assertEqual(items[0]["published"], "2026-10-19T08:00:00Z")
        self.assertIn("interest-rate", items[0]["summary"])

    def test_rejects_non_http_article_links(self):
        xml = b"""<rss><channel><item>
          <title>Market story</title><link>javascript:alert(1)</link>
          <description>Some useful summary text.</description>
        </item></channel></rss>"""
        self.assertEqual(_parse_rss_items(xml, "Example", "SPY"), [])

    def test_limit_is_respected(self):
        xml = b"""<rss><channel>
          <item><title>First</title><link>https://example.com/1</link></item>
          <item><title>Second</title><link>https://example.com/2</link></item>
        </channel></rss>"""
        self.assertEqual(len(_parse_rss_items(xml, "Example", "SPY", limit=1)), 1)


if __name__ == "__main__":
    unittest.main()
