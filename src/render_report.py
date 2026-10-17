"""Rendu du modèle éditorial : page HTML soignée (lecture longue) et version texte.

Parti pris graphique : une note de recherche, pas un tableau de bord. Une colonne de lecture
étroite en serif, des chiffres alignés en sans-serif, et un plan de lecture chiffré en minutes
qui sert de table des matières. Pas de cartes, pas d'ombres, pas de dégradés.
"""
from __future__ import annotations

import html
import re
from datetime import datetime
from typing import Any

try:
    from . import calendar_events
except ImportError:  # exécution en script
    import calendar_events  # type: ignore[no-redef]

IMPORTANCE_LABEL = {"élevée": "élevé", "moyenne": "moyen", "faible": "faible"}
URL_RE = re.compile(r"(https?://[^\s<]+)")
GOOGLE_FONTS = ("https://fonts.googleapis.com/css2?family=Newsreader:ital,opsz,wght@0,6..72,400;0,6..72,500;0,6..72,600;1,6..72,400"
                "&family=IBM+Plex+Sans:wght@400;500;600&display=swap")

CSS = """
:root{
  --paper:#F3F5F8;--surface:#FFFFFF;--ink:#17212B;--muted:#566474;--rule:#D6DCE4;--accent:#2B5C8F;
  --gain:#17734A;--loss:#B42318;--warn-bg:#FFF3D1;--warn:#6F4700;--info-bg:#E8F0F8;
  --serif:'Newsreader',Georgia,'Times New Roman',serif;
  --sans:'IBM Plex Sans',system-ui,-apple-system,'Segoe UI',Roboto,sans-serif;
  color-scheme:light dark;
}
@media (prefers-color-scheme:dark){:root{
  --paper:#0E141B;--surface:#141C25;--ink:#E8EDF2;--muted:#9AA8B7;--rule:#263341;--accent:#86B6EA;
  --gain:#4CC38A;--loss:#FF8F85;--warn-bg:#2B2410;--warn:#E8C26B;--info-bg:#15222F}}
*{box-sizing:border-box}
html{scroll-padding-top:1.5rem}
@media (prefers-reduced-motion:no-preference){html{scroll-behavior:smooth}}
body{margin:0;background:var(--paper);color:var(--ink);font:18px/1.7 var(--serif);
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:var(--accent);text-underline-offset:.18em;overflow-wrap:anywhere}
a:focus-visible,summary:focus-visible{outline:3px solid var(--accent);outline-offset:3px;border-radius:2px}
.shell{display:grid;grid-template-columns:16rem minmax(0,44rem);gap:4rem;max-width:68rem;margin:0 auto;padding:3rem 1.5rem 5rem}
.masthead{grid-column:1 / -1;max-width:50rem}
.brand{font:500 .9rem/1.2 var(--sans);color:var(--muted);display:flex;flex-wrap:wrap;gap:.5rem 1.25rem;align-items:baseline}
.brand strong{color:var(--ink);font-weight:600}
.masthead h1{font:500 clamp(2rem,5vw,3.1rem)/1.12 var(--serif);letter-spacing:-.012em;margin:1.4rem 0 1rem;text-wrap:balance}
.dek{font-size:1.2rem;line-height:1.55;color:var(--muted);margin:0 0 1.6rem;max-width:42rem}
.facts{display:flex;flex-wrap:wrap;gap:.4rem 2.2rem;margin:0;font:400 .88rem/1.4 var(--sans)}
.facts div{display:flex;gap:.45rem}.facts dt{color:var(--muted)}.facts dd{margin:0;font-weight:600}
nav.plan{position:sticky;top:1.5rem;align-self:start;font-family:var(--sans);font-size:.88rem;max-height:calc(100vh - 3rem);overflow:auto}
nav.plan h2{font:600 .95rem/1.3 var(--sans);margin:0 0 .3rem}
nav.plan p{margin:0 0 1rem;color:var(--muted);font-size:.82rem;line-height:1.45}
nav.plan ol{list-style:none;margin:0;padding:0;border-left:1px solid var(--rule)}
nav.plan li{margin:0}
nav.plan a{display:grid;grid-template-columns:1fr auto;gap:.6rem;padding:.38rem 0 .38rem .85rem;color:var(--ink);text-decoration:none;position:relative}
nav.plan a:hover{color:var(--accent)}
nav.plan a .m{color:var(--muted);font-variant-numeric:tabular-nums}
nav.plan a .bar{position:absolute;left:-1px;top:0;bottom:0;width:3px;background:var(--accent);opacity:.12}
main{min-width:0}
section{margin:0 0 3.4rem}
section>header{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:space-between;gap:.25rem 1rem;border-top:2px solid var(--ink);padding-top:.9rem;margin-bottom:1.1rem}
section h2{font:500 1.85rem/1.2 var(--serif);margin:0;letter-spacing:-.008em}
section header .meta{font:400 .85rem var(--sans);color:var(--muted)}
h3{font:600 .95rem/1.3 var(--sans);margin:2rem 0 .6rem;color:var(--ink)}
p{margin:0 0 1.05rem}
p.intro{font-style:italic;color:var(--muted)}
ul.takeaways{list-style:none;padding:0;margin:0 0 1.6rem}
ul.takeaways li{padding:.75rem 0 .75rem 1.1rem;border-left:3px solid var(--accent);margin:0 0 .55rem;font-size:1.05rem;line-height:1.55}
ul{padding-left:1.25rem;margin:0 0 1.2rem}li{margin:0 0 .45rem}
.chip{display:inline-block;font:500 .75rem/1 var(--sans);border:1px solid var(--rule);color:var(--muted);border-radius:4px;padding:.28rem .5rem;margin:0 0 .8rem}
.chip.high{border-color:var(--loss);color:var(--loss)}.chip.warn{background:var(--warn-bg);border-color:transparent;color:var(--warn)}
.chip.ok{color:var(--gain);border-color:var(--gain)}
.table-wrap{overflow-x:auto;margin:1.2rem 0 1.5rem;border-top:1px solid var(--rule)}
table{border-collapse:collapse;width:100%;font:400 .86rem/1.35 var(--sans);font-variant-numeric:tabular-nums lining-nums}
caption{text-align:left;font:600 .8rem var(--sans);color:var(--muted);padding:.55rem 0}
th{font-weight:600;text-align:left;color:var(--muted);padding:.5rem .7rem .5rem 0;border-bottom:1px solid var(--ink);white-space:nowrap}
td{padding:.55rem .7rem .55rem 0;border-bottom:1px solid var(--rule);vertical-align:top}
th.n,td.n{text-align:right;padding-right:1rem}
td .sub{display:block;color:var(--muted);font-size:.74rem}
.up{color:var(--gain)}.down{color:var(--loss)}
svg.spark{display:block;width:84px;height:22px;overflow:visible}
svg.spark polyline{fill:none;stroke:currentColor;stroke-width:1.6;stroke-linejoin:round;stroke-linecap:round}
.probs{margin:1rem 0 1.5rem;font:400 .9rem var(--sans)}
.probs div.row{display:grid;grid-template-columns:7.5rem 1fr 3rem;gap:.8rem;align-items:center;margin:.4rem 0}
.probs .track{height:.7rem;background:var(--rule);border-radius:2px;overflow:hidden}
.probs .fill{display:block;height:100%}
.probs .v{text-align:right;font-weight:600;font-variant-numeric:tabular-nums}
.probs small{display:block;margin-top:.6rem;color:var(--muted);line-height:1.5}
.callout{font:400 .95rem/1.55 var(--sans);padding:.9rem 1.1rem;margin:1.3rem 0;border-radius:4px;background:var(--info-bg)}
.callout.warn{background:var(--warn-bg);color:var(--warn)}
.note{font:400 .88rem/1.55 var(--sans);color:var(--muted);margin:0 0 1.2rem}
article.story{margin:0 0 1.7rem;padding-bottom:1.3rem;border-bottom:1px solid var(--rule)}
article.story h3{font:500 1.15rem/1.35 var(--serif);margin:0 0 .25rem}
article.story .src{font:400 .8rem var(--sans);color:var(--muted);margin:0 0 .6rem}
article.story .read{font:400 .93rem/1.6 var(--sans);margin:.5rem 0 .4rem}
.scenario{margin:0 0 1.25rem}.scenario h3{margin:1.4rem 0 .3rem;font:600 1rem var(--sans)}
.day{font:600 .95rem var(--sans);margin:1.8rem 0 .5rem;padding-bottom:.35rem;border-bottom:1px solid var(--rule)}
.event{display:grid;grid-template-columns:4.2rem 1fr;gap:.2rem 1rem;margin:0 0 1.1rem}
.event .t{font:600 .9rem var(--sans);font-variant-numeric:tabular-nums;color:var(--accent)}
.event .what{font-size:1rem;line-height:1.5}.event .tags{margin:.3rem 0 .2rem;display:flex;flex-wrap:wrap;gap:.35rem}
.event .tags .chip{margin:0}.event .cats{font:400 .8rem var(--sans);color:var(--muted)}
details.annex{margin:3rem 0 0;border-top:2px solid var(--ink);padding-top:.8rem;font-family:var(--sans)}
details.annex summary{cursor:pointer;font-weight:600;font-size:.95rem}
details.annex pre{white-space:pre-wrap;overflow-wrap:anywhere;font:400 .78rem/1.55 var(--sans);color:var(--muted);margin-top:1rem}
footer{grid-column:1 / -1;max-width:44rem;margin:0 0 0 auto;font:400 .8rem/1.55 var(--sans);color:var(--muted);border-top:1px solid var(--rule);padding-top:1rem}
@media (max-width:62rem){
  .shell{display:block;padding:1.6rem 1.15rem 4rem}
  nav.plan{position:static;max-height:none;margin:1.8rem 0 2.4rem}
  footer{margin:2rem 0 0}.event{grid-template-columns:3.6rem 1fr}
}
@media (max-width:34rem){body{font-size:17px}.probs div.row{grid-template-columns:5.5rem 1fr 2.6rem}}
@media print{
  body{background:#fff;color:#000;font-size:11pt}.shell{display:block;padding:0;max-width:none}
  nav.plan{display:none}section{break-inside:auto}section>header,h3,caption{break-after:avoid}
  .table-wrap,article.story,.event,.scenario{break-inside:avoid}a{color:#000;text-decoration:none}
  details.annex[open]>pre{font-size:8pt}
}
"""


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def linkify(text: str) -> str:
    out, last = [], 0
    for m in URL_RE.finditer(text):
        url = m.group(1).rstrip(".,;)")
        out.append(esc(text[last:m.start()]))
        out.append(f'<a href="{esc(url)}" rel="noopener">{esc(url)}</a>')
        last = m.start() + len(url)
    out.append(esc(text[last:]))
    return "".join(out)


