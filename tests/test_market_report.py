import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.market_report import AssetRow, _quarterly_fact_points, evaluate_forecasts, infer_macro_impact, market_conviction, evaluate_scenario_forecasts, render_professional_html



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
