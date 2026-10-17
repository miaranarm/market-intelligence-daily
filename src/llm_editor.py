"""Couche rédactionnelle optionnelle : un modèle de langage commente les données déjà collectées.

Règles de sécurité (elles sont appliquées par le code, pas seulement demandées au modèle) :
- le modèle ne reçoit que des données publiques de marché déjà présentes dans le rapport ;
- il ne calcule ni ne choisit aucune probabilité : elles viennent du code et sont en lecture seule ;
- tout paragraphe contenant un nombre absent des données fournies est écarté ;
- tout paragraphe qui ressemble à un conseil d'achat ou de vente est écarté ;
- sans clé d'API, ou en cas d'échec, le rapport est produit sans cette couche (aucun blocage).

Activation : définir le secret ANTHROPIC_API_KEY (modèle réglable avec LLM_MODEL).
"""
from __future__ import annotations

import json
import math
import os
import re
import time
from typing import Any

import requests

try:
    from . import editorial
except ImportError:  # exécution en script
    import editorial  # type: ignore[no-redef]

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-sonnet-5-5"
NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")
ADVICE_RE = re.compile(r"\b(achetez|vendez|shortez|il faut acheter|il faut vendre|nous recommandons d.acheter|nous recommandons de vendre|prenez position)\b", re.I)
FREE_SMALL_INTEGER = 10  # les petits entiers (« trois », « 5 séances ») ne sont pas des données de marché
SECTION_KEYS = ("synthese", "regime", "agenda", "scenarios")

SYSTEM_PROMPT = """Tu es l'analyste d'un rapport de marché quotidien en français destiné à un lecteur averti (ancien banquier).
Tu reçois un JSON de faits : prix, variations, séries macroéconomiques, calendrier, actualités, diagnostic chiffré.

RÈGLES ABSOLUES
1. N'utilise que les faits du JSON. N'invente aucun chiffre, aucune date, aucun événement, aucune citation.
2. Ne calcule aucun nouveau nombre (pas de différences, de moyennes, de ratios) : cite uniquement les nombres présents tels quels, avec la même précision, écrits sans séparateur de milliers (81609 et non 81 609), avec la virgule décimale.
3. Les probabilités du champ « diagnostic » sont en lecture seule. Ne les modifie pas, n'en propose aucune autre, ne dis pas qu'elles sont fiables : elles sont expérimentales et non calibrées.
4. Sépare nettement ce que les données montrent de ton interprétation : commence toute interprétation par « Interprétation : » et formule les causes comme des hypothèses conditionnelles (« pourrait », « serait compatible avec »). Une corrélation sur une séance n'est pas une cause.
5. Aucun conseil d'achat, de vente ou de prise de position. Tu peux dire ce qui confirmerait ou invaliderait un scénario.
6. Lorsque tu t'appuies sur une actualité, nomme sa source (champ « source »). Si un événement du calendrier est « à confirmer », écris-le.
7. Si les données manquent pour une rubrique, dis-le en une phrase au lieu de combler.
8. Ton sobre, précis, sans emphase ni superlatifs, comme une note de recherche d'une banque privée.

FORMAT
Réponds par un unique objet JSON, sans texte autour, sans balises de code, de la forme :
{"synthese":["..."],"regime":["..."],"agenda":["..."],"scenarios":["..."],"categories":{"indices":["..."],"futures":["..."],"actions":["..."],"matieres":["..."],"devises":["..."],"crypto":["..."],"obligations":["..."],"etf":["..."],"fonds":["..."]}}
Chaque valeur est une liste de paragraphes de 80 à 140 mots. synthese : 3 paragraphes. regime, agenda, scenarios : 2 paragraphes chacun. Chaque catégorie : 2 paragraphes (1 seul si peu de données).
"""


