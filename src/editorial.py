"""Composition éditoriale du rapport : construit un modèle structuré (sections et blocs).

Le modèle est ensuite rendu en HTML (render_report.py) et en texte brut (courriel, archive).
Ce module ne fait aucun accès réseau et n'importe rien de market_report.py : toutes les
données arrivent par le dictionnaire `ctx`, ce qui le rend entièrement testable hors ligne.
"""
from __future__ import annotations

import html
import math
import re
from datetime import date
from typing import Any, Callable

try:  # import en tant que paquet (tests : src.editorial)
    from . import calendar_events
    from . import enrichment
except ImportError:  # exécution en script (python src/market_report.py)
    import calendar_events  # type: ignore[no-redef]
    import enrichment  # type: ignore[no-redef]

NBSP = "\u00a0"
NNBSP = "\u202f"
WORDS_PER_MINUTE = 220  # lecture silencieuse d'un texte d'analyse en français
TABLE_WORD_WEIGHT = 0.35  # un tableau se parcourt plus qu'il ne se lit

KIND_LABELS = {
    "morning": "Rapport du matin",
    "update": "Point de la mi-journée",
    "audit": "Bilan de la séance",
    "weekly": "Perspectives de la semaine",
}

CATEGORIES: list[dict[str, Any]] = [
    {"key": "indices", "label": "Indices boursiers",
     "intro": "Les grands indices donnent la température du marché actions : direction, leadership entre régions et niveau de nervosité mesuré par le VIX.",
     "match": lambda r: r.ticker == "^VIX" or ("equity index" in r.asset_class.casefold() and "futures" not in r.asset_class.casefold()),
     "keywords": ("stock market", "equity index", "indices", "index", "market selloff", "market rally", "global shares", "global stocks")},
    {"key": "futures", "label": "Futures sur indices",
     "intro": "Les contrats à terme cotent presque en continu : ils signalent l'humeur à l'ouverture suivante, avant que les indices au comptant ne réagissent.",
     "match": lambda r: "equity index futures" in r.asset_class.casefold(),
     "keywords": ("equity index futures", "nasdaq futures", "s&p 500 futures", "dow futures", "index futures", "futures point to", "stock futures")},
    {"key": "actions", "label": "Actions",
     "intro": "Les valeurs individuelles révèlent ce que les indices moyennent : leadership sectoriel, dispersion et réaction aux résultats d'entreprise.",
     "match": lambda r: r.asset_class.casefold() in {"us equity", "european equity", "asian equity", "equity"},
     "keywords": ("earnings", "quarterly results", "revenue", "profit warning", "guidance", "shares of", "stock rises", "stock falls", "semiconductor", "capital expenditure", "company reports")},
    {"key": "matieres", "label": "Matières premières",
     "intro": "Énergie, métaux et produits agricoles transmettent les chocs d'offre, la demande industrielle et les anticipations d'inflation.",
     "match": lambda r: "commodity" in r.asset_class.casefold(),
     "keywords": ("oil", "crude", "brent", "gold", "silver", "copper", "natural gas", "opec", "commodity", "commodities", "supply disruption", "agriculture", "coffee")},
    {"key": "devises", "label": "Devises",
     "intro": "Le change arbitre entre écarts de taux, croissance relative et demande de valeurs refuges ; le dollar en est le pivot.",
     "match": lambda r: r.asset_class.casefold() == "fx",
     "keywords": ("forex", "currency", "currencies", "dollar", "euro", "yen", "exchange rate", "fx market", "fed rate", "central bank decision", "interest-rate decision")},
    {"key": "crypto", "label": "Crypto-monnaies",
     "intro": "Les actifs numériques cotent jour et nuit, week-end compris : ils servent souvent de baromètre d'appétit pour le risque entre deux séances boursières.",
     "match": lambda r: r.asset_class.casefold() == "crypto",
     "keywords": ("bitcoin", "ethereum", "crypto", "digital asset", "cryptoasset", "spot bitcoin etf")},
    {"key": "obligations", "label": "Obligations",
     "intro": "Les taux d'intérêt fixent le prix de l'argent : leur niveau, leur pente et leurs variations conditionnent la valorisation de tous les autres actifs.",
     "match": lambda r: r.asset_class.casefold() in {"rates", "bond futures"},
     "keywords": ("bond", "bonds", "treasury yield", "bond yield", "credit spread", "credit market", "debt issuance", "fixed income")},
    {"key": "etf", "label": "ETF",
     "intro": "Les fonds indiciels cotés permettent de lire les rotations : grandes contre petites capitalisations, technologie contre énergie, crédit contre emprunts d'État.",
     "match": lambda r: "etf" in r.asset_class.casefold(),
     "keywords": ("etf", "exchange-traded fund", "fund flows", "inflows into etfs", "outflows from etfs", "passive investing")},
    {"key": "fonds", "label": "Fonds d'investissement",
     "intro": "Les fonds communs ne publient qu'une valeur liquidative par jour : leur variation reflète la clôture, pas la séance en cours.",
     "match": lambda r: "mutual fund" in r.asset_class.casefold(),
     "keywords": ("mutual fund", "investment fund", "fund manager", "mutual fund flows", "fund asset allocation", "portfolio flows")},
]
CATEGORY_LABELS = {c["key"]: c["label"] for c in CATEGORIES}

CURRENCY_TICKERS = {"USD": "DX-Y.NYB", "EUR": "EURUSD=X", "JPY": "USDJPY=X", "GBP": "GBPUSD=X",
                    "AUD": "AUDUSD=X", "NZD": "NZDUSD=X", "CAD": "USDCAD=X", "CHF": "USDCHF=X",
                    "CNY": "USDCNY=X", "INR": "USDINR=X"}


# ----------------------------------------------------------------------------- formatage
def fr_num(value: float | None, digits: int = 2, signed: bool = False) -> str:
    if value is None or not isinstance(value, (int, float)) or not math.isfinite(value):
        return "n.d."
    body = f"{abs(value):,.{digits}f}".replace(",", NNBSP).replace(".", ",")
    if value < 0 and float(body.replace(NNBSP, "").replace(",", ".")) != 0:
        return "−" + body
    return ("+" + body) if signed and value > 0 else body


def fr_pct(value: float | None, digits: int = 2, signed: bool = True) -> str:
    text = fr_num(value, digits, signed)
    return text if text == "n.d." else text + NBSP + "%"


def fmt_level(row: Any) -> str:
    price = getattr(row, "price", None)
    if price is None:
        return "n.d."
    if str(row.asset_class).casefold() == "rates":
        return fr_num(price, 3) + NBSP + "%"
    return fr_num(price, 4 if abs(price) < 10 else 2)


def fr_pp(value: float, signed: bool = False) -> str:
    """Points de pourcentage, avec accord (le pluriel commence à 2)."""
    return f"{fr_num(value, 2, signed)} {'point' if abs(value) < 2 else 'points'} de pourcentage"


def fr_bp(value: float) -> str:
    return f"{fr_num(value, 1, True)} {'point' if abs(value) < 2 else 'points'} de base"


def fr_text(text: str) -> str:
    """Met au format français les pourcentages à virgule décimale anglaise (« -1.95 % » devient « −1,95 % »)."""
    def fix(m: re.Match[str]) -> str:
        sign = "−" if m.group(1) == "-" else m.group(1)
        return f"{sign}{m.group(2)},{m.group(3)}{NBSP}%"
    return re.sub(r"(?<![\w.])([+-]?)(\d+)\.(\d+)\s?%", fix, text)


def plural(n: int, one: str, many: str) -> str:
    return one if n in (0, 1) else many


def _present(values: list[Any]) -> list[float]:
    return [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(v)]


def _avg(values: list[Any]) -> float | None:
    vals = _present(values)
    return sum(vals) / len(vals) if vals else None


def _by_ticker(rows: list[Any]) -> dict[str, Any]:
    return {r.ticker: r for r in rows}


def _move(row: Any, attr: str = "daily_pct") -> str:
    return fr_pct(getattr(row, attr, None)) if row is not None else "n.d."


def _direction_word(pct: float | None) -> str:
    if pct is None:
        return "est indisponible"
    if pct >= 1:
        return "progresse nettement"
    if pct >= 0.2:
        return "progresse"
    if pct <= -1:
        return "recule nettement"
    if pct <= -0.2:
        return "recule"
    return "est quasi stable"


def _sigma_daily(row: Any) -> float | None:
    vol = getattr(row, "annualized_vol_pct", None)
    return float(vol) / math.sqrt(252) if isinstance(vol, (int, float)) and vol > 0 else None


def _zscore(row: Any) -> float | None:
    sigma = _sigma_daily(row)
    daily = getattr(row, "daily_pct", None)
    if sigma and daily is not None:
        return daily / sigma
    return None


