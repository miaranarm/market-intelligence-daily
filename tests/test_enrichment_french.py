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
