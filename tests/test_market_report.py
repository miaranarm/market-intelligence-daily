import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from zoneinfo import ZoneInfo

from src.market_report import ASSETS, AssetRow, NEWS_FEEDS, FRED_SERIES, _parse_fred_csv, _fetch_one_fred_series, fetch_fred_macro_series, fetch_bls_macro_fallback, fetch_macro_series_with_fallback, append_macro_series, _news_dedupe_key, _feed_entries, _is_recent_news_item, _summarize_news_text, _enrich_news_item, _is_google_news_url, prioritize_news, append_priority_news, _price_freshness_note, _quarterly_fact_points, _quarterly_or_q4_fact_points, evaluate_forecasts, infer_macro_impact, market_conviction, evaluate_scenario_forecasts, render_professional_html, report_archive_filename, fmt, send_email




class ReportArchiveLinkTests(unittest.TestCase):
    def test_archive_filename_is_stable_and_separates_report_types(self):
        timestamp = "2026-10-17T09:59:02+03:00"
        self.assertEqual(report_archive_filename("morning", timestamp), "morning-20261017-095902.html")
        self.assertEqual(report_archive_filename("update", timestamp), "update-20261017-095902.html")


class EmailReportBodyTests(unittest.TestCase):
    @patch.dict("os.environ", {
        "SMTP_USERNAME": "sender@example.com",
        "SMTP_APP_PASSWORD": "test-app-password",
        "REPORT_RECIPIENT": "reader@example.com",
    })
    @patch("src.market_report.smtplib.SMTP")
    def test_email_contains_full_report_and_archive_link(self, smtp_mock):
        smtp = smtp_mock.return_value.__enter__.return_value
        report_text = (
            "RAPPORT MULTI-ACTIFS — 05:30\n"
            "ACTUALITÉS PRIORITAIRES\n"
            "Brent : hausse de 3,2 %; source : https://publisher.example/oil-story"
        )
        archive_url = "https://miaranarm.github.io/market-intelligence-daily/reports/morning-test.html"

        send_email("[Market Intelligence] MORNING", archive_url, report_text)

        smtp.login.assert_called_once_with("sender@example.com", "test-app-password")
        message = smtp.send_message.call_args.args[0]
        self.assertEqual(message["To"], "reader@example.com")
        self.assertIn(report_text, message.get_body(preferencelist=("plain",)).get_content())
        html_body = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("ACTUALITÉS PRIORITAIRES", html_body)
        self.assertIn(archive_url, html_body)
        self.assertIn("publisher.example/oil-story", html_body)



class PriorityNewsTests(unittest.TestCase):
    def test_prioritizes_market_moving_news_and_keeps_source_details(self):
        news = [
            {"title": "Local community event", "source": "Google News", "published": "2026-10-17T04:00:00Z", "url": "https://example.com/local"},
            {"title": "Federal Reserve signals interest rate decision after inflation data", "source": "Federal Reserve", "published": "2026-10-16T12:00:00Z", "url": "https://example.com/fed"},
            {"title": "Company earnings and guidance disappoint investors", "source": "Financial Times", "published": "2026-10-16T10:00:00Z", "url": "https://example.com/earnings"},
        ]
        selected = prioritize_news(news, 2)
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected[0]["url"], "https://example.com/fed")
        self.assertIn("source", selected[0])
        self.assertIn("published", selected[0])



