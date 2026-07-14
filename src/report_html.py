"""Erzeugt ein optionales statisches HTML-Dashboard (--html) neben dem Excel-Report.

Bewusst ohne externe Abhängigkeiten (kein CDN) - reines HTML/CSS/JS, sortierbare
Tabelle per Klick auf die Spaltenüberschrift und ein einfaches SVG-Histogramm
der Score-Verteilung.
"""
from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Template

from src.models import ClientRun

_TEMPLATE = Template(
    """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>GBP-Audit Dashboard - {{ client_slug }}</title>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 2rem; color: #1a1a1a; background: #fafafa; }
  h1 { font-size: 1.4rem; }
  .meta { color: #555; margin-bottom: 1.5rem; }
  table { border-collapse: collapse; width: 100%; background: #fff; box-shadow: 0 1px 3px rgba(0,0,0,.1); }
  th, td { padding: 0.5rem 0.75rem; border-bottom: 1px solid #eee; text-align: left; font-size: 0.9rem; }
  th { cursor: pointer; background: #4472C4; color: #fff; position: sticky; top: 0; user-select: none; }
  th:hover { background: #345; }
  tr:hover { background: #f5f7ff; }
  .ampel { display: inline-block; padding: 0.1rem 0.5rem; border-radius: 4px; font-weight: 600; }
  .gruen { background: #C6EFCE; color: #256029; }
  .gelb { background: #FFEB9C; color: #7a5b00; }
  .rot { background: #FFC7CE; color: #7a0010; }
  .na { background: #E7E6E6; color: #555; }
  .hist { display: flex; align-items: flex-end; gap: 4px; height: 120px; margin: 1rem 0 2rem; }
  .bar { background: #4472C4; width: 24px; position: relative; }
  .bar span { position: absolute; top: -1.2rem; font-size: 0.7rem; left: 50%; transform: translateX(-50%); }
  .bar label { position: absolute; bottom: -1.4rem; font-size: 0.65rem; left: 50%; transform: translateX(-50%); white-space: nowrap; }
</style>
</head>
<body>
<h1>GBP-Audit Dashboard: {{ client_slug }}</h1>
<p class="meta">Lauf vom {{ run_date }} - Modus {{ modus }} - {{ anzahl_standorte }} Standort(e)</p>

<h2>Score-Verteilung</h2>
<div class="hist" id="hist"></div>

<h2>Standorte</h2>
<table id="tbl">
<thead>
<tr>
<th data-key="name">Standort</th>
<th data-key="address">Adresse</th>
<th data-key="score">Gesamtscore</th>
<th data-key="ampel">Ampel</th>
<th data-key="top_mangel">Top-Mangel</th>
</tr>
</thead>
<tbody>
{% for r in rows %}
<tr>
<td>{{ r.name }}</td>
<td>{{ r.address }}</td>
<td>{{ r.score if r.score is not none else "n/a" }}</td>
<td><span class="ampel {{ r.ampel_class }}">{{ r.ampel }}</span></td>
<td>{{ r.top_mangel }}</td>
</tr>
{% endfor %}
</tbody>
</table>

<script>
const rows = {{ rows_json | safe }};

function renderHistogram() {
  const buckets = [0,0,0,0,0]; // rot(<40), rot(40-59), gelb(60-84), gruen(85-100), n/a
  const labels = ["<40", "40-59", "60-84", "85-100", "n/a"];
  rows.forEach(r => {
    if (r.score === null) { buckets[4]++; return; }
    if (r.score < 40) buckets[0]++;
    else if (r.score < 60) buckets[1]++;
    else if (r.score < 85) buckets[2]++;
    else buckets[3]++;
  });
  const max = Math.max(...buckets, 1);
  const hist = document.getElementById("hist");
  buckets.forEach((count, i) => {
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.height = Math.max(4, (count / max) * 100) + "px";
    bar.innerHTML = `<span>${count}</span><label>${labels[i]}</label>`;
    hist.appendChild(bar);
  });
}

function sortTable(key, asc) {
  const tbody = document.querySelector("#tbl tbody");
  const sorted = [...rows].sort((a, b) => {
    let av = a[key], bv = b[key];
    if (av === null) av = -1;
    if (bv === null) bv = -1;
    if (typeof av === "string") return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    return asc ? av - bv : bv - av;
  });
  tbody.innerHTML = sorted.map(r => `
    <tr>
      <td>${r.name}</td>
      <td>${r.address}</td>
      <td>${r.score !== null ? r.score : "n/a"}</td>
      <td><span class="ampel ${r.ampel_class}">${r.ampel}</span></td>
      <td>${r.top_mangel}</td>
    </tr>`).join("");
}

document.querySelectorAll("#tbl th").forEach(th => {
  let asc = true;
  th.addEventListener("click", () => {
    sortTable(th.dataset.key, asc);
    asc = !asc;
  });
});

renderHistogram();
</script>
</body>
</html>
"""
)


def write_html_report(client_run: ClientRun, output_path: Path) -> Path:
    rows = []
    for r in client_run.results:
        top = r.gruppen and next(
            (
                c.befund
                for gs in sorted(r.gruppen, key=lambda g: g.gewicht_prozent, reverse=True)
                for c in gs.checks
                if c.status.value in ("fehler", "warnung")
            ),
            "-",
        )
        rows.append(
            {
                "name": r.location.name,
                "address": r.location.address,
                "score": r.gesamtscore,
                "ampel": r.ampel,
                "ampel_class": "na" if r.ampel == "n/a" else r.ampel,
                "top_mangel": top or "-",
            }
        )

    html = _TEMPLATE.render(
        client_slug=client_run.client_slug,
        run_date=client_run.run_date,
        modus=client_run.modus.value,
        anzahl_standorte=len(client_run.results),
        rows=rows,
        rows_json=json.dumps(rows, ensure_ascii=False),
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    return output_path
