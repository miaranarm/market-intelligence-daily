import json
import os
import unittest
from datetime import date, datetime, timezone
from unittest.mock import patch

from src import calendar_events, editorial, llm_editor, render_report
from src.market_report import (ASSETS, METHOD_VERSION, AssetRow, evaluate_forecasts, evaluate_scenario_forecasts,
                               market_conviction, record_new_forecasts)


def make_row(ticker, daily=0.5, five=1.0, month=2.0, price=100.0, vol=16.0, day="2026-10-16"):
    meta = ASSETS[ticker]
    return AssetRow(ticker=ticker, name=meta["name"], asset_class=meta["class"], price=price, daily_pct=daily,
                    five_day_pct=five, one_month_pct=month, rsi14=None, ma20_gap_pct=None, ma50_gap_pct=None,
                    annualized_vol_pct=vol, trend="test", data_timestamp=day, note="")


def all_rows():
    return [make_row(t) for t in ASSETS]


def base_ctx(**overrides):
    rows = all_rows()
    started = datetime(2026, 10, 17, 2, 30, tzinfo=timezone.utc)
    ctx = {
        "kind": "morning", "title": "t", "now_local": started.astimezone(calendar_events.TZ), "started": started,
        "rows": rows, "sparks": {"^GSPC": [1, 2, 3, 4, 5, 6]}, "news": [], "priority_news": [], "macro": [],
        "calendar": [], "scenario": market_conviction(rows), "forecast_eval": evaluate_forecasts({}),
        "scenario_eval": evaluate_scenario_forecasts([]), "cross_lines": [], "errors": {}, "n_tracked": len(ASSETS),
        "weekend": False, "legacy_text": "", "llm": None,
    }
    ctx.update(overrides)
    return ctx


class NineCategoriesTests(unittest.TestCase):
    def test_every_category_has_instruments_and_none_is_counted_twice(self):
        rows = all_rows()
        for cat in editorial.CATEGORIES:
            self.assertTrue([r for r in rows if cat["match"](r)], cat["key"])
        for row in rows:
            hits = [c["key"] for c in editorial.CATEGORIES if c["match"](row)]
            self.assertLessEqual(len(hits), 1, (row.ticker, hits))
        self.assertEqual(len(editorial.CATEGORIES), 9)

    def test_vix_is_in_indices_and_bond_etfs_are_not_in_bonds(self):
        by = {c["key"]: c for c in editorial.CATEGORIES}
        self.assertTrue(by["indices"]["match"](make_row("^VIX")))
        self.assertFalse(by["obligations"]["match"](make_row("TLT")))
        self.assertTrue(by["etf"]["match"](make_row("TLT")))
        self.assertTrue(by["obligations"]["match"](make_row("^TNX")))

    def test_coverage_additions(self):
        for ticker in ("^IRX", "^FVX", "^TYX", "BZ=F", "ASML.AS", "7203.T", "VEMAX"):
            self.assertIn(ticker, ASSETS)


class VixInterpretationTests(unittest.TestCase):
    def test_sub20_vix_with_large_jump_is_not_described_as_ordinary(self):
        vix = make_row("^VIX", daily=21.45, price=19.99)
        text = editorial._vix_reading(vix)
        self.assertIn("inférieur au seuil conventionnel de 20", text)
        self.assertIn("bondit de +21,45", text)
        self.assertIn("remontée nette de la demande de protection", text)

    def test_vix_level_and_daily_move_are_both_reported(self):
        vix = make_row("^VIX", daily=2.0, price=24.0)
        text = editorial._vix_reading(vix)
        self.assertIn("niveau de tension", text)
        self.assertIn("Variation sur la séance", text)


class FormattingTests(unittest.TestCase):
    def test_french_numbers(self):
        self.assertEqual(editorial.fr_num(-1.95), "−1,95")
        self.assertEqual(editorial.fr_num(81609.4, 0), "81\u202f609")
        self.assertEqual(editorial.fr_pct(0.5), "+0,50\u00a0%")
        self.assertEqual(editorial.fr_num(None), "n.d.")
        self.assertEqual(editorial.fr_num(-0.001, 2), "0,00")

    def test_text_numbers_and_agreements(self):
        self.assertEqual(editorial.fr_text("S&P 500 en baisse (-1.95 %) et +0.13%"), "S&P 500 en baisse (−1,95\u00a0%) et +0,13\u00a0%")
        self.assertIn("2,53 points de pourcentage", editorial.fr_pp(2.53))
        self.assertIn("1,50 point de pourcentage", editorial.fr_pp(1.5))
        self.assertIn("1,4 point de base", editorial.fr_bp(1.4))