class PriorityNewsRenderingTests(unittest.TestCase):
    def test_report_starts_news_with_excerpt_source_and_analysis(self):
        lines = []
        news = [{
            "title": "Federal Reserve holds rates after inflation update",
            "source": "Federal Reserve",
            "published": "2026-10-16T18:00:00Z",
            "summary": "The committee maintained the target range after reviewing inflation and activity. Officials said future decisions would depend on incoming data, while markets continued to assess the timing of any policy easing.",
            "url": "https://example.org/fed-release",
        }]
        append_priority_news(lines, news)
        rendered = "\n".join(lines)
        self.assertLess(rendered.index("LES ACTUALITÉS QUI COMPTENT"), rendered.index("1. Federal Reserve holds rates"))
        self.assertIn("The committee maintained the target range", rendered)
        self.assertIn("https://example.org/fed-release", rendered)
        self.assertIn("POUR LES MARCHÉS :", rendered)

    @patch("src.market_report._enrich_news_item", side_effect=lambda item: item)
    def test_excludes_aggregator_links_but_keeps_direct_headline_only_items(self, _enrich):
        news = [
            {
                "title": "Bitcoin ETF rules announced",
                "source": "Google News",
                "published": "2026-10-17T04:00:00Z",
                "summary": "Regulators announced a new framework for exchange-traded products tied to digital assets, with implementation details to be confirmed by the exchange.",
                "url": "https://news.google.com/rss/articles/example",
            },
            {
                "title": "Central bank publishes policy statement",
                "source": "Publisher",
                "published": "2026-10-17T04:00:00Z",
                "summary": "",
                "url": "https://publisher.example/policy-statement",
            },
            {
                "title": "Oil prices rise after supply disruption",
                "source": "Publisher",
                "published": "2026-10-17T04:00:00Z",
                "summary": "Oil futures rose after the producer group reported an unexpected interruption to supply. The report described the affected output and said traders were monitoring how long the disruption might last.",
                "url": "https://publisher.example/oil-supply-disruption",
            },
            {
                "title": "Global stocks slide as inflation surprises investors",
                "source": "Investment Week",
                "published": "2026-10-17T03:00:00Z",
                "summary": "Global stocks declined after the latest inflation data came in above expectations. Technology shares led losses, while investors reassessed the outlook for interest rates and bond yields.",
                "url": "https://news.google.com/rss/articles/publisher-story?oc=5",
            },
            {
                "title": "Banknote imagery advisory group minutes – 15 July 2026",
                "source": "Bank of England",
                "published": "2026-10-16T11:00:00Z",
                "summary": "Members considered the proposed animals and their habitats for future banknote imagery and discussed design features to support authentication.",
                "url": "https://www.bankofengland.co.uk/minutes/2026/july/banknote-advisory-minutes-15-july",
            },
        ]
        lines = []
        append_priority_news(lines, news)
        rendered = "\n".join(lines)
        self.assertIn("Oil prices rise after supply disruption", rendered)
        self.assertIn("Global stocks slide as inflation surprises investors", rendered)
        self.assertIn("https://news.google.com/rss/articles/publisher-story?oc=5", rendered)
        self.assertNotIn("Bitcoin ETF rules announced", rendered)
        self.assertIn("Central bank publishes policy statement", rendered)
        self.assertNotIn("Banknote imagery advisory group minutes", rendered)
        self.assertIn("résumé détaillé de l’éditeur n’a pas pu être vérifié", rendered)



class NewsFeedSummaryTests(unittest.TestCase):
    def test_google_news_url_is_detected_until_resolved_to_publisher(self):
        self.assertTrue(_is_google_news_url("https://news.google.com/rss/articles/example"))
        self.assertTrue(_is_google_news_url("https://news.google.com"))
        self.assertFalse(_is_google_news_url("https://www.reuters.com/world/markets/story"))
        self.assertFalse(_is_google_news_url("https://www.cnbc.com/2026/10/17/story.html"))

    def test_extractive_summary_prioritizes_concrete_facts_and_skips_boilerplate(self):
        source = (
            "The central bank said it will publish further information in due course. "
            "Consumer prices rose 3.2 percent in September, above the 2.8 percent forecast, "
            "according to the official release. Investors pushed the 10-year Treasury yield "
            "up 12 basis points after the data was released."
        )
        summary = _summarize_news_text(source, max_chars=500)
        self.assertIn("3.2 percent", summary)
        self.assertIn("2.8 percent forecast", summary)
        self.assertIn("12 basis points", summary)
        self.assertLessEqual(len(summary), 500)

    def test_extractive_summary_drops_publisher_navigation_chrome(self):
        source = (
            "The administration extended the waiver through April 2027 to ease a diesel supply shortage. "
            "Livestream Menu Make It select USA INTL Livestream Search quotes, news & videos "
            "Livestream Watchlist SIGN IN Create free account."
        )
        summary = _summarize_news_text(source, max_chars=500)
        self.assertIn("April 2027", summary)
        self.assertNotIn("Livestream", summary)
        self.assertNotIn("Watchlist", summary)
        self.assertNotIn("Create free account", summary)

    @patch("src.market_report.requests.get")
    def test_enrichment_rejects_page_text_missing_distinctive_headline_entity(self, get_mock):
        class FakeResponse:
            url = "https://publisher.example/xrp-lending"
            text = (
                "<html><body>"
                "<meta property='og:description' content='GENIUS Act stablecoin issuers may offer "
                "off-chain yields through tokenized real-world assets, according to market participants.'>"
                "<p>GENIUS Act stablecoin issuers may offer off-chain yields through tokenized "
                "real-world assets, according to market participants and analysts.</p>"
                "</body></html>"
            )
            def raise_for_status(self):
                return None
        get_mock.return_value = FakeResponse()
        item = {
            "title": "XRP Ledger is set to fix its lending code before anyone can use it",
            "url": "https://publisher.example/xrp-lending",
            "published": "2026-10-19T04:00:00Z",
            "source": "CoinDesk",
            "summary": "",
        }
        result = _enrich_news_item(item)
        self.assertEqual(result["summary"], "")

    @patch("src.market_report.requests.get")
    def test_enrichment_extracts_factual_publisher_paragraphs(self, get_mock):
        class FakeResponse:
            url = "https://publisher.example/article"
            text = (
                "<html><head><title>Market story</title></head><body>"
                "<p>Consumer prices rose 3.2 percent in September, above economists' "
                "forecast of 2.8 percent, the government reported on Friday.</p>"
                "<p>The 10-year Treasury yield climbed 12 basis points as traders "
                "reassessed the expected path of interest rates.</p>"
                "</body></html>"
            )
            def raise_for_status(self):
                return None
        get_mock.return_value = FakeResponse()
        item = {
            "title": "Inflation surprises markets",
            "url": "https://publisher.example/article",
            "published": "2026-10-17T05:00:00Z",
            "source": "Publisher",
            "summary": "",
        }
        result = _enrich_news_item(item)
        self.assertIn("3.2 percent", result["summary"])
        self.assertIn("12 basis points", result["summary"])
        self.assertEqual(result["url"], "https://publisher.example/article")

    def test_rss_excerpt_html_and_whitespace_are_normalized(self):
        xml = ET.fromstring(
            "<rss><channel><item><title>Market update</title>"
            "<link>https://example.org/story</link>"
            "<description><![CDATA[<p>First line\n  second line</p>]]></description>"
            "</item></channel></rss>"
        )
        entries = _feed_entries(xml, "Test feed")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["summary"], "First line second line")


