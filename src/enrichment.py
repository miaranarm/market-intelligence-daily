"""Enrichissement des informations collectées par le rapport.

Ce module comble les lacunes constatées dans le rapport du 19/10/2026 :

* des mouvements majeurs (KOSPI −15 % sur un mois, Samsung −14 %, Broadcom −4,5 %) sans aucune
  explication, car les flux généraux ne parlent pas de chaque valeur : on va chercher les
  actualités propres à chaque mouvement inhabituel ;
* un tableau macro réduit à trois séries (le taux directeur, le 2 ans et les anticipations
  d'inflation manquaient quand FRED est injoignable) : replis officiels NY Fed, Trésor américain, BCE ;
* un agenda sans calendrier des résultats d'entreprises en pleine saison de publication ;
* des cours de dates différentes comparés entre eux sans avertissement.

Principe inchangé : aucune donnée inventée. Chaque source est indépendante, un échec est
consigné et ne bloque jamais le rapport.
"""
from __future__ import annotations

import html
import io
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from typing import Any

import requests

USER_AGENT = "MarketIntelligenceDaily/0.1 (personal research; contact via repository owner)"

# --------------------------------------------------------------------------- flux d'actualités
# Flux éditeurs supplémentaires. Un flux qui change d'adresse est signalé dans les erreurs
# du rapport (« flux indisponibles ») et dans data/feed_health.json ; il ne bloque rien.
EXTRA_NEWS_FEEDS: list[tuple[str, str]] = [
    ("CNBC — marchés et investissement", "https://www.cnbc.com/id/15839069/device/rss/rss.html"),
    ("CNBC — économie", "https://www.cnbc.com/id/20910258/device/rss/rss.html"),
    ("CNBC — technologie", "https://www.cnbc.com/id/19854910/device/rss/rss.html"),
    ("CNBC — énergie", "https://www.cnbc.com/id/19836768/device/rss/rss.html"),
    ("CNBC — Asie-Pacifique", "https://www.cnbc.com/id/19832390/device/rss/rss.html"),
    ("CNBC — Europe", "https://www.cnbc.com/id/19794221/device/rss/rss.html"),
    ("MarketWatch — à la une (flux éditeur)", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("MarketWatch — pouls du marché (flux éditeur)", "https://feeds.content.dowjones.io/public/rss/mw_marketpulse"),
    ("BBC — économie et entreprises (flux éditeur)", "https://feeds.bbci.co.uk/news/business/rss.xml"),
    ("BBC — monde (flux éditeur)", "https://feeds.bbci.co.uk/news/world/rss.xml"),
    ("The Guardian — monde (flux éditeur)", "https://www.theguardian.com/world/rss"),
    ("OilPrice — pétrole et énergie (flux éditeur)", "https://oilprice.com/rss/main"),
    ("CoinDesk — crypto (flux éditeur)", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph — crypto (flux éditeur)", "https://cointelegraph.com/rss"),
    ("Le Monde — économie (flux éditeur)", "https://www.lemonde.fr/economie/rss_full.xml"),
]

# Sujets sans rapport avec les marchés : ils étaient remontés dans « Faits marquants »
# (appareils connectés, vol dérouté, capital-investissement sans contenu).
OFF_TOPIC_MARKERS = (
    "apple watch", "always on", "smart glasses", "wearable", "flight from", "flight to", "diverted",
    "recipe", "celebrity", "horoscope", "football", "premier league", "tv show", "box office",
    "royal family", "fashion week", "travel tips", "wellness",
)
# Pour qu'une actualité soit retenue comme « fait marquant », elle doit toucher au moins un de
# ces thèmes (sinon elle est écartée plutôt que de remplir la place avec du hors-sujet).
MARKET_THEMES = (
    "stock", "share", "equit", "bond", "yield", "treasury", "rate", "inflation", "cpi", "gdp",
    "growth", "central bank", "fed", "ecb", "boj", "oil", "crude", "gas", "gold", "copper",
    "commodit", "currency", "dollar", "yen", "euro", "bitcoin", "crypto", "earnings", "profit",
    "revenue", "guidance", "tariff", "trade", "export", "sanction", "budget", "deficit", "debt",
    "bank", "credit", "market", "economy", "economic", "recession", "unemploy", "jobs", "ipo",
    "merger", "acquisition", "chip", "semiconductor", "opec", "war", "ceasefire", "strike",
    "unrest", "inflation", "inflation", "marché", "bourse", "taux", "économie", "budget",
)


def _matches_market_theme(text: str, theme: str) -> bool:
    """Match un thème comme un mot ou une expression, pas comme une sous-chaîne accidentelle.

    Les trois thèmes terminés par une racine (equit, commodit, unemploy) gardent une
    recherche de préfixe de mot pour couvrir leurs variantes. Les autres acceptent le
    pluriel anglais courant, sans faire correspondre par exemple « rate » à « corporate »
    ou « war » à « awards ».
    """
    theme = theme.casefold().strip()
    if theme in {"equit", "commodit", "unemploy"}:
        pattern = r"(?<!\w)" + re.escape(theme) + r"\w*"
    else:
        suffix = r"(?:s|es)?" if re.fullmatch(r"[a-z]+", theme) else ""
        pattern = r"(?<!\w)" + re.escape(theme) + suffix + r"(?!\w)"
    return re.search(pattern, text, flags=re.UNICODE) is not None


def is_market_relevant(item: dict[str, str]) -> bool:
    """Vrai si l'actualité touche à un thème de marché et n'est pas du hors-sujet évident."""
    text = f"{item.get('title', '')} {item.get('summary', '')}".casefold()
    if any(marker in text for marker in OFF_TOPIC_MARKERS):
        return False
    return any(_matches_market_theme(text, theme) for theme in MARKET_THEMES)


def has_substance(item: dict[str, str], min_chars: int = 60) -> bool:
    """Une actualité sans aucun extrait (titre seul) n'apprend rien au lecteur."""
    return len(re.sub(r"\s+", " ", item.get("summary", "")).strip()) >= min_chars


# --------------------------------------------------------------------------- mouvements inhabituels
def _sigma_daily_pct(row: Any) -> float | None:
    vol = getattr(row, "annualized_vol_pct", None)
    try:
        return float(vol) / (252 ** 0.5) if vol else None
    except (TypeError, ValueError):
        return None


# Seuils absolus (séance, cinq séances, un mois, en %) : un mouvement n'est « notable » que s'il est
# à la fois statistiquement inhabituel (écart-type) et assez grand pour compter. Sans plancher
# absolu, des paires de devises à très faible volatilité (EUR/GBP −0,26 %) remontaient en tête ;
# sans le déclencheur « extrême », un KOSPI à −10 % sur cinq séances passait sous le radar car sa
# propre volatilité, gonflée par la chute, faisait paraître le mouvement banal.
ABSOLUTE_FLOORS = {
    "fx": (0.8, 2.0, 4.0),
    "crypto": (4.0, 10.0, 18.0),
    "commodity": (3.0, 7.0, 12.0),
    "stock": (3.0, 7.0, 12.0),
    "index": (1.5, 4.0, 7.0),
}


def _floor_kind(asset_class: str) -> str:
    cls = asset_class.casefold()
    if cls == "fx":
        return "fx"
    if cls == "crypto":
        return "crypto"
    if "commodity" in cls:
        return "commodity"
    if "equity" in cls and "index" not in cls:
        return "stock"
    return "index"


def _fr(value: float, digits: int = 2, signed: bool = False) -> str:
    """Nombre au format français (virgule décimale, vrai signe moins)."""
    text = f"{value:+.{digits}f}" if signed else f"{value:.{digits}f}"
    return text.replace(".", ",").replace("-", "\u2212")


def notable_movers(rows: list[Any], limit: int = 12) -> list[dict[str, Any]]:
    """Instruments dont un mouvement sort de l'ordinaire, sur plusieurs horizons.

    Le rapport ne regardait que la séance : un KOSPI à −10 % sur cinq séances passait inaperçu.
    Les fonds communs (une valeur par jour), les taux (variation relative trompeuse) et le VIX
    (traité à part) sont exclus. Classement par ampleur rapportée au seuil de la classe d'actifs.
    """
    out: list[dict[str, Any]] = []
    horizons = (("daily_pct", "séance", 1), ("five_day_pct", "cinq séances", 5), ("one_month_pct", "un mois", 21))
    for r in rows:
        cls = str(getattr(r, "asset_class", ""))
        if "mutual fund" in cls.casefold() or cls.casefold() == "rates" or getattr(r, "ticker", "") == "^VIX":
            continue
        sigma = _sigma_daily_pct(r)
        floors = ABSOLUTE_FLOORS[_floor_kind(cls)]
        reasons: list[tuple[float, str]] = []
        for (attr, label, days), floor in zip(horizons, floors):
            move = getattr(r, attr, None)
            if move is None:
                continue
            ratio = abs(move) / floor
            z = abs(move) / (sigma * days ** 0.5) if sigma else None
            unusual = z is not None and z >= (1.6 if days == 1 else 1.8 if days == 5 else 2.0)
            if (unusual and ratio >= 1.0) or ratio >= 1.5:
                text = f"{label} {_fr(move, 2, True)} %" + (f" ({_fr(z, 1)} écart-type)" if z is not None else "")
                reasons.append((ratio, text))
        if reasons:
            out.append({
                "ticker": r.ticker, "name": r.name, "asset_class": cls,
                "score": max(s for s, _ in reasons), "reasons": [t for _, t in sorted(reasons, reverse=True)],
                "daily_pct": getattr(r, "daily_pct", None), "five_day_pct": getattr(r, "five_day_pct", None),
                "one_month_pct": getattr(r, "one_month_pct", None),
            })
    out.sort(key=lambda m: m["score"], reverse=True)
    return out[:limit]


# --------------------------------------------------------------------------- actualités par valeur
YAHOO_TICKER_RSS = "https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
# Pas de flux par titre pour les indices, devises et matières premières : requête thématique.
THEMATIC_QUERIES = {
    "^KS11": "KOSPI Korea stocks", "^N225": "Nikkei Japan stocks", "^HSI": "Hang Seng Hong Kong stocks",
    "^GSPC": "S&P 500 Wall Street stocks", "^IXIC": "Nasdaq tech stocks selloff",
    "BZ=F": "Brent crude oil price", "CL=F": "WTI crude oil price", "GC=F": "gold price",
    "SI=F": "silver price", "HG=F": "copper price", "KC=F": "coffee prices",
    "BTC-USD": "bitcoin price", "ETH-USD": "ether price", "SOL-USD": "solana price", "XRP-USD": "XRP price",
    "USDJPY=X": "yen dollar intervention", "DX-Y.NYB": "dollar index",
}


def _parse_rss_items(content: bytes, source: str, ticker: str, limit: int = 4) -> list[dict[str, str]]:
    """Parse RSS 2.0 and Atom feeds, including namespaced Atom links and dates."""
    root = ET.fromstring(content)
    items: list[dict[str, str]] = []
    # Match local tag names so XML namespace prefixes do not silently turn a healthy
    # Atom feed into zero headlines.
    nodes = [node for node in root.iter() if node.tag.split("}")[-1].casefold() in {"item", "entry"}]
    for node in nodes:
        children = {child.tag.split("}")[-1].casefold(): child for child in node}
        title_node = children.get("title")
        title = "".join(title_node.itertext()).strip() if title_node is not None else ""
        link_node = children.get("link")
        link = ""
        if link_node is not None:
            if link_node.attrib:
                links = [child for child in node if child.tag.split("}")[-1].casefold() == "link"]
                preferred = next((child for child in links if child.attrib.get("rel", "alternate") == "alternate"), links[0] if links else None)
                link = (preferred.attrib.get("href", "") if preferred is not None else "").strip()
            else:
                link = (link_node.text or "").strip()
        if not title or not link or not link.startswith(("https://", "http://")):
            continue
        desc_node = next((children[key] for key in ("description", "summary", "content") if key in children), None)
        desc = "".join(desc_node.itertext()) if desc_node is not None else ""
        date_node = next((children[key] for key in ("pubdate", "published", "updated", "date") if key in children), None)
        published = "".join(date_node.itertext()).strip() if date_node is not None else ""
        items.append({
            "title": html.unescape(title), "url": link, "source": source,
            "published": published,
            "summary": re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", desc))).strip(),
            "ticker": ticker,
        })
        if len(items) >= limit:
            break
    return items

def _fetch_one_mover(mover: dict[str, Any]) -> tuple[list[dict[str, str]], str | None]:
    ticker = mover["ticker"]
    cls = str(mover.get("asset_class", "")).casefold()
    is_single_stock = "equity" in cls and "index" not in cls and "futures" not in cls
    is_etf = "etf" in cls
    if is_single_stock or is_etf:
        url, source = YAHOO_TICKER_RSS.format(ticker=ticker), f"Yahoo Finance — actualités {mover['name']}"
    elif ticker in THEMATIC_QUERIES:
        from urllib.parse import quote_plus
        url = f"https://news.google.com/rss/search?q={quote_plus(THEMATIC_QUERIES[ticker] + ' when:2d')}&hl=en-US&gl=US&ceid=US:en"
        source = f"Google News — {THEMATIC_QUERIES[ticker]}"
    else:
        return [], None
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=12)
        response.raise_for_status()
        return _parse_rss_items(response.content, source, ticker), None
    except Exception as exc:  # noqa: BLE001 - échec isolé, consigné
        return [], f"actualités {ticker}: {type(exc).__name__}: {str(exc)[:100]}"


def fetch_mover_news(movers: list[dict[str, Any]], max_movers: int = 10) -> tuple[list[dict[str, str]], list[str]]:
    """Actualités propres à chaque mouvement inhabituel (au plus quatre par instrument)."""
    selected = movers[:max_movers]
    if not selected:
        return [], []
    news: list[dict[str, str]] = []
    errors: list[str] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        for items, error in pool.map(_fetch_one_mover, selected):
            news += items
            if error:
                errors.append(error)
    return news, errors


MOVE_WORDS = (
    # Anglais : titres des flux internationaux.
    "fall", "fell", "drop", "slide", "slump", "plunge", "tumble", "sell-off", "selloff", "rout", "retreat", "sink",
    "rally", "surge", "jump", "soar", "gain", "rise", "rose", "climb", "rebound", "spike", "lose", "lost", "weak", "strong",
    # Français : notamment Le Monde et les flux francophones.
    "baisse", "baisses", "recul", "recule", "reculent", "chute", "chute de", "chutent", "plonge", "plongent",
    "dévisse", "dévissent", "s'effondre", "s'effondrent", "fléchit", "fléchissent", "perd", "perdent",
    "perte", "pertes", "hausse", "hausses", "bondit", "bondissent", "grimpe", "grimpent", "progresse",
    "progressent", "gagne", "gagnent", "rebond", "rebondit", "rebondissent", "se redresse", "en baisse",
    "en hausse", "en repli",
)
# Mots qui désignent un instrument dans le texte des articles généraux (indices, matières premières).
ALIASES = {
    "^KS11": ("kospi", "korea"), "^N225": ("nikkei",), "^HSI": ("hang seng",), "^IXIC": ("nasdaq",), "QQQ": ("nasdaq", "qqq"),
    "NQ=F": ("nasdaq",), "^GSPC": ("s&p 500",), "SPY": ("s&p 500",), "XLK": ("tech stocks", "technology stocks", "tech sell"),
    "XLE": ("energy stocks", "oil stocks"), "BZ=F": ("brent",), "CL=F": ("wti", "crude"), "KC=F": ("coffee",),
    "GC=F": ("gold",), "SI=F": ("silver",), "HG=F": ("copper",), "EEM": ("emerging markets",), "005930.KS": ("samsung",),
    "TSM": ("tsmc", "taiwan semiconductor"), "CAT": ("caterpillar",), "AVGO": ("broadcom",),
}


def is_recent(published: str, max_age_days: float = 4.0, now: datetime | None = None) -> bool:
    """Vrai uniquement si la date est lisible, récente et pas anormalement future.

    Pour rattacher une actualité à un mouvement de marché, une date absente ou illisible
    n'est pas une preuve de fraîcheur : on l'écarte plutôt que de risquer une causalité
    fondée sur un article ancien. Une tolérance de six heures absorbe les décalages d'horloge
    et de fuseau des flux.
    """
    from email.utils import parsedate_to_datetime
    if not published or not published.strip():
        return False
    try:
        try:
            when = parsedate_to_datetime(published)
        except (TypeError, ValueError, OverflowError):
            when = datetime.fromisoformat(published.strip().replace("Z", "+00:00"))
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        age = ((now or datetime.now(timezone.utc)) - when.astimezone(timezone.utc)).total_seconds() / 86400
        return -0.25 <= age <= max_age_days
    except (TypeError, ValueError, OverflowError):
        return False


def _entity_words(mover: dict[str, Any]) -> tuple[str, ...]:
    words = list(ALIASES.get(mover["ticker"], ()))
    first = re.sub(r"\(.*?\)", "", mover["name"]).strip().casefold()
    if first and len(first) > 3:
        words.append(first)
    ticker = mover["ticker"].casefold()
    if re.fullmatch(r"[a-z]{2,5}", ticker):
        words.append(ticker)
    return tuple(dict.fromkeys(words))


def _contains_term(text: str, term: str) -> bool:
    """Recherche un terme entier, pas une sous-chaîne accidentelle (CAT dans education, rise dans enterprise)."""
    term = re.sub(r"\s+", " ", term.strip().casefold())
    if not term:
        return False
    # Les limites \w respectent les noms composés tout en empêchant les correspondances au milieu d'un mot.
    return re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text.casefold(), flags=re.UNICODE) is not None


