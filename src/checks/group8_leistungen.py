"""Gruppe 8 - Leistungen/Produkte (Modus B, Gewicht 5%)."""
from __future__ import annotations

from src.checks.base import CheckContext, nicht_pruefbar, ok, warnung
from src.models import Modus

GRUPPE = "leistungen"


def _serviceitems_gepflegt(ctx: CheckContext):
    loc_id = ctx.location.id
    if ctx.modus != Modus.B:
        return nicht_pruefbar(
            "leistungen_serviceitems",
            GRUPPE,
            ctx.modus,
            "Leistungen/Produkte sind nur mit Verwaltungszugriff (Modus B) prüfbar.",
            standort_id=loc_id,
        )

    schwelle = ctx.config.get("checks", {}).get("leistungen_mindestanzahl", 3)
    items = ctx.profile.service_items or []

    if len(items) >= schwelle:
        return ok(
            "leistungen_serviceitems",
            GRUPPE,
            ctx.modus,
            f"{len(items)} Leistungen/Produkte gepflegt (Schwellenwert: {schwelle}).",
            standort_id=loc_id,
        )
    return warnung(
        "leistungen_serviceitems",
        GRUPPE,
        ctx.modus,
        f"Nur {len(items)} Leistungen/Produkte gepflegt (Schwellenwert: {schwelle}).",
        "Weitere Leistungen/Produkte im Profil ergänzen.",
        punkte=max(0.0, 100.0 * len(items) / schwelle) if schwelle else 0.0,
        standort_id=loc_id,
    )


def run(ctx: CheckContext) -> list:
    if ctx.profile is None:
        return [
            nicht_pruefbar(
                "leistungen_serviceitems",
                GRUPPE,
                ctx.modus,
                "Kein GBP-Profil vorhanden - siehe Gruppe 'Existenz'.",
                standort_id=ctx.location.id,
            )
        ]
    return [_serviceitems_gepflegt(ctx)]