class AssetUniverseTests(unittest.TestCase):
    def test_fx_watchlist_covers_major_currency_pairs(self):
        expected = {
            "EURUSD=X", "USDJPY=X", "GBPUSD=X", "AUDUSD=X",
            "NZDUSD=X", "USDCAD=X", "USDCHF=X", "USDCNY=X",
            "USDINR=X", "EURGBP=X",
        }
        self.assertTrue(expected.issubset(ASSETS))
        self.assertTrue(all(ASSETS[ticker]["class"] == "FX" for ticker in expected))

    def test_global_indices_and_diversifying_instruments_are_in_watchlist(self):
        expected = {
            "^GDAXI", "^FCHI", "^AXJO", "^KS11", "^NSEI", "^GSPTSE",
            "ZC=F", "ZW=F", "ZS=F", "KC=F", "SOL-USD", "XRP-USD",
            "VEA", "VWO", "XLK", "XLE", "AGG",
        }
        self.assertTrue(expected.issubset(ASSETS))
        self.assertEqual(ASSETS["^GDAXI"]["class"], "German equity index")
        self.assertEqual(ASSETS["ZW=F"]["class"], "Agricultural commodity")
        self.assertEqual(ASSETS["AGG"]["class"], "Bond ETF")


class PublicScenarioDisplayTests(unittest.TestCase):
    def test_report_does_not_publish_uncalibrated_heuristic_as_probabilities(self):
        import src.market_report as report_module
        lines = []
        report_module.append_funnel_report(
            lines, "morning", [], [], [], None, None, [], [], []
        )
        rendered = "\\n".join(lines)
        self.assertNotIn("Probabilités directionnelles expérimentales", rendered)
        self.assertNotIn("hausse 30 %", rendered)
        self.assertIn("Les pourcentages de probabilité ne sont pas publiés", rendered)


class PriceFormattingTests(unittest.TestCase):
    def test_raw_prices_are_unsigned_but_percentage_changes_keep_sign(self):
        self.assertEqual(fmt(19.99), "19.99")
        self.assertEqual(fmt(19.99, "%"), "+19.99%")
        self.assertEqual(fmt(-2.5, "%"), "-2.50%")


class PriceFreshnessTests(unittest.TestCase):
    def test_recent_quote_has_no_warning(self):
        self.assertEqual(_price_freshness_note("2026-10-16", today=__import__("datetime").date(2026, 10, 16)), "")

    def test_old_quote_is_flagged(self):
        self.assertIn("ATTENTION", _price_freshness_note("2026-10-01", today=__import__("datetime").date(2026, 10, 16)))

    def test_future_quote_is_flagged(self):
        self.assertIn("futur", _price_freshness_note("2026-10-20", today=__import__("datetime").date(2026, 10, 16)))

    def test_missing_quote_date_is_flagged(self):
        self.assertIn("indisponible", _price_freshness_note(None))



