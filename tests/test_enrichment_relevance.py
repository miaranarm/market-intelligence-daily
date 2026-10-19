"""Regression tests for false-positive instrument/news matching."""
from src.enrichment import _contains_term, relevance_score


def _mover(ticker="CAT", name="Caterpillar"):
    return {"ticker": ticker, "name": name, "asset_class": "US Equity"}


def test_short_ticker_does_not_match_inside_an_unrelated_word():
    item = {"title": "Education companies rise", "summary": "Enterprise software shares gain"}
    assert relevance_score(item, _mover()) == 0


def test_company_name_and_directional_word_match_as_whole_terms():
    item = {"title": "Caterpillar shares fall after outlook cut", "summary": ""}
    assert relevance_score(item, _mover()) == 4


def test_direction_word_inside_another_word_is_not_a_move():
    assert not _contains_term("Enterprise results were mixed", "rise")


def test_multiword_alias_matches_with_word_boundaries():
    assert _contains_term("Nasdaq stocks fall sharply", "nasdaq")
    assert not _contains_term("a nasdaq-related label", "daq")


def test_market_theme_does_not_match_inside_unrelated_words():
    from src.enrichment import is_market_relevant

    assert not is_market_relevant({
        "title": "Corporate awards ceremony announced",
        "summary": "Executives gather for an annual corporate event.",
    })


def test_market_theme_matches_plural_market_terms():
    from src.enrichment import is_market_relevant

    assert is_market_relevant({
        "title": "Global stocks fall as bond yields rise",
        "summary": "Investors reassess valuations after the session.",
    })


def test_geopolitical_market_story_remains_relevant():
    from src.enrichment import is_market_relevant

    assert is_market_relevant({
        "title": "Oil prices rise after shipping disruption",
        "summary": "Energy markets react to supply concerns.",
    })
