"""Gruppe 5 - Fotos (Modus A eingeschränkt als Indiz, voll in Modus B, Gewicht 10%)."""
from __future__ import annotations

import datetime as dt

from src.checks.base import CheckContext, fehler, nicht_pruefbar, ok, warnung
from src.models import Modus

GRUPPE = "fotos"


def _fotos_modus_a(ctx: CheckContext):
    loc_id = ctx.location.id
    count = ctx.profile.photo_count

    if count is None:
        return nicht_pruefbar(
            "fotos_anzahl_indiz",
            GRUPPE,
            ctx.modus,
            "Keine Foto-Anzahl über die Places API verfügbar.",
            standort_id=loc_id,
        )
    if count == 0:
        return fehler(
            "fotos_anzahl_indiz",
            GRUPPE,
            ctx.modus,
            "Keine Fotos im Profil erkennbar (Indiz aus Public Audit, eingeschränkt aussagekräftig).",
            "Fotos zum Profil hinzufügen; für eine vollständige Fotoprüfung ist Verwaltungszugriff nötig.",
            punkte=20.0,
            standort_id=loc_id,
        )
    if count < 5:
        return warnung(
            "fotos_anzahl_indiz",
            GRUPPE,
            ctx.modus,
            f"Nur {count} Fotos über die Places API sichtbar (Indiz, eingeschränkt aussagekräftig).",
            "Weitere aktuelle Fotos ergänzen.",
            punkte=60.0,
            standort_id=loc_id,
        )
    return ok(
        "fotos_anzahl_indiz",
        GRUPPE,
        ctx.modus,
        f"{count} Fotos über die Places API sichtbar (Indiz, eingeschränkt aussagekräftig).",
        standort_id=loc_id,
    )


def _modus_b_guard(check_id: str, ctx: CheckContext):
    if ctx.modus != Modus.B:
        return nicht_pruefbar(
            check_id,
            GRUPPE,
            ctx.modus,
            "Nur mit Verwaltungszugriff (Modus B) vollständig prüfbar.",
            standort_id=ctx.location.id,
        )
    return None


def _fotos_mindestanzahl_modus_b(ctx: CheckContext):
    guard = _modus_b_guard("fotos_mindestanzahl", ctx)
    if guard:
        return guard

    loc_id = ctx.location.id
    schwelle = ctx.config.get("checks", {}).get("fotos_mindestanzahl_inhaber", 10)
    fotos = ctx.profile.owner_photos or []

    if len(fotos) >= schwelle:
        return ok(
            "fotos_mindestanzahl",
            GRUPPE,
            ctx.modus,
            f"{len(fotos)} eigene Inhaberfotos vorhanden (Schwellenwert: {schwelle}).",
            standort_id=loc_id,
        )
    return warnung(
        "fotos_mindestanzahl",
        GRUPPE,
        ctx.modus,
        f"Nur {len(fotos)} eigene Inhaberfotos vorhanden (Schwellenwert: {schwelle}).",
        "Weitere aktuelle Fotos hochladen.",
        punkte=max(0.0, 100.0 * len(fotos) / schwelle) if schwelle else 0.0,
        standort_id=loc_id,
    )


def _aussen_innen_vorhanden(ctx: CheckContext):
    guard = _modus_b_guard("fotos_aussen_innen", ctx)
    if guard:
        return guard

    loc_id = ctx.location.id
    fotos = ctx.profile.owner_photos or []
    kategorien = {
        (f.get("locationAssociation", {}) or {}).get("category")
        for f in fotos
        if isinstance(f, dict)
    }
    hat_aussen = "EXTERIOR" in kategorien
    hat_innen = "INTERIOR" in kategorien

    if hat_aussen and hat_innen:
        return ok("fotos_aussen_innen", GRUPPE, ctx.modus, "Außen- und Innenaufnahmen vorhanden.", standort_id=loc_id)
    if not fotos:
        return fehler(
            "fotos_aussen_innen",
            GRUPPE,
            ctx.modus,
            "Weder Außen- noch Innenaufnahmen vorhanden.",
            "Mindestens je ein Außen- und ein Innenfoto hochladen.",
            standort_id=loc_id,
        )
    fehlend = [n for n, vorhanden in (("Außenaufnahme", hat_aussen), ("Innenaufnahme", hat_innen)) if not vorhanden]
    return warnung(
        "fotos_aussen_innen",
        GRUPPE,
        ctx.modus,
        f"Es fehlt: {', '.join(fehlend)}.",
        "Fehlende Aufnahmeart ergänzen.",
        punkte=50.0,
        standort_id=loc_id,
    )


def _aktualitaet(ctx: CheckContext, heute: dt.date | None = None):
    guard = _modus_b_guard("fotos_aktualitaet", ctx)
    if guard:
        return guard

    loc_id = ctx.location.id
    max_alter_monate = ctx.config.get("checks", {}).get("fotos_max_alter_monate", 12)
    fotos = ctx.profile.owner_photos or []

    zeitstempel = []
    for f in fotos:
        raw = f.get("createTime") if isinstance(f, dict) else None
        if not raw:
            continue
        try:
            zeitstempel.append(dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).date())
        except ValueError:
            continue

    if not zeitstempel:
        return nicht_pruefbar(
            "fotos_aktualitaet",
            GRUPPE,
            ctx.modus,
            "Keine auswertbaren Zeitstempel für eigene Fotos vorhanden.",
            standort_id=loc_id,
        )

    heute = heute or dt.date.today()
    neuestes = max(zeitstempel)
    alter_monate = (heute.year - neuestes.year) * 12 + (heute.month - neuestes.month)

    if alter_monate <= max_alter_monate:
        return ok(
            "fotos_aktualitaet",
            GRUPPE,
            ctx.modus,
            f"Neuestes eigenes Foto ist {alter_monate} Monate alt.",
            standort_id=loc_id,
        )
    return warnung(
        "fotos_aktualitaet",
        GRUPPE,
        ctx.modus,
        f"Neuestes eigenes Foto ist {alter_monate} Monate alt (Schwelle: {max_alter_monate}).",
        "Aktuelle Fotos hochladen.",
        punkte=30.0,
        standort_id=loc_id,
    )


def run(ctx: CheckContext, heute: dt.date | None = None) -> list:
    if ctx.profile is None:
        loc_id = ctx.location.id
        return [
            nicht_pruefbar(cid, GRUPPE, ctx.modus, "Kein GBP-Profil vorhanden - siehe Gruppe 'Existenz'.", standort_id=loc_id)
            for cid in ("fotos_anzahl_indiz", "fotos_mindestanzahl", "fotos_aussen_innen", "fotos_aktualitaet")
        ]
    return [
        _fotos_modus_a(ctx),
        _fotos_mindestanzahl_modus_b(ctx),
        _aussen_innen_vorhanden(ctx),
        _aktualitaet(ctx, heute=heute),
    ]
