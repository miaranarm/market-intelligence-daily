import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from src.market_report import evaluate_forecasts, render_professional_html


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