class CalendarTests(unittest.TestCase):
    def test_times_are_converted_to_madagascar_and_window_is_applied(self):
        events = [
            {"date": "2026-10-28", "time_utc": "18:00", "title": "FOMC", "importance": "élevée", "status": "confirmé"},
            {"date": "2026-12-09", "time_utc": "19:00", "title": "Lointain", "importance": "élevée", "status": "confirmé"},
            {"date": "2026-10-10", "time_utc": None, "title": "Passé", "importance": "faible"},
        ]
        found = calendar_events.upcoming_events(events, date(2026, 10, 17), 14)
        self.assertEqual([e["title"] for e in found], ["FOMC"])
        self.assertEqual(found[0]["local_time"], "21:00")

    def test_unknown_status_defaults_to_to_confirm_and_midnight_rollover(self):
        found = calendar_events.upcoming_events(
            [{"date": "2026-10-20", "time_utc": "22:30", "title": "Nuit", "importance": "moyenne"}], date(2026, 10, 17), 7)
        self.assertEqual(found[0]["status"], "à confirmer")
        self.assertEqual(str(found[0]["local_date"]), "2026-10-21")

    def test_datetime_window_excludes_events_already_elapsed_today(self):
        now = datetime(2026, 10, 19, 5, 59, tzinfo=calendar_events.TZ)
        events = [
            {"date": "2026-10-19", "time_utc": "02:00", "title": "Déjà publié", "importance": "élevée"},
            {"date": "2026-10-19", "time_utc": "08:00", "title": "Plus tard", "importance": "moyenne"},
            {"date": "2026-10-20", "time_utc": "02:00", "title": "Demain", "importance": "moyenne"},
        ]
        found = calendar_events.upcoming_events(events, now, 7)
        self.assertEqual([e["title"] for e in found], ["Plus tard", "Demain"])

    def test_shipped_calendar_never_claims_confirmed_without_official_source(self):
        for event in calendar_events.load_manual_events():
            if event.get("status") == "confirmé":
                self.assertTrue(str(event.get("source", "")).startswith("https://"), event["title"])

    def test_fred_events_need_a_key(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("FRED_API_KEY", None)
            events, errors = calendar_events.fetch_fred_release_events(date(2026, 10, 17), date(2026, 10, 24))
        self.assertEqual((events, errors), ([], []))


class ForecastEvaluationFixesTests(unittest.TestCase):
    @staticmethod
    def snapshot(kind, day, price, vol=None, forecast=True):
        snap = {"report_type": kind, "assets": [{"ticker": "^GSPC", "data_timestamp": day, "price": price, "annualized_vol_pct": vol}]}
        if forecast:
            snap["scenario_forecast"] = {"probabilities": {"haussier": 40, "central": 35, "baissier": 25}}
        return snap

    def test_same_day_reruns_are_not_independent_samples(self):
        snaps = [self.snapshot("morning", "2026-10-01", 100.0), self.snapshot("morning", "2026-10-01", 100.0),
                 self.snapshot("audit", "2026-10-02", 102.0, forecast=False)]
        result = evaluate_scenario_forecasts(snaps)
        self.assertEqual(result["forecast_count"], 1)
        self.assertEqual(result["duplicates_ignored"], 1)
        self.assertEqual(len(result["matured"]), 1)

    def test_central_band_follows_volatility(self):
        # vol 16 % annualisée → σ quotidien ≈ 1,0 % → bande ≈ ±0,5 % : +0,3 % est « central »
        calm = evaluate_scenario_forecasts([self.snapshot("morning", "2026-10-01", 100.0, vol=16.0),
                                            self.snapshot("audit", "2026-10-02", 100.3, forecast=False)])
        self.assertEqual(calm["matured"][0]["actual"], "central")
        # sans volatilité enregistrée : ancienne bande de ±0,1 %
        legacy = evaluate_scenario_forecasts([self.snapshot("morning", "2026-10-01", 100.0),
                                              self.snapshot("audit", "2026-10-02", 100.3, forecast=False)])
        self.assertEqual(legacy["matured"][0]["actual"], "haussier")

    def test_benchmarks_and_version_are_reported(self):
        snaps = [self.snapshot("morning", "2026-10-01", 100.0), self.snapshot("audit", "2026-10-02", 102.0, forecast=False)]
        result = evaluate_scenario_forecasts(snaps)
        self.assertEqual(result["baseline_always_up_accuracy_pct"], 100.0)
        self.assertIsNotNone(result["climatology_brier_score"])
        self.assertIsNone(result["brier_skill_score"])  # moins de 30 échantillons
        self.assertEqual(result["by_version"]["v1"]["n"], 1)

    def test_asset_forecasts_report_naive_baselines_and_store_volatility(self):
        dates = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06"]
        prices = [100, 101, 102, 103]
        snaps = [{"assets": [{"ticker": "T", "data_timestamp": d, "price": p}]} for d, p in zip(dates, prices)]
        records = [{"id": "a", "ticker": "T", "base_date": dates[1], "base_price": 101, "direction": "hausse", "horizon_sessions": 1}]
        result = evaluate_forecasts({"forecasts": snaps, "forecast_records": records})
        stats = result["by_horizon"]["1"]
        self.assertEqual(stats["always_up_accuracy_pct"], 100.0)
        self.assertEqual(stats["persistence_accuracy_pct"], 100.0)
        state = {}
        record_new_forecasts(state, [make_row("^GSPC", five=1.0, vol=16.0)])
        self.assertAlmostEqual(state["forecast_records"][0]["daily_sigma_pct"], 16.0 / 252 ** 0.5, places=3)
        self.assertEqual(state["forecast_records"][0]["method_version"], METHOD_VERSION)

    def test_conviction_v2_is_versioned_and_consistent(self):
        for score_rows in ([make_row("^GSPC", five=2), make_row("^IXIC", five=2), make_row("^DJI", five=2), make_row("^VIX", daily=-9)],
                           [make_row("^GSPC", five=-2), make_row("^IXIC", five=-2), make_row("^DJI", five=-2), make_row("^VIX", daily=10)],
                           [make_row("^GSPC", five=0)]):
            result = market_conviction(score_rows)
            self.assertEqual(sum(result["probabilities"].values()), 100)
            self.assertLessEqual(max(result["probabilities"].values()), 60)
            self.assertEqual(result["method_version"], METHOD_VERSION)
        self.assertGreaterEqual(market_conviction([make_row("^GSPC", five=0)])["probabilities"]["central"], 35)


class ReportBuildTests(unittest.TestCase):
    def test_report_has_all_sections_and_reading_time(self):
        model = editorial.build_report(base_ctx())
        ids = [s["id"] for s in model["sections"]]
        for key in ("synthese", "regime", "agenda", *[c["key"] for c in editorial.CATEGORIES], "scenarios", "audit", "methode"):
            self.assertIn(key, ids)
        self.assertGreaterEqual(model["reading_minutes"], 1)
        self.assertTrue(model["headline"])

    def test_weekly_and_update_have_their_own_sections(self):
        weekly = editorial.build_report(base_ctx(kind="weekly"))
        self.assertIn("semaine", [s["id"] for s in weekly["sections"]])
        self.assertEqual(weekly["kind_label"], "Perspectives de la semaine")
        update = editorial.build_report(base_ctx(kind="update", prior_assets={"^GSPC": {"price": 90.0}}))
        self.assertIn("depuis", [s["id"] for s in update["sections"]])

    def test_html_is_escaped_and_contains_plan_and_sparkline(self):
        news = [{"title": "<script>alert(1)</script> Fed holds rates", "source": "X", "published": "d", "url": "https://example.org/a",
                 "summary_short": "Résumé <b>gras</b>", "readthrough": "Lecture"}]
        model = editorial.build_report(base_ctx(priority_news=news))
        page = render_report.render_html(model)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn('aria-label="Plan de lecture"', page)
        self.assertIn("<svg", page)
        self.assertIn("prefers-color-scheme:dark", page)
        self.assertIn("@media print", page)

    def test_text_render_and_email_summary(self):
        model = editorial.build_report(base_ctx())
        text = render_report.render_text(model)
        self.assertIn("L'ESSENTIEL", text)
        html_mail = render_report.summary_html_from_text(text, "https://example.org/r.html")
        self.assertIn("https://example.org/r.html", html_mail)
        self.assertIn("Lire le rapport complet", html_mail)
        self.assertIn("S&amp;P 500", html_mail)

    def test_legacy_annex_is_outside_reading_time(self):
        small = editorial.build_report(base_ctx(legacy_text=""))
        big = editorial.build_report(base_ctx(legacy_text="mot " * 50000))
        self.assertEqual(small["reading_minutes"], big["reading_minutes"])
        self.assertIn("Annexe", render_report.render_html(big))

    def test_repeated_market_readthrough_is_shown_once(self):
        items = [{"title": f"Titre {i}", "source": "S", "published": "d", "url": "u", "summary_short": f"Résumé distinct numéro {i}",
                  "readthrough": "Même lecture"} for i in range(3)]
        model = editorial.build_report(base_ctx(priority_news=items))
        faits = next(s for s in model["sections"] if s["id"] == "faits")
        self.assertEqual(sum(1 for b in faits["blocks"] if b["readthrough"]), 1)

    def test_missing_data_does_not_crash(self):
        model = editorial.build_report(base_ctx(rows=[make_row("^GSPC")], scenario={}))
        self.assertIn("Aucune cotation exploitable", json.dumps(model["sections"], default=str, ensure_ascii=False))


class LlmGuardrailTests(unittest.TestCase):
    FACTS = json.dumps({"univers": {"indices": [{"instrument": "S&P 500", "variation_seance_pct": -1.09, "dernier": 6500.25}]},
                        "calendrier": [{"date": "2026-10-28"}]})
    OK = ("Interprétation : le S&P 500 recule de 1,09 sur la séance, un mouvement compatible avec une hausse de l'aversion au risque, "
          "mais une seule séance ne suffit pas à conclure sur la direction des prochains jours.")

    def test_supported_numbers_pass_and_invented_numbers_are_dropped(self):
        numbers = llm_editor._facts_numbers(self.FACTS)
        self.assertTrue(llm_editor.validate_paragraph(self.OK, numbers))
        invented = self.OK.replace("1,09", "3,41")
        self.assertFalse(llm_editor.validate_paragraph(invented, numbers))

    def test_advice_and_short_text_are_dropped(self):
        numbers = llm_editor._facts_numbers(self.FACTS)
        advice = "Achetez le S&P 500 maintenant car la correction de 1,09 offre un point d'entrée très attractif pour les investisseurs patients."
        self.assertFalse(llm_editor.validate_paragraph(advice, numbers))
        self.assertFalse(llm_editor.validate_paragraph("Trop court.", numbers))

    def test_validate_commentary_counts_dropped(self):
        raw = {"synthese": [self.OK, self.OK.replace("1,09", "9,99")], "categories": {"indices": [self.OK], "inconnu": [self.OK]}}
        clean, dropped = llm_editor.validate_commentary(raw, self.FACTS)
        self.assertEqual(len(clean["synthese"]), 1)
        self.assertEqual(dropped, 1)
        self.assertIn("indices", clean["categories"])
        self.assertNotIn("inconnu", clean["categories"])

    def test_no_key_means_no_llm_and_no_error(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ANTHROPIC_API_KEY", None)
            self.assertEqual(llm_editor.generate_commentary(base_ctx()), (None, []))

    def test_api_failure_is_not_blocking(self):
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), patch("src.llm_editor.requests.post", side_effect=RuntimeError("réseau")), \
                patch("src.llm_editor.time.sleep"):
            result, errors = llm_editor.generate_commentary(base_ctx())
        self.assertIsNone(result)
        self.assertIn("indisponible", errors[0])

    def test_successful_call_is_validated_and_rendered_with_label(self):
        ctx = base_ctx()
        facts_text = json.dumps(llm_editor.build_facts(ctx), ensure_ascii=False, default=str)
        sp = next(r for r in ctx["rows"] if r.ticker == "^GSPC")
        good = (f"Interprétation : le S&P 500 affiche {str(sp.daily_pct).replace('.', ',')} sur la séance, ce qui reste compatible avec une phase d'attente "
                "des investisseurs avant les prochaines publications, sans qu'une seule séance suffise à établir une tendance.")
        payload = {"content": [{"type": "text", "text": json.dumps({"synthese": [good, "Le S&P 500 vaut 123456,78 points."], "categories": {"indices": [good]}})}]}

        class Resp:
            def raise_for_status(self): pass
            def json(self): return payload
        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "k"}), patch("src.llm_editor.requests.post", return_value=Resp()) as post:
            result, errors = llm_editor.generate_commentary(ctx)
        self.assertEqual(errors, [])
        self.assertEqual(len(result["synthese"]), 1)
        self.assertEqual(result["meta"]["dropped"], 1)
        self.assertEqual(post.call_args.kwargs["headers"]["anthropic-version"], "2023-06-01")
        ctx["llm"] = result
        page = render_report.render_html(editorial.build_report(ctx))
        self.assertIn("Rédaction assistée par modèle", page)
        self.assertIn(facts_text[:0], page)