class FredMacroSeriesTests(unittest.TestCase):
    def test_fred_csv_parser_uses_latest_non_missing_observation(self):
        csv_text = (
            "observation_date,CPIAUCSL,UNRATE,PAYEMS,FEDFUNDS,DGS10,DGS2,T10YIE\n"
            "2025-09-01,320.0,4.1,158000,4.33,4.0,3.8,2.2\n"
            "2026-09-01,330.0,4.3,159000,4.25,4.1,3.7,2.3\n"
            "2026-10-01,.,.,.,.,4.2,3.8,.\n"
        )
        rows = {x["id"]: x for x in _parse_fred_csv(csv_text)}
        self.assertEqual(rows["CPIAUCSL"]["date"], "2026-09-01")
        self.assertEqual(rows["CPIAUCSL"]["yoy_pct"], 3.12)
        self.assertEqual(rows["UNRATE"]["value"], 4.3)
        self.assertEqual(rows["CPIAUCSL"]["previous_date"], "2025-09-01")
        self.assertEqual(rows["CPIAUCSL"]["change"], 10.0)
        self.assertEqual(rows["DGS10"]["date"], "2026-10-01")
        self.assertAlmostEqual(rows["DGS10"]["change"], 0.1)
        self.assertEqual(set(rows), set(FRED_SERIES))

    def test_fred_csv_missing_date_column_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "date"):
            _parse_fred_csv("CPIAUCSL\n330.0\n")

    def test_macro_rendering_explains_changes_in_correct_units(self):
        lines = []
        append_macro_series(lines, [
            {"id": "DGS10", "name": "Treasury 10 ans", "unit": "% annuel", "date": "2026-10-16",
             "value": 4.2, "previous_date": "2026-10-15", "change": 0.1, "source": "https://example.com"},
            {"id": "PAYEMS", "name": "Emploi", "unit": "milliers", "date": "2026-09-01",
             "value": 159000, "previous_date": "2026-08-01", "change": 120, "source": "https://example.com"},
        ])
        rendered = "\\n".join(lines)
        self.assertIn("+0.100 point de pourcentage", rendered)
        self.assertIn("+120.000 milliers d'emplois", rendered)

    def test_fred_series_are_official_series_pages_and_csv_endpoint(self):
        from src.market_report import FRED_CSV_URL
        self.assertIn("fred.stlouisfed.org/graph/fredgraph.csv", FRED_CSV_URL)
        self.assertIn("DGS10", FRED_CSV_URL)
        self.assertIn("CPIAUCSL", FRED_CSV_URL)

    def test_fetch_fred_keeps_successful_series_when_another_fails(self):
        sample = {"id": "DGS10", "name": "Treasury", "date": "2026-10-15", "value": 4.1, "unit": "%"}
        def fake_fetch(series_id):
            if series_id == "UNRATE":
                return None, "FRED UNRATE: Timeout"
            return {**sample, "id": series_id}, None
        with patch("src.market_report._fetch_one_fred_series", side_effect=fake_fetch):
            rows, errors = fetch_fred_macro_series()
        self.assertEqual(len(rows), len(FRED_SERIES) - 1)
        self.assertEqual([row["id"] for row in rows], [key for key in FRED_SERIES if key != "UNRATE"])
        self.assertEqual(errors, ["FRED UNRATE: Timeout"])

    def test_single_series_fetch_uses_series_specific_endpoint_and_parses_row(self):
        class FakeResponse:
            text = "observation_date,DGS10\n2026-10-15,4.1\n"
            def raise_for_status(self):
                return None
        with patch("src.market_report.requests.get", return_value=FakeResponse()) as get:
            row, error = _fetch_one_fred_series("DGS10")
        self.assertIsNone(error)
        self.assertEqual(row["id"], "DGS10")
        self.assertEqual(row["value"], 4.1)
        self.assertIn("id=DGS10", get.call_args.args[0])
        self.assertEqual(get.call_args.kwargs["timeout"], 12)

    def test_bls_fallback_parses_official_monthly_series_and_cpi_yoy(self):
        class FakeResponse:
            def raise_for_status(self):
                return None
            def json(self):
                return {
                    "status": "REQUEST_SUCCEEDED",
                    "Results": {"series": [
                        {"seriesID": "CUUR0000SA0", "data": [
                            {"year": "2026", "period": "M09", "value": "320.0"},
                            {"year": "2025", "period": "M09", "value": "310.0"},
                        ]},
                        {"seriesID": "LNS14000000", "data": [
                            {"year": "2026", "period": "M09", "value": "4.2"},
                        ]},
                        {"seriesID": "CES0000000001", "data": [
                            {"year": "2026", "period": "M09", "value": "159000.0"},
                        ]},
                    ]}
                }
        with patch("src.market_report.requests.post", return_value=FakeResponse()) as post:
            rows, errors = fetch_bls_macro_fallback({"CPIAUCSL", "UNRATE", "PAYEMS"})
        by_id = {x["id"]: x for x in rows}
        self.assertEqual(set(by_id), {"CPIAUCSL", "UNRATE", "PAYEMS"})
        self.assertEqual(by_id["CPIAUCSL"]["yoy_pct"], 3.23)
        self.assertEqual(by_id["CPIAUCSL"]["change"], 10.0)
        self.assertEqual(by_id["CPIAUCSL"]["previous_date"], "2025-09-01")
        self.assertEqual(by_id["UNRATE"]["value"], 4.2)
        self.assertEqual(by_id["PAYEMS"]["value"], 159000.0)
        self.assertEqual(by_id["CPIAUCSL"]["provider"], "BLS — source officielle de repli")
        self.assertEqual(by_id["CPIAUCSL"]["display_id"], "CUUR0000SA0")
        self.assertEqual(by_id["UNRATE"]["display_id"], "LNS14000000")
        self.assertEqual(by_id["PAYEMS"]["display_id"], "CES0000000001")
        self.assertEqual(errors, [])
        self.assertIn("api.bls.gov/publicAPI/v1", post.call_args.args[0])
        self.assertEqual(post.call_args.kwargs["timeout"], 12)

    def test_macro_orchestrator_fills_missing_fred_series_with_bls_fallback(self):
        fred = ([{"id": "DGS10", "name": "Treasury", "date": "2026-10-15", "value": 4.1}], ["FRED timeout"])
        fallback = ([{"id": "UNRATE", "name": "Unemployment", "date": "2026-09-01", "value": 4.2, "provider": "BLS"}], [])
        with patch("src.market_report.fetch_fred_macro_series", return_value=fred), patch(
            "src.market_report.fetch_bls_macro_fallback", return_value=fallback
        ) as fallback_call:
            rows, errors = fetch_macro_series_with_fallback()
        self.assertEqual([x["id"] for x in rows], ["UNRATE", "DGS10"])
        self.assertEqual(errors, ["FRED timeout"])
        self.assertEqual(fallback_call.call_args.args[0], {"CPIAUCSL", "UNRATE", "PAYEMS"})


