import unittest
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src import editorial, enrichment


def row(ticker, name, cls, daily=0.1, five=0.2, month=0.5, vol=20.0, stamp="2026-10-16"):
    return SimpleNamespace(ticker=ticker, name=name, asset_class=cls, price=100.0, daily_pct=daily, five_day_pct=five,
                           one_month_pct=month, annualized_vol_pct=vol, data_timestamp=stamp)


class RelevanceTests(unittest.TestCase):
    def test_off_topic_items_are_rejected(self):
        self.assertFalse(enrichment.is_market_relevant({"title": "Always on, always listening: new AI devices", "summary": "Apple Watch Siri Recap stocks"}))
        self.assertFalse(enrichment.is_market_relevant({"title": "Flight from Israel diverted after 'threat'", "summary": ""}))

    def test_market_items_are_kept(self):
        self.assertTrue(enrichment.is_market_relevant({"title": "France debt hits record as bond yields rise", "summary": ""}))

    def test_title_only_items_lack_substance(self):
        self.assertFalse(enrichment.has_substance({"title": "Private equity finds next Asian frontier", "summary": ""}))
        self.assertTrue(enrichment.has_substance({"title": "x", "summary": "A long enough excerpt describing what happened in the market today."}))


class MoverTests(unittest.TestCase):
    def test_multi_horizon_outliers_are_detected(self):
        kospi = row("^KS11", "KOSPI", "South Korean equity index", daily=-0.05, five=-11.27, month=-15.25, vol=18.0)
        calm = row("^GSPC", "S&P 500", "US equity index", daily=0.2, five=0.3, month=0.5, vol=15.0)
        fund = row("VFIAX", "Vanguard 500", "Mutual fund", daily=-5, five=-9, month=-9, vol=10.0)
        movers = enrichment.notable_movers([kospi, calm, fund])
        self.assertEqual([m["ticker"] for m in movers], ["^KS11"])
        self.assertTrue(any("cinq séances" in r for r in movers[0]["reasons"]))

    def test_attach_news_states_absence(self):
        movers = [{"ticker": "AVGO", "name": "Broadcom"}, {"ticker": "TSLA", "name": "Tesla"}]
        news = [{"ticker": "AVGO", "title": "Broadcom shares plunge", "summary": "Broadcom shares fell after earnings guidance.", "url": "u1", "published": "Mon, 19 Oct 2026 08:00:00 GMT"}, {"ticker": "AVGO", "title": "Broadcom shares plunge", "summary": "Broadcom shares fell after earnings guidance.", "url": "u2", "published": "Mon, 19 Oct 2026 08:01:00 GMT"}]
        # Ce test vérifie le rattachement et la déduplication, pas la fenêtre de fraîcheur.
        with patch.object(enrichment, "is_recent", return_value=True):
            out = enrichment.attach_news_to_movers(movers, news)
        self.assertEqual(len(out[0]["news"]), 1)  # doublon de titre écarté
        self.assertEqual(out[1]["news"], [])

    def test_rss_parsing_extracts_items(self):
        xml = b"<rss><channel><item><title>Broadcom slides</title><link>https://y/1</link><description>&lt;p&gt;AI chip worries&lt;/p&gt;</description></item></channel></rss>"
        items = enrichment._parse_rss_items(xml, "Yahoo", "AVGO")
        self.assertEqual(items[0]["summary"], "AI chip worries")
        self.assertEqual(items[0]["ticker"], "AVGO")


class FreshnessTests(unittest.TestCase):
    def test_mixed_dates_are_flagged(self):
        rows = [row("^GSPC", "S&P", "US equity index", stamp="2026-10-16"), row("^N225", "Nikkei", "Japanese equity index", stamp="2026-10-19")]
        note = enrichment.freshness_note(rows, datetime(2026, 10, 19, tzinfo=timezone.utc))
        self.assertIn("pas synchronisés", note)
        self.assertIn("16/10", note)
        self.assertIn("19/10", note)
        self.assertIn("ne permettent pas", note)
        self.assertIsNone(enrichment.freshness_note(rows[:1], datetime(2026, 10, 19, tzinfo=timezone.utc)))

    def test_frozen_prices_exclude_funds(self):
        rows = [row("005930.KS", "Samsung", "Asian equity", daily=0.0), row("FTBFX", "Fidelity bond", "Bond mutual fund", daily=0.0)]
        self.assertEqual([r.ticker for r in enrichment.frozen_price_suspects(rows)], ["005930.KS"])


