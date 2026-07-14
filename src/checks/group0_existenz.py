"""Gruppe 0 - Existenz & Auffindbarkeit (Modus A, Gewicht 10%)."""
from __future__ import annotations

from src.checks.base import CheckContext, fehler, nicht_pruefbar, ok, warnung

GRUPPE = "existenz_auffindbarkeit"

_GESCHLOSSEN_STATUS = {"CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"}


def run(ctx: CheckContext) -> list:
    results = []
    loc_id = ctx.location.id

    if ctx.profile is None:
        results.append(
            fehler(
                "existenz_gbp_vorhanden",
                GRUPPE,
                ctx.modus,
                f"Für den Standort '{ctx.location.name}' ({ctx.location.address}) wurde kein "
                "Google-Unternehmensprofil gefunden.",
                "Google-Unternehmensprofil für diesen Standort anlegen und verifizieren lassen.",
                punkte=0.0,
                standort_id=loc_id,
            )
        )
        # Folgechecks dieser Gruppe sind ohne Profil nicht sinnvoll auswertbar
        return results

    results.append(
        ok(
            "existenz_gbp_vorhanden",
            GRUPPE,
            ctx.modus,
            "Google-Unternehmensprofil wurde gefunden und zugeordnet.",
            standort_id=loc_id,
        )
    )

    if ctx.location.duplicate_place_ids:
        results.append(
            warnung(
                "existenz_keine_duplikate",
                GRUPPE,
                ctx.modus,
                f"{len(ctx.location.duplicate_place_ids)} möglicher Duplikat-/Alteintrag(e) im "
                "Umkreis gefunden (ähnlicher Name, ggf. unbeansprucht oder veraltet).",
                "Duplikate bei Google zusammenführen lassen oder als geschlossen/verschoben markieren.",
                punkte=40.0,
                standort_id=loc_id,
            )
        )
    else:
        results.append(
            ok(
                "existenz_keine_duplikate",
                GRUPPE,
                ctx.modus,
                "Keine Duplikate oder verwaisten Alteinträge in der Umgebung gefunden.",
                standort_id=loc_id,
            )
        )

    status = (ctx.profile.business_status or "").upper()
    if status in _GESCHLOSSEN_STATUS:
        results.append(
            fehler(
                "existenz_betriebsstatus",
                GRUPPE,
                ctx.modus,
                f"Profil ist als '{status}' markiert, obwohl der Standort laut Website aktiv ist.",
                "Betriebsstatus im Google-Unternehmensprofil korrigieren (Wiedereröffnung markieren).",
                standort_id=loc_id,
            )
        )
    elif not status:
        results.append(
            nicht_pruefbar(
                "existenz_betriebsstatus",
                GRUPPE,
                ctx.modus,
                "Betriebsstatus im Profil nicht angegeben.",
                standort_id=loc_id,
            )
        )
    else:
        results.append(
            ok(
                "existenz_betriebsstatus",
                GRUPPE,
                ctx.modus,
                f"Betriebsstatus korrekt: {status}.",
                standort_id=loc_id,
            )
        )

    return results
