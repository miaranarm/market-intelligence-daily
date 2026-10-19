import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src import market_report as mr


def fake_frames():
    index = pd.date_range(end="2026-10-16", periods=80, freq="B")
    return {t: pd.DataFrame({"Close": [100 + i * 0.1 + (i % 3) for i in range(80)]}, index=index) for t in mr.ASSETS}


NEWS = [{"title": "Brent oil rises as supply concerns grow", "source": "Reuters", "published": "Fri, 16 Oct 2026 20:00:00 GMT",
         "url": "https://example.org/oil",
         "summary": "Oil prices rose on Friday as traders weighed supply disruption risks in the Middle East and the outlook for demand, "
                    "while inventories in the United States fell more than analysts had expected."}]


class EndToEndOfflineTests(unittest.TestCase):
    def run_report(self, kind):
        tmp = Path(tempfile.mkdtemp())
        patches = [
            patch.object(mr, "STATE_DIR", tmp), patch.object(mr, "FORECAST_FILE", tmp / "forecasts.json"),
            patch.object(mr, "HISTORY_FILE", tmp / "market_history.csv"),
            patch.object(mr, "fetch_prices", return_value=(fake_frames(), [])),
            patch.object(mr, "fetch_news", return_value=(NEWS, [])),
            patch.object(mr, "_enrich_news_item", side_effect=lambda x: x),
            patch.object(mr, "fetch_company_fundamentals", return_value=([], [])),
            patch.object(mr, "fetch_macro_series_with_fallback", return_value=([], [])),
            patch.object(mr.enrichment, "complete_macro", side_effect=lambda series: (series, [])),
            patch.object(mr.enrichment, "fetch_mover_news", return_value=([], [])),
            patch.object(mr.enrichment, "fetch_earnings_events", return_value=([], [])),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        return mr.make_report(kind), tmp

    def test_weekly_report_end_to_end(self):
        (plain, page, snapshot, model), tmp = self.run_report("weekly")
        self.assertEqual(model["kind"], "weekly")
        self.assertIn("PERSPECTIVES DE LA SEMAINE", plain)
        self.assertIn("<svg", page)  # mini-graphiques de 30 jours
        self.assertIn("Annexe", page)
        self.assertEqual(snapshot["scenario_forecast"]["method_version"], mr.METHOD_VERSION)
        json.dumps(snapshot)  # l'instantané reste sérialisable
        self.assertNotIn("sparks", snapshot)
        mr.write_state(snapshot, [mr.AssetRow(**a) for a in snapshot["assets"]])
        self.assertTrue((tmp / "forecasts.json").exists())

    def test_every_report_type_builds_and_covers_nine_categories(self):
        for kind in ("morning", "update", "audit"):
            (plain, page, snapshot, model), _ = self.run_report(kind)
            titles = [s["title"] for s in model["sections"]]
            for label in ("Indices boursiers", "Futures sur indices", "Actions", "Matières premières", "Devises",
                          "Crypto-monnaies", "Obligations", "ETF", "Fonds d'investissement"):
                self.assertIn(label, titles, kind)

    def test_email_subject_uses_french_label(self):
        self.assertEqual(mr.email_subject("weekly", "2026-10-18T18:00:00+03:00"),
                         "[Market Intelligence] Perspectives de la semaine — 2026-10-18 18:00")


if __name__ == "__main__":
    unittest.main()
