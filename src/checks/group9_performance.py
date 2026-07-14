"""Gruppe 9 - Performance-Baseline (Modus B, Gewicht 10%).

Keine klassische Pass/Fail-Prüfung, sondern primär Datenerhebung: letzte 12
Monate Impressionen, Wegbeschreibungen, Anrufe, Website-Klicks. Die einzige
bewertende Komponente ist die Quartilseinteilung bei Mehrstandort-Kunden
(schwächste 10% werden markiert) sowie der Vergleich zum letzten Lauf.
"""
from __future__ import annotations

import statistics
from typing import Any, Optional

from src.checks.base import CheckContext, nicht_pruefbar, ok, result, warnung
from src.models import CheckStatus, Modus

GRUPPE = "performance"

_IMPRESSION_METRICS = (
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
)


def _total_impressions(metrics: dict[str, Any]) -> int:
    return sum(int(metrics.get(m, 0) or 0) for m in _IMPRESSION_METRICS)


def _normalized(metrics: dict[str, Any], key: str) -> Optional[float]:
    total = _total_impressions(metrics)
    if total <= 0:
        return None
    return (metrics.get(key, 0) or 0) / total * 1000


def _kennzahlen(ctx: CheckContext):
    loc_id = ctx.location.id
    if ctx.modus != Modus.B:
        return nicht_pruefbar(
            "performance_kennzahlen",
            GRUPPE,
            ctx.modus,
            "Performance-Baseline ist nur mit Verwaltungszugriff (Modus B) verfügbar.",
            standort_id=loc_id,
        )
    metrics = ctx.profile.performance_metrics
    if not metrics:
        return nicht_pruefbar(
            "performance_kennzahlen",
            GRUPPE,
            ctx.modus,
            "Keine Performance-Daten über die Business Profile Performance API verfügbar.",
            standort_id=loc_id,
        )

    total = _total_impressions(metrics)
    directions = metrics.get("BUSINESS_DIRECTION_REQUESTS", 0) or 0
    calls = metrics.get("CALL_CLICKS", 0) or 0
    clicks = metrics.get("WEBSITE_CLICKS", 0) or 0
    befund = (
        f"12-Monats-Impressionen: {total} (davon Suche: "
        f"{metrics.get('BUSINESS_IMPRESSIONS_DESKTOP_SEARCH', 0) + metrics.get('BUSINESS_IMPRESSIONS_MOBILE_SEARCH', 0)}, "
        f"Maps: {metrics.get('BUSINESS_IMPRESSIONS_DESKTOP_MAPS', 0) + metrics.get('BUSINESS_IMPRESSIONS_MOBILE_MAPS', 0)}). "
        f"Wegbeschreibungen: {directions}, Anrufe: {calls}, Website-Klicks: {clicks}."
    )
    # Datenerhebung ohne Bewertung -> kein punkte-Wert (fließt informativ, nicht wertend, in den Report ein)
    return result("performance_kennzahlen", GRUPPE, ctx.modus, CheckStatus.OK, None, befund, standort_id=loc_id)