def sparkline(values: list[float] | None) -> str:
    if not values or len(values) < 5:
        return '<span class="note">n.d.</span>'
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    w, h = 84.0, 22.0
    pts = " ".join(f"{i * w / (len(values) - 1):.1f},{h - 2 - (v - lo) / span * (h - 4):.1f}" for i, v in enumerate(values))
    cls = "up" if values[-1] >= values[0] else "down"
    label = f"Tendance sur {len(values)} séances : de {values[0]:.4g} à {values[-1]:.4g}"
    return f'<svg class="spark {cls}" viewBox="0 0 84 22" role="img" aria-label="{esc(label)}"><polyline points="{pts}"/></svg>'


def _cell(cell: dict[str, Any], numeric: bool) -> str:
    cls = " ".join(x for x in ("n" if numeric else "", cell.get("cls", "")) if x)
    attr = f' class="{cls}"' if cls else ""
    if "spark" in cell:
        return f"<td>{sparkline(cell['spark'])}</td>"
    inner = esc(cell.get("t", ""))
    if cell.get("href"):
        inner = f'<a href="{esc(cell["href"])}" rel="noopener">{inner}</a>'
    if cell.get("sub"):
        inner += f'<span class="sub">{esc(cell["sub"])}</span>'
    return f"<td{attr}>{inner}</td>"


