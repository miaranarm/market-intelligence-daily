import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from zoneinfo import ZoneInfo

from src.market_report import AssetRow, NEWS_FEEDS, FRED_SERIES, _parse_fred_csv, _fetch_one_fred_series, fetch_fred_macro_series, _news_dedupe_key, _feed_entries, _is_recent_news_item, _price_freshness_note, _quarterly_fact_points, _quarterly_or_q4_fact_points, evaluate_forecasts, infer_macro_impact, market_conviction, evaluate_scenario_forecasts, render_professional_html



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
        self.assertEqual(rows["DGS10"]["date"], "2026-10-01")
        self.assertEqual(set(rows), set(FRED_SERIES))

    def test_fred_csv_missing_date_column_fails_clearly(self):
        with self.assertRaisesRegex(ValueError, "date"):
            _parse_fred_csv("CPIAUCSL\n330.0\n")

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
            "<source>Publisher</source></item></channel></rss>"
        )
        items = _feed_entries(root, "Fallback")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.org/rss")
        self.assertEqual(items[0]["source"], "Publisher")

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
        self.assertGreaterEqual(bullish["probabilities"]["haussier"], 75)
        self.assertGreaterEqual(bearish["probabilities"]["baissier"], 75)
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


if __name__ == "__main__":
    unittest.main()