def _yield_bps(row: Any) -> float | None:
    """Variation quotidienne d'un rendement exprimée en points de base."""
    if row is None or row.price is None or row.daily_pct is None:
        return None
    return row.price * row.daily_pct  # price en %, daily_pct en % du niveau : (p*d/100)*100 pb


def _first_sentence(text: str) -> str:
    return text.strip()


# ----------------------------------------------------------------------------- analyses par univers
def _breadth_paragraph(rows: list[Any], noun: str = "instruments", suivi: str = "suivis") -> str:
    n = len(rows)
    daily = [r for r in rows if r.daily_pct is not None]
    if not daily:
        return f"Aucune variation de séance exploitable n'a été reçue pour ces {noun}."
    up = sum(r.daily_pct > 0 for r in daily)
    down = sum(r.daily_pct < 0 for r in daily)
    ordered = sorted(daily, key=lambda r: r.daily_pct, reverse=True)
    five = [r for r in rows if r.five_day_pct is not None]
    month = [r for r in rows if r.one_month_pct is not None]
    text = (f"Sur les {n} {noun} {suivi}, {up} progressent et {down} reculent sur la dernière séance ; "
            f"la variation moyenne, non pondérée, ressort à {fr_pct(_avg([r.daily_pct for r in daily]))}.")
    if len(ordered) >= 2:
        text += (f" {ordered[0].name} mène le groupe ({fr_pct(ordered[0].daily_pct)}) et "
                 f"{ordered[-1].name} ferme la marche ({fr_pct(ordered[-1].daily_pct)}).")
    if five:
        text += f" Sur cinq séances, {sum(r.five_day_pct > 0 for r in five)} sur {len(five)} sont en hausse"
        text += (f" ; sur un mois, {sum(r.one_month_pct > 0 for r in month)} sur {len(month)}." if month else ".")
    return text


def _vix_reading(vix: Any) -> str:
    if vix is None or vix.price is None:
        return ""
    level = vix.price
    daily = getattr(vix, "daily_pct", None)
    if level < 15:
        zone = "niveau historiquement bas : la protection est relativement peu demandée"
    elif level < 20:
        zone = "niveau inférieur au seuil conventionnel de 20"
    elif level < 30:
        zone = "niveau de tension : la demande de protection est élevée"
    else:
        zone = "niveau de stress : la protection est chère"
    text = f"Le VIX, mesure de la volatilité implicite attendue du S&P 500, s'établit à {fr_num(level, 2)} : {zone}."
    if daily is not None and daily >= 15:
        text += f" Attention toutefois : il bondit de {fr_pct(daily)} sur la dernière séance disponible, mouvement rapide qui signale une remontée nette de la demande de protection malgré un niveau encore sous 20."
    elif daily is not None and daily <= -15:
        text += f" Il recule de {fr_pct(daily)} sur la dernière séance disponible, signe d'une détente rapide de la demande de protection."
    else:
        text += f" Variation sur la séance : {_move(vix)}."
    return text


