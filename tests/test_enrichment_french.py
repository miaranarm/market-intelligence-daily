from src.enrichment import relevance_score


def test_french_headline_links_named_index_to_market_move():
    mover = {"ticker": "^GSPC", "name": "S&P 500", "asset_class": "index"}
    item = {
        "title": "Le S&P 500 chute après une séance agitée à Wall Street",
        "summary": "Les investisseurs réduisent leur exposition aux actions.",
    }

    assert relevance_score(item, mover) >= 3


def test_french_headline_links_company_to_market_move():
    mover = {"ticker": "AVGO", "name": "Broadcom Inc.", "asset_class": "equity"}
    item = {
        "title": "Broadcom bondit après ses résultats",
        "summary": "Le groupe relève ses perspectives.",
    }

    assert relevance_score(item, mover) >= 3


def test_english_headline_matching_is_preserved():
    mover = {"ticker": "^KS11", "name": "KOSPI", "asset_class": "index"}
    item = {
        "title": "KOSPI plunges as technology shares sell off",
        "summary": "Investors react to fresh uncertainty.",
    }

    assert relevance_score(item, mover) >= 3


def test_inflected_english_move_verbs_are_recognised():
    mover = {"ticker": "AVGO", "name": "Broadcom Inc.", "asset_class": "equity"}
    for verb in ("slides", "falls", "plunged", "rallies", "surging", "tumbles"):
        item = {"title": f"Broadcom {verb} on AI chip worries", "summary": "Shares moved."}
        assert relevance_score(item, mover) >= 3, verb


def test_substring_false_positives_stay_rejected():
    mover = {"ticker": "CAT", "name": "Caterpillar", "asset_class": "equity"}
    item = {"title": "Higher education enterprise software", "summary": "Rising enrolment in education."}
    assert relevance_score(item, mover) == 0


def test_rebound_headline_does_not_explain_a_decline():
    from src.enrichment import attach_news_to_movers
    mover = {"ticker": "QQQ", "name": "Invesco Nasdaq 100 ETF", "asset_class": "ETF",
             "daily_pct": -2.5, "five_day_pct": -5.52, "one_month_pct": -0.89}
    bounce = {"title": "Bitcoin extends bounce as Nasdaq stocks rebound", "summary": "Gains across crypto.", "url": "b", "published": "", "ticker": "QQQ"}
    selloff = {"title": "Nasdaq sell-off deepens as tech stocks fall", "summary": "Shares fell.", "url": "s", "published": "", "ticker": "QQQ"}
    from src import enrichment
    from unittest.mock import patch
    with patch.object(enrichment, "is_recent", return_value=True):
        out = attach_news_to_movers([mover], [bounce, selloff])
    assert [n["url"] for n in out[0]["news"]] == ["s"]


def test_rise_headline_explains_a_rise_and_mixed_text_is_kept():
    from src import enrichment
    from unittest.mock import patch
    mover = {"ticker": "XLE", "name": "Energy Select Sector SPDR ETF", "asset_class": "ETF", "daily_pct": 2.5, "five_day_pct": 4.9}
    mixed = {"title": "Energy stocks rise even as tech falls", "summary": "Energy stocks rose.", "url": "m", "published": "", "ticker": "XLE"}
    with patch.object(enrichment, "is_recent", return_value=True):
        out = enrichment.attach_news_to_movers([mover], [mixed])
    assert len(out[0]["news"]) == 1