class NewsSourceCoverageTests(unittest.TestCase):
    def test_multilateral_sources_have_targeted_discovery_queries(self):
        feeds = dict(NEWS_FEEDS)
        self.assertTrue(any("site%3Aimf.org" in url and "Google News" in name for name, url in feeds.items()))
        self.assertTrue(any("site%3Aworldbank.org" in url and "Google News" in name for name, url in feeds.items()))
        self.assertTrue(any("Federal Reserve" in name for name in feeds))
        self.assertTrue(any("Bank of Japan" in name for name in feeds))
        # Do not depend on the BLS RSS endpoints that failed in the hosted runner.
        self.assertFalse(any("bls.gov/feed/" in url for url in feeds.values()))
        self.assertTrue(any("Bureau of Economic Analysis" in name and url == "https://apps.bea.gov/rss/rss.xml" for name, url in feeds.items()))
        self.assertTrue(any("Census Bureau" in name and url == "https://www.census.gov/economic-indicators/indicator.xml" for name, url in feeds.items()))
        self.assertTrue(any("BLS emploi" in name and "site%3Abls.gov" in url for name, url in feeds.items()))
        self.assertTrue(any("BLS CPI" in name and "site%3Abls.gov" in url for name, url in feeds.items()))
        self.assertTrue(any("BLS PPI" in name and "site%3Abls.gov" in url for name, url in feeds.items()))
        self.assertTrue(any("allocations chômage" in name and "site%3Adol.gov" in url for name, url in feeds.items()))


class NewsDeduplicationTests(unittest.TestCase):
    def test_headline_key_ignores_case_punctuation_and_html_entities(self):
        self.assertEqual(
            _news_dedupe_key("Markets &amp; Rates: Policy UPDATE!"),
            _news_dedupe_key("MARKETS rates policy update"),
        )

    def test_different_headlines_remain_distinct(self):
        self.assertNotEqual(
            _news_dedupe_key("Inflation rises in September"),
            _news_dedupe_key("Inflation falls in September"),
        )


class FeedFormatCompatibilityTests(unittest.TestCase):
    def test_rss_items_are_normalized(self):
        root = ET.fromstring(
            "<rss><channel><item><title>Policy update</title>"
            "<link>https://example.org/rss</link><pubDate>Fri, 16 Oct 2026 10:00:00 GMT</pubDate>"
            "<source>Publisher</source><description><![CDATA[Inflation came in above forecasts, pushing Treasury yields higher.]]></description></item></channel></rss>"
        )
        items = _feed_entries(root, "Fallback")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.org/rss")
        self.assertEqual(items[0]["source"], "Publisher")
        self.assertIn("Inflation came in above forecasts", items[0]["summary"])
        self.assertIn("Treasury yields higher", items[0]["summary"])

    def test_atom_entries_with_namespaces_are_normalized(self):
        root = ET.fromstring(
            '<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Macro release</title>'
            '<link href="https://example.org/atom" rel="alternate"/>'
            '<updated>2026-10-16T10:00:00Z</updated><source><title>Official publisher</title></source>'
            '</entry></feed>'
        )
        items = _feed_entries(root, "Fallback")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.org/atom")
        self.assertEqual(items[0]["published"], "2026-10-16T10:00:00Z")
        self.assertEqual(items[0]["source"], "Official publisher")


class NewsFreshnessTests(unittest.TestCase):
    def test_recent_headlines_are_kept(self):
        now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(_is_recent_news_item("Fri, 16 Oct 2026 10:00:00 GMT", now=now))

    def test_old_headlines_are_rejected(self):
        now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(_is_recent_news_item("Thu, 23 Jul 2026 07:00:00 GMT", now=now))

    def test_undated_or_unparseable_headlines_are_preserved(self):
        now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(_is_recent_news_item("", now=now))
        self.assertTrue(_is_recent_news_item("date unavailable", now=now))

    def test_implausibly_future_dated_headlines_are_rejected(self):
        now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        self.assertFalse(_is_recent_news_item("Sun, 25 Oct 2026 12:00:00 GMT", now=now))

    def test_iso8601_atom_dates_are_parsed_for_freshness(self):
        now = datetime(2026, 10, 16, 12, 0, tzinfo=timezone.utc)
        self.assertTrue(_is_recent_news_item("2026-10-16T10:00:00Z", now=now))
        self.assertFalse(_is_recent_news_item("2026-07-23T07:00:00Z", now=now))
        self.assertFalse(_is_recent_news_item("2026-10-25T12:00:00Z", now=now))