class MacroTests(unittest.TestCase):
    def test_treasury_xml_parsing_and_breakeven(self):
        def entry(day, y2, y10):
            return (f"<entry><content><m:properties xmlns:m='m' xmlns:d='d'><d:NEW_DATE>{day}T00:00:00</d:NEW_DATE>"
                    f"<d:BC_2YEAR>{y2}</d:BC_2YEAR><d:BC_10YEAR>{y10}</d:BC_10YEAR></m:properties></content></entry>")
        nominal = f"<feed>{entry('2026-10-15', 4.80, 5.05)}{entry('2026-10-16', 4.85, 5.10)}</feed>".encode()
        real = f"<feed>{entry('2026-10-15', 0, 2.60)}{entry('2026-10-16', 0, 2.65)}</feed>".encode()
        def fake_get(url, **kw):
            resp = MagicMock()
            resp.content = real if "real" in url else nominal
            return resp
        with patch.object(enrichment.requests, "get", side_effect=fake_get):
            items, errors = enrichment.fetch_treasury_curve(date(2026, 10, 19))
        by = {i["id"]: i for i in items}
        self.assertEqual(by["DGS2"]["value"], 4.85)
        self.assertAlmostEqual(by["DGS10"]["change"], 0.05)
        self.assertAlmostEqual(by["T10YIE"]["value"], 2.45)
        self.assertEqual(errors, [])

    def test_nyfed_effr(self):
        payload = {"refRates": [{"effectiveDate": "2026-10-15", "percentRate": 4.33}, {"effectiveDate": "2026-10-16", "percentRate": 4.34, "targetRateFrom": 4.25, "targetRateTo": 4.5}]}
        resp = MagicMock(); resp.json.return_value = payload
        with patch.object(enrichment.requests, "get", return_value=resp):
            item, err = enrichment.fetch_nyfed_effr()
        self.assertIsNone(err)
        self.assertEqual(item["value"], 4.34)
        self.assertEqual(item["target_range"], "4.25–4.50")

    def test_complete_macro_never_overwrites_fred_and_survives_failures(self):
        existing = [{"id": "CPIAUCSL", "name": "CPI", "value": 1, "date": "2026-09-01", "unit": "", "source": "s"},
                    {"id": "DGS10", "name": "10y FRED", "value": 5.0, "date": "2026-10-16", "unit": "", "source": "s", "provider": "FRED"}]
        with patch.object(enrichment, "fetch_nyfed_effr", return_value=(None, "NY Fed: boom")), \
             patch.object(enrichment, "fetch_treasury_curve", return_value=([{"id": "DGS10", "name": "x", "value": 9.9, "date": "d", "unit": "", "source": "s"},
                                                                              {"id": "DGS2", "name": "2y", "value": 4.8, "date": "d", "unit": "", "source": "s"}], [])), \
             patch.object(enrichment, "fetch_ecb_deposit_rate", return_value=(None, None)):
            merged, errors = enrichment.complete_macro(existing)
        ids = [m["id"] for m in merged]
        self.assertEqual(ids, ["CPIAUCSL", "DGS2", "DGS10"])
        self.assertEqual(next(m for m in merged if m["id"] == "DGS10")["value"], 5.0)
        self.assertEqual(errors, ["NY Fed: boom"])


class EarningsTests(unittest.TestCase):
    def test_parse_earnings_date_variants(self):
        self.assertEqual(enrichment.parse_earnings_date({"Earnings Date": [date(2026, 10, 22)]}), date(2026, 10, 22))
        self.assertEqual(enrichment.parse_earnings_date({"Earnings Date": datetime(2026, 10, 22, 21, 0)}), date(2026, 10, 22))
        self.assertIsNone(enrichment.parse_earnings_date({}))
        self.assertIsNone(enrichment.parse_earnings_date(None))


