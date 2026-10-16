from __future__ import annotations

import argparse
import html
import json
import math
import os
import smtplib
import ssl
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
import yfinance as yf

TZ = ZoneInfo("Indian/Antananarivo")
ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "data"
FORECAST_FILE = STATE_DIR / "forecasts.json"
HISTORY_FILE = STATE_DIR / "market_history.csv"
USER_AGENT = "MarketIntelligenceDaily/0.1 (personal research; contact via repository owner)"

ASSETS: dict[str, dict[str, str]] = {
    "^GSPC": {"name": "S&P 500", "class": "US equity index"},
    "^IXIC": {"name": "Nasdaq Composite", "class": "US equity index"},
    "^DJI": {"name": "Dow Jones", "class": "US equity index"},
    "^STOXX50E": {"name": "Euro Stoxx 50", "class": "European equity index"},
    "^FTSE": {"name": "FTSE 100", "class": "UK equity index"},
    "^N225": {"name": "Nikkei 225", "class": "Japanese equity index"},
    "^HSI": {"name": "Hang Seng", "class": "Hong Kong equity index"},
    "^VIX": {"name": "VIX volatility index", "class": "Implied volatility"},
    "ES=F": {"name": "S&P 500 E-mini futures", "class": "Equity index futures"},
    "NQ=F": {"name": "Nasdaq 100 E-mini futures", "class": "Equity index futures"},
    "YM=F": {"name": "Dow Jones E-mini futures", "class": "Equity index futures"},
    "RTY=F": {"name": "Russell 2000 E-mini futures", "class": "Equity index futures"},
    "ZN=F": {"name": "US Treasury 10-year note futures", "class": "Bond futures"},
    "ZB=F": {"name": "US Treasury bond futures", "class": "Bond futures"},
    "^TNX": {"name": "US 10-year Treasury yield", "class": "Rates"},
    "DX-Y.NYB": {"name": "US Dollar Index", "class": "FX"},
    "EURUSD=X": {"name": "EUR/USD", "class": "FX"},
    "USDJPY=X": {"name": "USD/JPY", "class": "FX"},
    "GC=F": {"name": "Gold futures", "class": "Commodity"},
    "SI=F": {"name": "Silver futures", "class": "Commodity"},
    "CL=F": {"name": "WTI crude oil futures", "class": "Commodity"},
    "NG=F": {"name": "Natural gas futures", "class": "Commodity"},
    "HG=F": {"name": "Copper futures", "class": "Commodity"},
    "BTC-USD": {"name": "Bitcoin", "class": "Crypto"},
    "ETH-USD": {"name": "Ethereum", "class": "Crypto"},
    "SPY": {"name": "SPDR S&P 500 ETF", "class": "ETF"},
    "QQQ": {"name": "Invesco Nasdaq 100 ETF", "class": "ETF"},
    "TLT": {"name": "US Treasury 20+ year ETF", "class": "Bond ETF"},
    "IEF": {"name": "iShares 7–10 Year Treasury ETF", "class": "Bond ETF"},
    "BND": {"name": "Vanguard Total Bond Market ETF", "class": "Bond ETF"},
    "LQD": {"name": "Investment-grade corporate bond ETF", "class": "Bond ETF"},
    "EFA": {"name": "Developed markets ex-US equity ETF", "class": "ETF"},
    "EEM": {"name": "Emerging markets equity ETF", "class": "ETF"},
    "IWM": {"name": "Russell 2000 small-cap equity ETF", "class": "ETF"},
    "HYG": {"name": "High-yield corporate bond ETF", "class": "Credit ETF"},
    "GLD": {"name": "Gold ETF", "class": "ETF"},
    "AAPL": {"name": "Apple", "class": "US equity"},
    "MSFT": {"name": "Microsoft", "class": "US equity"},
    "NVDA": {"name": "Nvidia", "class": "US equity"},
    "AMZN": {"name": "Amazon", "class": "US equity"},
}

NEWS_FEEDS = [
    ("Google News — marchés et économie", "https://news.google.com/rss/search?q=global+markets+economy+central+banks&hl=en-US&gl=US&ceid=US:en"),
    ("Google News — entreprises et résultats", "https://news.google.com/rss/search?q=stocks+earnings+corporate+results&hl=en-US&gl=US&ceid=US:en"),
    ("Google News — matières premières et géopolitique", "https://news.google.com/rss/search?q=oil+gold+commodities+geopolitics&hl=en-US&gl=US&ceid=US:en"),
]

