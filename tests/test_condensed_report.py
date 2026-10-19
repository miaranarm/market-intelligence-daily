from src import editorial


def item(n, summary="Shares fell sharply on Friday as investors sold technology stocks after a weak session in Asia. More detail follows here."):
    return {"title": f"Story {n}", "source": "CNBC", "published": "x", "summary": summary, "readthrough": f"Lecture {n}", "url": f"https://x/{n}"}


def test_facts_are_limited_short_and_readthrough_only_for_top_items():
    ctx = {"priority_news": [item(i, "A" * 400 + ". " + "B" * 50) for i in range(8)]}
    blocks = editorial._news_blocks(ctx, editorial.FACTS_LIMIT)
    assert len(blocks) == editorial.FACTS_LIMIT == 5
    assert all(len(b["summary"]) <= editorial.FACTS_EXCERPT_CHARS + 1 for b in blocks)
    assert sum(1 for b in blocks if b["readthrough"]) == editorial.FACTS_READTHROUGH_COUNT


def test_shorten_cuts_on_a_sentence_boundary_when_possible():
    text = "First sentence is here. " + "Second sentence continues for quite a while longer than the limit allows."
    assert editorial._shorten(text, 40) == "First sentence is here."
    assert editorial._shorten("short", 40) == "short"


def test_unexplained_movers_are_grouped_in_one_line():
    movers = [{"ticker": f"T{i}", "name": f"Name{i}", "reasons": [f"séance −{i},00 %"], "news": []} for i in range(1, 4)]
    blocks = editorial._movers_blocks({"movers": movers})
    notes = [b for b in blocks if b["kind"] == "note"]
    assert len(notes) == 1 and "cause non établie" in notes[0]["text"]
    assert all(f"Name{i}" in notes[0]["text"] for i in range(1, 4))
    assert not any(b["kind"] == "h3" for b in blocks)


def test_article_already_cited_is_not_repeated():
    shared = item(1)
    movers = [{"ticker": "A", "name": "Alpha", "reasons": ["séance −3,00 %"], "news": [shared]},
              {"ticker": "B", "name": "Beta", "reasons": ["séance −4,00 %"], "news": [shared]}]
    blocks = editorial._movers_blocks({"movers": movers})
    assert sum(1 for b in blocks if b["kind"] == "news") == 1
    assert any("déjà citée" in b.get("text", "") for b in blocks)
    # et un article déjà présent dans « Faits marquants » n'est pas répété non plus
    blocks = editorial._movers_blocks({"movers": movers[:1], "_faits_urls": {shared["url"]}})
    assert not any(b["kind"] == "news" for b in blocks)


def test_movers_are_capped_and_no_readthrough_in_movers():
    movers = [{"ticker": f"T{i}", "name": f"N{i}", "reasons": ["séance −5,00 %"], "news": [item(i)]} for i in range(12)]
    blocks = editorial._movers_blocks({"movers": movers})
    news = [b for b in blocks if b["kind"] == "news"]
    assert len(news) == editorial.MOVERS_LIMIT == 8
    assert all(not b["readthrough"] for b in news)