def _quartil_einordnung(ctx: CheckContext):
    loc_id = ctx.location.id
    if ctx.modus != Modus.B:
        return nicht_pruefbar(
            "performance_quartil",
            GRUPPE,
            ctx.modus,
            "Performance-Baseline ist nur mit Verwaltungszugriff (Modus B) verfügbar.",
            standort_id=loc_id,
        )
    if not ctx.is_multi_location:
        return nicht_pruefbar(
            "performance_quartil",
            GRUPPE,
            ctx.modus,
            "Quartilseinteilung nur bei Mehrstandort-Kunden relevant (dieser Kunde hat einen Standort).",
            standort_id=loc_id,
        )

    metrics = ctx.profile.performance_metrics
    if not metrics:
        return nicht_pruefbar(
            "performance_quartil",
            GRUPPE,
            ctx.modus,
            "Keine Performance-Daten für die Quartilseinteilung verfügbar.",
            standort_id=loc_id,
        )

    eigener_wert = _normalized(metrics, "BUSINESS_DIRECTION_REQUESTS")
    peer_werte = [
        v
        for p in ctx.peer_profiles
        if p.performance_metrics and (v := _normalized(p.performance_metrics, "BUSINESS_DIRECTION_REQUESTS")) is not None
    ]

    if eigener_wert is None or len(peer_werte) < 3:
        return nicht_pruefbar(
            "performance_quartil",
            GRUPPE,
            ctx.modus,
            "Zu wenige vergleichbare Standorte mit Performance-Daten für eine Quartilseinteilung.",
            standort_id=loc_id,
        )

    alle_werte = sorted(peer_werte + [eigener_wert])
    dezile = statistics.quantiles(alle_werte, n=10)
    schwellenwert_10_prozent = dezile[0]

    befund = f"Wegbeschreibungen pro 1.000 Impressionen: {eigener_wert:.1f} (Kundenvergleich, {len(alle_werte)} Standorte)."

    if eigener_wert <= schwellenwert_10_prozent:
        return warnung(
            "performance_quartil",
            GRUPPE,
            ctx.modus,
            befund + " Zählt zu den schwächsten 10% im Kundenvergleich.",
            "Ursachen für unterdurchschnittliche Performance analysieren (Sichtbarkeit, Fotos, Bewertungen, Kategorien).",
            punkte=20.0,
            standort_id=loc_id,
        )
    return ok("performance_quartil", GRUPPE, ctx.modus, befund, standort_id=loc_id, punkte=90.0)


def _delta_zum_vorlauf(ctx: CheckContext):
    loc_id = ctx.location.id
    if ctx.modus != Modus.B:
        return nicht_pruefbar(
            "performance_delta",
            GRUPPE,
            ctx.modus,
            "Performance-Baseline ist nur mit Verwaltungszugriff (Modus B) verfügbar.",
            standort_id=loc_id,
        )
    if ctx.previous_profile is None or not ctx.previous_profile.performance_metrics:
        return nicht_pruefbar(
            "performance_delta",
            GRUPPE,
            ctx.modus,
            "Kein vorheriger Lauf mit Performance-Daten zum Vergleich vorhanden.",
            standort_id=loc_id,
        )
    if not ctx.profile.performance_metrics:
        return nicht_pruefbar(
            "performance_delta",
            GRUPPE,
            ctx.modus,
            "Keine aktuellen Performance-Daten zum Vergleich vorhanden.",
            standort_id=loc_id,
        )

    alt_total = _total_impressions(ctx.previous_profile.performance_metrics)
    neu_total = _total_impressions(ctx.profile.performance_metrics)
    delta_prozent = ((neu_total - alt_total) / alt_total * 100) if alt_total else None

    if delta_prozent is None:
        befund = f"Impressionen aktuell: {neu_total} (vorheriger Lauf: {alt_total}, kein Prozentvergleich möglich)."
    else:
        richtung = "Anstieg" if delta_prozent >= 0 else "Rückgang"
        befund = f"Impressionen: {richtung} um {abs(delta_prozent):.0f}% gegenüber dem letzten Lauf ({alt_total} -> {neu_total})."

    return result("performance_delta", GRUPPE, ctx.modus, CheckStatus.OK, None, befund, standort_id=loc_id)


def run(ctx: CheckContext) -> list:
    if ctx.profile is None:
        loc_id = ctx.location.id
        return [
            nicht_pruefbar(cid, GRUPPE, ctx.modus, "Kein GBP-Profil vorhanden - siehe Gruppe 'Existenz'.", standort_id=loc_id)
            for cid in ("performance_kennzahlen", "performance_quartil", "performance_delta")
        ]
    return [_kennzahlen(ctx), _quartil_einordnung(ctx), _delta_zum_vorlauf(ctx)]