def build_facts(ctx: dict[str, Any]) -> dict[str, Any]:
    rows = ctx.get("rows", [])
    categories: dict[str, list[dict[str, Any]]] = {}
    for cat in editorial.CATEGORIES:
        members = [r for r in rows if cat["match"](r)]
        categories[cat["key"]] = [{
            "instrument": r.name, "ticker": r.ticker, "dernier": r.price, "variation_seance_pct": r.daily_pct,
            "variation_5_seances_pct": r.five_day_pct, "variation_1_mois_pct": r.one_month_pct, "cours_du": r.data_timestamp,
        } for r in members]
    scenario = ctx.get("scenario") or {}
    now = ctx.get("now_local")
    return {
        "type_de_rapport": ctx.get("kind"),
        "date_locale": now.strftime("%Y-%m-%d %H:%M") if now else None,
        "marches_fermes_week_end": bool(ctx.get("weekend")),
        "diagnostic": {"intitule": scenario.get("stance"), "score": scenario.get("score"),
                       "probabilites_pct_lecture_seule": scenario.get("probabilities"), "elements": scenario.get("evidence")},
        "univers": categories,
        "macro": [{"serie": m.get("name"), "valeur": m.get("value"), "observation": m.get("date"),
                   "variation": m.get("change"), "inflation_sur_un_an_pct": m.get("yoy_pct")} for m in ctx.get("macro") or []],
        "calendrier": [{"date": str(e["local_date"]), "heure_madagascar": e.get("local_time"), "evenement": e["title"],
                        "importance": e["importance"], "statut": e["status"]} for e in ctx.get("calendar") or []],
        "actualites": [{"id": f"n{i + 1}", "titre": n.get("title"), "source": n.get("source"), "date": n.get("published"),
                        "resume": (n.get("summary") or "")[:420]} for i, n in enumerate((ctx.get("priority_news") or [])[:12])],
    }


def _facts_numbers(facts_text: str) -> list[float]:
    return [float(x.replace(",", ".")) for x in NUMBER_RE.findall(facts_text)]


def _supported(token: str, numbers: list[float]) -> bool:
    value = float(token.replace(",", "."))
    if value <= FREE_SMALL_INTEGER and "." not in token and "," not in token:
        return True
    decimals = len(token.replace(",", ".").split(".")[1]) if ("." in token or "," in token) else 0
    for f in numbers:
        if math.isclose(round(abs(f), decimals), abs(value), abs_tol=1e-9):
            return True
    return False


def validate_paragraph(text: str, numbers: list[float]) -> bool:
    if not isinstance(text, str) or len(text.split()) < 12:
        return False
    if ADVICE_RE.search(text):
        return False
    cleaned = text.replace("\u00a0", "").replace("\u202f", "")
    return all(_supported(tok, numbers) for tok in NUMBER_RE.findall(cleaned))


def validate_commentary(raw: Any, facts_text: str) -> tuple[dict[str, Any], int]:
    """Garde uniquement les paragraphes dont tous les nombres figurent dans les faits."""
    numbers = _facts_numbers(facts_text)
    dropped = 0
    clean: dict[str, Any] = {"categories": {}}
    if not isinstance(raw, dict):
        return clean, 0

    def keep(paragraphs: Any) -> list[str]:
        nonlocal dropped
        out = []
        for p in paragraphs if isinstance(paragraphs, list) else []:
            if validate_paragraph(p, numbers):
                out.append(p.strip())
            else:
                dropped += 1
        return out
    for key in SECTION_KEYS:
        kept = keep(raw.get(key))
        if kept:
            clean[key] = kept
    valid_keys = {c["key"] for c in editorial.CATEGORIES}
    for key, paragraphs in (raw.get("categories") or {}).items() if isinstance(raw.get("categories"), dict) else []:
        if key in valid_keys:
            kept = keep(paragraphs)
            if kept:
                clean["categories"][key] = kept
    return clean, dropped


def _parse_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise


def call_model(facts_text: str, api_key: str, model: str, timeout: int = 240) -> str:
    payload = {"model": model, "max_tokens": 9000, "system": SYSTEM_PROMPT,
               "messages": [{"role": "user", "content": "Faits du rapport (JSON) :\n" + facts_text}]}
    headers = {"x-api-key": api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}
    last: Exception | None = None
    for attempt in range(2):
        try:
            response = requests.post(API_URL, headers=headers, json=payload, timeout=timeout)
            response.raise_for_status()
            blocks = response.json().get("content", [])
            return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")
        except Exception as exc:  # noqa: BLE001
            last = exc
            if attempt == 0:
                time.sleep(3)
    assert last is not None
    raise last


def generate_commentary(ctx: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    """Renvoie (commentaire validé ou None, messages d'incident). Ne lève jamais d'exception."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None, []
    model = os.environ.get("LLM_MODEL", "").strip() or DEFAULT_MODEL
    try:
        facts_text = json.dumps(build_facts(ctx), ensure_ascii=False, default=str)
        raw = _parse_json(call_model(facts_text, api_key, model))
        clean, dropped = validate_commentary(raw, facts_text)
        if not (clean.get("categories") or any(clean.get(k) for k in SECTION_KEYS)):
            return None, [f"Rédaction assistée : aucun paragraphe n'a passé le contrôle ({dropped} écarté(s))."]
        clean["meta"] = {"model": model, "dropped": dropped}
        return clean, []
    except Exception as exc:  # noqa: BLE001 - la couche est optionnelle
        return None, [f"Rédaction assistée indisponible : {type(exc).__name__}: {str(exc)[:140]}"]