@dataclass
class AssetRow:
    ticker: str
    name: str
    asset_class: str
    price: float | None
    daily_pct: float | None
    five_day_pct: float | None
    one_month_pct: float | None
    rsi14: float | None
    ma20_gap_pct: float | None
    ma50_gap_pct: float | None
    annualized_vol_pct: float | None
    trend: str
    data_timestamp: str | None
    note: str

def num(value: Any, digits: int = 2) -> float | None:
    try:
        value = float(value)
        if not math.isfinite(value):
            return None
        return round(value, digits)
    except (TypeError, ValueError):
        return None

def fmt(value: float | None, suffix: str = "", digits: int = 2) -> str:
    return "n.d." if value is None else f"{value:+.{digits}f}{suffix}"

def fetch_prices() -> tuple[dict[str, pd.DataFrame], list[str]]:
    data: dict[str, pd.DataFrame] = {}
    errors: list[str] = []
    for ticker in ASSETS:
        try:
            frame = yf.download(
                ticker, period="6mo", interval="1d", auto_adjust=True,
                progress=False, threads=False, timeout=20
            )
            if frame is None or frame.empty:
                errors.append(f"{ticker}: aucune donnée reçue")
                continue
            if isinstance(frame.columns, pd.MultiIndex):
                frame.columns = frame.columns.get_level_values(0)
            frame = frame.loc[:, ~frame.columns.duplicated()]
            if "Close" not in frame or frame["Close"].dropna().empty:
                errors.append(f"{ticker}: cours de clôture absent")
                continue
            data[ticker] = frame.dropna(subset=["Close"])
            time.sleep(0.15)
        except Exception as exc:
            errors.append(f"{ticker}: {type(exc).__name__}: {str(exc)[:160]}")
    return data, errors

def analyse_asset(ticker: str, frame: pd.DataFrame) -> AssetRow:
    closes = frame["Close"].dropna().astype(float)
    latest = float(closes.iloc[-1])
    returns = closes.pct_change().dropna()
    daily = (closes.iloc[-1] / closes.iloc[-2] - 1) * 100 if len(closes) > 1 else None
    week = (closes.iloc[-1] / closes.iloc[-6] - 1) * 100 if len(closes) > 5 else None
    month = (closes.iloc[-1] / closes.iloc[-22] - 1) * 100 if len(closes) > 21 else None
    ma20 = float(closes.rolling(20).mean().iloc[-1]) if len(closes) >= 20 else None
    ma50 = float(closes.rolling(50).mean().iloc[-1]) if len(closes) >= 50 else None
    delta = closes.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    rsi_val = num(rsi.iloc[-1])
    vol = num(returns.tail(30).std(ddof=1) * math.sqrt(252) * 100) if len(returns) >= 10 else None
    ma20_gap = num((latest / ma20 - 1) * 100) if ma20 else None
    ma50_gap = num((latest / ma50 - 1) * 100) if ma50 else None
    if ma20_gap is None or ma50_gap is None:
        trend = "Historique insuffisant"
    elif ma20_gap > 0 and ma50_gap > 0:
        trend = "Hausse / au-dessus des MM20 et MM50"
    elif ma20_gap < 0 and ma50_gap < 0:
        trend = "Baisse / sous les MM20 et MM50"
    else:
        trend = "Mixte / tendance à confirmer"
    # This is a descriptive technical label, not a forecast or trading signal.
    note = "RSI élevé" if rsi_val is not None and rsi_val >= 70 else (
        "RSI faible" if rsi_val is not None and rsi_val <= 30 else "Aucun extrême RSI détecté"
    )
    last_date = str(pd.Timestamp(closes.index[-1]).date()) if len(closes) else None
    meta = ASSETS[ticker]
    return AssetRow(
        ticker=ticker, name=meta["name"], asset_class=meta["class"],
        price=num(latest, 4), daily_pct=num(daily), five_day_pct=num(week),
        one_month_pct=num(month), rsi14=rsi_val, ma20_gap_pct=ma20_gap,
        ma50_gap_pct=ma50_gap, annualized_vol_pct=vol, trend=trend,
        data_timestamp=last_date, note=note
    )

def fetch_news() -> tuple[list[dict[str, str]], list[str]]:
    items: list[dict[str, str]] = []
    errors: list[str] = []
    seen: set[str] = set()
    headers = {"User-Agent": USER_AGENT}
    for feed_name, url in NEWS_FEEDS:
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                published = (item.findtext("pubDate") or "").strip()
                source = item.findtext("source") or feed_name
                if title and link and link not in seen:
                    seen.add(link)
                    items.append({"title": title, "url": link, "published": published, "source": source})
        except Exception as exc:
            errors.append(f"{feed_name}: {type(exc).__name__}: {str(exc)[:120]}")
    return items[:18], errors

def classify_move(pct: float | None) -> str:
    if pct is None:
        return "indisponible"
    if pct >= 1:
        return "forte hausse"
    if pct >= 0.2:
        return "hausse"
    if pct <= -1:
        return "forte baisse"
    if pct <= -0.2:
        return "baisse"
    return "quasi stable"

def scenario_context(rows: list[AssetRow]) -> list[str]:
    by = {r.ticker: r for r in rows}
    lines: list[str] = []
    sp = by.get("^GSPC")
    nasdaq = by.get("^IXIC")
    vix = by.get("^VIX")
    tnx = by.get("^TNX")
    gold = by.get("GC=F")
    oil = by.get("CL=F")
    btc = by.get("BTC-USD")
    if sp and nasdaq:
        if sp.five_day_pct is not None and nasdaq.five_day_pct is not None:
            if sp.five_day_pct > 0 and nasdaq.five_day_pct > 0:
                lines.append("Les grands indices US ont progressé sur cinq séances : biais de momentum positif à court terme, à confirmer par les prochaines clôtures.")
            elif sp.five_day_pct < 0 and nasdaq.five_day_pct < 0:
                lines.append("Les grands indices US ont reculé sur cinq séances : momentum récent négatif, sans que cela suffise à établir une prévision directionnelle.")
            else:
                lines.append("Les indices US divergent sur cinq séances : leadership sectoriel ou dispersion à surveiller.")
    if vix and vix.daily_pct is not None and vix.daily_pct >= 8:
        lines.append("Le VIX a fortement progressé sur la dernière séance disponible : surveiller une hausse de l'aversion au risque.")
    if tnx and tnx.daily_pct is not None and sp and sp.daily_pct is not None:
        if tnx.daily_pct > 0.5 and sp.daily_pct < -0.5:
            lines.append("Hausse du rendement Treasury US 10 ans et baisse des actions US : combinaison compatible avec une pression des taux sur les valorisations, mais non causale à elle seule.")
    if gold and oil and gold.daily_pct is not None and oil.daily_pct is not None:
        if gold.daily_pct > 0.5 and oil.daily_pct > 0.5:
            lines.append("Or et pétrole progressent ensemble : vérifier si le mouvement reflète dollar, inflation anticipée, offre ou risque géopolitique.")
    if btc and btc.daily_pct is not None:
        lines.append(f"Bitcoin : variation de la dernière séance disponible {fmt(btc.daily_pct, '%')}; la crypto cote en continu, contrairement à la plupart des marchés traditionnels.")
    return lines or ["Pas assez de données croisées pour formuler un commentaire de régime robuste."]

def read_state() -> dict[str, Any]:
    try:
        return json.loads(FORECAST_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"forecasts": []}

def write_state(snapshot: dict[str, Any], rows: list[AssetRow]) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state = read_state()
    forecasts = state.get("forecasts", [])
    forecasts.append(snapshot)
    state["forecasts"] = forecasts[-500:]
    FORECAST_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    out = pd.DataFrame([asdict(r) for r in rows])
    out.insert(0, "run_time_utc", snapshot["run_time_utc"])
    out.insert(1, "report_type", snapshot["report_type"])
    out.to_csv(HISTORY_FILE, mode="a", header=not HISTORY_FILE.exists(), index=False)