def relevance_score(item: dict[str, str], mover: dict[str, Any]) -> int:
    """Une actualité explique un mouvement si elle nomme réellement l'instrument et décrit une variation.
    Les limites de mots évitent les faux positifs de tickers courts et de verbes inclus dans d'autres mots."""
    title, summary = item.get("title", ""), item.get("summary", "")
    entities = _entity_words(mover)
    in_title = any(_contains_term(title, e) for e in entities)
    in_summary = any(_contains_term(summary, e) for e in entities)
    move_title = any(_contains_term(title, w) for w in MOVE_WORDS)
    move_summary = any(_contains_term(summary, w) for w in MOVE_WORDS)
    score = 0
    if in_title:
        score += 2
    elif in_summary:
        score += 1
    if move_title:
        score += 2
    elif move_summary:
        score += 1
    return score if (in_title or in_summary) else 0


def attach_news_to_movers(movers: list[dict[str, Any]], news: list[dict[str, str]],
                          general_news: list[dict[str, str]] | None = None) -> list[dict[str, Any]]:
    """Associe à chaque mouvement ses actualités (flux par valeur + flux généraux déjà collectés),
    récentes et pertinentes ; sans actualité trouvée, le rapport le dit explicitement."""
    enriched = []
    for m in movers:
        candidates = [n for n in news if n.get("ticker") == m["ticker"]] + list(general_news or [])
        scored = []
        seen: set[str] = set()
        for n in candidates:
            key = re.sub(r"\W+", " ", n["title"].casefold()).strip()
            if key in seen or not is_recent(n.get("published", "")):
                continue
            score = relevance_score(n, m)
            if score >= 3:
                seen.add(key)
                scored.append((score, n))
        scored.sort(key=lambda sn: sn[0], reverse=True)
        enriched.append({**m, "news": [n for _, n in scored[:2]]})
    return enriched


