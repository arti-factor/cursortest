"""Gruppe 4 - Beschreibung & Attribute (Modus B, Gewicht 10%)."""
from __future__ import annotations

from rapidfuzz import fuzz

from src.checks.base import CheckContext, fehler, nicht_pruefbar, ok, warnung
from src.models import Modus

GRUPPE = "beschreibung_attribute"


def _modus_b_guard(check_id: str, ctx: CheckContext):
    if ctx.modus != Modus.B:
        return nicht_pruefbar(
            check_id,
            GRUPPE,
            ctx.modus,
            "Nur mit Verwaltungszugriff (Modus B) prüfbar.",
            standort_id=ctx.location.id,
        )
    return None


def _beschreibung_laenge(ctx: CheckContext):
    guard = _modus_b_guard("beschreibung_laenge", ctx)
    if guard:
        return guard

    loc_id = ctx.location.id
    mindestlaenge = ctx.config.get("checks", {}).get("beschreibung_mindestlaenge", 250)
    text = ctx.profile.description or ""

    if not text:
        return fehler(
            "beschreibung_laenge",
            GRUPPE,
            ctx.modus,
            "Keine Unternehmensbeschreibung im Profil hinterlegt.",
            "Aussagekräftige Beschreibung mit Lokalbezug ergänzen.",
            standort_id=loc_id,
        )
    if len(text) < mindestlaenge:
        return warnung(
            "beschreibung_laenge",
            GRUPPE,
            ctx.modus,
            f"Beschreibung ist mit {len(text)} Zeichen kürzer als empfohlen ({mindestlaenge}).",
            "Beschreibung ausführlicher gestalten.",
            punkte=50.0,
            standort_id=loc_id,
        )
    return ok("beschreibung_laenge", GRUPPE, ctx.modus, f"Beschreibung vorhanden ({len(text)} Zeichen).", standort_id=loc_id)


def _beschreibung_duplikat(ctx: CheckContext):
    guard = _modus_b_guard("beschreibung_duplikat", ctx)
    if guard:
        return guard

    loc_id = ctx.location.id
    if not ctx.is_multi_location:
        return nicht_pruefbar(
            "beschreibung_duplikat",
            GRUPPE,
            ctx.modus,
            "Nur bei Mehrstandort-Kunden relevant (dieser Kunde hat einen Standort).",
            standort_id=loc_id,
        )

    eigener_text = ctx.profile.description or ""
    if not eigener_text:
        return nicht_pruefbar(
            "beschreibung_duplikat",
            GRUPPE,
            ctx.modus,
            "Keine Beschreibung vorhanden, Duplikatsprüfung nicht möglich.",
            standort_id=loc_id,
        )

    schwelle = ctx.config.get("checks", {}).get("beschreibung_duplikat_aehnlichkeit_max", 85)
    duplikate = []
    for peer in ctx.peer_profiles:
        peer_text = peer.description or ""
        if not peer_text:
            continue
        aehnlichkeit = fuzz.token_sort_ratio(eigener_text.lower(), peer_text.lower())
        if aehnlichkeit >= schwelle:
            duplikate.append((peer.display_name, aehnlichkeit))

    if duplikate:
        beispiele = ", ".join(f"{name} ({ae:.0f}%)" for name, ae in duplikate[:3])
        return warnung(
            "beschreibung_duplikat",
            GRUPPE,
            ctx.modus,
            f"Beschreibung ist nahezu identisch mit {len(duplikate)} anderen Standorten: {beispiele}.",
            "Individuelle Beschreibung mit Lokalbezug (Stadtteil, Team, Besonderheiten) formulieren.",
            punkte=40.0,
            standort_id=loc_id,
        )
    return ok(
        "beschreibung_duplikat",
        GRUPPE,
        ctx.modus,
        "Beschreibung ist individuell und nicht dupliziert.",
        standort_id=loc_id,
    )


def _erwartete_attribute(ctx: CheckContext):
    guard = _modus_b_guard("beschreibung_attribute", ctx)
    if guard:
        return guard

    loc_id = ctx.location.id
    erwartete = (ctx.config.get("beschreibung_attribute", {}) or {}).get("erwartete_attribute", [])
    if not erwartete:
        return nicht_pruefbar(
            "beschreibung_attribute",
            GRUPPE,
            ctx.modus,
            "Keine erwarteten Attribute in der Kundenkonfiguration hinterlegt.",
            standort_id=loc_id,
        )

    vorhandene = set(ctx.profile.attributes.keys()) if ctx.profile.attributes else set()
    fehlende = [a for a in erwartete if a not in vorhandene]

    if not fehlende:
        return ok(
            "beschreibung_attribute",
            GRUPPE,
            ctx.modus,
            f"Alle {len(erwartete)} erwarteten Attribute sind gepflegt.",
            standort_id=loc_id,
        )
    return warnung(
        "beschreibung_attribute",
        GRUPPE,
        ctx.modus,
        f"{len(fehlende)} von {len(erwartete)} erwarteten Attributen fehlen: {', '.join(fehlende)}.",
        "Fehlende Attribute im Profil ergänzen.",
        punkte=max(0.0, 100.0 - 100.0 * len(fehlende) / len(erwartete)),
        standort_id=loc_id,
    )


def run(ctx: CheckContext) -> list:
    if ctx.profile is None:
        loc_id = ctx.location.id
        return [
            nicht_pruefbar(cid, GRUPPE, ctx.modus, "Kein GBP-Profil vorhanden - siehe Gruppe 'Existenz'.", standort_id=loc_id)
            for cid in ("beschreibung_laenge", "beschreibung_duplikat", "beschreibung_attribute")
        ]
    return [_beschreibung_laenge(ctx), _beschreibung_duplikat(ctx), _erwartete_attribute(ctx)]
