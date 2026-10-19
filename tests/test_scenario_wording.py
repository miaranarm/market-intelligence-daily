import unittest
from datetime import datetime, timezone

from src import editorial
from src.market_report import ASSETS, AssetRow


def make_row(ticker, daily=0.0, five=0.0, price=100.0, day="2026-10-16"):
    meta = ASSETS[ticker]
    return AssetRow(
        ticker=ticker, name=meta["name"], asset_class=meta["class"], price=price,
        daily_pct=daily, five_day_pct=five, one_month_pct=0.0, rsi14=None,
        ma20_gap_pct=None, ma50_gap_pct=None, annualized_vol_pct=16.0,
        trend="test", data_timestamp=day, note="",
    )


class ScenarioWordingTests(unittest.TestCase):
    def test_bearish_scenario_is_conditional_not_a_false_current_state(self):
        rows = [make_row(ticker) for ticker in ASSETS]
        by = {row.ticker: row for row in rows}
        by["^VIX"] = make_row("^VIX", daily=21.45, price=19.99)
        by["^TNX"] = make_row("^TNX", price=5.098)
        by["DX-Y.NYB"] = make_row("DX-Y.NYB", price=101.84)
        by["^GSPC"] = make_row("^GSPC", daily=-1.09, five=-1.95, price=6500.0)
        by["^IXIC"] = make_row("^IXIC", daily=-2.15, five=-4.48, price=22000.0)
        ctx = {
            "scenario": {"score": -5},
            "calendar": [],
            "llm": None,
        }
        blocks = editorial._scenario_blocks(ctx, by)
        scenario_a = next(block["body"] for block in blocks if block.get("title", "").startswith("Scénario A"))
        scenario_b = next(block["body"] for block in blocks if block.get("title", "").startswith("Scénario B"))
        self.assertIn("dépasse durablement son niveau actuel de 20,0", scenario_a)
        self.assertNotIn("VIX reste au-dessus de 20,0", scenario_a)
        self.assertIn("repasse sous son niveau actuel de 20,0", scenario_b)
        self.assertNotIn("probabilités expérimentales", scenario_b)
        self.assertIn("hypothèse et non un fait établi", scenario_a)


if __name__ == "__main__":
    unittest.main()