# --------------------------------------------------------------------------- nettoyage des extraits
CHROME_PATTERNS = re.compile(r"(discover our|index offering|subscribe|sign up|newsletter|click here|read more|"
                             r"all rights reserved|premium feature|key data points|advertisement)", re.I)


def clean_summary(text: str) -> str:
    """Nettoie les extraits RSS avant affichage : HTML, entités, habillage et fragments tronqués."""
    # Les flux mélangent texte brut, entités HTML et balises. Décoder les entités avant
    # suppression des balises évite d'afficher &amp; / &nbsp; et de conserver du contenu caché.
    normalized = html.unescape(text or "")
    normalized = re.sub(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>", " ", normalized)
    normalized = re.sub(r"(?s)<!--.*?-->", " ", normalized)
    normalized = re.sub(r"(?s)<[^>]+>", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"“‘'])", normalized)
    kept = [s for s in sentences
            if s and not CHROME_PATTERNS.search(s)
            and not re.match(r"^\d{1,2}(,|\s+to\b|\s+and\b)", s)
            ]
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


# --------------------------------------------------------------------------- cohérence des dates de cours
def date_cohorts(rows: list[Any]) -> dict[str, list[str]]:
    """Regroupe les tickers par date de dernière cotation (clé = date ISO)."""
    cohorts: dict[str, list[str]] = {}
    for r in rows:
        stamp = str(getattr(r, "data_timestamp", "") or "")[:10]
        if stamp:
            cohorts.setdefault(stamp, []).append(r.ticker)
    return cohorts


def same_session(a: Any, b: Any) -> bool:
    """Deux cotations sont comparables si elles portent la même date."""
    da, db = str(getattr(a, "data_timestamp", "") or "")[:10], str(getattr(b, "data_timestamp", "") or "")[:10]
    return bool(da and db and da == db)


def frozen_price_suspects(rows: list[Any]) -> list[Any]:
    """Instruments non-fonds à variation de séance exactement nulle : donnée possiblement figée
    (séance asiatique en cours, jour férié ou cours non rafraîchi)."""
    return [r for r in rows
            if getattr(r, "daily_pct", None) == 0.0
            and "mutual fund" not in str(getattr(r, "asset_class", "")).casefold()]


def freshness_note(rows: list[Any], now_local: datetime) -> str | None:
    """Phrase d'avertissement sur le mélange de dates de cotation, ou None si tout est homogène."""
    cohorts = date_cohorts(rows)
    if len(cohorts) <= 1:
        return None
    ordered = sorted(cohorts.items(), key=lambda kv: kv[0])
    parts = [f"{day[8:10]}/{day[5:7]} : {len(t)} instrument{'s' if len(t) > 1 else ''}" for day, t in ordered]
    return ("Les cours n'ont pas tous la même date de séance (" + " ; ".join(parts) +
            "). Les moyennes et comparaisons entre marchés mélangent donc des séances différentes : "
            "les observations ne sont pas synchronisées : une variation observée sur un marché ne doit pas être interprétée comme une réaction simultanée sur les autres marchés. Comparer les actifs exige de tenir compte de la date propre à chaque cotation.")


# --------------------------------------------------------------------------- macro : replis officiels
def fetch_nyfed_effr() -> tuple[dict[str, Any] | None, str | None]:
    """Taux effectif des fonds fédéraux (Réserve fédérale de New York, sans clé)."""
    url = "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/2.json"
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        response.raise_for_status()
        rows = sorted(response.json().get("refRates", []), key=lambda r: r.get("effectiveDate", ""))
        if not rows:
            return None, "NY Fed EFFR: aucune observation"
        last = rows[-1]
        item: dict[str, Any] = {
            "id": "FEDFUNDS", "display_id": "EFFR", "name": "Taux effectif des fonds fédéraux", "unit": "% annuel",
            "date": last["effectiveDate"], "value": float(last["percentRate"]),
            "source": "https://www.newyorkfed.org/markets/reference-rates/effr", "provider": "NY Fed",
        }
        if len(rows) >= 2:
            item["previous_date"], item["previous_value"] = rows[-2]["effectiveDate"], float(rows[-2]["percentRate"])
            item["change"] = item["value"] - item["previous_value"]
        # Fourchette cible, si fournie
        if last.get("targetRateFrom") is not None and last.get("targetRateTo") is not None:
            item["target_range"] = f"{float(last['targetRateFrom']):.2f}–{float(last['targetRateTo']):.2f}"
        return item, None
    except Exception as exc:  # noqa: BLE001
        return None, f"NY Fed EFFR: {type(exc).__name__}: {str(exc)[:120]}"


def _treasury_url(kind: str, month: str) -> str:
    return ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
            f"?data={kind}&field_tdr_date_value_month={month}")


def parse_treasury_xml(content: bytes) -> list[dict[str, Any]]:
    """Lit le flux XML (Atom/OData) de courbes du Trésor : une entrée par jour, valeurs par échéance."""
    root = ET.fromstring(content)
    days: list[dict[str, Any]] = []
    for props in root.iter():
        if not props.tag.endswith("}properties") and props.tag != "properties":
            continue
        record: dict[str, Any] = {}
        for child in props:
            tag = child.tag.split("}")[-1]
            text = (child.text or "").strip()
            if tag == "NEW_DATE" and text:
                record["date"] = text[:10]
            elif tag.startswith(("BC_", "TC_")) and text:
                try:
                    record[tag] = float(text)
                except ValueError:
                    continue
        if record.get("date"):
            days.append(record)
    days.sort(key=lambda d: d["date"])
    return days


def fetch_treasury_curve(today: date | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Rendements 2 ans et 10 ans nominaux et anticipations d'inflation à 10 ans (nominal − réel),
    depuis le Trésor américain : repli officiel quand FRED est injoignable."""
    today = today or datetime.now(timezone.utc).date()
    months = [today.strftime("%Y%m"), (today.replace(day=1) - timedelta(days=1)).strftime("%Y%m")]
    errors: list[str] = []

    def load(kind: str) -> list[dict[str, Any]]:
        for month in months:
            try:
                response = requests.get(_treasury_url(kind, month), headers={"User-Agent": USER_AGENT}, timeout=20)
                response.raise_for_status()
                days = parse_treasury_xml(response.content)
                if days:
                    return days
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Trésor US {kind} {month}: {type(exc).__name__}: {str(exc)[:100]}")
        return []

    nominal, real = load("daily_treasury_yield_curve"), load("daily_treasury_real_yield_curve")
    out: list[dict[str, Any]] = []

    def make(sid: str, name: str, days: list[dict[str, Any]], getter: Any) -> None:
        points = [(d["date"], getter(d)) for d in days if getter(d) is not None]
        if not points:
            return
        item: dict[str, Any] = {"id": sid, "name": name, "unit": "% annuel", "date": points[-1][0], "value": points[-1][1],
                                "source": "https://home.treasury.gov/resource-center/data-chart-center/interest-rates",
                                "provider": "Trésor américain"}
        if len(points) >= 2:
            item["previous_date"], item["previous_value"] = points[-2]
            item["change"] = points[-1][1] - points[-2][1]
        out.append(item)

    make("DGS2", "Rendement du Treasury à 2 ans", nominal, lambda d: d.get("BC_2YEAR"))
    make("DGS10", "Rendement du Treasury à 10 ans", nominal, lambda d: d.get("BC_10YEAR"))
    if nominal and real:
        real_by_date = {d["date"]: d for d in real}
        def breakeven(d: dict[str, Any]) -> float | None:
            r = real_by_date.get(d["date"])
            real10 = None if not r else (r.get("TC_10YEAR") if r.get("TC_10YEAR") is not None else r.get("BC_10YEAR"))
            if d.get("BC_10YEAR") is not None and real10 is not None:
                return round(d["BC_10YEAR"] - real10, 3)
            return None
        make("T10YIE", "Anticipations d'inflation à 10 ans (breakeven, nominal moins réel)", nominal, breakeven)
    return out, errors


def fetch_ecb_deposit_rate() -> tuple[dict[str, Any] | None, str | None]:
    """Taux de la facilité de dépôt de la BCE (entrepôt de données officiel de la BCE)."""
    url = ("https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV"
           "?lastNObservations=2&format=csvdata")
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        response.raise_for_status()
        import csv
        reader = list(csv.DictReader(io.StringIO(response.text)))
        points = sorted(((r["TIME_PERIOD"], float(r["OBS_VALUE"])) for r in reader if r.get("OBS_VALUE")), key=lambda p: p[0])
        if not points:
            return None, "BCE taux de dépôt: aucune observation"
        item: dict[str, Any] = {
            "id": "ECBDFR", "name": "Taux de la facilité de dépôt de la BCE", "unit": "% annuel",
            "date": points[-1][0], "value": points[-1][1],
            "source": "https://data.ecb.europa.eu/data/datasets/FM", "provider": "BCE",
        }
        if len(points) >= 2:
            item["previous_date"], item["previous_value"] = points[-2]
            item["change"] = points[-1][1] - points[-2][1]
        return item, None
    except Exception as exc:  # noqa: BLE001
        return None, f"BCE taux de dépôt: {type(exc).__name__}: {str(exc)[:120]}"


def complete_macro(existing: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """Complète le tableau macro avec les replis officiels pour ce qui manque ; n'écrase jamais FRED."""
    have = {m["id"] for m in existing}
    errors: list[str] = []
    added: list[dict[str, Any]] = []
    if "FEDFUNDS" not in have:
        item, err = fetch_nyfed_effr()
        if item:
            added.append(item)
        if err:
            errors.append(err)
    if not {"DGS2", "DGS10", "T10YIE"} <= have:
        items, errs = fetch_treasury_curve()
        added += [i for i in items if i["id"] not in have]
        errors += errs
    item, err = fetch_ecb_deposit_rate()
    if item:
        added.append(item)
    if err:
        errors.append(err)
    order = ["CPIAUCSL", "UNRATE", "PAYEMS", "FEDFUNDS", "DGS2", "DGS10", "T10YIE", "ECBDFR"]
    merged = {m["id"]: m for m in existing}
    merged.update({a["id"]: a for a in added if a["id"] not in merged})
    return [merged[k] for k in order if k in merged] + [m for k, m in merged.items() if k not in order], errors


# --------------------------------------------------------------------------- calendrier des résultats
def parse_earnings_date(calendar: Any) -> date | None:
    """Extrait la prochaine date de résultats d'un objet `Ticker.calendar` de yfinance (dict ou DataFrame)."""
    try:
        value = calendar.get("Earnings Date") if hasattr(calendar, "get") else None
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            value = value[0] if value else None
        if value is None:
            return None
        if hasattr(value, "date") and callable(value.date):
            return value.date()
        if isinstance(value, date):
            return value
        return date.fromisoformat(str(value)[:10])
    except Exception:  # noqa: BLE001
        return None


def fetch_earnings_events(tickers: dict[str, str], today: date, days: int = 14) -> tuple[list[dict[str, Any]], list[str]]:
    """Prochains résultats des valeurs suivies. Les dates de yfinance sont des estimations :
    elles sont toujours étiquetées « à confirmer »."""
    try:
        import yfinance as yf
    except Exception as exc:  # noqa: BLE001
        return [], [f"Calendrier des résultats: yfinance indisponible ({type(exc).__name__})"]
    horizon = today + timedelta(days=days)
    events: list[dict[str, Any]] = []
    errors: list[str] = []

    def one(item: tuple[str, str]) -> tuple[dict[str, Any] | None, str | None]:
        ticker, name = item
        try:
            when = parse_earnings_date(yf.Ticker(ticker).calendar)
            if when and today <= when <= horizon:
                return {
                    "date": when.isoformat(), "time_utc": None,
                    "title": f"Résultats trimestriels : {name} ({ticker})", "region": "Entreprises",
                    "importance": "moyenne", "categories": ["actions"], "currencies": [],
                    "status": "à confirmer", "source": f"https://finance.yahoo.com/quote/{ticker}",
                    "note": "Date estimée par Yahoo Finance; vérifier le communiqué de l'entreprise. L'heure (avant ou après séance) n'est pas fournie.",
                }, None
        except Exception as exc:  # noqa: BLE001
            return None, f"résultats {ticker}: {type(exc).__name__}: {str(exc)[:80]}"
        return None, None

    with ThreadPoolExecutor(max_workers=4) as pool:
        for event, error in pool.map(one, tickers.items()):
            if event:
                events.append(event)
            if error:
                errors.append(error)
    return events, errors[:5]


# --------------------------------------------------------------------------- santé des flux
def feed_health(per_feed_counts: dict[str, int]) -> list[str]:
    """Liste des flux ayant répondu sans aucun élément exploitable (adresse probablement périmée)."""
    return sorted(name for name, count in per_feed_counts.items() if count == 0)