class EditorialIntegrationTests(unittest.TestCase):
    def ctx(self, **extra):
        rows = [row("^GSPC", "S&P 500", "US equity index"), row("^VIX", "VIX", "Implied volatility")]
        base = {"kind": "morning", "rows": rows, "calendar": [], "news": [], "priority_news": [], "macro": [], "sparks": {},
                "scenario": {"score": -5, "stance": "Biais baissier", "probabilities": {"hausse": 18, "centre": 27, "baisse": 55}},
                "errors": {}, "n_tracked": 2}
        base.update(extra)
        return base

    def test_movers_section_states_missing_explanations(self):
        movers = [{"ticker": "^KS11", "name": "KOSPI", "reasons": ["cinq séances −11,27 %"], "five_day_pct": -11.27, "one_month_pct": -15.25,
                   "news": []},
                  {"ticker": "AVGO", "name": "Broadcom", "reasons": ["séance −4,52 %"], "five_day_pct": -9.07, "one_month_pct": -5.17,
                   "news": [{"title": "Broadcom slides on AI worries", "source": "Yahoo", "published": "x", "url": "https://y/1", "summary": "Shares fell."}]}]
        model = editorial.build_report(self.ctx(movers=movers))
        section = next(s for s in model["sections"] if s["id"] == "mouvements")
        texts = " ".join(str(b) for b in section["blocks"])
        self.assertIn("cause non établie", texts)
        self.assertIn("Broadcom slides on AI worries", texts)
        takeaways = model["sections"][0]["blocks"][0]["items"]
        self.assertTrue(any("Mouvements de fond" in t and "KOSPI" in t for t in takeaways))

    def test_no_movers_no_section(self):
        model = editorial.build_report(self.ctx())
        self.assertFalse(any(s["id"] == "mouvements" for s in model["sections"]))

    def test_scenario_b_no_longer_contradicts_probabilities(self):
        model = editorial.build_report(self.ctx())
        scenarios = next(s for s in model["sections"] if s["id"] == "scenarios")
        body = " ".join(str(b) for b in scenarios["blocks"])
        self.assertNotIn("le plus probable après", body)

    def test_freshness_note_is_rendered(self):
        model = editorial.build_report(self.ctx(freshness_note="Les cours n'ont pas tous la même date"))
        regime = next(s for s in model["sections"] if s["id"] == "regime")
        self.assertIn("même date", " ".join(str(b) for b in regime["blocks"]))


if __name__ == "__main__":
    unittest.main()


class RealReportRegressionTests(unittest.TestCase):
    """Cas réels du rapport du 19/10/2026."""

    def test_clean_summary_drops_chrome_and_truncated_fragments(self):
        text = ("Podobnik said the expansion is part of a broader plan. Index Offering Discover our index offerings with $49 billion. "
                "9, the Wall Street Journal reported on Monday. Crude oil prices hovered near recent highs on Sunday.")
        cleaned = enrichment.clean_summary(text)
        self.assertNotIn("Index Offering", cleaned)
        self.assertNotIn("9, the Wall Street", cleaned)
        self.assertIn("Crude oil prices hovered", cleaned)

    def test_unrelated_article_citing_etf_is_not_attached(self):
        mover = {"ticker": "QQQ", "name": "Invesco Nasdaq 100 ETF", "asset_class": "ETF"}
        moderna = {"title": "Stocktwits Pharma Pulse: Moderna-Merck Cancer Vaccine Grabs Spotlight", "published": "Mon, 19 Oct 2026 08:00:00 GMT",
                   "summary": "The Invesco QQQ Trust (QQQ), down 6%, fell last week.", "url": "u", "ticker": "QQQ"}
        selloff = {"title": "Tech Stock Sell-Off: 1 Unstoppable Nasdaq ETF to Buy", "published": "Mon, 19 Oct 2026 08:05:00 GMT",
                   "summary": "The Nasdaq-100 ETF QQQ fell.", "url": "v", "ticker": "QQQ"}
        # Dates figées pour une régression historique : isoler le test de pertinence de l'horloge.
        with patch.object(enrichment, "is_recent", return_value=True):
            out = enrichment.attach_news_to_movers([mover], [moderna, selloff])
        self.assertEqual([n["url"] for n in out[0]["news"]], ["v"])

    def test_old_articles_are_not_attached(self):
        mover = {"ticker": "EEM", "name": "Emerging markets equity ETF", "asset_class": "ETF"}
        old = {"title": "Emerging markets ETFs fall", "summary": "x fell", "published": "Wed, 30 Sep 2026 11:20:00 +0000", "url": "o", "ticker": "EEM"}
        with patch.object(enrichment, "is_recent", wraps=lambda p, **k: False):
            self.assertEqual(enrichment.attach_news_to_movers([mover], [old])[0]["news"], [])

    def test_ai_readthrough_is_suppressed_for_unrelated_oil_story(self):
        from src import editorial
        story = {
            "title": "Oil prices slide as sanctions relief raises hopes of increased supply",
            "summary": "Brent crude futures fell as traders weighed possibly higher Russian supplies.",
            "readthrough": "Le marché arbitre entre la croissance attendue des revenus liés à l’IA et le coût du financement des infrastructures.",
            "source": "CNBC",
            "published": "Mon, 19 Oct 2026 04:51:56 GMT",
            "url": "https://example.org/oil",
        }
        block = editorial._news_block(story, {})
        self.assertIn("Interprétation écartée", block["readthrough"])
        self.assertNotIn("revenus liés à l’IA", block["readthrough"])

    def test_general_news_explains_index_without_network(self):
        mover = {"ticker": "^KS11", "name": "KOSPI", "asset_class": "South Korean equity index"}
        general = [{"title": "Bitcoin, Korea's Kospi and Nasdaq futures rally as China GDP beats estimates", "published": "Mon, 19 Oct 2026 08:00:00 GMT",
                    "summary": "Asian stocks rally.", "url": "g", "source": "CoinDesk"}]
        # Le scénario teste le rattachement sémantique, pas la fraîcheur d'une date historique.
        with patch.object(enrichment, "is_recent", return_value=True):
            out = enrichment.attach_news_to_movers([mover], [], general)
        self.assertEqual(out[0]["news"][0]["url"], "g")

    def test_breakeven_accepts_tc_prefix_for_real_yields(self):
        def entry(day, tag, v):
            return (f"<entry><content><m:properties xmlns:m='m' xmlns:d='d'><d:NEW_DATE>{day}T00:00:00</d:NEW_DATE>"
                    f"<d:{tag}>{v}</d:{tag}></m:properties></content></entry>")
        nominal = ("<feed><entry><content><m:properties xmlns:m='m' xmlns:d='d'><d:NEW_DATE>2026-10-16T00:00:00</d:NEW_DATE>"
                   "<d:BC_2YEAR>4.74</d:BC_2YEAR><d:BC_10YEAR>5.09</d:BC_10YEAR></m:properties></content></entry></feed>").encode()
        real = f"<feed>{entry('2026-10-16', 'TC_10YEAR', 2.60)}</feed>".encode()
        resp = lambda c: MagicMock(content=c)
        with patch.object(enrichment.requests, "get", side_effect=lambda url, **kw: resp(real if "real" in url else nominal)):
            items, _ = enrichment.fetch_treasury_curve(date(2026, 10, 19))
        self.assertAlmostEqual({i["id"]: i for i in items}["T10YIE"]["value"], 2.49)


class EditorialRegressionTests(unittest.TestCase):
    def test_same_story_is_not_repeated_in_every_universe(self):
        from src import market_report as mr
        story = {"title": "Deutsche Bank targets Asia crypto custody expansion", "url": "https://x/1", "published": "", "source": "CoinDesk",
                 "summary": "The bank also plans stablecoin conversion, tokenized deposits and digital bond issuance as part of a target of roughly 8% annual revenue growth by 2028."}
        picked = mr.news_for_keywords([story], ("crypto",), 3)
        self.assertEqual(len(picked), 1)
        self.assertEqual(mr.news_for_keywords([story], ("crypto",), 3, exclude_urls={"https://x/1"}), [])
        # mot simple absent du titre : plus de rattachement via le corps de l'article
        self.assertEqual(mr.news_for_keywords([story], ("bond",), 3), [])

    def test_dollar_index_inconsistent_with_pairs_is_flagged(self):
        pairs = {"EURUSD=X": 0.21, "USDJPY=X": -0.05, "GBPUSD=X": 0.43, "USDCAD=X": -0.52, "USDCHF=X": -0.46}
        rows = [row(t, t, "FX", daily=v, stamp="2026-10-19") for t, v in pairs.items()] + [row("DX-Y.NYB", "US Dollar Index", "FX", daily=-0.01, stamp="2026-10-19")]
        by = {r.ticker: r for r in rows}
        text = " ".join(editorial._analyse_devises(rows, by, {}))
        self.assertIn("Incohérence", text)
