"""Berechnet Gruppen- und Gesamtscore aus den Check-Ergebnissen eines Standorts.

Im Modus A sind mehrere Kriteriengruppen (4, 7, 8, 9 und Teile von 5/6)
komplett "nicht prüfbar". Damit der Gesamtscore trotzdem vergleichbar bleibt,
werden die Gewichte automatisch auf die im aktuellen Modus lauffähigen
Gruppen renormalisiert (Summe bleibt 100%).
"""
from __future__ import annotations

from typing import Any, Optional

from src.checks import GROUPS
from src.models import CheckResult, GroupScore, LocationAuditResult, Modus


def _group_score_from_checks(gruppe: str, checks: list[CheckResult]) -> GroupScore:
    bewertbare = [c for c in checks if c.punkte is not None]
    if not bewertbare:
        return GroupScore(gruppe=gruppe, punkte=None, gewicht_prozent=0.0, checks=checks, lauffaehig=False)
    durchschnitt = sum(c.punkte for c in bewertbare) / len(bewertbare)
    return GroupScore(gruppe=gruppe, punkte=round(durchschnitt, 1), gewicht_prozent=0.0, checks=checks, lauffaehig=True)


def _ampel(score: Optional[float], ampel_config: dict[str, Any]) -> str:
    if score is None:
        return "n/a"
    if score >= ampel_config.get("gruen_ab", 85):
        return "gruen"
    if score >= ampel_config.get("gelb_ab", 60):
        return "gelb"
    return "rot"


def score_location(
    location,
    profile,
    modus: Modus,
    all_checks: list[CheckResult],
    scoring_config: dict[str, Any],
) -> LocationAuditResult:
    group_weights: dict[str, float] = scoring_config.get("group_weights", {})
    ampel_config: dict[str, Any] = scoring_config.get("ampel", {})

    checks_by_group: dict[str, list[CheckResult]] = {gruppe: [] for gruppe, _ in GROUPS}
    for c in all_checks:
        checks_by_group.setdefault(c.gruppe, []).append(c)

    group_scores = [_group_score_from_checks(gruppe, checks_by_group.get(gruppe, [])) for gruppe, _ in GROUPS]

    lauffaehige_gewichte = {
        gs.gruppe: group_weights.get(gs.gruppe, 0.0) for gs in group_scores if gs.lauffaehig
    }
    gesamtgewicht = sum(lauffaehige_gewichte.values())

    for gs in group_scores:
        roh_gewicht = group_weights.get(gs.gruppe, 0.0)
        if gs.lauffaehig and gesamtgewicht > 0:
            gs.gewicht_prozent = round(roh_gewicht / gesamtgewicht * 100, 1)
        else:
            gs.gewicht_prozent = 0.0

    if gesamtgewicht <= 0:
        gesamtscore = None
    else:
        gesamtscore = sum(
            gs.punkte * (gs.gewicht_prozent / 100) for gs in group_scores if gs.lauffaehig and gs.punkte is not None
        )
        gesamtscore = round(gesamtscore, 1)

    return LocationAuditResult(
        location=location,
        profile=profile,
        modus=modus,
        gesamtscore=gesamtscore,
        ampel=_ampel(gesamtscore, ampel_config),
        gruppen=group_scores,
    )


def top_massnahmen(result: LocationAuditResult, anzahl: int = 3) -> list[CheckResult]:
    """Sortiert Befunde nach Impact (Gewicht der Gruppe * Punkteabzug) für die Maßnahmenliste."""
    gewicht_je_gruppe = {gs.gruppe: gs.gewicht_prozent for gs in result.gruppen}
    mangelhafte = [
        c
        for gs in result.gruppen
        for c in gs.checks
        if c.status.value in ("warnung", "fehler")
    ]

    def impact(check: CheckResult) -> float:
        abzug = 100 - (check.punkte if check.punkte is not None else 0)
        return gewicht_je_gruppe.get(check.gruppe, 0.0) * abzug

    return sorted(mangelhafte, key=impact, reverse=True)[:anzahl]