class SecFundamentalParsingTests(unittest.TestCase):
    def test_quarterly_parser_selects_latest_quarter_and_year_comparable(self):
        payload = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"form": "10-Q", "fp": "Q1", "start": "2025-04-01", "end": "2025-06-30", "val": 800, "filed": "2025-08-01"},
                                {"form": "10-Q", "fp": "Q1", "start": "2026-04-01", "end": "2026-06-30", "val": 1000, "filed": "2026-08-01"},
                                {"form": "10-K", "fp": "FY", "start": "2025-01-01", "end": "2025-12-31", "val": 3000, "filed": "2026-02-01"},
                            ]
                        }
                    }
                }
            }
        }
        latest, prior, tag = _quarterly_fact_points(payload, ("Revenues",), ("USD",))
        self.assertEqual(tag, "Revenues")
        self.assertEqual(latest["val"], 1000)
        self.assertEqual(prior["val"], 800)
        self.assertEqual(latest["end"], "2026-06-30")


    def test_q4_is_derived_only_when_annual_and_all_three_quarters_match(self):
        facts = []
        for year, values in (
            (2024, (80, 180, 280, 1000)),
            (2025, (100, 200, 300, 1400)),
        ):
            starts = (f"{year}-01-01", f"{year}-04-01", f"{year}-07-01")
            ends = (f"{year}-03-31", f"{year}-06-30", f"{year}-09-30")
            for quarter, start, end, value in zip(("Q1", "Q2", "Q3"), starts, ends, values[:3]):
                month = {"Q1": "05", "Q2": "08", "Q3": "11"}[quarter]
                facts.append({
                    "form": "10-Q", "fp": quarter, "start": start, "end": end,
                    "val": value, "filed": f"{year}-{month}-01",
                })
            facts.append({
                "form": "10-K", "fp": "FY", "start": f"{year}-01-01",
                "end": f"{year}-12-31", "val": values[3],
                "filed": f"{year + 1}-02-01",
            })
        payload = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": facts}}}}}
        latest, prior, tag = _quarterly_or_q4_fact_points(payload, ("Revenues",), ("USD",))
        self.assertEqual(tag, "Revenues")
        self.assertEqual(latest["fp"], "Q4 (calculé)")
        self.assertEqual(latest["val"], 800)
        self.assertTrue(latest["derived"])
        self.assertEqual(prior["val"], 460)

    def test_q4_is_not_derived_without_all_three_discrete_quarters(self):
        payload = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [
            {"form": "10-Q", "fp": "Q1", "start": "2025-01-01", "end": "2025-03-31", "val": 100, "filed": "2025-05-01"},
            {"form": "10-Q", "fp": "Q2", "start": "2025-04-01", "end": "2025-06-30", "val": 200, "filed": "2025-08-01"},
            {"form": "10-K", "fp": "FY", "start": "2025-01-01", "end": "2025-12-31", "val": 1000, "filed": "2026-02-01"},
        ]}}}}}
        latest, _, _ = _quarterly_or_q4_fact_points(payload, ("Revenues",), ("USD",))
        self.assertEqual(latest["fp"], "Q2")

    def test_quarterly_parser_returns_none_when_only_annual_fact_exists(self):
        payload = {
            "facts": {
                "us-gaap": {
                    "Revenues": {
                        "units": {
                            "USD": [
                                {"form": "10-K", "fp": "FY", "start": "2025-01-01", "end": "2025-12-31", "val": 3000}
                            ]
                        }
                    }
                }
            }
        }
        latest, prior, tag = _quarterly_fact_points(payload, ("Revenues",), ("USD",))
        self.assertIsNone(latest)
        self.assertIsNone(prior)
        self.assertIsNone(tag)

class MarketConvictionTests(unittest.TestCase):
    @staticmethod
    def row(ticker, five_day, daily=0.0):
        return AssetRow(
            ticker=ticker, name=ticker, asset_class="test", price=100.0,
            daily_pct=daily, five_day_pct=five_day, one_month_pct=five_day,
            rsi14=None, ma20_gap_pct=None, ma50_gap_pct=None,
            annualized_vol_pct=None, trend="test", data_timestamp="2026-10-16", note=""
        )

    def test_bullish_and_bearish_scenarios_are_decisive_and_sum_to_100(self):
        bullish = market_conviction([
            self.row("^GSPC", 2.0), self.row("^IXIC", 2.0), self.row("^DJI", 2.0), self.row("^VIX", 0.0, -9.0)
        ])
        bearish = market_conviction([
            self.row("^GSPC", -2.0), self.row("^IXIC", -2.0), self.row("^DJI", -2.0), self.row("^VIX", 0.0, 10.0)
        ])
        # Uncalibrated momentum heuristics must not imply extreme directional confidence.
        self.assertLessEqual(bullish["probabilities"]["haussier"], 60)
        self.assertLessEqual(bearish["probabilities"]["baissier"], 60)
        self.assertEqual(sum(bullish["probabilities"].values()), 100)
        self.assertEqual(sum(bearish["probabilities"].values()), 100)
        self.assertIn("non calibrée", bullish["method"])