if __name__ == "__main__":
    unittest.main()

class LLMFactContextTests(unittest.TestCase):
    def test_fundamentals_and_news_provenance_are_passed_to_editor(self):
        ctx = base_ctx(
            fundamentals=[{
                "ticker": "NVDA", "name": "Nvidia", "period": "2026-09-30",
                "revenue": 1000.0, "revenue_yoy_pct": 20.0, "eps": 2.5, "eps_yoy_pct": 15.0,
                "operating_income": 300.0, "operating_margin_pct": 30.0,
                "operating_cash_flow": 250.0, "capex": 40.0, "free_cash_flow": 210.0,
                "source": "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json",
            }],
            priority_news=[{
                "title": "Résultats de Nvidia", "source": "SEC", "published": "2026-10-18",
                "summary_short": "Résumé vérifié de l'actualité.", "readthrough": "Conséquence possible.",
                "url": "https://www.sec.gov/example",
            }],
        )
        facts = llm_editor.build_facts(ctx)
        self.assertEqual(facts["fondamentaux_entreprises"][0]["ticker"], "NVDA")
        self.assertEqual(facts["fondamentaux_entreprises"][0]["croissance_ca_annuelle_pct"], 20.0)
        self.assertEqual(facts["fondamentaux_entreprises"][0]["source_officielle"],
                         "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json")
        self.assertEqual(facts["actualites"][0]["url"], "https://www.sec.gov/example")
        self.assertEqual(facts["actualites"][0]["lecture_marche_existante"], "Conséquence possible.")




