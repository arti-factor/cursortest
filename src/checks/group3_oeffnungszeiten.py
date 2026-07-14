"""Gruppe 3 - Öffnungszeiten (regulär: Modus A, Feiertage: Modus B, Gewicht 10%)."""
from __future__ import annotations

import datetime as dt

from src.checks.base import CheckContext, fehler, nicht_pruefbar, ok, warnung
from src.models import Modus
from src.util_geo import bundesland_from_plz

GRUPPE = "oeffnungszeiten"


def _regulaere_zeiten(ctx: CheckContext):
    loc_id = ctx.location.id
    hours = ctx.profile.regular_opening_hours or {}
    periods = hours.get("periods", [])

    if not periods:
        return fehler(
            "oeffnungszeiten_regulaer",
            GRUPPE,
            ctx.modus,
            "Keine regulären Öffnungszeiten im Profil hinterlegt.",
            "Öffnungszeiten für alle Wochentage im Profil eintragen.",
            standort_id=loc_id,
        )

    tage_mit_zeiten = {p.get("open", {}).get("day") for p in periods if p.get("open")}
    tage_mit_zeiten.discard(None)

    if len(tage_mit_zeiten) >= 6:
        return ok(
            "oeffnungszeiten_regulaer",
            GRUPPE,
            ctx.modus,
            f"Öffnungszeiten für {len(tage_mit_zeiten)} von 7 Wochentagen gepflegt.",
            standort_id=loc_id,
        )
    if len(tage_mit_zeiten) >= 4:
        return warnung(
            "oeffnungszeiten_regulaer",
            GRUPPE,
            ctx.modus,
            f"Nur für {len(tage_mit_zeiten)} von 7 Wochentagen sind Öffnungszeiten hinterlegt.",
            "Fehlende Wochentage ergänzen, damit Nutzer verlässlich planen können.",
            punkte=50.0,
            standort_id=loc_id,
        )
    return fehler(
        "oeffnungszeiten_regulaer",
        GRUPPE,
        ctx.modus,
        f"Nur für {len(tage_mit_zeiten)} von 7 Wochentagen sind Öffnungszeiten hinterlegt.",
        "Öffnungszeiten für die fehlenden Wochentage ergänzen.",
        punkte=20.0,
        standort_id=loc_id,
    )


def _feiertage_check(ctx: CheckContext, heute: dt.date | None = None):
    loc_id = ctx.location.id

    if ctx.modus != Modus.B:
        return nicht_pruefbar(
            "oeffnungszeiten_feiertage",
            GRUPPE,
            ctx.modus,
            "Feiertags-Sonderöffnungszeiten sind nur mit Verwaltungszugriff (Modus B) prüfbar.",
            standort_id=loc_id,
        )

    bundesland = bundesland_from_plz(ctx.location.zip)
    if not bundesland:
        return nicht_pruefbar(
            "oeffnungszeiten_feiertage",
            GRUPPE,
            ctx.modus,
            "Bundesland konnte aus der Postleitzahl nicht eindeutig abgeleitet werden.",
            standort_id=loc_id,
        )

    import holidays

    heute = heute or dt.date.today()
    horizont_ende = heute + dt.timedelta(days=60)
    de_holidays = holidays.Germany(subdiv=bundesland, years=[heute.year, horizont_ende.year])
    anstehende = sorted(d for d in de_holidays if heute <= d <= horizont_ende)

    if not anstehende:
        return ok(
            "oeffnungszeiten_feiertage",
            GRUPPE,
            ctx.modus,
            "Keine gesetzlichen Feiertage in den nächsten 60 Tagen zu prüfen.",
            standort_id=loc_id,
        )

    special_periods = (ctx.profile.special_hours or {}).get("specialHourPeriods", [])
    gepflegte_daten = {
        (p.get("startDate", {}).get("year"), p.get("startDate", {}).get("month"), p.get("startDate", {}).get("day"))
        for p in special_periods
    }

    fehlende = [d for d in anstehende if (d.year, d.month, d.day) not in gepflegte_daten]

    if not fehlende:
        return ok(
            "oeffnungszeiten_feiertage",
            GRUPPE,
            ctx.modus,
            f"Sonderöffnungszeiten für alle {len(anstehende)} anstehenden Feiertage ({bundesland}) gepflegt.",
            standort_id=loc_id,
        )

    return warnung(
        "oeffnungszeiten_feiertage",
        GRUPPE,
        ctx.modus,
        f"Für {len(fehlende)} von {len(anstehende)} anstehenden Feiertagen ({bundesland}) fehlen "
        f"Sonderöffnungszeiten: {', '.join(d.isoformat() for d in fehlende)}.",
        "Sonderöffnungszeiten für die genannten Feiertage im Profil ergänzen.",
        punkte=max(0.0, 100.0 - 100.0 * len(fehlende) / len(anstehende)),
        standort_id=loc_id,
    )


def run(ctx: CheckContext, heute: dt.date | None = None) -> list:
    if ctx.profile is None:
        loc_id = ctx.location.id
        return [
            nicht_pruefbar(cid, GRUPPE, ctx.modus, "Kein GBP-Profil vorhanden - siehe Gruppe 'Existenz'.", standort_id=loc_id)
            for cid in ("oeffnungszeiten_regulaer", "oeffnungszeiten_feiertage")
        ]
    return [_regulaere_zeiten(ctx), _feiertage_check(ctx, heute=heute)]