def make_report(report_type: str) -> tuple[str, str, dict[str, Any]]:
    started = datetime.now(timezone.utc)
    now_local = started.astimezone(TZ)
    data, data_errors = fetch_prices()
    rows = [analyse_asset(ticker, frame) for ticker, frame in data.items()]
    news, news_errors = fetch_news()
    rows.sort(key=lambda r: (r.asset_class, r.name))
    previous = read_state().get("forecasts", [])
    prior_morning = next((x for x in reversed(previous) if x.get("report_type") == "morning"), None)
    prior_update = next((x for x in reversed(previous) if x.get("report_type") == "update"), None)

    titles = {
        "morning": "Rapport initial — marchés multi-actifs",
        "update": "Mise à jour — changements depuis le dernier rapport",
        "audit": "Audit des prévisions et des données",
    }
    title = titles[report_type]
    lines = [
        title, f"Heure Madagascar : {now_local:%Y-%m-%d %H:%M:%S %Z}",
        f"Généré UTC : {started:%Y-%m-%d %H:%M:%S UTC}",
        "",
        "RÉSUMÉ ET LIMITES",
        f"Données de prix reçues pour {len(rows)}/{len(ASSETS)} actifs suivis.",
        "Le rapport est orienté vers les événements, les mouvements de marché, les scénarios et les actifs à surveiller. Les indicateurs techniques sont conservés et utilisés en interne pour l'analyse, mais ne sont pas affichés. Le moteur ne dispose pas encore d'une analyse fondamentale complète ni de probabilités directionnelles calibrées.",
        "Les données de marché peuvent être retardées, révisées ou indisponibles. Les variations portent sur la dernière séance reçue, pas nécessairement sur la séance en cours.",
        "",
    ]

    if report_type == "morning":
        lines += ["SCÉNARIO DE RÉFÉRENCE — INDICATEURS, PAS PRÉDICTION CERTAINE"]
        lines += ["- " + s for s in scenario_context(rows)]
        lines += [
            "- Les scénarios haussier, central et baissier ne reçoivent pas encore de probabilités chiffrées : elles ne seront ajoutées qu'après une méthode explicitement testée et calibrée.",
            "- Catalyseurs à surveiller : décisions et communications des banques centrales, inflation/emploi, résultats d'entreprises, rendements obligataires, dollar, pétrole et événements géopolitiques.",
            "",
        ]
    elif report_type == "update":
        lines += ["CHANGEMENTS DEPUIS LE RAPPORT INITIAL"]
        old = {}
        if prior_morning:
            old = {r["ticker"]: r for r in prior_morning.get("assets", [])}
        changes = []
        for row in rows:
            prev = old.get(row.ticker)
            if prev:
                old_d = prev.get("daily_pct")
                if row.daily_pct is not None and old_d is not None and abs(row.daily_pct - old_d) >= 0.5:
                    changes.append(f"- {row.name}: variation journalière calculée passée de {fmt(old_d, '%')} à {fmt(row.daily_pct, '%')}. Attention : la comparaison peut être redondante si la séance n'a pas changé.")
        lines += changes[:25] or ["- Aucun changement quantitatif comparable détecté, ou rapport initial absent. La fenêtre de données de Yahoo Finance peut ne pas refléter l'intraday."]
        lines += ["", "ACTUALITÉS RÉCENTES", "Les titres ci-dessous sont des pistes de vérification; leur présence ne prouve pas un effet de marché."]
    elif report_type == "audit":
        lines += ["AUDIT DES PRÉVISIONS"]
        lines += [
            f"- Instantanés historiques enregistrés : {len(previous)}.",
            "- Ce prototype n'émet pas encore de prévisions directionnelles probabilisées; il ne peut donc pas calculer honnêtement de taux de réussite ou de calibration probabiliste.",
            "- Les audits quantitatifs futurs compareront chaque prévision horodatée à un horizon défini, en séparant données disponibles à l'instant T et résultats ultérieurs.",
            "- Pas de conclusion de performance possible à partir d'un échantillon court ou de simples indicateurs techniques.",
            "",
            "CONTEXTE DU MARCHÉ",
        ]
        lines += ["- " + s for s in scenario_context(rows)]

    # Les indicateurs techniques restent dans les données internes pour aider à
    # hiérarchiser les scénarios; ils ne sont pas affichés dans le rapport envoyé.
    lines += ["", "PANORAMA DES MARCHÉS — MOUVEMENTS OBSERVÉS",
              "Les chiffres ci-dessous décrivent les mouvements de prix, pas des indicateurs techniques ni des ordres de trading.",
              "Actif | Classe | Dernier prix | Dernière séance disponible | 5 séances | 1 mois"]
    # Include every successfully collected asset, not only a hand-picked subset.
    # This prevents major indices, individual equities, and broad ETFs from
    # disappearing from the reader-facing panorama when their moves are small.
    selected = sorted(
        rows,
        key=lambda r: max(abs(r.daily_pct or 0), abs(r.five_day_pct or 0)),
        reverse=True,
    )
    for r in selected:
        lines.append(
            f"{r.name} ({r.ticker}) | {r.asset_class} | {fmt(r.price)} | "
            f"{fmt(r.daily_pct, '%')} | {fmt(r.five_day_pct, '%')} | {fmt(r.one_month_pct, '%')}"
        )
    watch = [r for r in rows if
             (r.daily_pct is not None and abs(r.daily_pct) >= 1.5) or
             (r.five_day_pct is not None and abs(r.five_day_pct) >= 4.0) or
             (r.one_month_pct is not None and abs(r.one_month_pct) >= 8.0)]
    watch.sort(key=lambda r: max(abs(r.daily_pct or 0), abs(r.five_day_pct or 0), abs(r.one_month_pct or 0)), reverse=True)
    lines += ["", "ACTIFS À SURVEILLER",
              "Sélection mécanique des mouvements les plus marqués, à confirmer par les fondamentaux, les actualités et le contexte; ce n'est pas une recommandation d'achat ou de vente."]
    for r in watch[:10]:
        lines.append(
            f"- {r.name} ({r.ticker}) : dernière séance {fmt(r.daily_pct, '%')}; "
            f"5 séances {fmt(r.five_day_pct, '%')}; 1 mois {fmt(r.one_month_pct, '%')}."
        )
    if not watch:
        lines.append("- Aucun mouvement ne dépasse les seuils de veille définis pour ce rapport.")
    lines += ["", "ACTUALITÉS À VÉRIFIER"]
    for item in news[:15]:
        lines.append(f"- {item['title']} — {item['source']} — {item['published']} — {item['url']}")
    if not news:
        lines.append("- Aucun flux d'actualité n'a pu être récupéré pendant cette exécution.")
    lines += ["", "QUALITÉ ET SOURCES", "- Prix historiques : Yahoo Finance via yfinance (source non institutionnelle, disponibilité non garantie).", "- Titres : flux RSS Google News, liens vers les publications d'origine lorsqu'ils sont fournis.", f"- Heure de collecte : {started.isoformat(timespec='seconds')}.", f"- Erreurs prix : {len(data_errors)}; erreurs flux actualités : {len(news_errors)}."]
    if data_errors:
        lines += ["", "DONNÉES MANQUANTES"] + [f"- {e}" for e in data_errors[:20]]
    if news_errors:
        lines += ["", "ERREURS DE FLUX"] + [f"- {e}" for e in news_errors]
    lines += ["", "Avertissement : contenu informatif et expérimental, pas un conseil d'investissement. Vérifier les données et les actualités avant toute décision."]
    plain = "\n".join(lines)

    escaped = html.escape(plain)
    html_body = (
        "<html><body style='font-family:Arial,sans-serif;line-height:1.45'>"
        f"<h2>{html.escape(title)}</h2><p>Heure Madagascar : {now_local:%Y-%m-%d %H:%M:%S %Z}</p>"
        "<p>Rapport orienté décision. Les indicateurs techniques servent à l'analyse interne et ne sont pas affichés. Les probabilités directionnelles calibrées ne sont pas encore activées.</p>"
        f"<pre style='white-space:pre-wrap;font-family:Arial,sans-serif'>{escaped}</pre>"
        "</body></html>"
    )
    snapshot = {
        "report_type": report_type,
        "run_time_utc": started.isoformat(timespec="seconds"),
        "run_time_madagascar": now_local.isoformat(timespec="seconds"),
        "assets": [asdict(r) for r in rows],
        "news": news[:15],
        "data_error_count": len(data_errors),
        "news_error_count": len(news_errors),
    }
    return plain, html_body, snapshot

