"""Gruppe 2 - Kategorien (Modus A, Gewicht 10%)."""
from __future__ import annotations

from collections import Counter

from src.checks.base import CheckContext, nicht_pruefbar, ok, warnung

GRUPPE = "kategorien"


def _soll_kategorie(ctx: CheckContext) -> str:
    return (ctx.config.get("kategorien", {}) or {}).get("soll_hauptkategorie", "") or ""


def _hauptkategorie_check(ctx: CheckContext):
    loc_id = ctx.location.id
    ist = ctx.profile.primary_type or ""
    soll = _soll_kategorie(ctx)

    if not soll:
        return nicht_pruefbar(
            "kategorien_hauptkategorie",
            GRUPPE,
            ctx.modus,
            f"Keine Soll-Hauptkategorie in der Kundenkonfiguration hinterlegt (gefunden: '{ist}'). "
            "Bei Bestätigung wird dieser Wert künftig als Soll übernommen.",
            standort_id=loc_id,
        )

    if ist == soll:
        return ok("kategorien_hauptkategorie", GRUPPE, ctx.modus, f"Hauptkategorie entspricht dem Soll ('{soll}').", standort_id=loc_id)

    return warnung(
        "kategorien_hauptkategorie",
        GRUPPE,
        ctx.modus,
        f"Hauptkategorie '{ist}' weicht vom Soll '{soll}' ab.",
        f"Hauptkategorie im Profil auf '{soll}' setzen.",
        punkte=30.0,
        standort_id=loc_id,
    )


def _mehrstandort_abweichung(ctx: CheckContext):
    loc_id = ctx.location.id
    if not ctx.is_multi_location:
        return nicht_pruefbar(
            "kategorien_mehrstandort_konsistenz",
            GRUPPE,
            ctx.modus,
            "Nur bei Mehrstandort-Kunden relevant (dieser Kunde hat einen Standort).",
            standort_id=loc_id,
        )

    all_primary = [ctx.profile.primary_type] + [p.primary_type for p in ctx.peer_profiles]
    all_primary = [t for t in all_primary if t]
    if not all_primary:
        return nicht_pruefbar(
            "kategorien_mehrstandort_konsistenz",
            GRUPPE,
            ctx.modus,
            "Keine Kategoriedaten für den Kundenvergleich verfügbar.",
            standort_id=loc_id,
        )

    counter = Counter(all_primary)
    haeufigste, _ = counter.most_common(1)[0]
    eigene = ctx.profile.primary_type

    if eigene == haeufigste:
        return ok(
            "kategorien_mehrstandort_konsistenz",
            GRUPPE,
            ctx.modus,
            f"Hauptkategorie entspricht dem kundenweit häufigsten Kategorien-Set ('{haeufigste}').",
            standort_id=loc_id,
        )

    return warnung(
        "kategorien_mehrstandort_konsistenz",
        GRUPPE,
        ctx.modus,
        f"Hauptkategorie '{eigene}' weicht vom kundenweit häufigsten Set ('{haeufigste}') ab.",
        "Prüfen, ob Abweichung fachlich begründet ist, sonst angleichen.",
        punkte=50.0,
        standort_id=loc_id,
    )


def run(ctx: CheckContext) -> list:
    if ctx.profile is None:
        loc_id = ctx.location.id
        return [
            nicht_pruefbar(cid, GRUPPE, ctx.modus, "Kein GBP-Profil vorhanden - siehe Gruppe 'Existenz'.", standort_id=loc_id)
            for cid in ("kategorien_hauptkategorie", "kategorien_mehrstandort_konsistenz")
        ]
    return [_hauptkategorie_check(ctx), _mehrstandort_abweichung(ctx)]