def _analyse_indices(rows: list[Any], by: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    paragraphs = [_breadth_paragraph([r for r in rows if r.ticker != "^VIX"], "indices")]
    sp, nq, dj = by.get("^GSPC"), by.get("^IXIC"), by.get("^DJI")
    if sp and nq:
        text = (f"Aux États-Unis, le S&P 500 {_direction_word(sp.daily_pct)} sur la séance ({_move(sp)}) et {_move(sp, 'five_day_pct')} sur cinq séances ; "
                f"le Nasdaq Composite affiche {_move(nq)} puis {_move(nq, 'five_day_pct')}")
        text += f", le Dow Jones {_move(dj)} puis {_move(dj, 'five_day_pct')}." if dj else "."
        if sp.five_day_pct is not None and nq.five_day_pct is not None:
            gap = nq.five_day_pct - sp.five_day_pct
            if abs(gap) >= 0.5:
                text += (f" L'écart de {fr_pp(abs(gap))} en faveur du Nasdaq montre que la technologie tire le marché."
                         if gap > 0 else
                         f" Le Nasdaq fait moins bien que le S&P 500 de {fr_pp(abs(gap))} sur cinq séances : la technologie pèse sur l'ensemble.")
        paragraphs.append(text)
    others = [r for r in rows if r.ticker not in {"^GSPC", "^IXIC", "^DJI", "^VIX"} and r.daily_pct is not None]
    if others and sp and sp.daily_pct is not None:
        europe = [r for r in others if r.ticker in {"^STOXX50E", "^FTSE", "^GDAXI", "^FCHI"}]
        asia = [r for r in others if r.ticker in {"^N225", "^HSI", "^AXJO", "^KS11", "^NSEI"}]
        parts = []
        if europe:
            parts.append(f"les indices européens {fr_pct(_avg([r.daily_pct for r in europe]))} en moyenne")
        if asia:
            parts.append(f"les indices asiatiques et océaniens {fr_pct(_avg([r.daily_pct for r in asia]))}")
        if parts:
            paragraphs.append("Ailleurs dans le monde, " + " et ".join(parts) + f", contre {_move(sp)} pour le S&P 500. "
                              "Les fuseaux horaires diffèrent : les séances asiatiques précèdent les séances américaines et n'en intègrent pas encore les mouvements.")
    vix = _vix_reading(by.get("^VIX"))
    if vix:
        paragraphs.append(vix)
    return paragraphs


def _analyse_futures(rows: list[Any], by: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    paragraphs = [_breadth_paragraph(rows, "contrats")]
    pairs = [("ES=F", "^GSPC", "S&P 500"), ("NQ=F", "^IXIC", "Nasdaq"), ("YM=F", "^DJI", "Dow Jones")]
    notes = []
    for fut, cash, label in pairs:
        f, c = by.get(fut), by.get(cash)
        if f and c and f.daily_pct is not None and c.daily_pct is not None:
            gap = f.daily_pct - c.daily_pct
            notes.append(f"{label} : contrat {fr_pct(f.daily_pct)} contre {fr_pct(c.daily_pct)} pour l'indice")
            if abs(gap) >= 0.3:
                notes[-1] += f" (écart de {fr_pp(abs(gap))}, {'les contrats anticipent un meilleur départ' if gap > 0 else 'les contrats annoncent un départ plus faible'})"
    if notes:
        paragraphs.append("Comparaison avec le marché au comptant : " + " ; ".join(notes) + ". "
                          "Un écart peut venir de l'heure de clôture ou d'un mouvement survenu après la fin de la séance : il se lit à l'ouverture, pas avant.")
    return paragraphs


def _analyse_actions(rows: list[Any], by: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    paragraphs = [_breadth_paragraph(rows, "valeurs", "suivies")]
    groups = {"américaines": [r for r in rows if r.asset_class == "US equity"],
              "européennes": [r for r in rows if r.asset_class == "European equity"],
              "asiatiques": [r for r in rows if r.asset_class == "Asian equity"]}
    parts = [f"{label} {fr_pct(_avg([r.daily_pct for r in g]))} ({len(g)} {plural(len(g), 'valeur', 'valeurs')})"
             for label, g in groups.items() if g and _avg([r.daily_pct for r in g]) is not None]
    if len(parts) >= 2:
        paragraphs.append("Par région, la variation moyenne de séance est de : " + " ; ".join(parts) + ". "
                          "L'échantillon est restreint (une trentaine de valeurs phares) : il illustre la tendance des grandes capitalisations, pas celle de tout le marché.")
    movers = sorted([r for r in rows if _zscore(r) is not None], key=lambda r: abs(_zscore(r)), reverse=True)[:3]
    if movers:
        paragraphs.append("Les mouvements les plus inhabituels par rapport à la volatilité propre de chaque titre : " +
                          " ; ".join(f"{r.name} ({fr_pct(r.daily_pct)}, soit {fr_num(_zscore(r), 1, True)} écart-type)" for r in movers) + ".")
    for item in (ctx.get("fundamentals") or [])[:8]:
        bits = []
        if item.get("revenue_yoy_pct") is not None:
            bits.append(f"chiffre d'affaires {fr_pct(item['revenue_yoy_pct'], 1)} sur un an")
        if item.get("eps_yoy_pct") is not None:
            bits.append(f"bénéfice par action dilué {fr_pct(item['eps_yoy_pct'], 1)}")
        if item.get("operating_margin_pct") is not None:
            bits.append(f"marge opérationnelle de {fr_pct(item['operating_margin_pct'], 1, False)}")
        if bits:
            paragraphs.append(f"{item['name']}, dernier trimestre publié à la SEC (clôturé le {item.get('period', 'date inconnue')}) : " + ", ".join(bits) +
                              ". Ce sont des chiffres publiés, pas des surprises par rapport au consensus.")
    return paragraphs


def _analyse_matieres(rows: list[Any], by: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    paragraphs = [_breadth_paragraph(rows, "matières premières", "suivies")]
    wti, brent = by.get("CL=F"), by.get("BZ=F")
    if wti and brent and wti.price and brent.price:
        paragraphs.append(f"Énergie : le Brent cote {fr_num(brent.price, 2)} dollars ({_move(brent)}) et le WTI {fr_num(wti.price, 2)} dollars ({_move(wti)}) ; "
                          f"l'écart Brent–WTI est de {fr_num(brent.price - wti.price, 2)} dollars le baril. Un écart qui s'élargit signale une tension propre au marché mondial plutôt qu'américain.")
    elif wti:
        paragraphs.append(f"Énergie : le WTI {_direction_word(wti.daily_pct)} ({_move(wti)}) à {fr_num(wti.price, 2)} dollars.")
    gold, silver, copper = by.get("GC=F"), by.get("SI=F"), by.get("HG=F")
    metals = []
    if gold and silver and gold.price and silver.price:
        metals.append(f"le rapport or/argent s'établit à {fr_num(gold.price / silver.price, 1)} (une hausse du ratio traduit une préférence pour le refuge sur le métal industriel)")
    if gold:
        metals.append(f"l'or {_direction_word(gold.daily_pct)} ({_move(gold)})")
    if copper:
        metals.append(f"le cuivre, baromètre de la demande industrielle, {_direction_word(copper.daily_pct)} ({_move(copper)})")
    if metals:
        paragraphs.append("Métaux : " + " ; ".join(metals) + ".")
    agri = [r for r in rows if "agricultural" in r.asset_class.casefold() and r.daily_pct is not None]
    if agri:
        paragraphs.append(f"Produits agricoles : variation moyenne de {fr_pct(_avg([r.daily_pct for r in agri]))} sur la séance pour {len(agri)} contrats (maïs, blé, soja, café).")
    return paragraphs


def _analyse_devises(rows: list[Any], by: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    paragraphs = [_breadth_paragraph([r for r in rows if r.ticker != "DX-Y.NYB"], "paires", "suivies")]
    dxy = by.get("DX-Y.NYB")
    usd_quoted_second = ["EURUSD=X", "GBPUSD=X", "AUDUSD=X", "NZDUSD=X"]
    usd_quoted_first = ["USDJPY=X", "USDCAD=X", "USDCHF=X", "USDCNY=X", "USDINR=X"]
    ups = downs = 0
    for t in usd_quoted_second:
        r = by.get(t)
        if r and r.daily_pct is not None:
            ups += r.daily_pct < 0
            downs += r.daily_pct > 0
    for t in usd_quoted_first:
        r = by.get(t)
        if r and r.daily_pct is not None:
            ups += r.daily_pct > 0
            downs += r.daily_pct < 0
    if dxy and dxy.price:
        text = (f"L'indice du dollar s'établit à {fr_num(dxy.price, 2)} ({_move(dxy)} sur la séance, {_move(dxy, 'five_day_pct')} sur cinq séances).")
        if ups + downs:
            text += f" Face aux {ups + downs} devises mesurées contre lui, le dollar progresse contre {ups} et recule contre {downs} : "
            text += "mouvement généralisé" if max(ups, downs) >= 0.75 * (ups + downs) else "mouvement partagé, sans tendance nette"
            text += "."
        weights = {"EURUSD=X": -0.576, "USDJPY=X": 0.136, "GBPUSD=X": -0.119, "USDCAD=X": 0.091, "USDCHF=X": 0.036}
        parts = [(w, by[t].daily_pct) for t, w in weights.items() if by.get(t) and by[t].daily_pct is not None]
        if len(parts) >= 4 and dxy.daily_pct is not None:
            implied = sum(w * p for w, p in parts)
            if abs(dxy.daily_pct - implied) > 0.12:
                text += (f" Incohérence à noter : les paires qui composent l'indice impliquent environ {fr_pct(implied)}, "
                         f"contre {fr_pct(dxy.daily_pct)} affichés : la cotation de l'indice est probablement décalée ; se fier aux paires.")
        pair_days = {str(by[t].data_timestamp)[:10] for t in usd_quoted_second + usd_quoted_first if by.get(t) and by[t].data_timestamp}
        dxy_day = str(dxy.data_timestamp)[:10] if dxy.data_timestamp else ""
        if pair_days and dxy_day and dxy_day not in pair_days:
            text += (f" Attention : l'indice du dollar est daté du {dxy_day[8:10]}/{dxy_day[5:7]} alors que les paires sont datées du "
                     f"{'/'.join(sorted(d[8:10] + '/' + d[5:7] for d in pair_days))} : les deux lectures ne portent pas sur la même séance.")
        paragraphs.append(text)
    jpy, eur, gbp = by.get("USDJPY=X"), by.get("EURUSD=X"), by.get("GBPUSD=X")
    detail = []
    if eur:
        detail.append(f"EUR/USD à {fr_num(eur.price, 4)} ({_move(eur)})")
    if gbp:
        detail.append(f"GBP/USD à {fr_num(gbp.price, 4)} ({_move(gbp)})")
    if jpy:
        detail.append(f"USD/JPY à {fr_num(jpy.price, 2)} ({_move(jpy)})")
    if detail:
        paragraphs.append("Principales paires : " + ", ".join(detail) + ". Sur le yen, le risque d'intervention officielle limite l'intérêt de poursuivre un mouvement de hausse du dollar.")
    return paragraphs


def _analyse_crypto(rows: list[Any], by: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    paragraphs = [_breadth_paragraph(rows, "crypto-monnaies", "suivies")]
    btc, eth, nq = by.get("BTC-USD"), by.get("ETH-USD"), by.get("^IXIC")
    if btc and btc.price:
        text = f"Le bitcoin cote {fr_num(btc.price, 0)} dollars ({_move(btc)} sur 24 heures, {_move(btc, 'five_day_pct')} sur cinq jours, {_move(btc, 'one_month_pct')} sur un mois)."
        if eth and eth.five_day_pct is not None and btc.five_day_pct is not None:
            gap = eth.five_day_pct - btc.five_day_pct
            text += f" L'ether fait {'mieux' if gap > 0 else 'moins bien'} que le bitcoin de {fr_pp(abs(gap))} sur cinq jours, signe d'un appétit pour le risque {'plus' if gap > 0 else 'moins'} marqué au sein du secteur."
        paragraphs.append(text)
    if btc and nq and btc.daily_pct is not None and nq.daily_pct is not None:
        same = (btc.daily_pct > 0) == (nq.daily_pct > 0)
        paragraphs.append(f"Le bitcoin ({_move(btc)}) et le Nasdaq ({_move(nq)}) vont {'dans le même sens' if same else 'en sens opposés'} sur la dernière séance. "
                          "Les horaires ne se recouvrent pas (24 heures sur 24 contre une séance), et une seule séance ne suffit pas à conclure à une corrélation.")
    return paragraphs


def _analyse_obligations(rows: list[Any], by: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    paragraphs = []
    curve = [(by.get(t), label) for t, label in (("^IRX", "3 mois"), ("^FVX", "5 ans"), ("^TNX", "10 ans"), ("^TYX", "30 ans")) if by.get(t) and by[t].price]
    if curve:
        parts = []
        for row, label in curve:
            bps = _yield_bps(row)
            parts.append(f"{label} à {fr_num(row.price, 3)} %" + (f" ({fr_bp(bps)})" if bps is not None else ""))
        paragraphs.append("Courbe des taux américains : " + ", ".join(parts) + ".")
        irx, tnx, fvx, tyx = by.get("^IRX"), by.get("^TNX"), by.get("^FVX"), by.get("^TYX")
        slopes = []
        if irx and tnx and irx.price and tnx.price:
            slopes.append(f"10 ans moins 3 mois : {fr_num((tnx.price - irx.price) * 100, 0, True)} points de base")
        if fvx and tyx and fvx.price and tyx.price:
            slopes.append(f"30 ans moins 5 ans : {fr_num((tyx.price - fvx.price) * 100, 0, True)} points de base")
        macro = {m["id"]: m for m in ctx.get("macro") or []}
        if "DGS10" in macro and "DGS2" in macro:
            slopes.append(f"10 ans moins 2 ans ({macro['DGS10'].get('provider', 'FRED')}, {macro['DGS10']['date']}) : {fr_num((macro['DGS10']['value'] - macro['DGS2']['value']) * 100, 0, True)} points de base")
        if slopes:
            paragraphs.append("Pente de la courbe : " + " ; ".join(slopes) + ". Une pente négative (courbe inversée) a historiquement précédé les ralentissements ; une pente qui se redresse peut refléter des baisses de taux anticipées ou une prime de terme plus élevée : la pente seule ne tranche pas.")
    futs = [by.get("ZN=F"), by.get("ZB=F")]
    futs = [f for f in futs if f and f.daily_pct is not None]
    if futs:
        paragraphs.append("Contrats à terme sur emprunts du Trésor : " + ", ".join(f"{f.name} {_move(f)}" for f in futs) +
                          ". Le prix d'une obligation évolue à l'inverse de son rendement : un contrat qui monte correspond à des taux qui baissent."
                          + (_bond_date_gap_note(by, futs) or ""))
    if not paragraphs:
        paragraphs.append(_breadth_paragraph(rows, "instruments"))
    return paragraphs


def _bond_date_gap_note(by: dict[str, Any], futs: list[Any]) -> str | None:
    """Les futures de taux cotent presque en continu, les rendements au comptant s'arrêtent à la clôture :
    sans cet avertissement, « contrat en hausse » et « rendement en hausse » semblent se contredire."""
    tnx = by.get("^TNX")
    if not tnx or not tnx.data_timestamp:
        return None
    tnx_day = str(tnx.data_timestamp)[:10]
    later = [f for f in futs if f.data_timestamp and str(f.data_timestamp)[:10] > tnx_day]
    if not later:
        return None
    day = str(later[0].data_timestamp)[:10]
    return (f" Les contrats sont datés du {day[8:10]}/{day[5:7]} et les rendements au comptant du {tnx_day[8:10]}/{tnx_day[5:7]} : "
            "les futures intègrent déjà la réouverture, ce qui explique qu'ils puissent monter pendant que le dernier rendement coté était en hausse.")


def _relative(by: dict[str, Any], a: str, b: str, attr: str = "five_day_pct") -> tuple[float, Any, Any] | None:
    ra, rb = by.get(a), by.get(b)
    if ra and rb and getattr(ra, attr) is not None and getattr(rb, attr) is not None:
        return getattr(ra, attr) - getattr(rb, attr), ra, rb
    return None


def _analyse_etf(rows: list[Any], by: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    paragraphs = [_breadth_paragraph(rows, "ETF")]
    meanings = [
        ("IWM", "SPY", "petites capitalisations face aux grandes", "les petites valeurs, plus sensibles aux taux et au crédit, devancent le marché large", "les grandes valeurs, jugées plus défensives, résistent mieux"),
        ("XLK", "XLE", "technologie face à l'énergie", "la croissance domine les cycliques de l'énergie", "l'énergie fait mieux que la technologie"),
        ("EEM", "EFA", "émergents face aux pays développés hors États-Unis", "l'appétit pour les marchés émergents progresse", "les marchés développés sont préférés aux émergents"),
        ("HYG", "IEF", "crédit à haut rendement face aux emprunts d'État", "le crédit risqué fait mieux que les emprunts d'État, signe d'appétit pour le risque", "le crédit risqué sous-performe les emprunts d'État, signe de prudence"),
        ("GLD", "SPY", "or face aux actions américaines", "le refuge or devance les actions", "les actions devancent le refuge or"),
    ]
    lines = []
    for a, b, label, pos, neg in meanings:
        rel = _relative(by, a, b)
        if rel:
            gap = rel[0]
            lines.append(f"{label} : {fr_pp(gap, True)} sur cinq séances ({pos if gap > 0 else neg})")
    if lines:
        paragraphs.append("Rotations sur cinq séances, lues par différence de performance : " + " ; ".join(lines) + ".")
    return paragraphs


def _analyse_fonds(rows: list[Any], by: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    paragraphs = [_breadth_paragraph(rows, "fonds")]
    paragraphs.append("Un fonds commun est valorisé une fois par jour, après la clôture américaine : sa variation de séance reflète la veille de bourse, et la date indiquée dans le tableau fait foi. "
                      "Pour juger l'écart entre gestion indicielle et gestion active, comparer sur plusieurs mois plutôt que sur une journée.")
    vf, spy = by.get("VFIAX"), by.get("SPY")
    if vf and spy and vf.five_day_pct is not None and spy.five_day_pct is not None:
        paragraphs.append(f"Contrôle de cohérence : le fonds indiciel VFIAX affiche {_move(vf, 'five_day_pct')} sur cinq séances, l'ETF SPY {_move(spy, 'five_day_pct')} : les deux répliquent le même indice, l'écart doit rester minime.")
    return paragraphs


ANALYSERS: dict[str, Callable[[list[Any], dict[str, Any], dict[str, Any]], list[str]]] = {
    "indices": _analyse_indices, "futures": _analyse_futures, "actions": _analyse_actions,
    "matieres": _analyse_matieres, "devises": _analyse_devises, "crypto": _analyse_crypto,
    "obligations": _analyse_obligations, "etf": _analyse_etf, "fonds": _analyse_fonds,
}


# ----------------------------------------------------------------------------- blocs
def spark_values(sparks: dict[str, list[float]], ticker: str) -> list[float] | None:
    values = sparks.get(ticker)
    return values if values and len(values) >= 5 else None


def instrument_table(rows: list[Any], sparks: dict[str, list[float]]) -> dict[str, Any]:
    table_rows = []
    for r in sorted(rows, key=lambda x: (x.daily_pct is None, -(x.daily_pct or 0))):
        def pct_cell(v: float | None) -> dict[str, Any]:
            return {"t": fr_pct(v), "cls": ("up" if v and v > 0 else "down" if v and v < 0 else "")}
        table_rows.append([
            {"t": r.name, "sub": r.ticker}, {"t": fmt_level(r)}, pct_cell(r.daily_pct), pct_cell(r.five_day_pct),
            pct_cell(r.one_month_pct), {"spark": spark_values(sparks, r.ticker)}, {"t": r.data_timestamp or "n.d."},
        ])
    return {"kind": "table", "caption": "Instruments suivis", "numeric": {1, 2, 3, 4},
            "headers": ["Instrument", "Dernier", "1 séance", "5 séances", "1 mois", "30 jours", "Cours du"], "rows": table_rows}


def _event_line(event: dict[str, Any]) -> str:
    when = calendar_events.format_day(event["local_date"])
    if event.get("local_time"):
        when += f" à {event['local_time']} (heure de Madagascar)"
    return f"{when} : {event['title']} ({event['status']})."


def _events_for(ctx: dict[str, Any], key: str, limit: int = 2) -> list[dict[str, Any]]:
    return [e for e in ctx.get("calendar", []) if key in (e.get("categories") or [])][:limit]


def _scrub_source_suffix(line: str) -> str:
    return re.sub(r"\s+—\s+Source des cours\s*:.*$", "", line).strip()


# ----------------------------------------------------------------------------- sections
def _headline(ctx: dict[str, Any], by: dict[str, Any]) -> tuple[str, str]:
    scenario = ctx.get("scenario") or {}
    sp, vix = by.get("^GSPC"), by.get("^VIX")
    stance = scenario.get("stance", "Régime indéterminé")
    sp5 = sp.five_day_pct if sp else None
    vixd = vix.daily_pct if vix else None
    if sp5 is not None and vixd is not None and sp5 <= -1 and vixd >= 8:
        head = f"Aversion au risque : le S&P 500 cède {fr_pct(abs(sp5), 2, False)} sur cinq séances et le VIX bondit de {fr_pct(vixd, 1, False)}."
    elif sp5 is not None and sp5 >= 1 and (vixd is None or vixd <= 0):
        head = f"Appétit pour le risque : le S&P 500 gagne {fr_pct(sp5, 2, False)} sur cinq séances dans une volatilité contenue."
    elif sp5 is not None:
        head = f"Marchés sans direction tranchée : le S&P 500 affiche {fr_pct(sp5)} sur cinq séances, le VIX {fr_pct(vixd, 1)} sur la dernière."
    else:
        head = f"Panorama de {len(ctx.get('rows', []))} actifs : régime {stance.lower()}."
    if ctx.get("kind") == "weekly":
        head = "Semaine écoulée. " + head
    probs = scenario.get("probabilities") or {}
    dek = stance + "."
    if probs:
        dek += (f" Probabilités expérimentales à un horizon de une à cinq séances : hausse {probs.get('haussier')} %, "
                f"zone centrale {probs.get('central')} %, baisse {probs.get('baissier')} %. "
                "Elles sont issues d'une règle simple et n'ont pas été calibrées statistiquement.")
    return head, dek


def _takeaways(ctx: dict[str, Any], by: dict[str, Any]) -> list[str]:
    items: list[str] = []
    sp, nq, vix = by.get("^GSPC"), by.get("^IXIC"), by.get("^VIX")
    if sp:
        items.append(f"Actions américaines : S&P 500 {_move(sp)} sur la séance et {_move(sp, 'five_day_pct')} sur cinq séances ; Nasdaq {_move(nq)} puis {_move(nq, 'five_day_pct')}." if nq else
                     f"Actions américaines : S&P 500 {_move(sp)} sur la séance et {_move(sp, 'five_day_pct')} sur cinq séances.")
    if vix and vix.price:
        items.append(_vix_reading(vix))
    tnx, dxy = by.get("^TNX"), by.get("DX-Y.NYB")
    if tnx and tnx.price:
        bps = _yield_bps(tnx)
        text = f"Taux : le rendement américain à 10 ans s'établit à {fr_num(tnx.price, 3)} %"
        text += f" ({fr_bp(bps)})" if bps is not None else ""
        if dxy and dxy.price:
            text += f" ; l'indice du dollar est à {fr_num(dxy.price, 2)} ({_move(dxy)})"
        items.append(text + ".")
    oil, gold = by.get("BZ=F") or by.get("CL=F"), by.get("GC=F")
    if oil or gold:
        bits = []
        if oil:
            bits.append(f"{oil.name} {_move(oil)}")
        if gold:
            bits.append(f"or {_move(gold)}")
        items.append("Matières premières : " + ", ".join(bits) + " sur la séance.")
    btc = by.get("BTC-USD")
    if btc:
        items.append(f"Crypto : bitcoin à {fr_num(btc.price, 0)} dollars ({_move(btc)} sur 24 heures).")
    deep = [m for m in (ctx.get("movers") or []) if m.get("five_day_pct") is not None and abs(m["five_day_pct"]) >= 5]
    if deep:
        items.append("Mouvements de fond à surveiller : " + " ; ".join(
            f"{m['name']} {fr_pct(m['five_day_pct'])} sur cinq séances" + (f" et {fr_pct(m['one_month_pct'])} sur un mois" if m.get("one_month_pct") is not None and abs(m["one_month_pct"]) >= 5 else "")
            for m in deep[:3]) + ".")
    top = next((e for e in ctx.get("calendar", []) if e["importance"] == "élevée"), None)
    if top:
        items.append("Prochain rendez-vous majeur : " + _event_line(top))
    if ctx.get("weekend"):
        items.append("Les marchés d'actions, de taux et de change sont fermés ce week-end : les cours ci-dessous datent de la dernière séance et seule la crypto cote en continu.")
    return items


def _regime_blocks(ctx: dict[str, Any], by: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = ctx.get("scenario") or {}
    blocks: list[dict[str, Any]] = []
    probs = scenario.get("probabilities")
    if probs:
        blocks.append({"kind": "p", "text": f"Notre règle de lecture croise le momentum des grands indices américains et le mouvement du VIX pour dégager un diagnostic : {scenario.get('stance', 'indéterminé').lower()} (score {fr_num(scenario.get('score', 0), 0, True)})."})
        blocks.append({"kind": "probs", "probs": probs, "note": "Probabilités expérimentales, non calibrées. La zone centrale désigne un mouvement du S&P 500 inférieur à une demi-volatilité quotidienne, dans un sens ou dans l'autre."})
    if scenario.get("evidence"):
        blocks.append({"kind": "list", "items": [fr_text(e if e.endswith(".") else e + ".") for e in scenario["evidence"]]})
    cross = [fr_text(_scrub_source_suffix(x)) for x in ctx.get("cross_lines", []) if "Pas assez de données" not in x]
    if cross:
        blocks.append({"kind": "h3", "text": "Interactions entre marchés"})
        blocks.append({"kind": "list", "items": cross})
    if ctx.get("freshness_note"):
        blocks.append({"kind": "note", "text": ctx["freshness_note"]})
    macro = ctx.get("macro") or []
    if macro:
        blocks.append({"kind": "h3", "text": "Tableau de bord macroéconomique"})
        has_change = any(m.get("change") is not None for m in macro)
        rows = []
        for m in macro:
            if m["id"] == "CPIAUCSL":
                value = f"{fr_num(m['value'], 1)} (inflation sur un an : {fr_pct(m.get('yoy_pct'), 2)})" if m.get("yoy_pct") is not None else fr_num(m["value"], 1)
            elif m["id"] == "PAYEMS":
                value = f"{fr_num(m['value'], 0)} milliers"
            else:
                value = fr_num(m["value"], 2) + NBSP + "%"
            row = [{"t": m["name"]}, {"t": value}, {"t": str(m["date"])}]
            if has_change:
                change = "n.d."
                if m.get("change") is not None:
                    if m["id"] == "CPIAUCSL":
                        unit = " pt d'indice"
                    elif m["id"] == "PAYEMS":
                        unit = " milliers"
                    else:
                        unit = " pt de %"
                    change = fr_num(m["change"], 2, True) + unit
                row.append({"t": change})
            row.append({"t": m.get("provider", "FRED"), "href": m.get("source")})
            rows.append(row)
        headers = ["Indicateur", "Valeur", "Observation du"] + (["Variation vs observation précédente"] if has_change else []) + ["Source"]
        blocks.append({"kind": "table", "caption": "Indicateurs macroéconomiques", "numeric": {1} | ({3} if has_change else set()),
                       "headers": headers, "rows": rows})
        blocks.append({"kind": "note", "text": "Ces séries sont publiées avec un décalage (mensuel pour l'inflation et l'emploi) : elles décrivent le fond de l'économie, pas la séance du jour."})
    else:
        blocks.append({"kind": "note", "text": "Aucune série macroéconomique exploitable n'a pu être récupérée lors de cette exécution : le diagnostic ci-dessus repose uniquement sur les prix."})
    return blocks


def _agenda_blocks(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    events = ctx.get("calendar", [])
    horizon = ctx.get("calendar_days", 7)
    blocks: list[dict[str, Any]] = []
    if not events:
        blocks.append({"kind": "p", "text": f"Aucun événement n'est répertorié pour les {horizon} prochains jours dans notre calendrier. Ce n'est pas une garantie de calme : le fichier data/calendar_manual.json est tenu à la main et la clé FRED_API_KEY, si elle est absente, prive le calendrier des publications américaines."})
        return blocks
    blocks.append({"kind": "p", "text": f"Voici les rendez-vous des {horizon} prochains jours, avec les heures converties en heure de Madagascar. Un événement « à confirmer » doit être vérifié sur le site de l'institution avant toute décision."})
    blocks.append({"kind": "events", "events": [
        {"day": calendar_events.format_day(e["local_date"]), "time": e.get("local_time"), "title": e["title"], "region": e.get("region", ""),
         "importance": e["importance"], "status": e["status"], "note": e.get("note", ""), "source": e.get("source", ""),
         "categories": [CATEGORY_LABELS.get(k, k) for k in e.get("categories", [])]} for e in events]})
    return blocks


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", text.casefold()).strip()


def _news_block(item: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Bloc d'actualité sans redite : pas de résumé qui répète le titre, pas deux fois la même lecture de marché."""
    seen: set[str] = ctx.setdefault("_seen_readthrough", set())
    title = item.get("title", "")
    summary = enrichment.clean_summary(item.get("summary_short") or item.get("summary", ""))
    if summary and (_norm(summary).startswith(_norm(title)[:45]) or _norm(title).startswith(_norm(summary)[:45])):
        summary = ""

    # RSS descriptions can accidentally come from a sidebar or a neighbouring story.
    # If a headline contains a distinctive acronym/entity, require it in the excerpt;
    # otherwise hide the excerpt and its derived interpretation instead of publishing
    # a confident but unrelated market explanation.
    common_acronyms = {"US", "UK", "EU", "GDP", "CPI", "PCE", "ETF", "CEO", "IPO", "AI",
                       "SEC", "FOMC", "ECB", "BOJ", "OPEC", "PMI", "WTI", "NYSE", "NASDAQ"}
    title_acronyms = {token.casefold() for token in re.findall(r"\b[A-Z]{2,6}\b", html.unescape(title))
                      if token not in common_acronyms}
    acronym_mismatch = bool(summary and title_acronyms and not any(
        re.search(rf"\b{re.escape(token)}\b", html.unescape(summary).casefold())
        for token in title_acronyms
    ))

    # Also catch unrelated excerpts when the headline has no distinctive acronym.
    # Conservative by design: if several meaningful headline terms are all absent
    # from the excerpt, suppress the excerpt rather than infer a causal link.
    stopwords = {
        "about", "after", "amid", "among", "before", "being", "could", "from", "have",
        "into", "over", "says", "said", "than", "that", "their", "there", "these",
        "they", "this", "through", "under", "when", "where", "which", "while", "with",
        "will", "would", "your", "dans", "avec", "pour", "chez", "vers", "alors",
        "apres", "avant", "mais", "comme", "contre", "dans", "dont", "elle", "elles",
        "entre", "leur", "leurs", "plus", "pour", "sans", "sera", "sont", "sous",
        "tout", "tous", "une", "des", "les", "aux", "sur", "par", "pas", "qui",
        "que", "quoi", "est", "ont", "son", "ses", "the", "and", "for", "its",
        "not", "are", "was", "were", "has", "had", "but", "how", "why", "what",
        "new", "more", "less", "high", "low", "rise", "falls", "fall", "says",
    }
    title_terms = {
        token for token in _norm(html.unescape(title)).split()
        if len(token) >= 4 and token not in stopwords
    }
    summary_terms = set(_norm(html.unescape(summary)).split()) if summary else set()
    no_meaningful_overlap = len(title_terms) >= 3 and not (title_terms & summary_terms)
    item_summary_mismatch = acronym_mismatch or bool(summary and no_meaningful_overlap)
    if item_summary_mismatch:
        summary = ""
    read = item.get("readthrough", "")
    if item_summary_mismatch:
        read = ("Le résumé disponible ne correspond pas suffisamment à l'entité du titre; "
                "aucune conséquence de marché n'est attribuée sans vérifier l'article original.")
    if read in seen:
        read = ""
    elif read:
        seen.add(read)
    return {"kind": "news", "title": title, "source": item.get("source", "source non précisée"),
            "published": item.get("published", "date non fournie"), "summary": summary, "readthrough": read, "url": item.get("url", "")}


def _news_blocks(ctx: dict[str, Any], limit: int) -> list[dict[str, Any]]:
    return [_news_block(item, ctx) for item in (ctx.get("priority_news") or [])[:limit]]


def _movers_blocks(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    """Mouvements inhabituels (séance, cinq séances, un mois) et, pour chacun, ce que la presse en dit.
    Sans actualité propre trouvée, le rapport le dit : la cause n'est alors pas établie."""
    movers = ctx.get("movers") or []
    blocks: list[dict[str, Any]] = [{"kind": "p", "text": (
        "Un mouvement est retenu quand il est à la fois inhabituel au regard de la volatilité propre de l'instrument "
        "et assez ample pour compter, sur une séance, cinq séances ou un mois (ou franchement extrême en valeur absolue). Chaque ligne cite les actualités propres à l'instrument quand les flux en ont fourni ; "
        "à défaut, la cause n'est pas établie et le rapport s'abstient de l'inventer.")}]
    for m in movers:
        blocks.append({"kind": "h3", "text": f"{m['name']} ({m['ticker']})"})
        blocks.append({"kind": "p", "text": "Écart observé : " + " ; ".join(m["reasons"]) + "."})
        stories = m.get("news") or []
        if stories:
            for item in stories:
                summary = re.sub(r"\s+", " ", item.get("summary", "")).strip()
                blocks.append(_news_block({**item, "summary_short": summary[:320], "readthrough": ""}, ctx))
        else:
            blocks.append({"kind": "note", "text": "Aucune actualité propre à cet instrument dans les flux collectés : cause non établie."})
    return blocks


def _category_section(cat: dict[str, Any], rows: list[Any], by_all: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    blocks: list[dict[str, Any]] = [{"kind": "p", "text": cat["intro"], "cls": "intro"}]
    if not rows:
        blocks.append({"kind": "note", "text": "Aucune cotation exploitable n'a été reçue pour cette catégorie lors de cette exécution ; l'absence de donnée ne signifie pas absence de mouvement."})
    else:
        blocks.append(instrument_table(rows, ctx.get("sparks", {})))
        for paragraph in ANALYSERS[cat["key"]](rows, by_all, ctx):
            blocks.append({"kind": "p", "text": paragraph})
    llm_paragraphs = ((ctx.get("llm") or {}).get("categories") or {}).get(cat["key"])
    if llm_paragraphs:
        blocks.append({"kind": "h3", "text": "Commentaire rédigé à partir de ces données"})
        blocks.append({"kind": "chip", "text": "Rédaction assistée par modèle, limitée aux données de ce rapport"})
        blocks += [{"kind": "p", "text": t} for t in llm_paragraphs]
    picker = ctx.get("news_picker")
    shown: set[str] = ctx.setdefault("_shown_category_urls", set())
    try:
        stories = picker(ctx.get("news", []), cat["keywords"], 3, exclude_urls=shown) if picker else []
    except TypeError:  # sélecteur ancien sans exclusion
        stories = picker(ctx.get("news", []), cat["keywords"], 3) if picker else []
    shown.update(item.get("url", "") for item in stories)
    if stories:
        blocks.append({"kind": "h3", "text": "À la une pour cet univers"})
        for item in stories:
            blocks.append(_news_block(item, ctx))
    else:
        blocks.append({"kind": "note", "text": "Aucune nouvelle suffisamment ciblée n'a été identifiée dans les flux collectés ; ce silence ne dit rien du risque."})
    events = _events_for(ctx, cat["key"])
    if events:
        blocks.append({"kind": "h3", "text": "À l'agenda"})
        blocks.append({"kind": "list", "items": [_event_line(e) for e in events]})
    return {"id": cat["key"], "title": cat["label"], "blocks": blocks}


def _scenario_blocks(ctx: dict[str, Any], by: dict[str, Any]) -> list[dict[str, Any]]:
    scenario = ctx.get("scenario") or {}
    score = scenario.get("score", 0)
    vix, tnx, dxy, sp = by.get("^VIX"), by.get("^TNX"), by.get("DX-Y.NYB"), by.get("^GSPC")
    vix_level = fr_num(vix.price, 1) if vix and vix.price else "son niveau actuel"
    tnx_level = fr_num(tnx.price, 2) + NBSP + "%" if tnx and tnx.price else "son niveau actuel"
    dxy_level = fr_num(dxy.price, 1) if dxy and dxy.price else "son niveau actuel"
    top_event = next((e for e in ctx.get("calendar", []) if e["importance"] == "élevée"), None)
    event_txt = f" Le prochain test majeur est : {_event_line(top_event)}" if top_event else ""
    if score <= -1:
        main_title, main_body = "Scénario A — prolongement de la prudence", (
            f"Le scénario de baisse serait renforcé si le VIX dépasse durablement son niveau actuel de {vix_level}, si les rendements à 10 ans remontent au-dessus de {tnx_level} et si le dollar se raffermit près ou au-dessus de {dxy_level}. "
            "La confirmation la plus directe serait une nouvelle clôture des indices sous leurs récents creux ; sans ces confirmations, le biais reste une hypothèse et non un fait établi.")
        alt_title, alt_body = "Scénario B — rebond technique et retour au centre", (
            f"Le scénario de rebond gagnerait en crédibilité si le VIX repasse sous son niveau actuel de {vix_level}, si les rendements à 10 ans se détendent et si le S&P 500 reprend une partie de sa baisse. Un rebond isolé ne suffirait pas à établir la fin de la correction : il faudrait aussi observer une amélioration durable des clôtures et de la participation des marchés.")
    elif score >= 1:
        main_title, main_body = "Scénario A — poursuite de la hausse", (
            f"Le momentum se prolonge : le VIX reste contenu autour de {vix_level}, les rendements ne dépassent pas {tnx_level} et le dollar reste stable près de {dxy_level}. "
            "Les indices progressent avec une participation large entre secteurs.")
        alt_title, alt_body = "Scénario B — consolidation", (
            f"Les indices marquent une pause : les gains récents se digèrent, le VIX remonte légèrement au-dessus de {vix_level}. Les hausses rapides sont souvent suivies de phases latérales.")
    else:
        main_title, main_body = "Scénario A — marché sans direction", (
            f"Les signaux restent contradictoires : indices dans une fourchette étroite, VIX autour de {vix_level}, rendements près de {tnx_level}. Le marché attend un catalyseur.")
        alt_title, alt_body = "Scénario B — rupture haussière", (
            f"Un catalyseur favorable (publication, banque centrale) fait baisser le VIX sous {vix_level} et monter les indices.")
    shock_title, shock_body = "Scénario C — choc de volatilité", (
        "Une surprise de taux, une tension géopolitique ou budgétaire, ou un événement de crédit fait bondir le VIX, rompt les corrélations habituelles et provoque un mouvement refuge (dollar, yen, franc suisse, or, emprunts d'État)." + event_txt)
    blocks: list[dict[str, Any]] = [
        {"kind": "p", "text": "Ces scénarios sont conditionnels : ils décrivent ce qu'il faudrait observer, pas ce qui va se produire. Les niveaux cités sont les niveaux actuels, utilisés comme repères d'invalidation."},
        {"kind": "scenario", "title": main_title, "body": main_body},
        {"kind": "scenario", "title": alt_title, "body": alt_body},
        {"kind": "scenario", "title": shock_title, "body": shock_body},
    ]
    llm_scn = (ctx.get("llm") or {}).get("scenarios")
    if llm_scn:
        blocks.append({"kind": "chip", "text": "Rédaction assistée par modèle, limitée aux données de ce rapport"})
        blocks += [{"kind": "p", "text": t} for t in llm_scn]
    # liste de surveillance
    watch = []
    rows = ctx.get("rows", [])
    def material(r: Any) -> bool:
        floor = 0.5 if r.asset_class.casefold() == "fx" else 1.0
        return r.daily_pct is not None and abs(r.daily_pct) >= floor
    ranked = sorted([r for r in rows if _zscore(r) is not None and r.ticker != "^VIX" and material(r)], key=lambda r: abs(_zscore(r)), reverse=True)
    seen: set[str] = set()
    for r in ranked[:6]:
        z = abs(_zscore(r))
        seen.add(r.ticker)
        watch.append([{"t": r.name, "sub": r.ticker}, {"t": CATEGORY_LABELS.get(_category_of(r), "")},
                      {"t": fr_pct(r.daily_pct), "cls": "up" if r.daily_pct and r.daily_pct > 0 else "down"},
                      {"t": f"Mouvement de {fr_num(z, 1)} écart-type par rapport à sa volatilité habituelle"},
                      {"t": "Élevée" if z >= 2 else "Moyenne"}])
    for event in ctx.get("calendar", []):
        if event["importance"] != "élevée":
            continue
        for currency in event.get("currencies") or []:
            ticker = CURRENCY_TICKERS.get(currency)
            r = by.get(ticker) if ticker else None
            if r and r.ticker not in seen and len(watch) < 10:
                seen.add(r.ticker)
                watch.append([{"t": r.name, "sub": r.ticker}, {"t": "Devises"}, {"t": fr_pct(r.daily_pct), "cls": "up" if r.daily_pct and r.daily_pct > 0 else "down"},
                              {"t": f"Événement à venir ({calendar_events.format_day(event['local_date'])}) : {event['title'][:70]}"}, {"t": "Élevée"}])
    if watch:
        blocks.append({"kind": "h3", "text": "Liste de surveillance"})
        blocks.append({"kind": "table", "caption": "Liste de surveillance", "numeric": {2},
                       "headers": ["Instrument", "Univers", "Séance", "Pourquoi le surveiller", "Priorité"], "rows": watch})
        blocks.append({"kind": "note", "text": "Il s'agit d'une liste de surveillance fondée sur l'amplitude des mouvements et l'agenda, pas d'un classement de signaux d'achat ou de vente. À la réouverture, confronter ce biais au prix, aux niveaux techniques et à la réaction effective du marché."})
    return blocks


def _category_of(row: Any) -> str:
    for cat in CATEGORIES:
        if cat["match"](row):
            return cat["key"]
    return ""


def _audit_blocks(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    fe = ctx.get("forecast_eval") or {}
    se = ctx.get("scenario_eval") or {}
    blocks: list[dict[str, Any]] = [
        {"kind": "p", "text": "Un rapport n'a de valeur que s'il se mesure à la réalité. Chaque prévision est enregistrée avant le résultat, jamais réécrite, puis comparée à la séance qui suit. Surtout, elle est comparée à des règles naïves : une méthode qui ne fait pas mieux que « toujours hausse » ou « même direction qu'hier » n'apporte aucune information."}]
    n = len(se.get("matured", []))
    rows = [[{"t": "Scénarios S&P 500 du matin"},
             {"t": f"{se.get('forecast_count', 0)} prévisions uniques ; {n} arrivées à échéance ; {se.get('pending', 0)} en attente ; {se.get('duplicates_ignored', 0)} relances du même jour ignorées"}]]
    if n:
        rows.append([{"t": "Exactitude de la direction"}, {"t": f"{fr_num(se.get('accuracy_pct'), 1)} % (référence « toujours haussier » : {fr_num(se.get('baseline_always_up_accuracy_pct'), 1)} %)"}])
        rows.append([{"t": "Score de Brier"}, {"t": f"{fr_num(se.get('mean_brier_score'), 3)} (référence climatologique : {fr_num(se.get('climatology_brier_score'), 3)}" + (f" ; compétence {fr_num(se.get('brier_skill_score'), 2, True)}" if se.get("brier_skill_score") is not None else " ; compétence non calculée sous 30 échantillons") + ")"}])
    for horizon, label in (("1", "1 séance"), ("5", "5 séances")):
        st = (fe.get("by_horizon") or {}).get(horizon) or {}
        if st.get("n"):
            rows.append([{"t": f"Règle de momentum par actif, {label}"},
                         {"t": f"{st['correct']} bonnes directions sur {st['n']} ({fr_num(st['accuracy_pct'], 1)} %) ; toujours hausse : {fr_num(st['always_up_accuracy_pct'], 1)} % ; persistance : " + (f"{fr_num(st['persistence_accuracy_pct'], 1)} % ({st['persistence_n']} cas)" if st.get("persistence_accuracy_pct") is not None else "non évaluable")}])
        else:
            rows.append([{"t": f"Règle de momentum par actif, {label}"}, {"t": "aucun échantillon arrivé à échéance"}])
    blocks.append({"kind": "table", "caption": "Résultats de l'audit", "numeric": set(), "headers": ["Mesure", "Résultat"], "rows": rows})
    total = n + sum((fe.get("by_horizon") or {}).get(h, {}).get("n", 0) for h in ("1", "5"))
    if n < 30:
        blocks.append({"kind": "callout", "tone": "warn", "text": f"Échantillon insuffisant : {n} prévision{'s' if n > 1 else ''} de scénario arrivée{'s' if n > 1 else ''} à échéance, alors qu'il faut au moins trente séances distinctes pour tirer une conclusion. À ce stade, aucune probabilité de ce rapport ne doit être considérée comme fiable."})
    else:
        skill = se.get("brier_skill_score")
        verdict = ("Les probabilités font mieux que la climatologie." if skill is not None and skill > 0 else "Les probabilités ne font pas mieux que la climatologie : elles ne doivent pas guider une décision.")
        blocks.append({"kind": "callout", "tone": "info", "text": verdict + " Une exactitude directionnelle seule ne prouve pas la rentabilité : coûts, régimes de marché et validation hors échantillon restent à examiner."})
    wrong = [r for r in fe.get("matured", []) if not r.get("correct")][-3:]
    if wrong:
        blocks.append({"kind": "p", "text": "Dernières erreurs à examiner : " + " ; ".join(
            f"{r['name']} ({r['horizon_sessions']} séance(s), prévu {r['direction']}, réalisé {r['realized_direction']}, {fr_pct(r['realized_pct'])})" for r in wrong) + "."})
    if se.get("by_version") and len(se["by_version"]) > 1:
        blocks.append({"kind": "note", "text": "Plusieurs versions de la règle coexistent dans l'historique (" + ", ".join(f"{v} : {d['n']} cas" for v, d in se["by_version"].items()) + ") ; leurs résultats ne doivent pas être mélangés."})
    return blocks


def _method_blocks(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    err = ctx.get("errors", {})
    rows = ctx.get("rows", [])
    items = [
        f"Couverture : {len(rows)} actifs reçus sur {ctx.get('n_tracked', len(rows))} suivis.",
        "Prix : Yahoo Finance via la bibliothèque yfinance (source non officielle, données parfois retardées ou révisées).",
        "Macroéconomie : séries FRED avec replis officiels (BLS ; Réserve fédérale de New York pour le taux effectif ; Trésor américain pour les rendements 2 ans, 10 ans et anticipations d'inflation ; BCE pour le taux de dépôt) ; publications officielles de la Réserve fédérale, du BEA, du Census Bureau, de la BCE, de l'EIA, de la Banque d'Angleterre et de la Banque du Japon ; presse financière (CNBC, Yahoo Finance, Financial Times, Guardian) et recherches Google Actualités à titre de piste seulement.",
        "Fondamentaux d'entreprise : API XBRL de la SEC (EDGAR) pour un échantillon de sociétés américaines ; chiffres publiés, sans consensus.",
        "Calendrier : fichier data/calendar_manual.json tenu à la main (statut « confirmé » ou « à confirmer ») et, si la clé est fournie, dates officielles relayées par FRED.",
    ]
    if ctx.get("frozen_prices"):
        items.append("Cours à vérifier : variation de séance exactement nulle pour " + ", ".join(ctx["frozen_prices"]) +
                     " (séance en cours, jour férié ou cours non rafraîchi : ne pas lire cette immobilité comme un signal).")
    problems = []
    for key, label in (("prices", "cours"), ("news", "flux d'actualités"), ("fundamentals", "données d'entreprise"), ("macro", "séries macroéconomiques"), ("calendar", "calendrier")):
        if err.get(key):
            problems.append(f"{err[key]} {label} indisponible(s)")
    items.append("Incidents de collecte : " + (", ".join(problems) + ". Une donnée absente n'est pas une donnée nulle." if problems else "aucun signalé."))
    llm = ctx.get("llm")
    if llm:
        items.append(f"Rédaction : certains commentaires sont rédigés par un modèle de langage à partir des seules données de ce rapport ({llm.get('meta', {}).get('model', 'modèle non précisé')}) ; un contrôle automatique écarte tout paragraphe contenant un chiffre absent des données ({llm.get('meta', {}).get('dropped', 0)} paragraphe(s) écarté(s)). Les probabilités restent calculées par le code, jamais par le modèle.")
    else:
        items.append("Rédaction : cette édition est entièrement produite par des règles de calcul, sans modèle de langage.")
    items.append(f"Temps de lecture : estimé à {WORDS_PER_MINUTE} mots par minute, annexes exclues.")
    return [{"kind": "list", "items": items},
            {"kind": "callout", "tone": "warn", "text": "Contenu informatif et expérimental, qui ne constitue pas un conseil en investissement. Vérifier les données et les sources avant toute décision."}]


def _since_morning_blocks(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    prior = ctx.get("prior_assets") or {}
    changes = []
    for r in ctx.get("rows", []):
        old = prior.get(r.ticker)
        if old and old.get("price") and r.price and old["price"] != r.price:
            changes.append((r, (r.price / float(old["price"]) - 1) * 100))
    if not changes:
        return [{"kind": "p", "text": "Aucun écart de prix n'est mesurable depuis le rapport précédent (les mêmes dernières observations sont encore disponibles)."}]
    changes.sort(key=lambda x: abs(x[1]), reverse=True)
    rows = [[{"t": r.name, "sub": r.ticker}, {"t": fmt_level(r)}, {"t": fr_pct(c), "cls": "up" if c > 0 else "down"}] for r, c in changes[:10]]
    return [{"kind": "p", "text": "Ce point ne répète pas ce qui n'a pas changé : voici les instruments dont le dernier cours a le plus varié depuis le rapport du matin."},
            {"kind": "table", "caption": "Changements depuis le rapport précédent", "numeric": {1, 2}, "headers": ["Instrument", "Dernier", "Depuis le précédent rapport"], "rows": rows}]


def _week_review_blocks(ctx: dict[str, Any]) -> list[dict[str, Any]]:
    rows = [r for r in ctx.get("rows", []) if r.five_day_pct is not None]
    if not rows:
        return [{"kind": "p", "text": "Aucune performance hebdomadaire exploitable n'a été reçue."}]
    ordered = sorted(rows, key=lambda r: r.five_day_pct, reverse=True)

    def table(items: list[Any], caption: str) -> dict[str, Any]:
        return {"kind": "table", "caption": caption, "numeric": {2, 3}, "headers": ["Instrument", "Univers", "5 séances", "1 mois"],
                "rows": [[{"t": r.name, "sub": r.ticker}, {"t": CATEGORY_LABELS.get(_category_of(r), "")},
                          {"t": fr_pct(r.five_day_pct), "cls": "up" if r.five_day_pct > 0 else "down"},
                          {"t": fr_pct(r.one_month_pct), "cls": "up" if (r.one_month_pct or 0) > 0 else "down"}] for r in items]}
    blocks = [{"kind": "p", "text": f"Sur {len(rows)} instruments, {sum(r.five_day_pct > 0 for r in rows)} progressent et {sum(r.five_day_pct < 0 for r in rows)} reculent sur cinq séances. Voici les extrêmes de la semaine."},
              {"kind": "h3", "text": "Les plus fortes hausses"}, table(ordered[:8], "Plus fortes hausses sur cinq séances"),
              {"kind": "h3", "text": "Les plus fortes baisses"}, table(list(reversed(ordered[-8:])), "Plus fortes baisses sur cinq séances")]
    return blocks


# ----------------------------------------------------------------------------- assemblage
def block_words(block: dict[str, Any]) -> float:
    kind = block["kind"]

    def count(text: str) -> int:
        return len(str(text).split())
    if kind in ("p", "note", "callout", "chip"):
        return 0 if kind == "chip" else count(block.get("text", ""))
    if kind == "h3":
        return count(block.get("text", ""))
    if kind == "list":
        return sum(count(i) for i in block.get("items", []))
    if kind == "news":
        return count(block.get("title", "")) + count(block.get("summary", "")) + count(block.get("readthrough", ""))
    if kind == "scenario":
        return count(block.get("title", "")) + count(block.get("body", ""))
    if kind == "events":
        return sum(count(e["title"]) + count(e.get("note", "")) for e in block["events"])
    if kind == "table":
        words = sum(count(c.get("t", "")) for row in block["rows"] for c in row)
        return words * TABLE_WORD_WEIGHT
    if kind == "probs":
        return count(block.get("note", ""))
    return 0


def section_minutes(section: dict[str, Any]) -> float:
    return sum(block_words(b) for b in section["blocks"]) / WORDS_PER_MINUTE


def build_report(ctx: dict[str, Any]) -> dict[str, Any]:
    kind = ctx.get("kind", "morning")
    rows = ctx.get("rows", [])
    by = _by_ticker(rows)
    weekly = kind == "weekly"
    llm = ctx.get("llm") or {}
    headline, dek = _headline(ctx, by)
    sections: list[dict[str, Any]] = []

    synth_blocks: list[dict[str, Any]] = [{"kind": "list", "items": _takeaways(ctx, by), "cls": "takeaways"}]
    if llm.get("synthese"):
        synth_blocks.append({"kind": "chip", "text": "Rédaction assistée par modèle, limitée aux données de ce rapport"})
        synth_blocks += [{"kind": "p", "text": t} for t in llm["synthese"]]
    sections.append({"id": "synthese", "title": "L'essentiel", "blocks": synth_blocks})

    if kind == "update":
        sections.append({"id": "depuis", "title": "Depuis le rapport précédent", "blocks": _since_morning_blocks(ctx)})
    if weekly:
        sections.append({"id": "semaine", "title": "La semaine écoulée", "blocks": _week_review_blocks(ctx)})

    regime_blocks = _regime_blocks(ctx, by)
    if llm.get("regime"):
        regime_blocks.append({"kind": "chip", "text": "Rédaction assistée par modèle, limitée aux données de ce rapport"})
        regime_blocks += [{"kind": "p", "text": t} for t in llm["regime"]]
    sections.append({"id": "regime", "title": "Régime de marché", "blocks": regime_blocks})

    agenda = _agenda_blocks(ctx)
    if llm.get("agenda"):
        agenda += [{"kind": "p", "text": t} for t in llm["agenda"]]
    sections.append({"id": "agenda", "title": "La semaine à venir" if weekly else "Agenda", "blocks": agenda})

    news_blocks = _news_blocks(ctx, 8)
    if news_blocks:
        sections.append({"id": "faits", "title": "Faits marquants", "blocks": news_blocks})

    if ctx.get("movers"):
        sections.append({"id": "mouvements", "title": "Pourquoi ça bouge", "blocks": _movers_blocks(ctx)})

    for cat in CATEGORIES:
        members = [r for r in rows if cat["match"](r)]
        sections.append(_category_section(cat, members, by, ctx))

    sections.append({"id": "scenarios", "title": "Scénarios et liste de surveillance", "blocks": _scenario_blocks(ctx, by)})
    sections.append({"id": "audit", "title": "Fiabilité de nos analyses", "blocks": _audit_blocks(ctx)})
    sections.append({"id": "methode", "title": "Données, sources et limites", "blocks": _method_blocks(ctx)})

    for section in sections:
        section["minutes"] = max(1, round(section_minutes(section)))
    total_words = sum(block_words(b) for s in sections for b in s["blocks"])
    return {
        "kind": kind, "kind_label": KIND_LABELS.get(kind, kind), "title": ctx.get("title", KIND_LABELS.get(kind, "")),
        "headline": headline, "dek": dek, "now_local": ctx.get("now_local"), "started": ctx.get("started"),
        "sections": sections, "reading_minutes": max(1, round(total_words / WORDS_PER_MINUTE)), "words": int(total_words),
        "n_assets": len(rows), "n_tracked": ctx.get("n_tracked", len(rows)), "sparks": ctx.get("sparks", {}),
        "legacy_text": ctx.get("legacy_text", ""), "weekend": bool(ctx.get("weekend")),
    }