class ForecastEvaluationTests(unittest.TestCase):
    def test_forecasts_are_scored_only_after_horizon_is_available(self):
        dates = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]
        snapshots = [
            {"assets": [{"ticker": "TEST", "data_timestamp": day, "price": 100 + i}]}
            for i, day in enumerate(dates)
        ]
        records = [
            {"id": "one", "ticker": "TEST", "base_date": dates[0], "base_price": 100, "direction": "hausse", "horizon_sessions": 1},
            {"id": "five", "ticker": "TEST", "base_date": dates[0], "base_price": 100, "direction": "hausse", "horizon_sessions": 5},
            {"id": "pending", "ticker": "TEST", "base_date": dates[-1], "base_price": 105, "direction": "hausse", "horizon_sessions": 1},
        ]
        result = evaluate_forecasts({"forecasts": snapshots, "forecast_records": records})
        self.assertEqual(result["by_horizon"]["1"]["n"], 1)
        self.assertEqual(result["by_horizon"]["5"]["n"], 1)
        self.assertEqual(result["by_horizon"]["1"]["accuracy_pct"], 100.0)
        self.assertEqual(result["by_horizon"]["5"]["accuracy_pct"], 100.0)
        self.assertEqual(result["pending"], 1)

    def test_saved_morning_probabilities_are_scored_against_next_distinct_session(self):
        snapshots = [
            {
                "report_type": "morning",
                "scenario_forecast": {"probabilities": {"haussier": 75, "central": 15, "baissier": 10}},
                "assets": [{"ticker": "^GSPC", "data_timestamp": "2026-10-01", "price": 100.0}],
            },
            {
                "report_type": "update",
                "assets": [{"ticker": "^GSPC", "data_timestamp": "2026-10-01", "price": 100.0}],
            },
            {
                "report_type": "audit",
                "assets": [{"ticker": "^GSPC", "data_timestamp": "2026-10-02", "price": 102.0}],
            },
        ]
        result = evaluate_scenario_forecasts(snapshots)
        self.assertEqual(len(result["matured"]), 1)
        self.assertEqual(result["matured"][0]["actual"], "haussier")
        self.assertTrue(result["matured"][0]["correct"])
        self.assertEqual(result["pending"], 0)
        self.assertIsNotNone(result["mean_brier_score"])

    def test_morning_scenario_remains_pending_until_a_completed_distinct_session_exists(self):
        today = datetime.now(ZoneInfo("Indian/Antananarivo")).date().isoformat()
        yesterday = (datetime.now(ZoneInfo("Indian/Antananarivo")).date() - __import__("datetime").timedelta(days=1)).isoformat()
        forecast = {"probabilities": {"haussier": 65, "central": 20, "baissier": 15}}
        snapshots = [
            {"report_type": "morning", "scenario_forecast": forecast,
             "assets": [{"ticker": "^GSPC", "data_timestamp": yesterday, "price": 100.0}]},
            {"report_type": "update",
             "assets": [{"ticker": "^GSPC", "data_timestamp": today, "price": 101.0}]},
        ]
        result = evaluate_scenario_forecasts(snapshots)
        self.assertEqual(result["matured"], [])
        self.assertEqual(result["forecast_count"], 1)
        self.assertEqual(result["pending"], 1)

    def test_audit_distinguishes_absent_scenario_history_from_pending_forecasts(self):
        result = evaluate_scenario_forecasts([
            {"report_type": "update",
             "scenario_forecast": {"probabilities": {"haussier": 65, "central": 20, "baissier": 15}},
             "assets": [{"ticker": "^GSPC", "data_timestamp": "2026-10-15", "price": 100.0}]}
        ])
        self.assertEqual(result["forecast_count"], 0)
        self.assertEqual(result["matured"], [])
        self.assertEqual(result["pending"], 0)


    def test_macro_classifier_is_conditional_and_names_relevant_assets(self):
        theme, categories, impact = infer_macro_impact("US inflation data surprises markets")
        self.assertEqual(theme, "Inflation")
        self.assertIn("obligations", categories)
        self.assertIn("Comparer impérativement", impact)
        theme, categories, impact = infer_macro_impact("Oil prices rise after supply disruption")
        self.assertEqual(theme, "Énergie et matières premières")
        self.assertIn("matières premières", categories)
        self.assertIn("choc d'offre", impact)

    def test_professional_html_renders_sections_tables_and_source_links(self):
        plain = (
            "Rapport de test\nHeure Madagascar : 2026-10-16 13:30:00\nGénéré UTC : 2026-10-16 10:30:00 UTC\n\n"
            "TEST SECTION\nUn paragraphe de test.\n"
            "Actif | Classe | Dernier prix | Source\n"
            "S&P 500 | Indice | 100 | https://finance.yahoo.com/quote/%5EGSPC/\n"
        )
        html = render_professional_html(
            plain,
            "Rapport de test",
            datetime(2026, 10, 16, 13, 30, tzinfo=ZoneInfo("Indian/Antananarivo")),
            datetime(2026, 10, 16, 10, 30, tzinfo=timezone.utc),
        )
        self.assertIn("<table>", html)
        self.assertIn("<h2>Test Section</h2>", html)
        self.assertIn('target="_blank"', html)
        self.assertIn("finance.yahoo.com", html)
        self.assertIn("viewport", html)

    def test_all_nine_asset_classes_remain_visible_by_default(self):
        plain = (
            "Rapport de test\nHeure Madagascar : 2026-10-16 13:30:00\n"
            "Généré UTC : 2026-10-16 10:30:00 UTC\n\n"
            "NIVEAU 4 — CLASSES D'ACTIFS : OÙ SE CONCENTRE LE RISQUE ?\n"
            "Synthèse des classes d'actifs.\n"
            "LES 9 CATÉGORIES — ANALYSE PAR UNIVERS D’INVESTISSEMENT\n"
            "1. INDICES BOURSIERS\nFaits et lecture marché.\n"
            "2. FUTURES SUR INDICES\nFaits et lecture marché.\n"
            "3. ACTIONS\nFaits et lecture marché.\n"
            "4. MATIÈRES PREMIÈRES\nFaits et lecture marché.\n"
            "5. DEVISES (FOREX)\nFaits et lecture marché.\n"
            "6. CRYPTO-ACTIFS\nFaits et lecture marché.\n"
            "7. OBLIGATIONS ET CRÉDIT\nFaits et lecture marché.\n"
            "8. ETF\nFaits et lecture marché.\n"
            "9. FONDS D’INVESTISSEMENT\nFaits et lecture marché.\n"
        )
        html = render_professional_html(
            plain,
            "Rapport de test",
            datetime(2026, 10, 16, 13, 30, tzinfo=ZoneInfo("Indian/Antananarivo")),
            datetime(2026, 10, 16, 10, 30, tzinfo=timezone.utc),
        )
        self.assertNotIn("<details><summary>Niveau 4", html)
        self.assertIn("Indices Boursiers", html)
        self.assertIn("Crypto-Actifs", html)
        self.assertIn("Fonds D’Investissement", html)

    def test_long_supporting_sections_are_collapsed_and_excluded_from_reading_time(self):
        plain = (
            "Rapport de test\nHeure Madagascar : 2026-10-16 13:30:00\n"
            "Généré UTC : 2026-10-16 10:30:00 UTC\n\n"
            "FONDAMENTAUX PUBLIÉS — ÉCHANTILLON SEC EDGAR\n"
            + ("Détail justificatif des données fondamentales. " * 1200)
            + "\nNIVEAU 6 — INSTRUMENTS PRÉCIS ET LISTE DE SURVEILLANCE\n"
            + "Résumé visible et actionnable.\n"
        )
        html = render_professional_html(
            plain,
            "Rapport de test",
            datetime(2026, 10, 16, 13, 30, tzinfo=ZoneInfo("Indian/Antananarivo")),
            datetime(2026, 10, 16, 10, 30, tzinfo=timezone.utc),
        )
        self.assertIn("<details><summary>", html)
        self.assertIn("Détail justificatif des données fondamentales", html)
        self.assertIn("Temps de lecture estimé : 1 min", html)


