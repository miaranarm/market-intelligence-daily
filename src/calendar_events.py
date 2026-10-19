"""Calendrier des événements de la semaine : fichier tenu à la main + dates FRED optionnelles.

Principe : ne jamais inventer une date. Chaque événement porte un statut « confirmé » ou
« à confirmer » et sa source ; le rapport affiche ce statut tel quel.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

TZ = ZoneInfo("Indian/Antananarivo")
ROOT = Path(__file__).resolve().parents[1]
MANUAL_CALENDAR = ROOT / "data" / "calendar_manual.json"
IMPORTANCE_ORDER = {"élevée": 0, "moyenne": 1, "faible": 2}
WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
             "septembre", "octobre", "novembre", "décembre"]

# Publications FRED jugées importantes pour les marchés (nom exact de la « release » FRED).
FRED_RELEASES_OF_INTEREST = {
    "Employment Situation": ("Emploi américain : rapport mensuel (payrolls, chômage)", "élevée", ["devises", "obligations", "indices", "futures"]),
    "Consumer Price Index": ("États-Unis : indice des prix à la consommation (CPI)", "élevée", ["devises", "obligations", "indices", "matieres"]),
    "Producer Price Index": ("États-Unis : indice des prix à la production (PPI)", "moyenne", ["obligations", "devises"]),
    "Gross Domestic Product": ("États-Unis : produit intérieur brut (PIB)", "élevée", ["devises", "obligations", "indices"]),
    "Personal Income and Outlays": ("États-Unis : revenus et dépenses des ménages (inflation PCE)", "élevée", ["obligations", "devises", "indices"]),
    "Advance Monthly Sales for Retail and Food Services": ("États-Unis : ventes au détail", "moyenne", ["indices", "devises", "actions"]),
    "Job Openings and Labor Turnover Survey": ("États-Unis : offres d'emploi (JOLTS)", "moyenne", ["obligations", "devises"]),
    "Industrial Production and Capacity Utilization": ("États-Unis : production industrielle", "moyenne", ["indices", "matieres"]),
}


def load_manual_events(path: Path = MANUAL_CALENDAR) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    events = payload.get("events", []) if isinstance(payload, dict) else []
    return [e for e in events if isinstance(e, dict) and e.get("date") and e.get("title")]


def fetch_fred_release_events(start: date, end: date, api_key: str | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Dates de publication FRED (nécessite une clé gratuite FRED_API_KEY). Échec non bloquant."""
    api_key = api_key or os.environ.get("FRED_API_KEY", "").strip()
    if not api_key:
        return [], []
    try:
        response = requests.get(
            "https://api.stlouisfed.org/fred/releases/dates",
            params={
                "api_key": api_key, "file_type": "json",
                "realtime_start": start.isoformat(), "realtime_end": end.isoformat(),
                "include_release_dates_with_no_data": "true", "limit": 1000,
                "order_by": "release_date", "sort_order": "asc",
            },
            timeout=20,
        )
        response.raise_for_status()
        rows = response.json().get("release_dates", [])
    except Exception as exc:  # noqa: BLE001 - échec réseau ou clé invalide : on continue sans
        return [], [f"FRED calendrier: {type(exc).__name__}: {str(exc)[:120]}"]
    events: list[dict[str, Any]] = []
    for row in rows:
        name = str(row.get("release_name", ""))
        meta = FRED_RELEASES_OF_INTEREST.get(name)
        day = str(row.get("date", ""))
        if not meta or not day:
            continue
        title, importance, categories = meta
        events.append({
            "date": day, "time_utc": None, "title": title, "region": "États-Unis",
            "importance": importance, "categories": categories, "currencies": ["USD"],
            "status": "confirmé", "source": "https://fred.stlouisfed.org/releases/calendar",
            "note": "Date issue du calendrier officiel des publications relayé par FRED; l'heure n'est pas fournie.",
        })
    return events, []


def _localize(event: dict[str, Any]) -> dict[str, Any]:
    """Ajoute la date et l'heure locales (Madagascar) ainsi que le statut normalisé."""
    out = dict(event)
    out["status"] = event.get("status") if event.get("status") in ("confirmé", "à confirmer") else "à confirmer"
    out["importance"] = event.get("importance") if event.get("importance") in IMPORTANCE_ORDER else "moyenne"
    try:
        day = date.fromisoformat(str(event["date"]))
    except ValueError:
        return {}
    local_day, local_time = day, None
    time_utc = event.get("time_utc")
    if time_utc:
        try:
            hh, mm = [int(x) for x in str(time_utc).split(":")[:2]]
            moment = datetime(day.year, day.month, day.day, hh, mm, tzinfo=timezone.utc).astimezone(TZ)
            local_day, local_time = moment.date(), f"{moment:%H:%M}"
        except ValueError:
            pass
    out["local_date"] = local_day
    out["local_time"] = local_time
    return out


def upcoming_events(events: list[dict[str, Any]], today: date | datetime, days: int = 7) -> list[dict[str, Any]]:
    """Événements futurs dans la fenêtre locale; si l'heure actuelle est connue, exclut ceux déjà passés aujourd'hui."""
    now_local: datetime | None = None
    if isinstance(today, datetime):
        now_local = today.astimezone(TZ) if today.tzinfo else today.replace(tzinfo=TZ)
        start_day = now_local.date()
    else:
        start_day = today
    horizon = start_day + timedelta(days=days)
    seen: set[tuple[str, str]] = set()
    selected: list[dict[str, Any]] = []
    for raw in events:
        event = _localize(raw)
        if not event or not (start_day <= event["local_date"] <= horizon):
            continue
        # Date-only callers retain the old behavior. Datetime callers can prevent a
        # release that already happened earlier today from being advertised as upcoming.
        if (now_local is not None and event["local_date"] == start_day and event.get("local_time")
                and event["local_time"] <= now_local.strftime("%H:%M")):
            continue
        key = (str(event["local_date"]), str(event["title"]).casefold()[:40])
        if key in seen:
            continue
        seen.add(key)
        selected.append(event)
    selected.sort(key=lambda e: (e["local_date"], e["local_time"] or "99:99", IMPORTANCE_ORDER.get(e["importance"], 1)))
    return selected


def collect_calendar(today: date | datetime, days: int = 7) -> tuple[list[dict[str, Any]], list[str]]:
    manual = load_manual_events()
    start_day = today.date() if isinstance(today, datetime) else today
    fred, errors = fetch_fred_release_events(start_day, start_day + timedelta(days=days))
    return upcoming_events(manual + fred, today, days), errors


def format_day(day: date) -> str:
    return f"{WEEKDAYS_FR[day.weekday()]} {day.day} {MONTHS_FR[day.month - 1]}"