def render_block(block: dict[str, Any]) -> str:
    kind = block["kind"]
    if kind == "p":
        cls = f' class="{block["cls"]}"' if block.get("cls") else ""
        return f"<p{cls}>{linkify(block['text'])}</p>"
    if kind == "h3":
        return f"<h3>{esc(block['text'])}</h3>"
    if kind == "note":
        return f'<p class="note">{linkify(block["text"])}</p>'
    if kind == "chip":
        return f'<span class="chip">{esc(block["text"])}</span>'
    if kind == "callout":
        return f'<div class="callout {esc(block.get("tone", "info"))}">{linkify(block["text"])}</div>'
    if kind == "list":
        cls = f' class="{block["cls"]}"' if block.get("cls") else ""
        return f"<ul{cls}>" + "".join(f"<li>{linkify(i)}</li>" for i in block["items"]) + "</ul>"
    if kind == "table":
        numeric = block.get("numeric", set())
        head = "".join(f'<th scope="col"{" class=n" if i in numeric else ""}>{esc(h)}</th>' for i, h in enumerate(block["headers"]))
        body = "".join("<tr>" + "".join(_cell(c, i in numeric) for i, c in enumerate(row)) + "</tr>" for row in block["rows"])
        return (f'<div class="table-wrap"><table><caption>{esc(block.get("caption", ""))}</caption>'
                f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>")
    if kind == "probs":
        order = [("haussier", "Hausse", "var(--gain)"), ("central", "Zone centrale", "var(--muted)"), ("baissier", "Baisse", "var(--loss)")]
        rows = "".join(f'<div class="row"><span>{label}</span><span class="track"><span class="fill" style="width:{block["probs"].get(k, 0)}%;background:{color}"></span></span>'
                       f'<span class="v">{block["probs"].get(k, 0)} %</span></div>' for k, label, color in order)
        return f'<div class="probs" role="group" aria-label="Probabilités expérimentales">{rows}<small>{esc(block.get("note", ""))}</small></div>'
    if kind == "news":
        title = esc(block["title"])
        if block.get("url"):
            title = f'<a href="{esc(block["url"])}" rel="noopener">{title}</a>'
        read = f'<p class="read"><strong>Lecture marché.</strong> {esc(block["readthrough"])}</p>' if block.get("readthrough") else ""
        summary = f"<p>{esc(block['summary'])}</p>" if block.get("summary") else ""
        return (f'<article class="story"><h3>{title}</h3><p class="src">{esc(block["source"])}, {esc(block["published"])}</p>{summary}{read}</article>')
    if kind == "scenario":
        return f'<div class="scenario"><h3>{esc(block["title"])}</h3><p>{esc(block["body"])}</p></div>'
    if kind == "events":
        out, current = [], None
        for e in block["events"]:
            if e["day"] != current:
                current = e["day"]
                out.append(f'<div class="day">{esc(current)}</div>')
            label = IMPORTANCE_LABEL.get(e["importance"], e["importance"])
            imp = f'<span class="chip high">Impact {esc(label)}</span>' if e["importance"] == "élevée" else f'<span class="chip">Impact {esc(label)}</span>'
            status = f'<span class="chip ok">{esc(e["status"])}</span>' if e["status"] == "confirmé" else f'<span class="chip warn">{esc(e["status"])}</span>'
            src = ""
            if e.get("source"):
                src = f' <a href="{esc(e["source"])}" rel="noopener">source</a>' if e["source"].startswith("http") else f' <span class="note">Source : {esc(e["source"])}</span>'
            note = f'<div class="note">{esc(e["note"])}{src}</div>' if e.get("note") or src else ""
            cats = f'<div class="cats">Univers concernés : {esc(", ".join(e["categories"]))}</div>' if e.get("categories") else ""
            out.append(f'<div class="event"><div class="t">{esc(e["time"] or "heure ?")}</div><div><div class="what">{esc(e["title"])}</div>'
                       f'<div class="tags">{imp}{status}<span class="chip">{esc(e["region"])}</span></div>{cats}{note}</div></div>')
        return "".join(out)
    return ""


def render_html(model: dict[str, Any]) -> str:
    now: datetime | None = model.get("now_local")
    started: datetime | None = model.get("started")
    when = f"{calendar_events.format_day(now.date())} {now.year}, {now:%H:%M}" if now else ""
    sections = model["sections"]
    total = sum(s["minutes"] for s in sections) or 1
    plan = "".join(f'<li><a href="#{esc(s["id"])}"><span>{esc(s["title"])}</span><span class="m">{s["minutes"]} min</span>'
                   f'<span class="bar" style="width:{max(3, int(100 * s["minutes"] / total))}%"></span></a></li>' for s in sections)
    body = []
    for s in sections:
        body.append(f'<section id="{esc(s["id"])}" aria-labelledby="h-{esc(s["id"])}"><header><h2 id="h-{esc(s["id"])}">{esc(s["title"])}</h2>'
                    f'<span class="meta">Lecture : {s["minutes"]} min</span></header>' + "".join(render_block(b) for b in s["blocks"]) + "</section>")
    annex = ""
    if model.get("legacy_text"):
        annex = ('<details class="annex"><summary>Annexe : détail complet des données collectées (hors temps de lecture)</summary>'
                 f"<pre>{linkify(model['legacy_text'])}</pre></details>")
    weekend = ('<div class="callout warn">Les marchés d\'actions, de taux et de change sont fermés : les cours datent de la dernière séance.</div>'
               if model.get("weekend") else "")
    generated = f"{started:%d/%m/%Y à %H:%M UTC}" if started else "date inconnue"
    words = f"{model['words']:,}".replace(",", "\u202f")
    head = (
        '<!doctype html><html lang="fr"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{esc(model['kind_label'])} | Market Intelligence Daily</title>"
        '<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
        f'<link rel="stylesheet" href="{GOOGLE_FONTS}"><style>{CSS}</style></head>'
    )
    masthead = (
        '<header class="masthead"><div class="brand"><strong>Market Intelligence Daily</strong>'
        f'<span>{esc(model["kind_label"])}</span><span>{esc(when)} (heure de Madagascar)</span></div>'
        f'<h1>{esc(model["headline"])}</h1><p class="dek">{esc(model["dek"])}</p>'
        f'<dl class="facts"><div><dt>Lecture</dt><dd>{model["reading_minutes"]} min</dd></div>'
        f'<div><dt>Couverture</dt><dd>{model["n_assets"]} actifs sur {model["n_tracked"]}</dd></div>'
        f'<div><dt>Mots</dt><dd>{words}</dd></div></dl></header>'
    )
    nav = (f'<nav class="plan" aria-label="Plan de lecture"><h2>Plan de lecture</h2>'
           f'<p>Durée estimée de chaque partie, à 220 mots par minute.</p><ol>{plan}</ol></nav>')
    footer = (f"<footer>Rapport expérimental d'information, généré le {generated}. Il ne constitue pas un conseil en investissement : "
              "vérifier les données et les sources avant toute décision.</footer>")
    return f'{head}<body><div class="shell">{masthead}{nav}<main id="contenu">{weekend}{"".join(body)}{annex}</main>{footer}</div></body></html>'


# ----------------------------------------------------------------------------- texte
def render_text(model: dict[str, Any], include_headline: bool = True) -> str:
    lines: list[str] = []
    now = model.get("now_local")
    if include_headline:
        lines += [model["kind_label"].upper(), model["headline"], "", model["dek"], ""]
        if now:
            lines.append(f"Édition du {calendar_events.format_day(now.date())} {now.year}, {now:%H:%M} (heure de Madagascar). Lecture estimée : {model['reading_minutes']} min.")
        lines.append("")
    for s in model["sections"]:
        lines += ["", s["title"].upper(), f"(lecture : {s['minutes']} min)", ""]
        for b in s["blocks"]:
            k = b["kind"]
            if k in ("p", "note"):
                lines += [b["text"], ""]
            elif k == "h3":
                lines += [b["text"] + " :"]
            elif k == "chip":
                lines += [f"[{b['text']}]"]
            elif k == "callout":
                lines += [f"> {b['text']}", ""]
            elif k == "list":
                lines += [f"- {i}" for i in b["items"]] + [""]
            elif k == "probs":
                lines += [f"Hausse {b['probs'].get('haussier')} % ; zone centrale {b['probs'].get('central')} % ; baisse {b['probs'].get('baissier')} %.", b.get("note", ""), ""]
            elif k == "table":
                lines.append(b.get("caption", ""))
                lines.append(" | ".join(b["headers"]))
                for row in b["rows"]:
                    lines.append(" | ".join("tendance" if "spark" in c else (c.get("t", "") + (f" ({c['sub']})" if c.get("sub") else "")) for c in row))
                lines.append("")
            elif k == "news":
                lines += [f"* {b['title']}", f"  {b['source']}, {b['published']}"]
                if b.get("summary"):
                    lines.append(f"  {b['summary']}")
                if b.get("readthrough"):
                    lines.append(f"  Lecture marché : {b['readthrough']}")
                if b.get("url"):
                    lines.append(f"  {b['url']}")
                lines.append("")
            elif k == "scenario":
                lines += [b["title"], b["body"], ""]
            elif k == "events":
                for e in b["events"]:
                    lines.append(f"- {e['day']}{' à ' + e['time'] if e['time'] else ''} : {e['title']} [{e['status']}, impact {IMPORTANCE_LABEL.get(e['importance'], e['importance'])}]")
                    if e.get("note"):
                        lines.append(f"  {e['note']}")
                lines.append("")
    return "\n".join(lines).strip() + "\n"


def summary_html_from_text(text: str, report_url: str) -> str:
    """Courriel court et lisible, construit à partir du texte enregistré : l'essentiel et un lien vers la version complète."""
    lines = text.splitlines()
    kind_label = lines[0].title() if lines else "Rapport"
    headline = lines[1] if len(lines) > 1 else ""
    dek = lines[3] if len(lines) > 3 else ""
    minutes = re.search(r"Lecture estimée : (\d+) min", text)
    items: list[str] = []
    in_section = False
    for line in lines:
        if line.strip() == "L'ESSENTIEL":
            in_section = True
            continue
        if in_section:
            if line.startswith("- "):
                items.append(line[2:].strip())
            elif line.isupper() and line.strip():
                break
    bullets = "".join(f'<li style="margin:0 0 10px">{esc(i)}</li>' for i in items)
    label = f"Lire le rapport complet ({minutes.group(1)} min)" if minutes else "Lire le rapport complet"
    return (
        '<html><body style="margin:0;background:#F3F5F8;font-family:Georgia,serif;color:#17212B">'
        '<div style="max-width:640px;margin:0 auto;padding:28px 22px;background:#FFFFFF">'
        f'<p style="font:600 13px Arial,sans-serif;color:#566474;margin:0 0 12px">Market Intelligence Daily — {esc(kind_label)}</p>'
        f'<h1 style="font:500 26px/1.25 Georgia,serif;margin:0 0 12px">{esc(headline)}</h1>'
        f'<p style="font-size:16px;line-height:1.55;color:#566474;margin:0 0 18px">{esc(dek)}</p>'
        f'<ul style="font-size:16px;line-height:1.55;padding-left:18px;margin:0 0 22px">{bullets}</ul>'
        f'<p style="margin:0 0 6px"><a href="{esc(report_url)}" style="display:inline-block;background:#2B5C8F;color:#FFFFFF;text-decoration:none;'
        f'font:600 15px Arial,sans-serif;padding:12px 18px;border-radius:4px">{esc(label)}</a></p>'
        '<p style="font:12px/1.5 Arial,sans-serif;color:#566474;margin:22px 0 0">Contenu informatif et expérimental, pas un conseil en investissement. '
        "La version texte intégrale de ce rapport figure aussi dans ce message.</p></div></body></html>"
    )
