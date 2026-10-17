"""Génère un rapport d'aperçu HORS LIGNE à partir du dernier instantané enregistré dans data/forecasts.json.

Utile pour juger la mise en page sans accès réseau. Les mini-graphiques (30 jours) restent vides :
l'historique de prix n'est pas conservé dans l'instantané ; ils apparaissent lors des exécutions réelles.

Usage : python tools/preview_from_snapshot.py [morning|update|audit|weekly] [sortie.html]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src import calendar_events, editorial, market_report as mr, render_report  # noqa: E402


def macro_from_text(text: str) -> list[dict]:
    alias = {"CUUR0000SA0": "CPIAUCSL", "LNS14000000": "UNRATE", "CES0000000001": "PAYEMS"}
    out = []
    for m in re.finditer(r"^- (?P<name>.+?) \((?P<id>[A-Z0-9]+)\) : (?P<value>[\d.]+)(?P<rest>.*?); observation du (?P<date>[\d-]+); (?:variation[^;]*; )?fournisseur : (?P<prov>[^;]+); source : (?P<src>\S+?)\.$", text, re.M):
        yoy = re.search(r"([+-][\d.]+) %", m.group("rest"))
        out.append({"id": alias.get(m.group("id"), m.group("id")), "name": m.group("name"), "value": float(m.group("value")),
                    "date": m.group("date"), "unit": "", "yoy_pct": float(yoy.group(1)) if yoy else None, "change": None,
                    "provider": m.group("prov"), "source": m.group("src")})
    return out


def main() -> None:
    kind = sys.argv[1] if len(sys.argv) > 1 else "morning"
    target = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "apercu_rapport.html"
    state = json.loads((ROOT / "data" / "forecasts.json").read_text(encoding="utf-8"))
    snaps = state["forecasts"]
    last = snaps[-1]
    rows = [mr.AssetRow(**a) for a in last["assets"]]
    started = datetime.now(timezone.utc)
    now_local = started.astimezone(mr.TZ)
    cal, _ = calendar_events.collect_calendar(now_local.date(), 21 if kind == "weekly" else 14)
    legacy = (ROOT / "data" / "latest_morning.txt").read_text(encoding="utf-8")
    news = last.get("news", [])
    ctx = {
        "kind": kind, "title": editorial.KIND_LABELS[kind], "now_local": now_local, "started": started, "rows": rows, "sparks": {},
        "news": news, "priority_news": [mr.display_news(n) for n in mr.prioritize_news(news, 8)], "news_picker": mr.news_for_keywords,
        "macro": macro_from_text((ROOT / "data" / "latest_audit.txt").read_text(encoding="utf-8")), "fundamentals": [],
        "calendar": cal, "calendar_days": 21 if kind == "weekly" else 14, "scenario": mr.market_conviction(rows),
        "forecast_eval": mr.evaluate_forecasts({"forecasts": snaps[:-1], "forecast_records": state.get("forecast_records", [])}),
        "scenario_eval": mr.evaluate_scenario_forecasts(snaps[:-1]), "cross_lines": mr.scenario_context(rows),
        "prior_assets": {a["ticker"]: a for a in snaps[-2]["assets"]} if len(snaps) > 1 else {},
        "errors": {}, "n_tracked": len(mr.ASSETS), "weekend": now_local.weekday() >= 5, "legacy_text": legacy, "llm": None,
    }
    model = editorial.build_report(ctx)
    target.write_text(render_report.render_html(model), encoding="utf-8")
    print(f"{target} : {model['words']} mots, lecture estimée {model['reading_minutes']} min")
    for s in model["sections"]:
        print(f"  {s['minutes']:>2} min  {s['title']}")


if __name__ == "__main__":
    main()