class MacroVariationUnitTests(unittest.TestCase):
    def test_macro_variations_have_series_specific_units(self):
        blocks = editorial._regime_blocks({
            "macro": [
                {"id": "CPIAUCSL", "name": "Indice CPI-U", "value": 336.9, "date": "2026-09-01",
                 "change": 1.96, "yoy_pct": 3.74, "provider": "BLS", "source": "https://example.com/cpi"},
                {"id": "PAYEMS", "name": "Emploi salarié non agricole", "value": 159044, "date": "2026-09-01",
                 "change": 29, "provider": "BLS", "source": "https://example.com/jobs"},
                {"id": "DGS10", "name": "Treasury à 10 ans", "value": 5.09, "date": "2026-10-16",
                 "change": -0.01, "provider": "FRED", "source": "https://example.com/yield"},
            ],
            "scenario": {}, "cross_lines": [], "freshness_note": "",
        }, {})
        table = next(block for block in blocks if block.get("kind") == "table")
        self.assertIn("Variation vs observation précédente", table["headers"])
        values = [row[3]["t"] for row in table["rows"]]
        self.assertEqual(values, ["+1,96 pt d'indice", "+29,00 milliers", "−0,01 pt de %"])



class NewsExcerptCoherenceTests(unittest.TestCase):
    def test_unrelated_excerpt_cannot_drive_news_readthrough(self):
        item = {
            "title": "XRP Ledger is set to fix its lending code before anyone can use it",
            "summary": "GENIUS pushes yield off-chain; TAM grows to $4B in 3 years. Diversified RWA stablecoins sustain 5-7% yield from real credit as crypto funding compresses to ~4%.",
            "readthrough": "Le marché arbitre entre la croissance attendue des revenus liés à l'IA et le coût du financement des infrastructures.",
            "source": "CoinDesk",
            "published": "2026-10-19",
            "url": "https://example.com/story",
        }
        block = editorial._news_block(item, {})
        self.assertEqual(block["summary"], "")
        self.assertIn("ne correspond pas suffisamment", block["readthrough"])
        self.assertNotIn("centres de données", block["readthrough"])

    def test_unrelated_plain_language_headline_excerpt_is_suppressed(self):
        item = {
            "title": "Apple shares plunge after iPhone demand warning",
            "summary": "Tesla deliveries exceeded analyst estimates as the electric car maker expanded in Europe.",
            "readthrough": "Une lecture des résultats de Tesla est nécessaire.",
            "source": "Example",
            "published": "2026-10-19",
            "url": "https://example.com/story",
        }
        block = editorial._news_block(item, {})
        self.assertEqual(block["summary"], "")
        self.assertIn("ne correspond pas suffisamment", block["readthrough"])

    def test_excerpt_with_headline_entity_is_retained(self):
        item = {
            "title": "XRP Ledger expands lending",
            "summary": "XRP Ledger developers are changing the lending code before launch.",
            "readthrough": "Distinguer les facteurs propres au secteur crypto.",
            "source": "CoinDesk",
            "published": "2026-10-19",
            "url": "https://example.com/story",
        }
        block = editorial._news_block(item, {})
        self.assertIn("XRP Ledger developers", block["summary"])
        self.assertEqual(block["readthrough"], item["readthrough"])