def send_email(subject: str, plain: str, html_body: str) -> None:
    required = ("SMTP_USERNAME", "SMTP_APP_PASSWORD", "REPORT_RECIPIENT")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError("Secrets manquants : " + ", ".join(missing))
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ["SMTP_USERNAME"].strip()
    message["To"] = os.environ["REPORT_RECIPIENT"].strip()
    message.set_content(plain)
    message.add_alternative(html_body, subtype="html")
    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(message["From"], os.environ["SMTP_APP_PASSWORD"].replace(" ", ""))
        server.send_message(message)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report-type", choices=("morning", "update", "audit"), default="morning")
    parser.add_argument("--no-email", action="store_true", help="Generate files/state without sending email")
    args = parser.parse_args()
    plain, html_body, snapshot = make_report(args.report_type)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Save the exact report text to aid later audit.
    report_path = STATE_DIR / f"latest_{args.report_type}.txt"
    report_path.write_text(plain, encoding="utf-8")
    # Append the immutable forecast/data snapshot before email delivery.
    # Workflow commits state only after successful completion.
    rows = [AssetRow(**item) for item in snapshot["assets"]]
    write_state(snapshot, rows)
    subject = f"[Market Intelligence] {args.report_type.upper()} — {snapshot['run_time_madagascar'][:16]}"
    if not args.no_email:
        send_email(subject, plain, html_body)
    print(f"Report generated: {report_path.name}; assets={len(rows)}; type={args.report_type}; email={'disabled' if args.no_email else 'sent'}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
