from __future__ import annotations

import argparse
import html
import json
import math
import os
import re
import smtplib
import ssl
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
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
REPORT_URL = "https://miaranarm.github.io/market-intelligence-daily/"
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
    "GOOGL": {"name": "Alphabet", "class": "US equity"},
    "META": {"name": "Meta Platforms", "class": "US equity"},
    "TSLA": {"name": "Tesla", "class": "US equity"},
    "AVGO": {"name": "Broadcom", "class": "US equity"},
    "JPM": {"name": "JPMorgan Chase", "class": "US equity"},
    "BAC": {"name": "Bank of America", "class": "US equity"},
    "XOM": {"name": "Exxon Mobil", "class": "US equity"},
    "LLY": {"name": "Eli Lilly", "class": "US equity"},
    "WMT": {"name": "Walmart", "class": "US equity"},
    "COST": {"name": "Costco", "class": "US equity"},
    "CAT": {"name": "Caterpillar", "class": "US equity"},
    "VFIAX": {"name": "Vanguard 500 Index Fund Admiral Shares", "class": "Mutual fund"},
    "FXAIX": {"name": "Fidelity 500 Index Fund", "class": "Mutual fund"},
    "VTSAX": {"name": "Vanguard Total Stock Market Index Fund Admiral Shares", "class": "Mutual fund"},
    "VWELX": {"name": "Vanguard Wellington Fund", "class": "Balanced mutual fund"},
    "FBALX": {"name": "Fidelity Balanced Fund", "class": "Balanced mutual fund"},
    "FTBFX": {"name": "Fidelity Total Bond Fund", "class": "Bond mutual fund"},
}

