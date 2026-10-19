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


def is_market_relevant(item: dict[str, str]) -> bool:
    """Vrai si l'actualité touche à un thème de marché et n'est pas du hors-sujet évident."""
    text = f"{item.get('title', '')} {item.get('summary', '')}".casefold()
    if any(marker in text for marker in OFF_TOPIC_MARKERS):
        return False
    return any(theme in text for theme in MARKET_THEMES)


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
    root = ET.fromstring(content)
    items: list[dict[str, str]] = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        if not title or not link:
            continue
        desc = re.sub(r"<[^>]+>", " ", node.findtext("description") or "")
        items.append({
            "title": title, "url": link, "source": source,
            "published": (node.findtext("pubDate") or "").strip(),
            "summary": re.sub(r"\s+", " ", desc).strip(), "ticker": ticker,
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


def attach_news_to_movers(movers: list[dict[str, Any]], news: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Associe à chaque mouvement ses actualités ; sans actualité trouvée, le dit explicitement."""
    enriched = []
    for m in movers:
        related = [n for n in news if n.get("ticker") == m["ticker"]]
        seen: set[str] = set()
        unique = []
        for n in related:
            key = re.sub(r"\W+", " ", n["title"].casefold()).strip()
            if key not in seen:
                seen.add(key)
                unique.append(n)
        enriched.append({**m, "news": unique[:2]})
    return enriched


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
            "les places asiatiques et les devises datées d'aujourd'hui précèdent la séance américaine.")


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
            elif tag.startswith("BC_") and text:
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
            if r and d.get("BC_10YEAR") is not None and r.get("BC_10YEAR") is not None:
                return round(d["BC_10YEAR"] - r["BC_10YEAR"], 3)
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