class PublisherBoilerplateTests(unittest.TestCase):
    @patch("src.market_report.requests.get", side_effect=RuntimeError("network disabled in test"))
    def test_marketing_copy_is_not_accepted_as_a_market_news_summary(self, _get):
        item = {
            "title": "Market outlook for Bitcoin",
            "source": "CoinDesk",
            "published": "Mon, 19 Oct 2026 04:54:31 +0000",
            "summary": "Index Offering Discover our index offerings with $49 billion in benchmarked assets, trusted by 100+ global partners.",
            "url": "https://example.org/bitcoin-market-outlook",
        }
        result = _enrich_news_item(item)
        self.assertEqual(result["summary"], "")

    @patch("src.market_report.requests.get", side_effect=RuntimeError("network disabled in test"))
    def test_real_market_fact_summary_is_not_removed_as_boilerplate(self, _get):
        item = {
            "title": "Bitcoin market outlook after a sharp decline",
            "source": "Publisher",
            "published": "Mon, 19 Oct 2026 04:54:31 +0000",
            "summary": "Bitcoin fell 8 percent as investors reduced exposure to digital assets. Trading volumes increased and several major tokens underperformed broader risk assets.",
            "url": "https://example.org/bitcoin-facts",
        }
        result = _enrich_news_item(item)
        self.assertIn("Bitcoin fell 8 percent", result["summary"])


if __name__ == "__main__":
    unittest.main()