NEWS_FEEDS = [
    # Official primary sources: macroeconomic releases, monetary policy and energy.
    ("Federal Reserve — communiqués officiels", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("Bureau of Labor Statistics — statistiques du travail et inflation", "https://www.bls.gov/feed/bls_latest.rss"),
    ("Banque centrale européenne — communiqués", "https://www.ecb.europa.eu/rss/press.html"),
    ("US Energy Information Administration — énergie", "https://www.eia.gov/rss/todayinenergy.xml"),
    # Cross-checking across several publishers; aggregator headlines are leads, not independent proof.
    ("Google News — macroéconomie mondiale et banques centrales", "https://news.google.com/rss/search?q=inflation+employment+GDP+central+banks+interest+rates&hl=en-US&gl=US&ceid=US:en"),
    ("Google News — marchés et économie", "https://news.google.com/rss/search?q=global+markets+economy+central+banks&hl=en-US&gl=US&ceid=US:en"),
    ("Google News — résultats mondiaux des entreprises", "https://news.google.com/rss/search?q=company+earnings+quarterly+results+guidance+revenue+profit&hl=en-US&gl=US&ceid=US:en"),
    ("Google News — résultats et prévisions États-Unis", "https://news.google.com/rss/search?q=US+earnings+beat+miss+analyst+estimates+guidance&hl=en-US&gl=US&ceid=US:en"),
    ("Google News — résultats Europe et Royaume-Uni", "https://news.google.com/rss/search?q=European+UK+company+earnings+quarterly+results&hl=en-GB&gl=GB&ceid=GB:en"),
    ("Google News — résultats Asie et Chine", "https://news.google.com/rss/search?q=Asia+China+Japan+company+earnings+results+guidance&hl=en-US&gl=US&ceid=US:en"),
    ("Google News — technologie et semi-conducteurs", "https://news.google.com/rss/search?q=technology+semiconductor+earnings+AI+capital+expenditure&hl=en-US&gl=US&ceid=US:en"),
    ("Google News — banques et crédit", "https://news.google.com/rss/search?q=bank+earnings+net+interest+margin+credit+losses&hl=en-US&gl=US&ceid=US:en"),
    ("Google News — énergie et industrie", "https://news.google.com/rss/search?q=energy+industrial+company+earnings+production+guidance&hl=en-US&gl=US&ceid=US:en"),
    ("Google News — consommation et santé", "https://news.google.com/rss/search?q=consumer+healthcare+company+earnings+sales+guidance&hl=en-US&gl=US&ceid=US:en"),
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

def _is_recent_news_item(published: str, now: datetime | None = None, max_age_days: int = 10) -> bool:
    """Reject dated headlines older than the freshness window; keep undated/unparseable items transparently."""
    if not published:
        return True
    try:
        published_at = parsedate_to_datetime(published)
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        age_days = (reference - published_at.astimezone(timezone.utc)).total_seconds() / 86400
        return -1 <= age_days <= max_age_days
    except (TypeError, ValueError, OverflowError):
        return True


def fetch_news() -> tuple[list[dict[str, str]], list[str]]:
    feed_batches: list[list[dict[str, str]]] = []
    errors: list[str] = []
    seen: set[str] = set()
    headers = {"User-Agent": USER_AGENT}
    for feed_name, url in NEWS_FEEDS:
        batch: list[dict[str, str]] = []
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            root = ET.fromstring(response.content)
            # Cap each feed so one prolific publisher cannot crowd out other sources.
            for item in root.findall(".//item")[:6]:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                published = (item.findtext("pubDate") or "").strip()
                source = (item.findtext("source") or "").strip() or feed_name
                if title and link and link not in seen and _is_recent_news_item(published):
                    seen.add(link)
                    batch.append({"title": title, "url": link, "published": published, "source": source})
        except Exception as exc:
            # The BLS RSS endpoint may reject automated requests (HTTP 403). Use a
            # clearly identified Google News search restricted to BLS releases as fallback.
            if "Bureau of Labor Statistics" in feed_name:
                fallback_url = "https://news.google.com/rss/search?q=site%3Abls.gov%2Fnews.release+OR+site%3Abls.gov%2Fnews.release%2Farchives+CPI+employment+inflation&hl=en-US&gl=US&ceid=US:en"
                try:
                    fallback_response = requests.get(fallback_url, headers=headers, timeout=15)
                    fallback_response.raise_for_status()
                    fallback_root = ET.fromstring(fallback_response.content)
                    for item in fallback_root.findall(".//item")[:6]:
                        title = (item.findtext("title") or "").strip()
                        link = (item.findtext("link") or "").strip()
                        published = (item.findtext("pubDate") or "").strip()
                        source = (item.findtext("source") or "").strip() or "Google News — recherche ciblée BLS"
                        if title and link and link not in seen and _is_recent_news_item(published):
                            seen.add(link)
                            batch.append({"title": title, "url": link, "published": published, "source": source})
                    errors.append(f"{feed_name}: flux direct indisponible ({type(exc).__name__}); repli Google News ciblé BLS utilisé")
                except Exception as fallback_exc:
                    errors.append(f"{feed_name}: flux direct {type(exc).__name__}; repli également en échec: {type(fallback_exc).__name__}: {str(fallback_exc)[:100]}")
            else:
                errors.append(f"{feed_name}: {type(exc).__name__}: {str(exc)[:120]}")
        feed_batches.append(batch)

    # Round-robin interleaving keeps official sources and independent publishers visible together.
    items: list[dict[str, str]] = []
    for item_index in range(6):
        for batch in feed_batches:
            if item_index < len(batch):
                items.append(batch[item_index])
    return items[:36], errors



# CIKs are SEC-assigned company identifiers. Only issuers with stable, well-known filings are included.
SEC_COMPANIES: dict[str, dict[str, str]] = {
    "AAPL": {"name": "Apple", "cik": "0000320193"},
    "MSFT": {"name": "Microsoft", "cik": "0000789019"},
    "NVDA": {"name": "Nvidia", "cik": "0001045810"},
    "AMZN": {"name": "Amazon", "cik": "0001018724"},
    "GOOGL": {"name": "Alphabet", "cik": "0001652044"},
    "META": {"name": "Meta Platforms", "cik": "0001326801"},
    "TSLA": {"name": "Tesla", "cik": "0001318605"},
    "AVGO": {"name": "Broadcom", "cik": "0001730168"},
    "JPM": {"name": "JPMorgan Chase", "cik": "0000019617"},
    "BAC": {"name": "Bank of America", "cik": "0000070858"},
    "XOM": {"name": "Exxon Mobil", "cik": "0000034088"},
    "LLY": {"name": "Eli Lilly", "cik": "0000059478"},
    "WMT": {"name": "Walmart", "cik": "0000104169"},
    "COST": {"name": "Costco", "cik": "0000909832"},
    "CAT": {"name": "Caterpillar", "cik": "0000018230"},
}

REVENUE_TAGS = (
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "Revenues",
    "SalesRevenueNet",
    "SalesRevenueGoodsNet",
    "SalesRevenueServicesNet",
    "OperatingRevenues",
)
OPERATING_INCOME_TAGS = ("OperatingIncomeLoss",)
OPERATING_CASH_FLOW_TAGS = ("NetCashProvidedByUsedInOperatingActivities",)
CAPEX_TAGS = ("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets")

def _quarterly_fact_points(companyfacts: dict[str, Any], tag_names: tuple[str, ...], unit_names: tuple[str, ...]) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Return latest reported 10-Q quarterly fact and comparable year-earlier fact, without mixing annual totals."""
    facts = companyfacts.get("facts", {}).get("us-gaap", {})
    candidates: list[tuple[str, dict[str, Any]]] = []
    for tag in tag_names:
        node = facts.get(tag, {})
        for unit in unit_names:
            for item in node.get("units", {}).get(unit, []):
                if item.get("form") != "10-Q" or item.get("fp") not in ("Q1", "Q2", "Q3"):
                    continue
                if not item.get("start") or not item.get("end") or item.get("val") is None:
                    continue
                try:
                    from datetime import date
                    duration = (date.fromisoformat(item["end"]) - date.fromisoformat(item["start"])).days
                except (TypeError, ValueError):
                    continue
                if 70 <= duration <= 110:
                    candidates.append((tag, item))
        if candidates:
            break
    if not candidates:
        return None, None, None
    # Prefer the most recently filed version of the latest quarter end.
    candidates.sort(key=lambda pair: (pair[1].get("end", ""), pair[1].get("filed", "")))
    latest_tag, latest = candidates[-1]
    from datetime import date
    latest_end = date.fromisoformat(latest["end"])
    prior = []
    for tag, item in candidates:
        try:
            days = (latest_end - date.fromisoformat(item["end"])).days
        except (TypeError, ValueError):
            continue
        if 330 <= days <= 400:
            prior.append((abs(days - 365), item.get("filed", ""), item))
    prior_item = sorted(prior, key=lambda x: (x[0], x[1]))[0][2] if prior else None
    return latest, prior_item, latest_tag


def _quarterly_or_q4_fact_points(
    companyfacts: dict[str, Any], tag_names: tuple[str, ...], unit_names: tuple[str, ...]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """Prefer the latest discrete quarter; derive Q4 only when FY and all three matching quarters exist."""
    from datetime import date, timedelta

    latest, prior, tag = _quarterly_fact_points(companyfacts, tag_names, unit_names)
    facts = companyfacts.get("facts", {}).get("us-gaap", {})

    def discrete_quarters(node: dict[str, Any], unit: str, annual: dict[str, Any]) -> dict[str, dict[str, Any]]:
        selected: dict[str, dict[str, Any]] = {}
        for item in node.get("units", {}).get(unit, []):
            if item.get("form") != "10-Q" or item.get("fp") not in ("Q1", "Q2", "Q3"):
                continue
            if not item.get("start") or not item.get("end") or item.get("val") is None:
                continue
            try:
                start, end = date.fromisoformat(item["start"]), date.fromisoformat(item["end"])
                duration = (end - start).days
                fy_start, fy_end = date.fromisoformat(annual["start"]), date.fromisoformat(annual["end"])
            except (TypeError, ValueError):
                continue
            if 70 <= duration <= 110 and fy_start <= start <= end <= fy_end:
                fp = item["fp"]
                current = selected.get(fp)
                if current is None or item.get("filed", "") > current.get("filed", ""):
                    selected[fp] = item
        return selected

    def derive(annual: dict[str, Any], node: dict[str, Any], unit: str) -> dict[str, Any] | None:
        quarters = discrete_quarters(node, unit, annual)
        if set(quarters) != {"Q1", "Q2", "Q3"}:
            return None
        ends = [date.fromisoformat(quarters[q]["end"]) for q in ("Q1", "Q2", "Q3")]
        if ends != sorted(ends) or len(set(ends)) != 3:
            return None
        if annual.get("filed") and any(q.get("filed", "") > annual["filed"] for q in quarters.values()):
            return None
        value = float(annual["val"]) - sum(float(quarters[q]["val"]) for q in ("Q1", "Q2", "Q3"))
        return {
            "start": (ends[-1] + timedelta(days=1)).isoformat(),
            "end": annual["end"], "val": value, "form": "10-K",
            "fp": "Q4 (calculé)", "filed": annual.get("filed", ""),
            "derived": True,
        }

    for tag_name in (tag_names if tag is None else (tag,)):
        node = facts.get(tag_name, {})
        for unit in unit_names:
            annuals = []
            for item in node.get("units", {}).get(unit, []):
                if item.get("form") != "10-K" or item.get("fp") != "FY":
                    continue
                if not item.get("start") or not item.get("end") or item.get("val") is None:
                    continue
                try:
                    duration = (date.fromisoformat(item["end"]) - date.fromisoformat(item["start"])).days
                except (TypeError, ValueError):
                    continue
                if 330 <= duration <= 400:
                    annuals.append(item)
            annuals.sort(key=lambda x: (x.get("end", ""), x.get("filed", "")))
            q4_candidates = []
            for annual in annuals:
                q4 = derive(annual, node, unit)
                if q4 is not None:
                    q4_candidates.append((annual, q4))
            if not q4_candidates:
                continue
            annual, q4 = q4_candidates[-1]
            if latest and latest.get("end", "") >= q4["end"]:
                return latest, prior, tag
            prior_q4 = None
            for previous_annual, previous_q4 in reversed(q4_candidates[:-1]):
                days = (date.fromisoformat(q4["end"]) - date.fromisoformat(previous_q4["end"])).days
                if 330 <= days <= 400:
                    prior_q4 = previous_q4
                    break
            return q4, prior_q4, tag_name
    return latest, prior, tag

def fetch_company_fundamentals() -> tuple[list[dict[str, Any]], list[str]]:
    """Fetch SEC-reported quarterly fundamentals; derive Q4 only from annual totals minus Q1-Q3."""
    results: list[dict[str, Any]] = []
    errors: list[str] = []
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    for ticker, company in SEC_COMPANIES.items():
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company['cik']}.json"
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            payload = response.json()
            revenue, prior_revenue, revenue_tag = _quarterly_or_q4_fact_points(
                payload, REVENUE_TAGS, ("USD",)
            )
            eps, prior_eps, eps_tag = _quarterly_fact_points(
                payload, ("EarningsPerShareDiluted",), ("USD/shares",)
            )
            operating_income, _, operating_income_tag = _quarterly_or_q4_fact_points(
                payload, OPERATING_INCOME_TAGS, ("USD",)
            )
            operating_cash_flow, _, cash_flow_tag = _quarterly_or_q4_fact_points(
                payload, OPERATING_CASH_FLOW_TAGS, ("USD",)
            )
            capex, _, capex_tag = _quarterly_or_q4_fact_points(
                payload, CAPEX_TAGS, ("USD",)
            )
            if not revenue and not eps and not operating_income and not operating_cash_flow:
                errors.append(f"{ticker}: aucun chiffre trimestriel 10-Q exploitable dans les tags XBRL retenus")
                continue
            revenue_growth = None
            if revenue and prior_revenue and float(prior_revenue["val"]) != 0:
                revenue_growth = (float(revenue["val"]) / float(prior_revenue["val"]) - 1) * 100
            eps_growth = None
            if eps and prior_eps and float(prior_eps["val"]) != 0:
                eps_growth = (float(eps["val"]) / float(prior_eps["val"]) - 1) * 100
            latest_end = max(
                [x["end"] for x in (revenue, eps, operating_income, operating_cash_flow, capex) if x and x.get("end")],
                default="date inconnue"
            )
            revenue_value = float(revenue["val"]) if revenue else None
            operating_income_value = float(operating_income["val"]) if operating_income else None
            cash_flow_value = float(operating_cash_flow["val"]) if operating_cash_flow else None
            capex_value = abs(float(capex["val"])) if capex else None
            operating_margin_pct = (
                round(operating_income_value / revenue_value * 100, 2)
                if operating_income_value is not None and revenue_value not in (None, 0) else None
            )
            free_cash_flow_value = (
                cash_flow_value - capex_value
                if cash_flow_value is not None and capex_value is not None else None
            )
            results.append({
                "ticker": ticker, "name": company["name"], "period": latest_end,
                "revenue": revenue_value,
                "revenue_yoy_pct": round(revenue_growth, 2) if revenue_growth is not None else None,
                "revenue_tag": revenue_tag, "revenue_derived": bool(revenue and revenue.get("derived")), "eps": float(eps["val"]) if eps else None,
                "eps_yoy_pct": round(eps_growth, 2) if eps_growth is not None else None,
                "eps_tag": eps_tag, "eps_period": eps.get("end") if eps else None,
                "operating_income": operating_income_value,
                "operating_income_tag": operating_income_tag, "operating_income_derived": bool(operating_income and operating_income.get("derived")),
                "operating_margin_pct": operating_margin_pct,
                "operating_cash_flow": cash_flow_value,
                "operating_cash_flow_tag": cash_flow_tag, "operating_cash_flow_derived": bool(operating_cash_flow and operating_cash_flow.get("derived")),
                "capex": capex_value,
                "capex_tag": capex_tag, "capex_derived": bool(capex and capex.get("derived")),
                "free_cash_flow": free_cash_flow_value,
                "source": f"https://data.sec.gov/api/xbrl/companyfacts/CIK{company['cik']}.json",
            })
            time.sleep(0.12)
        except Exception as exc:
            errors.append(f"{ticker}: {type(exc).__name__}: {str(exc)[:120]}")
    return results, errors

def infer_macro_impact(headline: str) -> tuple[str, str, str]:
    """Conservative headline taxonomy; this proposes transmission channels, not verified event facts."""
    text = headline.casefold()
    if any(k in text for k in ("inflation", "consumer price", "cpi", "pce", "ppi", "price index")):
        return ("Inflation", "obligations, devises, indices/actions, or, ETF et fonds",
                "Comparer impérativement le chiffre publié au consensus et au précédent. Une surprise inflationniste à la hausse peut relever les taux anticipés et peser sur les prix obligataires et les valorisations; une surprise à la baisse peut produire l'effet inverse. Le titre seul ne permet pas de connaître le sens de la surprise.")
    if any(k in text for k in ("central bank", "federal reserve", "fed ", "ecb", "bank of japan", "interest rate", "rate decision", "monetary policy")):
        return ("Banques centrales", "obligations, devises, indices/futures, actions, crypto, ETF et fonds",
                "Lire le communiqué original et comparer le ton ainsi que la trajectoire des taux aux attentes déjà intégrées dans les prix. Un ton plus restrictif peut soutenir la devise et les rendements, mais peser sur les actifs sensibles aux taux; un ton plus accommodant peut inverser ces effets. La réaction dépend de la surprise, pas seulement de la décision.")
    if any(k in text for k in ("payroll", "employment", "unemployment", "jobless", "jobs report", "wage growth", "labor market")):
        return ("Emploi et salaires", "devises, obligations, indices/futures, actions, ETF et fonds",
                "Vérifier les chiffres et les révisions par rapport au consensus. Un marché du travail plus robuste peut repousser les baisses de taux attendues; un affaiblissement peut les avancer si l'inflation le permet. Surveiller la devise concernée, les rendements obligataires et les secteurs sensibles à la croissance.")
    if any(k in text for k in ("gdp", "gross domestic product", "pmi", "manufacturing", "retail sales", "economic growth", "recession", "industrial production")):
        return ("Croissance et activité", "indices/futures, actions, matières premières, devises, obligations, ETF et fonds",
                "Comparer la publication au consensus et aux données précédentes. Une activité plus forte peut soutenir les actifs cycliques et la demande de matières premières, tout en augmentant parfois les rendements; une surprise négative peut favoriser les obligations de qualité mais peser sur les actifs cycliques. L'effet dépend de l'inflation et du pays concerné.")
    if any(k in text for k in ("crude oil", "oil prices", "opec", "natural gas", "energy supply", "eia", "petroleum")):
        return ("Énergie et matières premières", "matières premières, devises des producteurs/importateurs, actions, indices, obligations, ETF et fonds",
                "Distinguer variation de l'offre, de la demande, des stocks et prime géopolitique. Un choc d'offre peut soutenir les prix de l'énergie et raviver les risques inflationnistes; un ralentissement de la demande peut peser sur les matières premières cycliques. Vérifier les données d'origine et la réaction effective des contrats à terme.")
    if any(k in text for k in ("tariff", "trade war", "trade deal", "sanction", "china economy", "chinese economy", "export restriction", "supply chain")):
        return ("Commerce international et Chine", "indices/futures, actions cycliques, matières premières, devises, ETF et fonds",
                "Évaluer les pays, secteurs et chaînes d'approvisionnement exposés. Des barrières commerciales ou restrictions peuvent modifier coûts, marges et perspectives de croissance; les matières premières et devises sensibles au commerce peuvent réagir. La direction dépend des mesures exactes, des représailles et de ce qui était déjà anticipé.")
    if any(k in text for k in ("geopolitical", "war ", "conflict", "attack", "ceasefire", "sanctions", "election", "political crisis")):
        return ("Géopolitique et risque", "matières premières, devises refuges, obligations, indices/futures, actions, crypto et fonds",
                "Identifier d'abord les actifs directement exposés et la transmission par l'énergie, le commerce ou les sanctions. Une hausse de l'aversion au risque peut favoriser certains actifs refuges, mais les réactions sont instables et peuvent s'inverser rapidement. Ne pas déduire automatiquement un mouvement de marché du seul titre.")
    if any(k in text for k in ("earnings", "quarterly results", "profit warning", "revenue", "guidance", "stock buyback", "eps", "beat estimates", "miss estimates", "operating margin", "cash flow", "capital expenditure", "capex", "investor day", "merger", "acquisition", "dividend cut", "layoffs")):
        return ("Résultats d'entreprises", "actions concernées, secteurs, indices/futures, ETF et fonds",
                "Comparer bénéfices, chiffre d'affaires et perspectives aux attentes, et distinguer le résultat publié des prévisions de direction. Les effets sur les indices et ETF dépendent du poids de l'entreprise et de la réaction après publication; les obligations et devises ne sont généralement touchées qu'indirectement.")
    if any(k in text for k in ("bitcoin", "crypto", "cryptocurrency", "digital asset", "crypto etf")):
        return ("Cryptoactifs et réglementation", "cryptomonnaies, ETF concernés, actions liées et appétit pour le risque",
                "Vérifier si la nouvelle porte sur la réglementation, les flux, la liquidité, la sécurité ou les conditions macroéconomiques. L'effet peut être spécifique à l'actif ou se transmettre au sentiment de risque; une corrélation avec les actions ne doit pas être supposée constante.")
    if any(k in text for k in ("treasury yield", "bond yield", "government bond", "debt auction", "credit spread", "sovereign debt")):
        return ("Obligations et crédit", "obligations, devises, indices/futures, actions, ETF obligataires et fonds",
                "Rappel : le prix d'une obligation à taux fixe évolue généralement en sens inverse de son rendement. Examiner la maturité, l'inflation, les anticipations de taux et le risque de crédit avant d'expliquer le mouvement; l'impact sur actions et devises dépend du contexte.")
    return ("À qualifier", "catégories à confirmer selon le sujet",
            "Le titre seul ne permet pas de déduire un impact fiable. Ouvrir la source originale, vérifier les faits, la date, les chiffres et le consensus éventuel, puis observer la réaction des actifs concernés. Aucune direction n'est attribuée automatiquement.")

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
    if not lines:
        return ["Pas assez de données croisées pour formuler un commentaire de régime robuste. — Source de données de marché : https://finance.yahoo.com/."]
    return [line + " — Source des cours : Yahoo Finance, données historiques https://finance.yahoo.com/." for line in lines]

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
    record_new_forecasts(state, rows)
    FORECAST_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    out = pd.DataFrame([asdict(r) for r in rows])
    out.insert(0, "run_time_utc", snapshot["run_time_utc"])
    out.insert(1, "report_type", snapshot["report_type"])
    out.to_csv(HISTORY_FILE, mode="a", header=not HISTORY_FILE.exists(), index=False)


def evaluate_forecasts(state: dict[str, Any]) -> dict[str, Any]:
    """Evaluate stored, rule-based directional forecasts against later distinct market dates."""
    snapshots = state.get("forecasts", [])
    prices: dict[str, dict[str, float]] = {}
    for snap in snapshots:
        for asset in snap.get("assets", []):
            ticker, day, price = asset.get("ticker"), asset.get("data_timestamp"), asset.get("price")
            if ticker and day and price is not None:
                try:
                    prices.setdefault(ticker, {})[str(day)] = float(price)
                except (TypeError, ValueError):
                    continue

    records = state.get("forecast_records", [])
    matured: list[dict[str, Any]] = []
    pending = 0
    for record in records:
        series = prices.get(record.get("ticker", ""), {})
        base_date = str(record.get("base_date", ""))
        future_dates = sorted(day for day in series if day > base_date)
        horizon = int(record.get("horizon_sessions", 1))
        if len(future_dates) < horizon:
            pending += 1
            continue
        target_date = future_dates[horizon - 1]
        base_price = record.get("base_price")
        target_price = series[target_date]
        if not base_price:
            continue
        realized_pct = (target_price / float(base_price) - 1) * 100
        direction = "hausse" if realized_pct > 0.1 else ("baisse" if realized_pct < -0.1 else "neutre")
        predicted = record.get("direction", "neutre")
        matured.append({
            **record,
            "target_date": target_date,
            "realized_pct": round(realized_pct, 4),
            "realized_direction": direction,
            "correct": direction == predicted,
        })

    by_horizon: dict[str, Any] = {}
    for horizon in (1, 5):
        sample = [r for r in matured if int(r.get("horizon_sessions", 1)) == horizon]
        by_horizon[str(horizon)] = {
            "n": len(sample),
            "correct": sum(bool(r["correct"]) for r in sample),
            "accuracy_pct": round(100 * sum(bool(r["correct"]) for r in sample) / len(sample), 1) if sample else None,
            "mean_abs_move_pct": round(sum(abs(float(r["realized_pct"])) for r in sample) / len(sample), 3) if sample else None,
        }
    return {"matured": matured, "pending": pending, "by_horizon": by_horizon}


def record_new_forecasts(state: dict[str, Any], rows: list[AssetRow]) -> None:
    """Store a transparent momentum-baseline forecast once per asset and market date."""
    records = state.setdefault("forecast_records", [])
    known = {r.get("id") for r in records}
    for row in rows:
        if not row.data_timestamp or row.price is None or row.five_day_pct is None:
            continue
        # Neutral forecasts are retained too; the simple baseline must be judged fairly.
        direction = "hausse" if row.five_day_pct >= 0.5 else ("baisse" if row.five_day_pct <= -0.5 else "neutre")
        for horizon in (1, 5):
            record_id = f"{row.ticker}|{row.data_timestamp}|{horizon}"
            if record_id in known:
                continue
            records.append({
                "id": record_id,
                "ticker": row.ticker,
                "name": row.name,
                "asset_class": row.asset_class,
                "base_date": row.data_timestamp,
                "base_price": row.price,
                "direction": direction,
                "horizon_sessions": horizon,
                "rule": "baseline descriptive: direction from 5-session return; >= +0.5% hausse, <= -0.5% baisse, otherwise neutre",
                "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            known.add(record_id)
    state["forecast_records"] = records[-10000:]


def append_self_audit(lines: list[str], state: dict[str, Any]) -> None:
    evaluation = evaluate_forecasts(state)
    lines.extend([
        "",
        "AUDIT CRITIQUE DES ANALYSES PRÉCÉDENTES",
        f"- Prévisions historiques enregistrées : {len(state.get('forecast_records', []))}; prévisions arrivées à échéance : {len(evaluation['matured'])}; encore en attente : {evaluation['pending']}.",
        "- Référence évaluée : règle de momentum simple fondée sur le rendement des cinq dernières séances. C'est un point de comparaison expérimental, pas une recommandation de trading.",
    ])
    for horizon, label in (("1", "1 séance"), ("5", "5 séances")):
        stats = evaluation["by_horizon"][horizon]
        if stats["n"]:
            lines.append(
                f"- Horizon {label} : {stats['correct']}/{stats['n']} directions correctes "
                f"({stats['accuracy_pct']} %); mouvement absolu moyen observé : {stats['mean_abs_move_pct']} %."
            )
        else:
            lines.append(f"- Horizon {label} : aucun échantillon arrivé à échéance; performance non évaluable.")
    if len(evaluation["matured"]) < 30:
        lines.append("- Conclusion méthodologique : échantillon encore insuffisant pour déclarer cette règle fiable ou modifier automatiquement la méthode.")
    else:
        lines.append("- Contrôle critique : interpréter les résultats avec les coûts, les régimes de marché et une validation hors échantillon; une exactitude directionnelle seule ne prouve pas la rentabilité.")
    if evaluation["matured"]:
        wrong = [r for r in evaluation["matured"] if not r["correct"]]
        if wrong:
            recent = wrong[-3:]
            details = "; ".join(
                f"{r['name']} ({r['horizon_sessions']} séance(s), prévu {r['direction']}, réalisé {r['realized_direction']}, {r['realized_pct']:+.2f} %)"
                for r in recent
            )
            lines.append(f"- Exemples d'erreurs à examiner : {details}.")
        else:
            lines.append("- Aucun échec directionnel dans l'échantillon arrivé à échéance; cela ne suffit pas à prouver la robustesse.")
    lines.append("- Source des prix évalués : Yahoo Finance via yfinance (https://finance.yahoo.com/); la qualité et la disponibilité de ces données ne sont pas garanties.")
    lines.append("- Les prévisions originales sont conservées pour empêcher toute réécriture rétrospective. Les changements de méthode devront être justifiés par des échantillons suffisants et des tests hors échantillon.")


def linkify_text(value: str) -> str:
    """Escape report text while turning source URLs into safe, clickable links."""
    chunks = re.split(r"(https?://[^\s<>]+)", value)
    rendered = []
    for chunk in chunks:
        if chunk.startswith(("https://", "http://")):
            clean_url = chunk.rstrip(".,;)")
            suffix = chunk[len(clean_url):]
            escaped_url = html.escape(clean_url, quote=True)
            rendered.append(f'<a href="{escaped_url}" target="_blank" rel="noopener noreferrer">{html.escape(clean_url)}</a>{html.escape(suffix)}')
        else:
            rendered.append(html.escape(chunk))
    return "".join(rendered)


def render_professional_html(plain: str, title: str, now_local: datetime, started: datetime) -> str:
    """Turn the text report into a responsive, sectioned HTML briefing."""
    lines = plain.splitlines()
    reading_minutes = max(1, round(len(plain.split()) / 180))
    content_lines = lines[4:] if len(lines) >= 4 else lines
    blocks: list[str] = []
    i = 0
    while i < len(content_lines):
        line = content_lines[i].strip()
        if not line:
            i += 1
            continue
        if line.startswith("Actif | Classe |"):
            headers = [x.strip() for x in line.split("|")]
            rows_html = []
            i += 1
            while i < len(content_lines) and " | " in content_lines[i]:
                cells = [x.strip() for x in content_lines[i].split("|")]
                rows_html.append("<tr>" + "".join(f"<td>{linkify_text(cell)}</td>" for cell in cells) + "</tr>")
                i += 1
            blocks.append("<div class='table-wrap'><table><thead><tr>" +
                          "".join(f"<th>{html.escape(cell)}</th>" for cell in headers) +
                          "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table></div>")
            continue
        if line == line.upper() and len(line) >= 5 and any(c.isalpha() for c in line):
            blocks.append(f"<h2>{html.escape(line.title() if len(line) < 55 else line)}</h2>")
            i += 1
            continue
        if line.startswith("- "):
            items = []
            while i < len(content_lines) and content_lines[i].strip().startswith("- "):
                items.append("<li>" + linkify_text(content_lines[i].strip()[2:]) + "</li>")
                i += 1
            blocks.append("<ul>" + "".join(items) + "</ul>")
            continue
        blocks.append("<p>" + linkify_text(line) + "</p>")
        i += 1

    return (
        "<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)} | Market Intelligence Daily</title>"
        "<style>"
        "*{box-sizing:border-box}body{margin:0;background:#edf1f7;color:#172238;font:15px/1.7 -apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif}"
        ".wrap{max-width:1180px;margin:0 auto;padding:26px 16px 56px}.hero{background:linear-gradient(125deg,#101a2d,#1d3b62 72%,#28517a);"
        "color:#fff;padding:clamp(24px,4vw,42px);border-radius:20px;box-shadow:0 16px 38px #10213b20}.eyebrow{font-size:11px;letter-spacing:.18em;"
        "text-transform:uppercase;color:#b6d0f1;font-weight:800}.hero h1{font-size:clamp(27px,4vw,42px);line-height:1.12;margin:12px 0 18px;max-width:850px}"
        ".meta{font-size:13px;color:#d3deed}.notice{margin:18px 0;padding:15px 18px;background:#fff8e8;border-left:4px solid #d9a441;border-radius:9px;color:#604b20}"
        ".report{background:#fff;padding:clamp(18px,3vw,34px);border-radius:18px;box-shadow:0 6px 26px #1722380a}.report h2{font-size:17px;letter-spacing:.035em;"
        "color:#19365b;margin:30px 0 12px;padding-bottom:9px;border-bottom:1px solid #e3e9f1}.report h2:first-child{margin-top:0}"
        ".report p{margin:10px 0}.report ul{padding-left:22px;margin:8px 0 18px}.report li{padding:3px 0}.table-wrap{overflow-x:auto;margin:14px 0 22px;border:1px solid #e3e9f1;border-radius:10px}"
        "table{border-collapse:collapse;width:100%;min-width:720px;font-size:13px}th{background:#f2f5fa;color:#344b68;text-align:left;font-weight:750}"
        "th,td{padding:10px 12px;border-bottom:1px solid #e9edf3;vertical-align:top}tbody tr:nth-child(even){background:#fafbfd}tbody tr:last-child td{border-bottom:0}"
        "a{color:#145ca8;text-decoration:none;overflow-wrap:anywhere}a:hover{text-decoration:underline}.footer{color:#68778d;font-size:12px;margin:18px 4px}"
        "@media(max-width:600px){.wrap{padding:12px 9px 30px}.hero,.report{border-radius:13px}.report{padding:16px}.report h2{font-size:15px}}"
        "</style></head><body><main class='wrap'>"
        "<header class='hero'><div class='eyebrow'>Daily Market Intelligence · Briefing multi-actifs</div>"
        f"<h1>{html.escape(title)}</h1><div class='meta'>Heure de Madagascar : {now_local:%d/%m/%Y à %H:%M:%S %Z}</div>"
        f"<div class='meta'>Généré le {started:%d/%m/%Y à %H:%M:%S UTC}</div>"
        f"<div class='meta'>Temps de lecture estimé : {reading_minutes} min (à 180 mots/minute)</div></header>"
        "<div class='notice'><strong>Lecture critique :</strong> les données de marché peuvent être retardées, révisées ou indisponibles. "
        "Les faits observés sont distingués des interprétations; les liens permettent de retrouver les sources citées.</div>"
        "<article class='report'>" + "".join(blocks) + "</article>"
        "<p class='footer'>Rapport expérimental d'information. Vérifier les données et les sources avant toute décision; ce document ne constitue pas un conseil en investissement.</p>"
        "</main></body></html>"
    )



def market_conviction(rows: list[AssetRow]) -> dict[str, Any]:
    """Transparent, uncalibrated cross-asset scoring heuristic; never label it statistically calibrated."""
    by = {r.ticker: r for r in rows}
    score = 0
    evidence: list[str] = []
    sp = by.get("^GSPC")
    ndx = by.get("^IXIC")
    dow = by.get("^DJI")
    vix = by.get("^VIX")
    if sp and sp.five_day_pct is not None:
        if sp.five_day_pct >= 1.0:
            score += 2; evidence.append(f"S&P 500 en hausse sur cinq séances ({sp.five_day_pct:+.2f} %)")
        elif sp.five_day_pct <= -1.0:
            score -= 2; evidence.append(f"S&P 500 en baisse sur cinq séances ({sp.five_day_pct:+.2f} %)")
    if ndx and ndx.five_day_pct is not None:
        if ndx.five_day_pct >= 1.0:
            score += 1; evidence.append(f"Nasdaq en hausse sur cinq séances ({ndx.five_day_pct:+.2f} %)")
        elif ndx.five_day_pct <= -1.0:
            score -= 1; evidence.append(f"Nasdaq en baisse sur cinq séances ({ndx.five_day_pct:+.2f} %)")
    if dow and dow.five_day_pct is not None:
        if dow.five_day_pct >= 1.0: score += 1
        elif dow.five_day_pct <= -1.0: score -= 1
    if vix and vix.daily_pct is not None:
        if vix.daily_pct >= 8:
            score -= 2; evidence.append(f"VIX en hausse marquée sur la dernière séance ({vix.daily_pct:+.2f} %)")
        elif vix.daily_pct <= -8:
            score += 1; evidence.append(f"VIX en net recul sur la dernière séance ({vix.daily_pct:+.2f} %)")
    if score >= 3:
        probs = {"haussier": 75, "central": 15, "baissier": 10}
        stance = "Biais haussier net"
    elif score == 2:
        probs = {"haussier": 65, "central": 20, "baissier": 15}
        stance = "Biais haussier"
    elif score == 1:
        probs = {"haussier": 60, "central": 25, "baissier": 15}
        stance = "Avantage haussier modéré"
    elif score <= -3:
        probs = {"haussier": 10, "central": 15, "baissier": 75}
        stance = "Biais baissier net"
    elif score == -2:
        probs = {"haussier": 15, "central": 20, "baissier": 65}
        stance = "Biais baissier"
    elif score == -1:
        probs = {"haussier": 15, "central": 25, "baissier": 60}
        stance = "Avantage baissier modéré"
    else:
        probs = {"haussier": 20, "central": 60, "baissier": 20}
        stance = "Signaux contradictoires : scénario central dominant"
    return {"score": score, "probabilities": probs, "stance": stance, "evidence": evidence,
            "method": "heuristique de momentum sur 5 séances et variation quotidienne du VIX; non calibrée, à évaluer contre les résultats futurs"}




def evaluate_scenario_forecasts(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    """Score saved morning scenario probabilities against the next distinct S&P 500 observation."""
    series: dict[str, dict[str, float]] = {}
    for snap in snapshots:
        for asset in snap.get("assets", []):
            ticker, day, price = asset.get("ticker"), asset.get("data_timestamp"), asset.get("price")
            if ticker == "^GSPC" and day and price is not None:
                try:
                    series.setdefault(str(day), {})["price"] = float(price)
                except (TypeError, ValueError):
                    continue
    dates = sorted(series)
    matured: list[dict[str, Any]] = []
    pending = 0
    for snap in snapshots:
        forecast = snap.get("scenario_forecast")
        if snap.get("report_type") != "morning" or not forecast:
            continue
        base_asset = next((a for a in snap.get("assets", []) if a.get("ticker") == "^GSPC"), None)
        if not base_asset or not base_asset.get("data_timestamp") or base_asset.get("price") is None:
            pending += 1
            continue
        base_date = str(base_asset["data_timestamp"])
        future_dates = [d for d in dates if d > base_date]
        if not future_dates:
            pending += 1
            continue
        target_date = future_dates[0]
        # Wait until the market-date is behind Madagascar's current date; the same-day daily bar may still be incomplete.
        if target_date >= datetime.now(TZ).date().isoformat():
            pending += 1
            continue
        base_price = float(base_asset["price"])
        target_price = series[target_date]["price"]
        if base_price <= 0:
            continue
        realized_pct = (target_price / base_price - 1) * 100
        actual = "haussier" if realized_pct > 0.1 else ("baissier" if realized_pct < -0.1 else "central")
        probs = forecast.get("probabilities", {})
        predicted = max(("haussier", "central", "baissier"), key=lambda k: float(probs.get(k, 0)))
        one_hot = {"haussier": 0.0, "central": 0.0, "baissier": 0.0}
        one_hot[actual] = 1.0
        brier = sum((float(probs.get(k, 0)) / 100 - one_hot[k]) ** 2 for k in one_hot)
        matured.append({
            "base_date": base_date, "target_date": target_date,
            "predicted": predicted, "actual": actual,
            "realized_pct": round(realized_pct, 4),
            "probabilities": probs, "correct": predicted == actual,
            "brier_score": round(brier, 4),
        })
    return {
        "matured": matured,
        "pending": pending,
        "accuracy_pct": round(100 * sum(x["correct"] for x in matured) / len(matured), 1) if matured else None,
        "mean_brier_score": round(sum(x["brier_score"] for x in matured) / len(matured), 4) if matured else None,
    }


def append_funnel_report(
    lines: list[str], report_type: str, rows: list[AssetRow],
    news: list[dict[str, str]], previous: list[dict[str, Any]],
    prior_morning: dict[str, Any] | None, prior_update: dict[str, Any] | None,
    data_errors: list[str], news_errors: list[str],
    company_fundamentals: list[dict[str, Any]],
) -> None:
    """Build the report from global regime to specific instruments and an auditable action plan."""
    conviction = market_conviction(rows)
    probs = conviction["probabilities"]
    by = {r.ticker: r for r in rows}
    lines += [
        "NIVEAU 1 — LE MONDE : RÉGIME MACROÉCONOMIQUE ET FINANCIER",
        f"Diagnostic de marché : {conviction['stance']}. Horizon indicatif : prochaines 1 à 5 séances; ce n'est pas une prévision long terme.",
        f"Probabilités directionnelles expérimentales : hausse {probs['haussier']} % · scénario central / marché sans direction nette {probs['central']} % · baisse {probs['baissier']} %.",
        "Ces probabilités sont issues d'une règle explicite de momentum et de volatilité, pas d'un modèle statistiquement calibré ni d'une probabilité implicite de marché. Elles seront confrontées aux résultats dans les rapports du soir; si les données croisées sont insuffisantes, la conviction doit être considérée comme fragile.",
        "Les variables réellement observées dans cette exécution sont les prix et variations disponibles. Croissance, inflation, liquidité et géopolitique ne seront qualifiées de moteurs confirmés que lorsqu'une publication ou une source vérifiable les étaye.",
    ]
    lines += [f"- Élément quantitatif : {x}." for x in conviction["evidence"]]
    if not conviction["evidence"]:
        lines.append("- Aucune convergence robuste des indicateurs de marché retenus; la probabilité centrale domine faute de signal directionnel convergent.")
    macro_news = [n for n in news if any(k in n["title"].casefold() for k in (
        "inflation", "cpi", "pce", "gdp", "growth", "recession", "central bank", "federal reserve",
        "fed ", "ecb", "interest rate", "employment", "payroll", "tariff", "sanction", "geopolit",
        "oil", "crude", "treasury", "bond yield", "pmi", "retail sales"))]
    lines += ["", "NIVEAU 2 — RÉGIONS ET ÉCONOMIES MAJEURES",
              "Lecture régionale : les signaux ci-dessous sont limités aux publications et instruments effectivement récupérés. L'absence de titre ne signifie pas l'absence de risque."]
    region_rules = [
        ("États-Unis et Canada", ("us ", "u.s.", "united states", "federal reserve", "fed ", "treasury", "canada", "american", "nvidia", "apple", "microsoft", "amazon", "jpmorgan")),
        ("Zone euro et Royaume-Uni", ("europe", "eurozone", "euro zone", "ecb", "european central bank", "britain", "british", "uk ", "united kingdom", "germany", "france")),
        ("Chine et Asie-Pacifique", ("china", "chinese", "japan", "japanese", "asia", "asia-pacific", "hong kong", "beijing", "tokyo", "hang seng")),
        ("Marchés émergents et autres régions", ("emerging market", "india", "brazil", "south africa", "indonesia", "mexico")),
    ]
    for label, keywords in region_rules:
        matches = [n for n in news if any(k in n["title"].casefold() for k in keywords)]
        lines.append(f"- {label} :")
        if matches:
            for item in matches[:3]:
                lines.append(f"  - {item['title']} — {item['source']} ({item['published']}) — {item['url']}")
        else:
            lines.append("  - Pas de publication régionale suffisamment identifiable dans les titres collectés; ne pas en déduire une absence de risque.")
    lines += ["", "NIVEAU 3 — GRANDES FORCES ET INTERACTIONS ENTRE LES MARCHÉS"]
    lines += [f"- {item}" for item in scenario_context(rows)]
    comparisons = [
        ("Actions US vs taux longs US", "^GSPC", "^TNX"),
        ("Technologie vs marché large", "^IXIC", "^GSPC"),
        ("Or vs dollar", "GC=F", "DX-Y.NYB"),
        ("Pétrole vs dollar", "CL=F", "DX-Y.NYB"),
        ("Bitcoin vs technologie", "BTC-USD", "^IXIC"),
    ]
    for label, left, right in comparisons:
        a, b = by.get(left), by.get(right)
        if a and b and a.daily_pct is not None and b.daily_pct is not None:
            relationship = "même sens" if a.daily_pct * b.daily_pct > 0 else ("sens opposés" if a.daily_pct * b.daily_pct < 0 else "mouvement mixte")
            lines.append(f"- {label} : {a.name} {a.daily_pct:+.2f} %; {b.name} {b.daily_pct:+.2f} %; mouvements de {relationship}. Une seule séance ne suffit pas à prouver une relation causale.")
        else:
            lines.append(f"- {label} : comparaison indisponible faute de données synchronisées suffisantes.")
    lines += ["", "NIVEAU 4 — CLASSES D'ACTIFS : OÙ SE CONCENTRE LE RISQUE ?",
              "La classification ci-dessous repose sur les actifs reçus. Les fonds communs sont inclus lorsque leur cotation de valeur liquidative est disponible; une donnée absente est signalée, jamais inventée."]
    classes: dict[str, list[AssetRow]] = {}
    for row in rows:
        classes.setdefault(row.asset_class, []).append(row)
    for cls, members in sorted(classes.items()):
        daily = [x for x in members if x.daily_pct is not None]
        weekly = [x for x in members if x.five_day_pct is not None]
        best = max(daily, key=lambda x: x.daily_pct) if daily else None
        worst = min(daily, key=lambda x: x.daily_pct) if daily else None
        avg = sum(x.daily_pct for x in daily) / len(daily) if daily else None
        lines.append(f"- {cls} : {len(members)} instrument(s) reçu(s); variation quotidienne moyenne non pondérée {fmt(avg, '%')}.")
        if best and worst:
            lines.append(f"  - Leader : {best.name} ({fmt(best.daily_pct, '%')}); lanterne rouge : {worst.name} ({fmt(worst.daily_pct, '%')}).")
        if weekly:
            positive = sum(1 for x in weekly if (x.five_day_pct or 0) > 0)
            lines.append(f"  - Sur cinq séances : {positive}/{len(weekly)} instrument(s) en hausse; cet indicateur de largeur n'est pas pondéré par capitalisation.")
    lines += ["", "NIVEAU 5 — SECTEURS, SEGMENTS, THÉMATIQUES ET MICROÉCONOMIE",
              "Ce niveau relie les résultats et décisions d'entreprise à leurs secteurs. Les titres de presse sont des pistes : chiffres publiés, consensus, guidance et réaction boursière doivent être vérifiés dans les documents originaux avant toute conclusion ferme."]
    corporate_keywords = (
        "earnings", "quarterly results", "profit warning", "revenue", "guidance", "eps", "beat estimates",
        "miss estimates", "operating margin", "cash flow", "capital expenditure", "capex", "investor day",
        "merger", "acquisition", "dividend cut", "layoffs", "sales", "forecast", "outlook", "orders",
        "semiconductor", "bank earnings", "company results")
    corporate_news = [n for n in news if any(k in n["title"].casefold() for k in corporate_keywords)]
    if corporate_news:
        for item in corporate_news[:18]:
            theme, categories, impact = infer_macro_impact(item["title"])
            lines.append(f"- Publication/événement d'entreprise ou sectoriel : {item['title']} — {item['source']} ({item['published']}) — Source : {item['url']}")
            lines.append(f"  - Lecture à vérifier : {impact}")
            lines.append(f"  - Transmission potentielle : {categories}.")
    else:
        lines.append("- Aucun titre clairement identifié comme publication d'entreprise dans les flux reçus. Cela ne signifie pas qu'aucune entreprise ne publie aujourd'hui : le calendrier des résultats n'est pas encore alimenté par une source spécialisée structurée.")
    sector_groups = [
        ("Technologie et semi-conducteurs", ("technology", "semiconductor", "chip", "nvidia", "apple", "microsoft", "artificial intelligence", "ai ")),
        ("Banques et crédit", ("bank", "jpmorgan", "credit", "loan", "deposit", "net interest margin")),
        ("Énergie et matières premières", ("oil", "energy", "gas", "opec", "exxon", "gold", "copper")),
        ("Consommation et distribution", ("consumer", "retail", "walmart", "costco", "amazon", "sales")),
        ("Santé et pharmacie", ("healthcare", "pharma", "drug", "lilly", "clinical")),
        ("Industrie et infrastructures", ("industrial", "manufacturing", "orders", "caterpillar", "capex")),
    ]
    for sector, keywords in sector_groups:
        matches = [n for n in corporate_news if any(k in n["title"].casefold() for k in keywords)]
        if matches:
            lines.append(f"- {sector} :")
            for item in matches[:2]:
                lines.append(f"  - {item['title']} — {item['url']}")
    lines += ["", "FONDAMENTAUX PUBLIÉS — ÉCHANTILLON SEC EDGAR",
              "Chiffres issus des données XBRL officielles de la SEC pour les derniers trimestres 10-Q disponibles. La comparaison annuelle n'est affichée que si un trimestre comparable existe; il ne s'agit pas d'une comparaison au consensus analystes. Les définitions comptables peuvent varier selon l'émetteur.",
              "Montants en milliards USD; BPA dilué en USD/action. La marge opérationnelle est calculée à partir du résultat opérationnel et du chiffre d'affaires trimestriels. Le flux de trésorerie disponible (FCF) est approximé par flux opérationnel moins investissements corporels; il peut être indisponible si un poste manque."]
    if company_fundamentals:
        for item in company_fundamentals:
            revenue = "n.d." if item["revenue"] is None else f"{item['revenue'] / 1_000_000_000:.2f} Md$"
            revenue_yoy = "comparaison annuelle indisponible" if item["revenue_yoy_pct"] is None else f"{item['revenue_yoy_pct']:+.1f} % sur un an"
            eps = "n.d." if item["eps"] is None else f"{item['eps']:.2f} $"
            eps_yoy = "comparaison annuelle indisponible" if item["eps_yoy_pct"] is None else f"{item['eps_yoy_pct']:+.1f} % sur un an"
            operating_income = "n.d." if item.get("operating_income") is None else f"{item['operating_income'] / 1_000_000_000:.2f} Md$"
            operating_margin = "n.d." if item.get("operating_margin_pct") is None else f"{item['operating_margin_pct']:.1f} %"
            operating_cash_flow = "n.d." if item.get("operating_cash_flow") is None else f"{item['operating_cash_flow'] / 1_000_000_000:.2f} Md$"
            capex = "n.d." if item.get("capex") is None else f"{item['capex'] / 1_000_000_000:.2f} Md$"
            free_cash_flow = "n.d." if item.get("free_cash_flow") is None else f"{item['free_cash_flow'] / 1_000_000_000:.2f} Md$"
            name = item["name"]
            ticker = item["ticker"]
            period = item["period"]
            source = item["source"]
            period_age_note = ""
            try:
                period_age_days = (datetime.now(timezone.utc).date() - datetime.fromisoformat(period).date()).days
                if period_age_days > 120:
                    period_age_note = f"; ATTENTION : période publiée il y a {period_age_days} jours (>120 jours)"
            except (TypeError, ValueError):
                period_age_note = "; ancienneté de la période indisponible"
            period_kind = "quatrième trimestre calculé à partir du total annuel moins Q1-Q3" if any(item.get(key) for key in ("revenue_derived", "operating_income_derived", "operating_cash_flow_derived", "capex_derived")) else "trimestre déclaré dans un 10-Q"
            eps_period = item.get("eps_period") or "n.d."
            lines.append(f"- {name} ({ticker}), {period_kind}, période close le {period}{period_age_note} : chiffre d'affaires {revenue} ({revenue_yoy}); BPA dilué {eps} ({eps_yoy}, période {eps_period}); résultat opérationnel {operating_income}; marge opérationnelle {operating_margin}; flux opérationnel {operating_cash_flow}; investissements corporels {capex}; FCF approximatif {free_cash_flow}. Source SEC : {source}")
    else:
        lines.append("- Aucun chiffre trimestriel SEC exploitable lors de cette collecte; aucune valeur n'est estimée ni remplacée par un chiffre de presse.")
    lines += ["", "NIVEAU 6 — INSTRUMENTS PRÉCIS ET LISTE DE SURVEILLANCE",
              "Les instruments sont sélectionnés par importance du mouvement et disponibilité des données, non comme recommandation automatique d'achat ou de vente."]
    if report_type == "update":
        old = {r["ticker"]: r for r in (prior_morning or {}).get("assets", [])}
        changes = []
        for row in rows:
            prev = old.get(row.ticker)
            if prev and row.daily_pct is not None and prev.get("daily_pct") is not None:
                diff = row.daily_pct - float(prev["daily_pct"])
                if abs(diff) >= 0.5:
                    changes.append((abs(diff), f"- {row.name} ({row.ticker}) : variation journalière disponible {float(prev['daily_pct']):+.2f} % au rapport du matin contre {row.daily_pct:+.2f} % maintenant; différence {diff:+.2f} points. Vérifier que les deux observations couvrent des séances comparables."))
        lines.append("Évolutions depuis le matin :")
        lines += [x[1] for x in sorted(changes, reverse=True)[:12]] if changes else ["- Aucun changement comparable supérieur à 0,5 point détecté ou rapport du matin indisponible."]
    movers = sorted([r for r in rows if r.daily_pct is not None],
                    key=lambda r: max(abs(r.daily_pct or 0), abs(r.five_day_pct or 0), abs(r.one_month_pct or 0)), reverse=True)
    lines.append("Instruments dont le mouvement mérite un examen prioritaire :")
    for r in movers[:20]:
        lines.append(f"- {r.name} ({r.ticker}) — classe : {r.asset_class}; dernier prix {fmt(r.price)}; dernière séance {fmt(r.daily_pct, '%')}; 5 séances {fmt(r.five_day_pct, '%')}; 1 mois {fmt(r.one_month_pct, '%')}. Source cours : https://finance.yahoo.com/quote/{r.ticker}/")
        if r.daily_pct is not None and r.five_day_pct is not None:
            if r.daily_pct * r.five_day_pct > 0:
                lines.append("  - Lecture multi-horizon : la variation de la dernière séance et celle des cinq séances sont dans le même sens; le mouvement récent confirme provisoirement le biais observé sur la semaine, sans garantir sa poursuite.")
            elif r.daily_pct * r.five_day_pct < 0:
                lines.append("  - Lecture multi-horizon : la dernière séance diverge du mouvement sur cinq séances; rechercher une prise de bénéfices, une nouvelle information ou un retournement avant de conclure.")
            else:
                lines.append("  - Lecture multi-horizon : les horizons ne donnent pas de signal directionnel concordant; la conviction doit rester conditionnelle.")
        if r.asset_class in ("US equity",):
            lines.append("  - Grille fondamentale : confronter le mouvement aux revenus, bénéfices, marges, flux de trésorerie, valorisation, prévisions des dirigeants et attentes déjà intégrées dans le cours. Sans chiffres de consensus vérifiés, aucune surprise bénéficiaire n'est présumée.")
        elif "index" in r.asset_class.lower():
            lines.append("  - Grille d'indice : vérifier la largeur du marché, la concentration des contributions, la dispersion sectorielle et la cohérence avec les rendements obligataires et la volatilité; un indice pondéré peut masquer une participation étroite.")
        elif "future" in r.asset_class.lower():
            lines.append("  - Grille futures : comparer le contrat au comptant, l'échéance, le roulement et l'heure de cotation. Les futures peuvent intégrer des nouvelles hors séance, mais une variation quotidienne ne constitue pas à elle seule une anticipation fiable de l'ouverture.")
        elif "bond" in r.asset_class.lower() or r.asset_class == "Rates":
            lines.append("  - Grille obligataire : distinguer rendement et prix. Les rendements et les prix des obligations à taux fixe évoluent généralement en sens inverse; surveiller inflation, trajectoire des banques centrales, duration, qualité de crédit et calendrier d'émissions.")
        elif r.asset_class in ("FX",):
            lines.append("  - Grille devises : rechercher le différentiel de taux et de croissance entre les deux zones, les surprises de données et le régime de risque. Un mouvement du dollar affecte différemment les importateurs, exportateurs et matières premières.")
        elif r.asset_class in ("Commodity",):
            lines.append("  - Grille matières premières : séparer l'offre, la demande, les stocks, la saisonnalité, la structure des échéances et la prime géopolitique. Le mouvement du contrat ne révèle pas seul lequel de ces facteurs domine.")
        elif r.asset_class == "Crypto":
            lines.append("  - Grille crypto : considérer la négociation continue, la liquidité, les flux, les risques de plateforme et de réglementation; les corrélations avec les actions peuvent se renforcer ou se rompre rapidement.")
        elif "fund" in r.asset_class.lower() or r.asset_class in ("ETF", "Bond ETF", "Credit ETF"):
            lines.append("  - Grille ETF/fonds : analyser l'exposition réelle, les principales positions, la concentration, les frais et la date de valeur liquidative. Les fonds communs publient souvent leur valeur avec retard; les variations ne sont pas nécessairement intrajournalières.")
        matching = [n for n in news if r.ticker.casefold() in n["title"].casefold() or r.name.casefold() in n["title"].casefold()]
        if matching:
            for item in matching[:2]:
                lines.append(f"  - Actualité associée à vérifier : {item['title']} — {item['url']}")
        lines.append("  - Confirmation/invalidation : vérifier la prochaine observation de clôture et rechercher une confirmation fondamentale ou inter-marchés. Invalider le scénario si le catalyseur supposé disparaît ou si les marchés de confirmation évoluent durablement à l'opposé.")
    if not movers:
        lines.append("- Aucun instrument n'a fourni de variation exploitable.")
    lines += ["", "PANORAMA COMPLET DES INSTRUMENTS COLLECTÉS",
              "Les cours sont ceux de la dernière observation quotidienne disponible; ils ne sont pas nécessairement des cours intrajournaliers. Pour les fonds communs, la valeur liquidative peut être publiée avec retard.",
              "Actif | Classe | Dernier prix | Dernière séance disponible | 5 séances | 1 mois | Source"]
    for r in sorted(rows, key=lambda x: (x.asset_class, x.name)):
        lines.append(f"{r.name} ({r.ticker}) | {r.asset_class} | {fmt(r.price)} | {fmt(r.daily_pct, '%')} | {fmt(r.five_day_pct, '%')} | {fmt(r.one_month_pct, '%')} | https://finance.yahoo.com/quote/{r.ticker}/")
    lines += ["", "NIVEAU 7 — DÉCISION, INVALIDATION ET AUDIT",
              "Plan de surveillance :",
              f"- Scénario dominant expérimental : {conviction['stance']} (hausse {probs['haussier']} %, central {probs['central']} %, baisse {probs['baissier']} %).",
              "- Confirmation : vérifier la prochaine clôture des grands indices, la réaction du VIX et la cohérence avec les rendements obligataires; ne pas agir sur un seul titre de presse.",
              "- Invalidation : si les indices et la volatilité évoluent à l'opposé des signaux ayant produit le score, réduire la conviction et recalculer les probabilités au prochain rapport.",
              "- Publications d'entreprises : vérifier le communiqué officiel, les chiffres par rapport au consensus, les prévisions de direction et la réaction du titre après publication.",
              "- Aucun niveau d'entrée, stop ou objectif de cours n'est inventé; ces niveaux exigent des données de prix et de risque adaptées à l'instrument et à l'horizon."]
    if report_type == "audit":
        lines += ["", "AUDIT DU SOIR — OBJECTIF : AMÉLIORER LE RAPPORT DU MATIN",
                  f"- Instantanés précédents enregistrés : {len(previous)}.",
                  "- La prévision heuristique d'aujourd'hui est conservée dans l'historique pour comparaison future; elle n'est pas encore calibrée sur un échantillon suffisant.",
                  "- Questions de contrôle : le scénario était-il correct, les catalyseurs identifiés étaient-ils les bons, les probabilités étaient-elles trop extrêmes ou trop prudentes, et quelles données ont manqué ?"]
    elif report_type == "morning":
        lines += ["", "ENGAGEMENT POUR L'AUDIT DU SOIR",
                  "- Les probabilités et les observations de cette édition doivent rester inchangées dans l'historique; le rapport du soir comparera ces hypothèses aux mouvements effectivement observés."]
    append_self_audit(lines, {"forecasts": previous, "forecast_records": read_state().get("forecast_records", [])})
    scenario_audit = evaluate_scenario_forecasts(previous)
    lines += ["", "AUDIT DES PROBABILITÉS DIRECTIONNELLES"]
    if scenario_audit["matured"]:
        lines.append(f"- Prévisions matinales évaluées sur la prochaine observation quotidienne distincte du S&P 500 : {len(scenario_audit['matured'])}; direction dominante correcte dans {scenario_audit['accuracy_pct']} % des cas.")
        lines.append(f"- Score de Brier multiclasses moyen : {scenario_audit['mean_brier_score']} (plus bas est préférable; 0 est parfait). Échantillon encore exploratoire; ne pas interpréter comme preuve de rentabilité.")
        for result in scenario_audit["matured"][-3:]:
            lines.append(f"- {result['base_date']} → {result['target_date']} : prévu {result['predicted']} ({result['probabilities']}); réalisé {result['actual']} ({result['realized_pct']:+.2f} %); Brier {result['brier_score']}.")
    else:
        lines.append("- Aucune prévision matinale arrivée à échéance avec une observation quotidienne distincte. Le score de calibration n'est pas encore disponible.")
    lines.append(f"- Prévisions matinales en attente : {scenario_audit['pending']}. Les résultats sont mesurés sur la prochaine date de données distincte disponible, pas sur une heure intrajournalière garantie.")


def make_report(report_type: str) -> tuple[str, str, dict[str, Any]]:
    started = datetime.now(timezone.utc)
    now_local = started.astimezone(TZ)
    data, data_errors = fetch_prices()
    rows = [analyse_asset(ticker, frame) for ticker, frame in data.items()]
    news, news_errors = fetch_news()
    company_fundamentals, fundamentals_errors = fetch_company_fundamentals()
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
        "Le rapport est orienté vers les événements, les mouvements de marché, les scénarios et les actifs à surveiller. Les indicateurs techniques sont conservés et utilisés en interne pour l'analyse, mais ne sont pas affichés. L'analyse fondamentale est alimentée par des titres multi-sources, mais le consensus chiffré et les rapports originaux ne sont pas disponibles pour chaque société. Les probabilités directionnelles sont expérimentales, explicites et non calibrées; elles seront auditées au rapport du soir.",
        "Les données de marché peuvent être retardées, révisées ou indisponibles. Les variations portent sur la dernière séance reçue, pas nécessairement sur la séance en cours.",
        "",
    ]

    append_funnel_report(lines, report_type, rows, news, previous, prior_morning, prior_update, data_errors, news_errors, company_fundamentals)
    lines += ["", "QUALITÉ ET SOURCES", "- Prix historiques : Yahoo Finance via yfinance (source non institutionnelle, disponibilité non garantie).", "- Titres : flux RSS Google News, liens vers les publications d'origine lorsqu'ils sont fournis.", f"- Heure de collecte : {started.isoformat(timespec='seconds')}.", f"- Erreurs prix : {len(data_errors)}; erreurs flux actualités : {len(news_errors)}; erreurs données fondamentales SEC : {len(fundamentals_errors)}."]
    if data_errors:
        lines += ["", "DONNÉES MANQUANTES"] + [f"- {e}" for e in data_errors[:20]]
    if news_errors:
        lines += ["", "ERREURS DE FLUX"] + [f"- {e}" for e in news_errors]
    if fundamentals_errors:
        lines += ["", "ERREURS DONNÉES FONDAMENTALES SEC"] + [f"- {e}" for e in fundamentals_errors[:15]]
    lines += ["", "Avertissement : contenu informatif et expérimental, pas un conseil d'investissement. Vérifier les données et les actualités avant toute décision."]
    plain = "\n".join(lines)

    html_body = render_professional_html(plain, title, now_local, started)
    snapshot = {
        "report_type": report_type,
        "run_time_utc": started.isoformat(timespec="seconds"),
        "run_time_madagascar": now_local.isoformat(timespec="seconds"),
        "assets": [asdict(r) for r in rows],
        "scenario_forecast": market_conviction(rows),
        "news": news[:36],
        "data_error_count": len(data_errors),
        "news_error_count": len(news_errors),
    }
    return plain, html_body, snapshot

def send_email(subject: str, report_url: str) -> None:
    required = ("SMTP_USERNAME", "SMTP_APP_PASSWORD", "REPORT_RECIPIENT")
    missing = [key for key in required if not os.environ.get(key)]
    if missing:
        raise RuntimeError("Secrets manquants : " + ", ".join(missing))
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = os.environ["SMTP_USERNAME"].strip()
    message["To"] = os.environ["REPORT_RECIPIENT"].strip()
    message.set_content(f"Le rapport de marché est disponible ici :\n{report_url}\n")
    message.add_alternative(
        "<html><body style=\"font-family:Arial,sans-serif\">"
        f"<p>Le rapport de marché est disponible ici : <a href=\"{html.escape(report_url, quote=True)}\">Ouvrir le rapport</a></p>"
        "</body></html>",
        subtype="html",
    )
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
    parser.add_argument("--send-link-only", action="store_true", help="Send the public report link without regenerating the report")
    args = parser.parse_args()
    if args.send_link_only:
        state = read_state()
        snapshot = next((x for x in reversed(state.get("forecasts", [])) if x.get("report_type") == args.report_type), None)
        if not snapshot:
            raise RuntimeError(f"Aucun rapport enregistré pour le type {args.report_type}")
        subject = f"[Market Intelligence] {args.report_type.upper()} — {snapshot['run_time_madagascar'][:16]}"
        send_email(subject, REPORT_URL)
        print(f"Report link emailed: type={args.report_type}; url={REPORT_URL}")
        return 0
    plain, html_body, snapshot = make_report(args.report_type)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    # Save the exact report text to aid later audit.
    report_path = STATE_DIR / f"latest_{args.report_type}.txt"
    report_path.write_text(plain, encoding="utf-8")
    public_dir = ROOT / "docs"
    public_dir.mkdir(parents=True, exist_ok=True)
    (public_dir / "index.html").write_text(html_body, encoding="utf-8")
    # Append the immutable forecast/data snapshot before email delivery.
    # Workflow commits state only after successful completion.
    rows = [AssetRow(**item) for item in snapshot["assets"]]
    write_state(snapshot, rows)
    subject = f"[Market Intelligence] {args.report_type.upper()} — {snapshot['run_time_madagascar'][:16]}"
    if not args.no_email:
        send_email(subject, REPORT_URL)
    print(f"Report generated: {report_path.name}; assets={len(rows)}; type={args.report_type}; email={'disabled' if args.no_email else 'sent'}")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise
